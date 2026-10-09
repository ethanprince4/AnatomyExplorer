"""Compact GPU geometry for the wgpu renderer.

A ViewerModel stores 76 bytes per vertex (pos3 nrm3 dpos3 dnrm3 fib1 col4 uv2, float32). Here that becomes

    pos   float32 x3            12 B  exact, always
    nrm   octahedral snorm16x2   4 B  always (the only lossy stream)
    dpos  float32 x3            12 B  only for parts where it is not constant
    dnrm  float32 x3            12 B  only for parts where it is not constant
    fib   float32                4 B  only for parts where it is not constant
    col   float32 x4            16 B  only for parts where it is not constant
    uv    float32 x2             8 B  only for parts where it is not constant
    anim  9 x uint32            36 B  only for parts with procedural animation data

Constant attributes (bit-identical on every vertex of a part) live once per part in ``const_tail`` (the 13 floats of
columns 6..18). Everything but the normal is bit-exact.

Memory is paged: the vertices of consecutive parts (ordered by vertex_base) share a page; a page is ONE buffer (uint32
words, usage STORAGE | INDEX | COPY_DST) holding every stream and the page's uint32 index data, each starting at a
256-byte aligned word offset (SECTION_ORDER, Page.offs; the shaders get the offsets as a uniform, see geom_prelude and
wgsl/geom.wgsl). Index values are rewritten page-local at upload (vertex - page.v0), so every draw uses base_vertex 0 and
set_index_buffer(page.buffer, "uint32", page.index_byte_offset). A part (its vertices, full index range and every LOD
level) never crosses a page. A page is at most ``page_bytes`` = min(max_storage_buffer_binding_size, max_buffer_size).

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


# ------------------------------------------------------------------------------------------------ page layout
# One page = one buffer of uint32 words. Its sections start at multiples of 256 bytes, in this order; the word offsets of a
# page are what wgsl/geom.wgsl reads (SECTION_INDEX == the G_* constants there).
SECTION_ORDER = ("pos", "nrm", "dpos", "dnrm", "fib", "col", "uv", "anim", "index")
SECTION_INDEX = {n: i for i, n in enumerate(SECTION_ORDER)}
SECTION_WORDS = {"pos": 3, "nrm": 1, "dpos": 3, "dnrm": 3, "fib": 1, "col": 4, "uv": 2, "anim": ANIM_BYTES // 4, "index": 1}
ALIGN_WORDS = 64                                     # 256 bytes
OFFS_VEC4 = 3                                        # a page's offsets in the shaders' uniform: three vec4<u32> (9 used)


def section_layout(counts):
    """counts: section -> number of elements (vertices, or indices for 'index'). Returns ({section: first word}, total words)."""
    offs, at = {}, 0
    for name in SECTION_ORDER:
        offs[name] = at
        at += int(counts.get(name, 0)) * SECTION_WORDS[name]
        at = -(-at // ALIGN_WORDS) * ALIGN_WORDS
    return offs, max(at, ALIGN_WORDS)


@dataclass
class Page:
    index: int
    v0: int                              # model vertex range [v0, v1) stored in this page
    v1: int
    parts: list                          # part indices (positions in model.parts)
    buffer: object = None                # the page's single sink handle (STORAGE | INDEX | COPY_DST)
    offs: dict = field(default_factory=dict)       # section -> first word
    counts: dict = field(default_factory=dict)     # section -> elements (vertices, or indices)
    words: int = 0                       # buffer size in words

    @property
    def nverts(self):
        return self.v1 - self.v0

    @property
    def nindices(self):
        return self.counts.get("index", 0)

    @property
    def stream_verts(self):
        return {g: c for g, c in self.counts.items() if g not in ("pos", "nrm", "index") and c}

    @property
    def index_byte_offset(self):
        return self.offs["index"] * 4

    @property
    def index_bytes(self):
        return max(self.nindices, 1) * 4

    def offsets_words(self):
        """(OFFS_VEC4 * 4,) uint32: the section offsets as the shaders' page-offset uniform holds them."""
        out = np.zeros(OFFS_VEC4 * 4, dtype=np.uint32)
        for name, k in SECTION_INDEX.items():
            out[k] = self.offs[name]
        return out


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
    clusters: object = None              # clusters.ClusterData when built with cluster_order=True (triangles stored in cluster order), else None
    order: object = None                 # TriangleOrder (stored -> original triangle) when cluster ordered

    @property
    def cluster_ordered(self):
        return self.clusters is not None

    def page_offsets(self, first=0, n=None):
        """(n, OFFS_VEC4 * 4) uint32: the section offsets of pages first .. first + n - 1 (the page-offset uniform's content)."""
        n = len(self.pages) - first if n is None else n
        return np.stack([self.pages[first + i].offsets_words() for i in range(n)]) if n else np.zeros((0, OFFS_VEC4 * 4), np.uint32)

    def release(self):
        for page in self.pages:
            if page.buffer is not None:
                self.sink.destroy(page.buffer)
            page.buffer = None
        self.pages = []


