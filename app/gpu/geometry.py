"""Compact GPU geometry for the wgpu renderer.

A ViewerModel stores 76 bytes per vertex (pos3 nrm3 dpos3 dnrm3 fib1 col4 uv2, float32). Here that becomes

    pos   float32 x3            12 B  exact, always
    nrm   octahedral snorm16x2   4 B  always (the only lossy stream)
    dpos  float32 x3            12 B  only for parts where it is not constant
    dnrm  float32 x3            12 B  only for parts where it is not constant
    fib   float32                4 B  only for parts where it is not constant
    col   float32 x4            16 B  only for parts where it is not constant
    uv    float32 x2             8 B  only for parts where it is not constant

Constant attributes (bit-identical on every vertex of a part) live once per part in ``const_tail`` (the 13 floats of
columns 6..18). Everything but the normal is bit-exact.

Memory is paged: the vertices of consecutive parts (ordered by vertex_base) share a page; a page owns one buffer per
stream plus one uint32 index buffer. Index values are rewritten page-local at upload (vertex - page.v0), so every
draw uses base_vertex 0. A part (its vertices, full index range and every LOD level) never crosses a page. Pages are
at most ``page_bytes`` = min(max_storage_buffer_binding_size, max_buffer_size, 1 GiB) per buffer.

Nothing of the vertex data is kept on the CPU after the upload: only the small per-part tables.

The buffer back end is a "sink" (GpuSink for wgpu, HostSink for tests without an adapter), both with
create(size, label) / write(handle, offset, array) / read(handle) / finish().
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np

from app.viewer import lod as _lod

GIB = 1 << 30
SCAN_ROWS = 1 << 19                    # vertex rows examined / packed per step
INDEX_CHUNK = 1 << 22                  # indices per upload step
VERTEX_FLOATS = 19
BYTES_BEFORE = VERTEX_FLOATS * 4

# stream name -> (first column, end column, bytes per vertex)
STREAMS = {
    "pos": (0, 3, 12), "nrm": (3, 6, 4),
    "dpos": (6, 9, 12), "dnrm": (9, 12, 12), "fib": (12, 13, 4), "col": (13, 17, 16), "uv": (17, 19, 8),
}
VARIABLE = ("dpos", "dnrm", "fib", "col", "uv")      # streams that exist only where the part's values differ
ANIM_BYTES = 36                                      # procedural animation stream: float16 x16 (four morph targets xyzw) + float32 phase
MAX_STREAM_BYTES = 16                                # the widest per-vertex stream (col)


class GeometryError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ octahedral normals
def _sign_nz(v):
    return np.where(v >= 0.0, 1.0, -1.0).astype(v.dtype)


def oct_encode(n):
    """(N, 3) vectors -> (N, 2) float32 octahedral coordinates in [-1, 1] (direction only; zero -> +Z)."""
    n = np.asarray(n, dtype=np.float32)
    l1 = np.abs(n).sum(axis=1, keepdims=True)
    safe = l1 > 1e-30
    p = n[:, :2] / np.where(safe, l1, 1.0)
    low = n[:, 2] < 0.0
    if low.any():
        q = (1.0 - np.abs(p[:, ::-1])) * _sign_nz(p)
        p = np.where(low[:, None], q, p)
    return np.where(safe, p, 0.0).astype(np.float32)


def oct_pack(p):
    """(N, 2) octahedral float -> (N,) uint32, x in the low 16 bits (WGSL unpack2x16snorm layout)."""
    q = np.rint(np.clip(p, -1.0, 1.0) * np.float32(32767.0)).astype(np.int16)
    return np.ascontiguousarray(q).view(np.uint32).reshape(-1)


def oct_unpack(u):
    """(N,) uint32 -> (N, 2) float32 like WGSL unpack2x16snorm: max(c / 32767, -1)."""
    q = np.ascontiguousarray(u, dtype=np.uint32).view(np.int16).reshape(-1, 2).astype(np.float32)
    return np.maximum(q / np.float32(32767.0), np.float32(-1.0))


def oct_decode(p):
    """(N, 2) octahedral float32 -> (N, 3) unit float32 vectors (the shader's decode)."""
    p = np.asarray(p, dtype=np.float32)
    z = 1.0 - np.abs(p[:, 0]) - np.abs(p[:, 1])
    n = np.stack([p[:, 0], p[:, 1], z], axis=1)
    low = z < 0.0
    if low.any():
        q = (1.0 - np.abs(n[:, ::-1][:, 1:])) * _sign_nz(n[:, :2])
        n[:, :2] = np.where(low[:, None], q, n[:, :2])
    ln = np.sqrt((n * n).sum(axis=1, keepdims=True))
    return n / np.maximum(ln, np.float32(1e-30))


def normal_error_degrees(n, packed):
    """Angle in degrees between the unit direction of each source normal and the decoded packed normal.
    Zero-length source normals give nan."""
    n = np.asarray(n, dtype=np.float64)
    ln = np.linalg.norm(n, axis=1)
    d = oct_decode(oct_unpack(packed)).astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        n = n / ln[:, None]
        # atan2(|cross|, dot): arccos of a dot near 1 cannot resolve angles below ~0.02 degrees
        ang = np.arctan2(np.linalg.norm(np.cross(n, d), axis=1), (n * d).sum(axis=1))
    return np.degrees(ang)


# ------------------------------------------------------------------------------------------------ sinks
class HostSink:
    """Stores 'buffers' as numpy byte arrays (tests without an adapter)."""

    def create(self, size, label=""):
        return np.zeros(max(int(size), 4), dtype=np.uint8)

    def write(self, handle, offset, arr):
        raw = np.ascontiguousarray(arr).view(np.uint8).reshape(-1)
        handle[offset:offset + raw.size] = raw

    def read(self, handle, offset=0, size=None):
        end = handle.size if size is None else offset + size
        return handle[offset:end].copy()

    def finish(self):
        pass

    def destroy(self, handle):
        pass


class GpuSink:
    """wgpu buffers. queue.write_buffer stages its data until the next submit, so the staged amount is bounded by
    submitting (and waiting for) the queue every ``flush_bytes``: no full-size temporary copy is ever alive."""

    def __init__(self, device, flush_bytes=64 << 20):
        import wgpu
        self.device, self.queue = device, device.queue
        self.usage = (wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.INDEX | wgpu.BufferUsage.COPY_DST |
                      wgpu.BufferUsage.COPY_SRC)
        self.flush_bytes = flush_bytes
        self.staged = 0

    def create(self, size, label=""):
        size = max(16, (int(size) + 3) & ~3)
        return self.device.create_buffer(size=size, usage=self.usage, label=label)

    def write(self, handle, offset, arr):
        raw = np.ascontiguousarray(arr)
        self.queue.write_buffer(handle, int(offset), raw)
        self.staged += raw.nbytes
        if self.staged >= self.flush_bytes:
            self.finish()

    def read(self, handle, offset=0, size=None):
        size = handle.size - offset if size is None else size
        return np.frombuffer(bytes(self.queue.read_buffer(handle, offset, size)), dtype=np.uint8)

    def finish(self):
        """Submit the staged writes and wait for the queue (wgpu-py 0.32's on_submitted_work_done is broken: submit a
        one-word copy and map its destination; the queue is in order)."""
        import wgpu
        if getattr(self, "_idle", None) is None:
            self._idle = (self.device.create_buffer(size=16, usage=wgpu.BufferUsage.COPY_SRC),
                          self.device.create_buffer(size=16, usage=wgpu.BufferUsage.MAP_READ | wgpu.BufferUsage.COPY_DST))
        src, dst = self._idle
        enc = self.device.create_command_encoder()
        enc.copy_buffer_to_buffer(src, 0, dst, 0, 16)
        self.queue.submit([enc.finish()])
        dst.map_sync(wgpu.MapMode.READ)
        dst.unmap()
        self.staged = 0

    def destroy(self, handle):
        try:
            handle.destroy()
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------ data classes
@dataclass
class Page:
    index: int
    v0: int                              # model vertex range [v0, v1) stored in this page
    v1: int
    parts: list                          # part indices (positions in model.parts)
    buffers: dict = field(default_factory=dict)    # stream name / "index" -> sink handle
    stream_verts: dict = field(default_factory=dict)   # variable stream -> vertex count
    nindices: int = 0

    @property
    def nverts(self):
        return self.v1 - self.v0


@dataclass
class GpuGeometry:
    sink: object
    pages: list
    page_of: np.ndarray                  # (P,) int32, -1 for parts without geometry
    vbase: np.ndarray                    # (P,) int64 first vertex of the part, page-local
    vcount: np.ndarray                   # (P,) int64
    ranges: list                         # per part: [(first_index, count)] level 0, then LOD levels 1..LEVELS (page-local)
    stream_base: np.ndarray              # (P, 5) int64: first vertex of the part in each VARIABLE stream, -1 constant
    const_tail: np.ndarray               # (P, 13) float32: columns 6..18 (the value where the stream is constant)
    gl_keys: list                        # per part: [GL ibo span start of level 0, 1, ...] (draw order, see gl_order_keys)
    stats: dict
    page_bytes: int
    anim_base: np.ndarray = None         # (P,) int64: first vertex of the part in the page's 'anim' stream (9 uint32 per vertex), -1 none

    def release(self):
        for page in self.pages:
            for h in page.buffers.values():
                self.sink.destroy(h)
            page.buffers = {}
        self.pages = []


# ------------------------------------------------------------------------------------------------ GL layout (order only)
def gl_order_keys(model):
    """Where app.viewer.renderer.Renderer._batched_indices puts every part's mesh in its index buffer: the draw
    order of the GL renderer (runs are drawn by span start, so this decides equal-depth ties). Returns
    (base {part id: start}, lods {part id: [start of level 1..LEVELS]})."""
    from app.viewer.renderer import _look_key
    parts = model.parts
    look_keys = {p.id: _look_key(p.look) for p in parts}
    by_look = sorted(parts, key=lambda p: (p.material_name, look_keys[p.id] or "", p.id))
    levels = getattr(model, "lod", None) or {}
    coarse = [p for p in by_look if p.id in levels]
    in_order = [p.id for p in by_look] == [p.id for p in sorted(parts, key=lambda p: p.first)]
    base, lods = {}, {}
    if in_order and not coarse:
        return {p.id: p.first for p in parts}, lods
    offset = 0
    if in_order:
        base = {p.id: p.first for p in parts}
        offset = len(model.indices)
    else:
        for p in by_look:
            base[p.id] = offset
            offset += p.count
    for _k in range(_lod.LEVELS):
        for p in coarse:
            lods.setdefault(p.id, []).append(offset)
            offset += len(levels[p.id].indices[_k])
    return base, lods


# ------------------------------------------------------------------------------------------------ planning
def page_limit(device):
    """Bytes per buffer: min(max_storage_buffer_binding_size, max_buffer_size, 1 GiB) of the device."""
    lim = device.limits
    def get(name):
        return lim.get(name, lim.get(name.replace("_", "-"), 1 << 62))
    return int(min(get("max_storage_buffer_binding_size"), get("max_buffer_size"), GIB))


def _part_levels(model, part):
    """(base array view, [unique LOD arrays in level order], level -> unique slot) of one part."""
    lod = (getattr(model, "lod", None) or {}).get(part.id)
    if lod is None:
        return [], []
    uniq, order = [], []
    seen = {}
    for arr in lod.indices:
        key = id(arr)
        if key not in seen:
            seen[key] = len(uniq)
            uniq.append(arr)
        order.append(seen[key])
    return uniq, order


def plan_pages(model, page_bytes):
    """Group the parts (ordered by vertex_base) into pages. Returns (pages, order, unique_lod) where pages is a list
    of lists of part indices."""
    parts = model.parts
    order = sorted((i for i, p in enumerate(parts) if p.vertex_count > 0 or p.count > 0),
                   key=lambda i: (parts[i].vertex_base, i))
    cap_v = page_bytes // MAX_STREAM_BYTES
    cap_i = page_bytes // 4
    pages, cur = [], None
    prev_end = 0
    for i in order:
        p = parts[i]
        if p.vertex_count <= 0:
            raise GeometryError(f"part {p.name!r} has indices but no vertex range")
        if p.vertex_base < prev_end:
            raise GeometryError(f"part {p.name!r} overlaps the vertices of the part before it")
        uniq, _ = _part_levels(model, p)
        n_idx = p.count + sum(len(a) for a in uniq)
        if p.vertex_count > cap_v or n_idx > cap_i:
            raise GeometryError(f"part {p.name!r} ({p.vertex_count} vertices, {n_idx} indices) is larger than a "
                                f"{page_bytes >> 20} MiB page")
        if cur is not None:
            span = p.vertex_base + p.vertex_count - cur["v0"]
            if span > cap_v or cur["idx"] + n_idx > cap_i:
                pages.append(cur)
                cur = None
        if cur is None:
            cur = {"v0": p.vertex_base, "v1": p.vertex_base, "parts": [], "idx": 0}
        cur["parts"].append(i)
        cur["v1"] = p.vertex_base + p.vertex_count
        cur["idx"] += n_idx
        prev_end = cur["v1"]
    if cur is not None:
        pages.append(cur)
    return pages


# ------------------------------------------------------------------------------------------------ build
def _scan_constants(vertices, parts, part_ids):
    """Per part: which VARIABLE streams differ between vertices, and the 13-float value of the first vertex."""
    cols = {g: (STREAMS[g][0] - 6, STREAMS[g][1] - 6) for g in VARIABLE}
    flags = np.zeros((len(parts), len(VARIABLE)), dtype=bool)
    tail = np.zeros((len(parts), 13), dtype=np.float32)
    for i in part_ids:
        p = parts[i]
        v0, n = p.vertex_base, p.vertex_count
        first = np.array(vertices[v0, 6:19], dtype=np.float32)
        tail[i] = first
        bits = first.view(np.uint32)
        todo = set(range(len(VARIABLE)))
        for a in range(0, n, SCAN_ROWS):
            blk = np.asarray(vertices[v0 + a:v0 + min(a + SCAN_ROWS, n), 6:19]).view(np.uint32)
            diff = (blk != bits).any(axis=0)
            for k in list(todo):
                c0, c1 = cols[VARIABLE[k]]
                if diff[c0:c1].any():
                    flags[i, k] = True
                    todo.discard(k)
            if not todo:
                break
    return flags, tail


def _anim_nonzero(src, p):
    """Does the part carry any non-zero procedural-animation data (morph targets or phase)?"""
    for a in range(0, p.vertex_count, SCAN_ROWS):
        blk = src[p.vertex_base + a:p.vertex_base + min(a + SCAN_ROWS, p.vertex_count)]
        if np.any(blk["m"]) or np.any(blk["phase"]):
            return True
    return False


def build_geometry(model, sink, page_bytes, measure=False, progress=None):
    """Upload model.vertices / model.indices (+ LOD levels) through ``sink``; returns a GpuGeometry.

    measure=True also records the normal error (max/mean angle), the spread of source normal lengths and the
    number of zero-length normals in ``stats`` (costs one decode of every normal)."""
    parts = model.parts
    vertices, indices = model.vertices, model.indices
    if vertices is None or vertices.ndim != 2 or vertices.shape[1] != VERTEX_FLOATS or vertices.dtype != np.float32:
        raise GeometryError("vertices must be a float32 (V, 19) array")
    plans = plan_pages(model, page_bytes)
    n = len(parts)
    part_ids = [i for pl in plans for i in pl["parts"]]
    flags, tail = _scan_constants(vertices, parts, part_ids)

    page_of = np.full(n, -1, dtype=np.int32)
    vbase = np.zeros(n, dtype=np.int64)
    vcount = np.zeros(n, dtype=np.int64)
    stream_base = np.full((n, len(VARIABLE)), -1, dtype=np.int64)
    anim_src = getattr(model, "anim_vertices", None)
    anim_base = np.full(n, -1, dtype=np.int64)
    ranges = [[(0, 0)] for _ in range(n)]
    pages = []
    nrm_stats = {"max_deg": 0.0, "sum_deg": 0.0, "count": 0, "len_min": math.inf, "len_max": 0.0, "zero": 0}

    for pi, pl in enumerate(plans):
        page = Page(index=pi, v0=pl["v0"], v1=pl["v1"], parts=pl["parts"])
        # ---- layout of the page
        index_layout = []                        # (source array, dest first index, part index)
        at = 0
        counts = {g: 0 for g in VARIABLE}
        n_anim = 0
        for i in pl["parts"]:
            p = parts[i]
            page_of[i] = pi
            vbase[i], vcount[i] = p.vertex_base - page.v0, p.vertex_count
            for k, g in enumerate(VARIABLE):
                if flags[i, k]:
                    stream_base[i, k] = counts[g]
                    counts[g] += p.vertex_count
            if anim_src is not None and _anim_nonzero(anim_src, p):
                anim_base[i] = n_anim
                n_anim += p.vertex_count
            lv = [(0, p.count)] if p.count else [(0, 0)]
            if p.count:
                index_layout.append((indices, p.first, p.count, at, i))
                lv = [(at, p.count)]
                at += p.count
            uniq, order = _part_levels(model, p)
            placed = []
            for arr in uniq:
                index_layout.append((arr, 0, len(arr), at, i))
                placed.append((at, len(arr)))
                at += len(arr)
            ranges[i] = lv + [placed[o] for o in order]
        page.nindices = at
        page.stream_verts = {g: c for g, c in counts.items() if c}
        if n_anim:
            page.stream_verts["anim"] = n_anim
        # ---- buffers
        page.buffers["pos"] = sink.create(page.nverts * 12, f"page{pi}.pos")
        page.buffers["nrm"] = sink.create(page.nverts * 4, f"page{pi}.nrm")
        for g, c in page.stream_verts.items():
            page.buffers[g] = sink.create(c * (ANIM_BYTES if g == "anim" else STREAMS[g][2]), f"page{pi}.{g}")
        page.buffers["index"] = sink.create(max(at, 1) * 4, f"page{pi}.index")
        # ---- pos / nrm: one contiguous run of the model's vertices
        for a in range(page.v0, page.v1, SCAN_ROWS):
            b = min(a + SCAN_ROWS, page.v1)
            blk = np.asarray(vertices[a:b])
            sink.write(page.buffers["pos"], (a - page.v0) * 12, np.ascontiguousarray(blk[:, 0:3]))
            nrm = np.ascontiguousarray(blk[:, 3:6])
            packed = oct_pack(oct_encode(nrm))
            sink.write(page.buffers["nrm"], (a - page.v0) * 4, packed)
            if measure:
                ln = np.linalg.norm(nrm.astype(np.float64), axis=1)
                nz = ln > 1e-12
                err = normal_error_degrees(nrm, packed)[nz]
                nrm_stats["zero"] += int((~nz).sum())
                if err.size:
                    nrm_stats["max_deg"] = max(nrm_stats["max_deg"], float(err.max()))
                    nrm_stats["sum_deg"] += float(err.sum())
                    nrm_stats["count"] += int(err.size)
                    nrm_stats["len_min"] = min(nrm_stats["len_min"], float(ln[nz].min()))
                    nrm_stats["len_max"] = max(nrm_stats["len_max"], float(ln[nz].max()))
        # ---- variable streams, part by part
        for i in pl["parts"]:
            p = parts[i]
            for k, g in enumerate(VARIABLE):
                if not flags[i, k]:
                    continue
                c0, c1, bpv = STREAMS[g]
                for a in range(0, p.vertex_count, SCAN_ROWS):
                    b = min(a + SCAN_ROWS, p.vertex_count)
                    blk = np.ascontiguousarray(vertices[p.vertex_base + a:p.vertex_base + b, c0:c1])
                    sink.write(page.buffers[g], (stream_base[i, k] + a) * bpv, blk)
        for i in pl["parts"]:
            if anim_base[i] >= 0:
                p = parts[i]
                for a in range(0, p.vertex_count, SCAN_ROWS):
                    b = min(a + SCAN_ROWS, p.vertex_count)
                    raw = np.ascontiguousarray(anim_src[p.vertex_base + a:p.vertex_base + b]).view(np.uint8)
                    sink.write(page.buffers["anim"], (anim_base[i] + a) * ANIM_BYTES, raw)
        # ---- indices, rewritten page-local and range-checked
        for src, first, count, dest, i in index_layout:
            for a in range(0, count, INDEX_CHUNK):
                b = min(a + INDEX_CHUNK, count)
                blk = np.asarray(src[first + a:first + b], dtype=np.uint32)
                lo, hi = int(blk.min()), int(blk.max())
                if lo < page.v0 or hi >= page.v1:
                    raise GeometryError(f"part {parts[i].name!r} indexes vertices outside its page "
                                        f"({lo}..{hi} not in {page.v0}..{page.v1 - 1})")
                sink.write(page.buffers["index"], (dest + a) * 4, blk - np.uint32(page.v0))
        pages.append(page)
        if progress:
            progress(pi + 1, len(plans))
    sink.finish()

    # ---- statistics
    nv = sum(pg.nverts for pg in pages)
    stream_bytes = sum(pg.nverts * 16 for pg in pages) + sum(c * (ANIM_BYTES if g == "anim" else STREAMS[g][2])
                                                              for pg in pages for g, c in pg.stream_verts.items())
    index_bytes = sum(pg.nindices * 4 for pg in pages)
    stats = {
        "pages": len(pages), "vertices": nv, "indices": sum(pg.nindices for pg in pages),
        "bytes_per_vertex_before": BYTES_BEFORE,
        "bytes_per_vertex_after": stream_bytes / max(nv, 1),
        "vertex_bytes": stream_bytes, "index_bytes": index_bytes, "gpu_bytes": stream_bytes + index_bytes,
        "variable_parts": {g: int(flags[:, k].sum()) for k, g in enumerate(VARIABLE)},
    }
    if measure:
        c = max(nrm_stats["count"], 1)
        stats["normals"] = {"max_angle_deg": nrm_stats["max_deg"], "mean_angle_deg": nrm_stats["sum_deg"] / c,
                            "len_min": nrm_stats["len_min"], "len_max": nrm_stats["len_max"],
                            "zero_length": nrm_stats["zero"]}
    base, lods = gl_order_keys(model)
    gl_keys = []
    for p in parts:
        gl_keys.append([base[p.id]] + list(lods.get(p.id, [])))
    return GpuGeometry(sink=sink, pages=pages, page_of=page_of, vbase=vbase, vcount=vcount, ranges=ranges,
                       stream_base=stream_base, const_tail=tail, gl_keys=gl_keys, stats=stats,
                       page_bytes=page_bytes, anim_base=anim_base)


# ------------------------------------------------------------------------------------------------ decode (tests, checks)
def decode_geometry(geom, model):
    """Rebuild (vertices (V,19) float32, index arrays) from the stored data, for comparison with the source model.
    Returns (vertices, indices) where vertices rows not owned by any part stay zero, and indices is
    {(part index, level): global uint32 array}. Normals come back as unit vectors."""
    sink = geom.sink
    parts = model.parts
    V = len(model.vertices)
    out = np.zeros((V, VERTEX_FLOATS), dtype=np.float32)
    idx = {}
    for page in geom.pages:
        raw = {name: sink.read(h) for name, h in page.buffers.items()}
        pos = raw["pos"].view(np.float32)[:page.nverts * 3].reshape(-1, 3)
        nrm = raw["nrm"].view(np.uint32)[:page.nverts]
        out[page.v0:page.v1, 0:3] = pos
        out[page.v0:page.v1, 3:6] = oct_decode(oct_unpack(nrm))
        index = raw["index"].view(np.uint32)
        for i in page.parts:
            p = parts[i]
            a, b = p.vertex_base, p.vertex_base + p.vertex_count
            out[a:b, 6:19] = geom.const_tail[i]
            for k, g in enumerate(VARIABLE):
                sb = geom.stream_base[i, k]
                if sb < 0:
                    continue
                c0, c1, bpv = STREAMS[g]
                arr = raw[g].view(np.float32).reshape(-1, c1 - c0)
                out[a:b, c0:c1] = arr[sb:sb + p.vertex_count]
            for level, (first, count) in enumerate(geom.ranges[i]):
                idx[(i, level)] = index[first:first + count] + np.uint32(page.v0)
    return out, idx