class TriangleOrder:
    """Stored triangle -> original triangle, for geometry built with cluster_order=True.

    Within one (part, level) index range the stored triangles are in cluster order: stored triangle k is the original
    triangle ``perm[tfirst + k]`` (range-local numbers). "Original" means the position of the triangle in the part's
    index array as the model has it: level 0 -> model.indices[part.first + 3 * t : +3], level L >= 1 ->
    model.lod[part.id].indices[L - 1][3 * t : +3]. Parts and levels without a cluster range (uncullable parts, fewer than 3
    indices) were not reordered: their stored order is the original order (identity). ``cd.perm`` is memory mapped when the
    cluster set comes from the cluster cache (it is saved and re-opened after a build), so this map costs no RAM."""

    def __init__(self, cd):
        self.cd = cd

    def range_of(self, part, level):
        lr = self.cd.level_range
        part = np.asarray(part, dtype=np.int64)
        level = np.minimum(np.asarray(level, dtype=np.int64), lr.shape[1] - 1)
        return lr[part, level].astype(np.int64)

    def original(self, part, level, stored):
        """Original range-local triangle numbers of the stored triangles (arrays broadcast against each other)."""
        cd = self.cd
        part, level, stored = np.broadcast_arrays(np.asarray(part, dtype=np.int64), np.asarray(level, dtype=np.int64),
                                                  np.asarray(stored, dtype=np.int64))
        if cd.n_ranges == 0:
            return stored.copy()
        r = self.range_of(part, level)
        ok = (r >= 0) & (stored >= 0)
        rr = np.where(ok, r, 0)
        ok &= stored < cd.r_ntri[rr]
        pos = np.where(ok, cd.r_tfirst[rr] + stored, 0)
        got = np.asarray(cd.perm[pos]).astype(np.int64) if cd.n_tris else np.zeros(part.shape, np.int64)
        return np.where(ok, got, stored)


class _Layout:
    """What clusters.build_clusters / cluster_cache.make_key read of a geometry: page_of, ranges, page_bytes."""

    def __init__(self, page_of, ranges, page_bytes):
        self.page_of, self.ranges, self.page_bytes = page_of, ranges, page_bytes


def geom_prelude(n_pages, group, binding0, uniform_binding=None):
    """WGSL for a pipeline that reads ``n_pages`` pages: the page buffers geo_0 .. geo_{n-1} at (group, binding0 + i), the
    page-offset uniform ``pgo`` (the first n_pages entries of GpuGeometry.page_offsets, OFFS_VEC4 vec4<u32> each) and the two
    functions wgsl/geom.wgsl is built on: geo_word(lp, word) and geo_off(lp, section). lp = page number within this pipeline."""
    ub = binding0 + n_pages if uniform_binding is None else uniform_binding
    out = []
    for i in range(n_pages):
        out.append(f"@group({group}) @binding({binding0 + i}) var<storage, read> geo_{i}: array<u32>;")
    out.append(f"@group({group}) @binding({ub}) var<uniform> pgo: array<vec4<u32>, {OFFS_VEC4 * max(n_pages, 1)}>;")
    out.append("fn geo_off(lp: u32, s: u32) -> u32 { return pgo[lp * %du + (s >> 2u)][s & 3u]; }" % OFFS_VEC4)
    if n_pages <= 1:
        out.append("fn geo_word(lp: u32, i: u32) -> u32 { return geo_0[i]; }")
    else:
        out.append("fn geo_word(lp: u32, i: u32) -> u32 {\n  switch lp {")
        for i in range(n_pages):
            out.append(f"    case {i}u: {{ return geo_{i}[i]; }}")
        out.append("    default: { return 0u; }\n  }\n}")
    return "\n".join(out)


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
    """Bytes per page buffer: min(max_storage_buffer_binding_size, max_buffer_size) of the device, rounded down to 256 (a u32
    word index addresses 16 GiB, so there is no further cap). Limits the device does not report count as 4 GiB."""
    lim = device.limits
    def get(name):
        return lim.get(name, lim.get(name.replace("_", "-"), 1 << 32))
    return int(min(get("max_storage_buffer_binding_size"), get("max_buffer_size"))) // 256 * 256


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


def plan_pages(model, page_bytes, flags, has_anim, max_pages=None):
    """Group the parts (ordered by vertex_base) into pages so that every page's buffer (all sections, with their 256-byte
    alignment) is at most ``page_bytes``. ``flags`` (P, len(VARIABLE)) bool and ``has_anim`` (P,) bool say which streams a part
    stores. Returns a list of dicts {v0, v1, parts, counts}. Raises GeometryError for a part that fills more than a page or
    when more than ``max_pages`` pages are needed (before anything is uploaded)."""
    parts = model.parts
    order = sorted((i for i, p in enumerate(parts) if p.vertex_count > 0 or p.count > 0),
                   key=lambda i: (parts[i].vertex_base, i))
    pages, cur = [], None
    prev_end = 0

    def grown(cur, i, p, n_idx):
        counts = dict(cur["counts"]) if cur else {}
        v0 = cur["v0"] if cur else p.vertex_base
        nv = p.vertex_base + p.vertex_count - v0
        counts["pos"] = counts["nrm"] = nv
        for k, g in enumerate(VARIABLE):
            if flags[i, k]:
                counts[g] = counts.get(g, 0) + p.vertex_count
        if has_anim[i]:
            counts["anim"] = counts.get("anim", 0) + p.vertex_count
        counts["index"] = counts.get("index", 0) + n_idx
        return counts, section_layout(counts)[1] * 4

    for i in order:
        p = parts[i]
        if p.vertex_count <= 0:
            raise GeometryError(f"part {p.name!r} has indices but no vertex range")
        if p.vertex_base < prev_end:
            raise GeometryError(f"part {p.name!r} overlaps the vertices of the part before it")
        uniq, _ = _part_levels(model, p)
        n_idx = p.count + sum(len(a) for a in uniq)
        counts, nbytes = grown(cur, i, p, n_idx)
        if cur is not None and nbytes > page_bytes:
            pages.append(cur)
            cur = None
            counts, nbytes = grown(None, i, p, n_idx)
        if nbytes > page_bytes:
            raise GeometryError(f"part {p.name!r} ({p.vertex_count} vertices, {n_idx} indices) is larger than a "
                                f"{page_bytes >> 20} MiB page")
        if cur is None:
            cur = {"v0": p.vertex_base, "v1": p.vertex_base, "parts": [], "counts": {}}
        cur["parts"].append(i)
        cur["v1"] = p.vertex_base + p.vertex_count
        cur["counts"] = counts
        prev_end = cur["v1"]
    if cur is not None:
        pages.append(cur)
    if max_pages is not None and len(pages) > max_pages:
        total = sum(section_layout(pl["counts"])[1] * 4 for pl in pages)
        raise GeometryError(f"the model needs {len(pages)} geometry pages of at most {page_bytes >> 20} MiB "
                            f"({total >> 20} MiB in all); this renderer binds at most {max_pages} pages per pipeline")
    return pages


# ------------------------------------------------------------------------------------------------ build
_ORDER_RAM = 512 << 20                    # a range up to this size is read into RAM once and gathered there


def _upload_ordered(sink, page, src, first, count, dest, part, cd, ri):
    """Write the indices of one cluster-ordered range: stored triangle k = source triangle perm[tfirst + k]."""
    ntri = count // 3
    t0 = int(cd.r_tfirst[ri])
    if int(cd.r_ntri[ri]) != ntri:
        raise GeometryError(f"part {part.name!r}: the cluster range holds {int(cd.r_ntri[ri])} triangles, the index range {ntri}")
    tris = np.asarray(src[first:first + count], dtype=np.uint32)
    if count * 4 <= _ORDER_RAM:
        tris = np.ascontiguousarray(tris)               # one sequential read of the range, then gather in RAM
    tris = tris.reshape(-1, 3)
    step = INDEX_CHUNK // 3
    for a in range(0, ntri, step):
        b = min(a + step, ntri)
        blk = np.ascontiguousarray(tris[np.asarray(cd.perm[t0 + a:t0 + b], dtype=np.int64)])
        lo, hi = int(blk.min()), int(blk.max())
        if lo < page.v0 or hi >= page.v1:
            raise GeometryError(f"part {part.name!r} indexes vertices outside its page ({lo}..{hi} not in {page.v0}..{page.v1 - 1})")
        sink.write(page.buffer, (page.offs["index"] + dest + 3 * a) * 4, blk.reshape(-1) - np.uint32(page.v0))


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


def build_geometry(model, sink, page_bytes, measure=False, progress=None, max_pages=None, cluster_order=False,
                   cluster_progress=None, cluster_cache_use=True):
    """Upload model.vertices / model.indices (+ LOD levels) through ``sink``; returns a GpuGeometry.

    max_pages: raise GeometryError (before any upload) when the model needs more pages than the renderer can bind.
    cluster_order=True: store the triangles of every cullable (part, level) index range in the order of the culler's
    clusters (app/gpu/clusters.py: Morton order, 64 per cluster; built or loaded from the cluster cache before the upload).
    Vertex data, layout, offsets and every range's (first, count) are unchanged, only the order of the triangles inside a
    range differs. The result carries ``clusters`` (ClusterData) and ``order`` (TriangleOrder, stored -> original triangle).
    Default False: byte-identical to the unordered layout.
    measure=True also records the normal error (max/mean angle), the spread of source normal lengths and the
    number of zero-length normals in ``stats`` (costs one decode of every normal)."""
    parts = model.parts
    vertices, indices = model.vertices, model.indices
    if vertices is None or vertices.ndim != 2 or vertices.shape[1] != VERTEX_FLOATS or vertices.dtype != np.float32:
        raise GeometryError("vertices must be a float32 (V, 19) array")
    n = len(parts)
    geo_ids = [i for i, p in enumerate(parts) if p.vertex_count > 0 or p.count > 0]
    for i in geo_ids:
        if parts[i].vertex_count <= 0:
            raise GeometryError(f"part {parts[i].name!r} has indices but no vertex range")
    flags, tail = _scan_constants(vertices, parts, geo_ids)
    anim_src = getattr(model, "anim_vertices", None)
    has_anim = np.zeros(n, dtype=bool)
    if anim_src is not None:
        for i in geo_ids:
            has_anim[i] = _anim_nonzero(anim_src, parts[i])
    plans = plan_pages(model, page_bytes, flags, has_anim, max_pages)

    page_of = np.full(n, -1, dtype=np.int32)
    vbase = np.zeros(n, dtype=np.int64)
    vcount = np.zeros(n, dtype=np.int64)
    stream_base = np.full((n, len(VARIABLE)), -1, dtype=np.int64)
    anim_base = np.full(n, -1, dtype=np.int64)
    ranges = [[(0, 0)] for _ in range(n)]
    pages = []
    layouts = []
    nrm_stats = {"max_deg": 0.0, "sum_deg": 0.0, "count": 0, "len_min": math.inf, "len_max": 0.0, "zero": 0}

    for pi, pl in enumerate(plans):
        page = Page(index=pi, v0=pl["v0"], v1=pl["v1"], parts=pl["parts"])
        # ---- layout of the page
        index_layout = []                        # (source array, first, count, dest first index, part index)
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
            if has_anim[i]:
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
        page.counts = {"pos": page.nverts, "nrm": page.nverts, **{g: c for g, c in counts.items() if c}, "index": at}
        if n_anim:
            page.counts["anim"] = n_anim
        assert page.counts == pl["counts"], (page.counts, pl["counts"])
        page.offs, page.words = section_layout(page.counts)
        layouts.append((page, index_layout))

    clusters = order = None
    index_range = {}
    if cluster_order:
        from . import cluster_cache
        clusters = cluster_cache.get_clusters(model, _Layout(page_of, ranges, page_bytes), progress=cluster_progress,
                                              use_cache=cluster_cache_use)
        order = TriangleOrder(clusters)
        index_range = {(int(g), int(f), 3 * int(t)): ri for ri, (g, f, t) in
                       enumerate(zip(clusters.r_page, clusters.r_first, clusters.r_ntri))}

    for pi, (page, index_layout) in enumerate(layouts):
        # ---- one buffer for the whole page
        page.buffer = sink.create(page.words * 4, f"page{pi}")
        o = page.offs
        # ---- pos / nrm: one contiguous run of the model's vertices
        for a in range(page.v0, page.v1, SCAN_ROWS):
            b = min(a + SCAN_ROWS, page.v1)
            blk = np.asarray(vertices[a:b])
            sink.write(page.buffer, (o["pos"] + (a - page.v0) * 3) * 4, np.ascontiguousarray(blk[:, 0:3]))
            nrm = np.ascontiguousarray(blk[:, 3:6])
            packed = oct_pack(oct_encode(nrm))
            sink.write(page.buffer, (o["nrm"] + (a - page.v0)) * 4, packed)
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
        for i in page.parts:
            p = parts[i]
            for k, g in enumerate(VARIABLE):
                if not flags[i, k]:
                    continue
                c0, c1, bpv = STREAMS[g]
                for a in range(0, p.vertex_count, SCAN_ROWS):
                    b = min(a + SCAN_ROWS, p.vertex_count)
                    blk = np.ascontiguousarray(vertices[p.vertex_base + a:p.vertex_base + b, c0:c1])
                    sink.write(page.buffer, (o[g] + (stream_base[i, k] + a) * (bpv // 4)) * 4, blk)
        for i in page.parts:
            if anim_base[i] >= 0:
                p = parts[i]
                for a in range(0, p.vertex_count, SCAN_ROWS):
                    b = min(a + SCAN_ROWS, p.vertex_count)
                    raw = np.ascontiguousarray(anim_src[p.vertex_base + a:p.vertex_base + b]).view(np.uint8)
                    sink.write(page.buffer, (o["anim"] + (anim_base[i] + a) * (ANIM_BYTES // 4)) * 4, raw)
        # ---- indices, rewritten page-local and range-checked
        for src, first, count, dest, i in index_layout:
            ri = index_range.get((pi, dest, count))
            if ri is not None:
                _upload_ordered(sink, page, src, first, count, dest, parts[i], clusters, ri)
                continue
            for a in range(0, count, INDEX_CHUNK):
                b = min(a + INDEX_CHUNK, count)
                blk = np.asarray(src[first + a:first + b], dtype=np.uint32)
                lo, hi = int(blk.min()), int(blk.max())
                if lo < page.v0 or hi >= page.v1:
                    raise GeometryError(f"part {parts[i].name!r} indexes vertices outside its page "
                                        f"({lo}..{hi} not in {page.v0}..{page.v1 - 1})")
                sink.write(page.buffer, (o["index"] + dest + a) * 4, blk - np.uint32(page.v0))
        pages.append(page)
        if progress:
            progress(pi + 1, len(layouts))
    sink.finish()

    # ---- statistics
    nv = sum(pg.nverts for pg in pages)
    sec_bytes = lambda pg, names: sum(pg.counts.get(s, 0) * SECTION_WORDS[s] * 4 for s in names)
    stream_bytes = sum(sec_bytes(pg, [s for s in SECTION_ORDER if s != "index"]) for pg in pages)
    index_bytes = sum(pg.nindices * 4 for pg in pages)
    gpu_bytes = sum(pg.words * 4 for pg in pages)
    stats = {
        "pages": len(pages), "vertices": nv, "indices": sum(pg.nindices for pg in pages),
        "bytes_per_vertex_before": BYTES_BEFORE,
        "bytes_per_vertex_after": stream_bytes / max(nv, 1),
        "vertex_bytes": stream_bytes, "index_bytes": index_bytes, "gpu_bytes": gpu_bytes,
        "padding_bytes": gpu_bytes - stream_bytes - index_bytes,
        "page_buffer_bytes": [pg.words * 4 for pg in pages],
        "variable_parts": {g: int(flags[:, k].sum()) for k, g in enumerate(VARIABLE)},
        "cluster_ordered": bool(cluster_order),
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
                       page_bytes=page_bytes, anim_base=anim_base, clusters=clusters, order=order)


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
        words = sink.read(page.buffer).view(np.uint32)
        o = page.offs
        pos = words[o["pos"]:o["pos"] + page.nverts * 3].view(np.float32).reshape(-1, 3)
        nrm = words[o["nrm"]:o["nrm"] + page.nverts]
        out[page.v0:page.v1, 0:3] = pos
        out[page.v0:page.v1, 3:6] = oct_decode(oct_unpack(nrm))
        index = words[o["index"]:o["index"] + page.nindices]
        for i in page.parts:
            p = parts[i]
            a, b = p.vertex_base, p.vertex_base + p.vertex_count
            out[a:b, 6:19] = geom.const_tail[i]
            for k, g in enumerate(VARIABLE):
                sb = geom.stream_base[i, k]
                if sb < 0:
                    continue
                c0, c1, bpv = STREAMS[g]
                w = c1 - c0
                arr = words[o[g]:o[g] + page.counts[g] * w].view(np.float32).reshape(-1, w)
                out[a:b, c0:c1] = arr[sb:sb + p.vertex_count]
            for level, (first, count) in enumerate(geom.ranges[i]):
                idx[(i, level)] = index[first:first + count] + np.uint32(page.v0)
    return out, idx
