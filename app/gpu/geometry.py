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

Compressed pages (build_geometry(..., compress=True), cluster-ordered geometry only). The vertices of every part are renumbered in
first-use order of its cluster-ordered triangle streams (clusters.py vorder; the vertex VALUES are unchanged), parts start at
multiples of 64 vertices, and the index data of a page is stored per cluster of 64 triangles (192 logical index positions, every
cluster range starts at a multiple of 192, so page cluster = position / 192):
    cdir   1 word per cluster: the page-local base vertex, or WIDE | slot when the cluster's vertex span does not fit 16 bits
    idx16  96 words per cluster: 192 x u16, the vertex minus the base (WIDE: the low 16 bits of the page-local vertex)
    idxhi  96 words per WIDE cluster: 192 x u16, the high 16 bits of the page-local vertex
6 B per index triangle (12 B for WIDE clusters) instead of 12. There is no hardware index buffer: geom.wgsl g_index decodes a
logical position, draws are non-indexed (vertex_index = logical position) or read through the culler's gather.

Quantised positions (stage 2, build_geometry(..., compress=2), app/gpu/quant.py): the "pos" section (12 B per vertex) is replaced by
    posb   6 words per 64 vertices: the block's grid (origin, power-of-two step per axis, bits per axis, data offset)
    posq   the blocks' fixed-point coordinates, 2 x (bits x + bits y + bits z) words per block
A block whose grid would move a vertex by more than the error budget (1/16 pixel at the closest zoom the viewer allows, see
quant.py) stays float32 inside posq (flag in posb). wgsl/geom.wgsl g_pos decodes. The cluster bounds of the quantised parts are
inflated by the realised maximum error of the part, so hi-Z culling never rejects a pixel of the decoded geometry.

The buffer back end is a "sink" (GpuSink for wgpu, HostSink for tests without an adapter), both with
create(size, label) / write(handle, offset, array) / read(handle) / finish().
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np

from app.viewer import lod as _lod

from . import clusters as _cl
from . import quant as _q

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
SECTION_ORDER = ("pos", "nrm", "dpos", "dnrm", "fib", "col", "uv", "anim", "index", "cdir", "idx16", "idxhi", "posq", "posb")
SECTION_INDEX = {n: i for i, n in enumerate(SECTION_ORDER)}
SECTION_WORDS = {"pos": 3, "nrm": 1, "dpos": 3, "dnrm": 3, "fib": 1, "col": 4, "uv": 2, "anim": ANIM_BYTES // 4, "index": 1,
                 "cdir": 1, "idx16": 1, "idxhi": 1, "posq": 1, "posb": _q.TABLE_WORDS}   # (cdir .. posq: counted in words; posb: per block)
CL_POS = 192                                         # logical index positions of a cluster (64 triangles x 3)
CL_WORDS = 96                                        # words of one cluster's 192 x u16
WIDE = 0x80000000                                    # cdir flag: the cluster's indices need 32 bits (idx16 low halves + idxhi)
ALIGN_WORDS = 64                                     # 256 bytes
OFFS_VEC4 = 4                                        # a page's offsets in the shaders' uniform: four vec4<u32> (14 used)


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
    nlogical: int = 0                    # compressed pages: logical index positions (a multiple of 192); 0 = u32 index section
    nwide: int = 0                       # compressed pages: clusters with 32-bit indices

    @property
    def nverts(self):
        return self.v1 - self.v0

    @property
    def compressed(self):
        return self.nlogical > 0

    @property
    def quantised(self):
        """Positions are stored as fixed-point blocks (posb / posq) instead of float32 (pos)."""
        return self.counts.get("posb", 0) > 0

    @property
    def nindices(self):
        """Index positions of the page (compressed pages: logical positions, including the padding of partial clusters)."""
        return self.nlogical if self.nlogical else self.counts.get("index", 0)

    @property
    def index_section_bytes(self):
        """Bytes the page spends on index data (u32 section, or cdir + idx16 + idxhi)."""
        return 4 * sum(self.counts.get(k, 0) for k in ("index", "cdir", "idx16", "idxhi"))

    @property
    def stream_verts(self):
        return {g: c for g, c in self.counts.items() if g not in ("pos", "nrm", "index") and c}

    @property
    def index_byte_offset(self):
        if self.compressed:
            raise GeometryError("a compressed page has no hardware index buffer (draw non-indexed, geom.wgsl g_index)")
        return self.offs["index"] * 4

    @property
    def index_bytes(self):
        if self.compressed:
            raise GeometryError("a compressed page has no hardware index buffer")
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
    compressed: bool = False             # pages hold renumbered vertices and u16 cluster-relative indices (see the module docstring)
    stage: int = 0                       # 0 plain pages, 1 compressed indices, 2 + quantised positions (the shaders' GEO_CMP / GEO_QPOS)
    quant: dict = None                   # stage 2: {"budget": per part (part space), "err": realised max error per part, "pixels": ..., ...}

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


def geom_prelude(n_pages, group, binding0, uniform_binding=None, compressed=False):
    """WGSL for a pipeline that reads ``n_pages`` pages: the page buffers geo_0 .. geo_{n-1} at (group, binding0 + i), the
    page-offset uniform ``pgo`` (the first n_pages entries of GpuGeometry.page_offsets, OFFS_VEC4 vec4<u32> each), the constant
    GEO_CMP (the pages are compressed: wgsl/geom.wgsl decodes indices from cdir / idx16 / idxhi) and the two functions
    wgsl/geom.wgsl is built on: geo_word(lp, word) and geo_off(lp, section). lp = page number within this pipeline.
    ``compressed`` is the stage (GpuGeometry.stage; True = 1): 1 = compressed indices, 2 = quantised positions as well (GEO_QPOS).
    A pipeline built for a stage must not be used with pages of another stage: include the stage in the key of every cached
    shader module."""
    ub = binding0 + n_pages if uniform_binding is None else uniform_binding
    stage = int(compressed)
    out = [f"const GEO_CMP: bool = {'true' if stage >= 1 else 'false'};",
           f"const GEO_QPOS: bool = {'true' if stage >= 2 else 'false'};"]
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


_part_levels = _cl.part_levels


def _align(n, a):
    return -(-int(n) // a) * a


def _padded(count):
    """Logical index positions a cluster range of ``count`` indices occupies in a compressed page (whole clusters)."""
    return _align(count, CL_POS)


def plan_pages(model, page_bytes, flags, has_anim, max_pages=None, cmp=None, qp=None):
    """Group the parts (ordered by vertex_base) into pages so that every page's buffer (all sections, with their 256-byte
    alignment) is at most ``page_bytes``. ``flags`` (P, len(VARIABLE)) bool and ``has_anim`` (P,) bool say which streams a part
    stores. ``cmp`` = (clusters per part, wide clusters per part) plans compressed pages (vertices renumbered per part and
    64-aligned, index data per cluster); None = u32 index section. ``qp`` = (blocks per part, quantised position words per part)
    (needs ``cmp``) stores the positions quantised (stage 2). Returns a list of dicts {v0, v1, parts, counts, vend}.
    Raises GeometryError for a part that fills more than a page or when more than ``max_pages`` pages are needed (before
    anything is uploaded)."""
    parts = model.parts
    order = sorted((i for i, p in enumerate(parts) if p.vertex_count > 0 or p.count > 0),
                   key=lambda i: (parts[i].vertex_base, i))
    pages, cur = [], None
    prev_end = 0

    def grown(cur, i, p, n_idx):
        counts = dict(cur["counts"]) if cur else {}
        v0 = cur["v0"] if cur else p.vertex_base
        if cmp is None:
            vend = 0
            nv = p.vertex_base + p.vertex_count - v0
            counts["index"] = counts.get("index", 0) + n_idx
        else:
            vend = _align(cur["vend"] if cur else 0, 64) + p.vertex_count
            nv = _align(vend, 64)
            counts["cdir"] = counts.get("cdir", 0) + int(cmp[0][i])
            counts["idx16"] = counts.get("idx16", 0) + CL_WORDS * int(cmp[0][i])
            if cmp[1][i]:
                counts["idxhi"] = counts.get("idxhi", 0) + CL_WORDS * int(cmp[1][i])
        if qp is None:
            counts["pos"] = counts["nrm"] = nv
        else:
            counts["nrm"] = nv
            counts["posb"] = counts.get("posb", 0) + int(qp[0][i])
            counts["posq"] = counts.get("posq", 0) + int(qp[1][i])
        for k, g in enumerate(VARIABLE):
            if flags[i, k]:
                counts[g] = counts.get(g, 0) + p.vertex_count
        if has_anim[i]:
            counts["anim"] = counts.get("anim", 0) + p.vertex_count
        return counts, section_layout(counts)[1] * 4, vend

    for i in order:
        p = parts[i]
        if p.vertex_count <= 0:
            raise GeometryError(f"part {p.name!r} has indices but no vertex range")
        if p.vertex_base < prev_end:
            raise GeometryError(f"part {p.name!r} overlaps the vertices of the part before it")
        uniq, _ = _part_levels(model, p)
        n_idx = p.count + sum(len(a) for a in uniq)
        counts, nbytes, vend = grown(cur, i, p, n_idx)
        if cur is not None and nbytes > page_bytes:
            pages.append(cur)
            cur = None
            counts, nbytes, vend = grown(None, i, p, n_idx)
        if nbytes > page_bytes:
            raise GeometryError(f"part {p.name!r} ({p.vertex_count} vertices, {n_idx} indices) is larger than a "
                                f"{page_bytes >> 20} MiB page")
        if cur is None:
            cur = {"v0": p.vertex_base, "v1": p.vertex_base, "parts": [], "counts": {}, "vend": 0}
        cur["parts"].append(i)
        cur["v1"] = p.vertex_base + p.vertex_count
        cur["counts"] = counts
        cur["vend"] = vend
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


def _compress_tables(cd, n_parts):
    """(clusters per part, wide clusters per part) of a cluster set: what plan_pages needs to size compressed pages."""
    ncl = np.zeros(n_parts, dtype=np.int64)
    np.add.at(ncl, np.asarray(cd.r_part, dtype=np.int64), np.asarray(cd.r_ccount, dtype=np.int64))
    nwide = np.zeros(n_parts, dtype=np.int64)
    r_part = np.asarray(cd.r_part, dtype=np.int64)
    step = 1 << 22
    for a in range(0, cd.n_clusters, step):
        b = min(a + step, cd.n_clusters)
        rp = r_part[np.asarray(cd.cl_range[a:b], dtype=np.int64)]
        w = (np.asarray(cd.cl_base[a:b]) >> np.uint32(31)).astype(np.int64)
        nwide += np.bincount(rp, weights=w, minlength=n_parts).astype(np.int64)
    return ncl, nwide


def _quant_plan(model, cd, geo_ids, n):
    """Stage 2: the grid of every 64-vertex block of every part (quant.plan_part), in the part's first-use vertex order.
    Returns {"blocks" (n,), "words" (n,), "err" (n,) realised maximum position error per part (part space), "budget" (n,),
    "tables": {part: (nb, 6) uint32}, ...statistics}."""
    vertices = model.vertices
    budget, (wpp, dmin) = _q.budget_part_space(model, geo_ids)
    blocks = np.zeros(n, dtype=np.int64)
    words = np.zeros(n, dtype=np.int64)
    err = np.zeros(n, dtype=np.float64)
    bud = np.zeros(n, dtype=np.float64)
    tables = {}
    nfloat = 0
    bits_sum = 0
    for i in geo_ids:
        p = model.parts[i]
        vo = np.asarray(cd.vorder[p.vertex_base:p.vertex_base + p.vertex_count]).astype(np.int64)
        pos = np.asarray(vertices[vo, 0:3], dtype=np.float32)
        tab, w, em, st = _q.plan_part(pos, budget[i])
        tables[i] = tab
        blocks[i], words[i], err[i], bud[i] = st["blocks"], w, em, budget[i]
        nfloat += st["float_blocks"]
    return {"blocks": blocks, "words": words, "err": err, "budget": bud, "tables": tables, "pixels": _q.qerr_pixels(),
            "world_per_pixel": wpp, "min_distance": dmin, "float_blocks": nfloat, "total_blocks": int(blocks.sum())}


def _inflate_bounds(cd, err):
    """The cluster set with every cluster box grown by the realised position error of its part (quantised positions move a
    vertex by at most that much, so the boxes of the float positions would not contain the decoded ones). The cache's own arrays
    are not touched."""
    if not np.any(err > 0):
        return cd
    r_part = np.asarray(cd.r_part, dtype=np.int64)
    geom = np.array(cd.cl_geom, dtype=np.float32)
    step = 1 << 22
    for a in range(0, len(geom), step):
        b = min(a + step, len(geom))
        e = err[r_part[np.asarray(cd.cl_range[a:b], dtype=np.int64)]] * 1.0001
        h = geom[a:b, 4:7].astype(np.float64) + e[:, None]
        geom[a:b, 4:7] = np.nextafter(h.astype(np.float32), np.float32(np.inf))
    return dataclasses.replace(cd, cl_geom=geom)


def _upload_quantised(sink, page, vertices, vo, vbase, qbase, tab):
    """Write the block table and the fixed-point data of one part's positions (first-use order ``vo``)."""
    pos = np.asarray(vertices[vo, 0:3], dtype=np.float32)
    data = _q.encode_part(pos, tab)
    tabp = tab.copy()
    tabp[:, 0] += np.uint32(qbase)
    o = page.offs
    sink.write(page.buffer, (o["posb"] + (vbase // _q.BLOCK) * _q.TABLE_WORDS) * 4, tabp)
    step = 1 << 24
    for a in range(0, len(data), step):
        sink.write(page.buffer, (o["posq"] + qbase + a) * 4, np.ascontiguousarray(data[a:a + step]))


def _upload_compressed(sink, page, src, first, count, dest, part, cd, ri, vbase, newof):
    """Write one cluster range of a compressed page: stored triangle k = source triangle perm[tfirst + k], vertices renumbered
    (newof: part-local old -> part-local new), as cdir / idx16 / idxhi entries of the range's clusters."""
    ntri = count // 3
    t0, c0 = int(cd.r_tfirst[ri]), int(cd.r_cfirst[ri])
    if int(cd.r_ntri[ri]) != ntri:
        raise GeometryError(f"part {part.name!r}: the cluster range holds {int(cd.r_ntri[ri])} triangles, the index range {ntri}")
    if dest % CL_POS:
        raise GeometryError(f"part {part.name!r}: compressed range at index position {dest} is not cluster aligned")
    tris = np.asarray(src[first:first + count], dtype=np.uint32)
    if count * 4 <= _ORDER_RAM:
        tris = np.ascontiguousarray(tris)
    tris = tris.reshape(-1, 3)
    vb = part.vertex_base
    o = page.offs
    step = (INDEX_CHUNK // 3) // 64 * 64
    for a in range(0, ntri, step):
        b = min(a + step, ntri)
        m = b - a
        ncl = -(-m // 64)
        sel = tris[np.asarray(cd.perm[t0 + a:t0 + b], dtype=np.int64)].astype(np.int64) - vb
        if sel.min() < 0 or sel.max() >= part.vertex_count:
            raise GeometryError(f"part {part.name!r} indexes vertices outside its own range")
        new = newof[sel].reshape(-1)
        cb = np.asarray(cd.cl_base[c0 + a // 64:c0 + a // 64 + ncl])
        wide = (cb >> np.uint32(31)) != 0
        base = (cb & np.uint32(0x7FFFFFFF)).astype(np.int64)
        flat = np.full(ncl * CL_POS, -1, dtype=np.int64)
        flat[:m * 3] = new
        blk = flat.reshape(ncl, CL_POS)
        pad = blk < 0
        blk = np.where(pad, base[:, None], blk)                         # padding: the cluster's base vertex (zero-area slots)
        if not np.array_equal(blk.min(axis=1), base):
            raise GeometryError(f"part {part.name!r}: the cluster cache's base vertices do not match the vertex order")
        off = blk - base[:, None]
        if (off[~wide] > 65535).any():
            raise GeometryError(f"part {part.name!r}: a cluster not flagged wide spans more than 16 bits")
        pl = blk + vbase                                                # page-local vertex
        low = np.where(wide[:, None], pl & 0xFFFF, off).astype(np.uint16)
        cdir = (base + vbase).astype(np.uint32)
        nw = int(wide.sum())
        if nw:
            slot = page.nwide + np.arange(nw, dtype=np.uint32)
            cdir[wide] = np.uint32(WIDE) | slot.astype(np.uint32)
            hi = (pl[wide] >> 16).astype(np.uint16)
            sink.write(page.buffer, (o["idxhi"] + int(page.nwide) * CL_WORDS) * 4, np.ascontiguousarray(hi).view(np.uint32))
            page.nwide += nw
        pc = dest // CL_POS + a // 64
        sink.write(page.buffer, (o["cdir"] + pc) * 4, cdir)
        sink.write(page.buffer, (o["idx16"] + pc * CL_WORDS) * 4, np.ascontiguousarray(low).view(np.uint32))


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
                   cluster_progress=None, cluster_cache_use=True, compress=False):
    """Upload model.vertices / model.indices (+ LOD levels) through ``sink``; returns a GpuGeometry.

    max_pages: raise GeometryError (before any upload) when the model needs more pages than the renderer can bind.
    cluster_order=True: store the triangles of every cullable (part, level) index range in the order of the culler's
    clusters (app/gpu/clusters.py: Morton order, 64 per cluster; built or loaded from the cluster cache before the upload).
    Vertex data, layout, offsets and every range's (first, count) are unchanged, only the order of the triangles inside a
    range differs. The result carries ``clusters`` (ClusterData) and ``order`` (TriangleOrder, stored -> original triangle).
    compress (needs cluster_order and a static model; silently off otherwise, see GpuGeometry.stage): False / 0 = plain pages
    (byte-identical to the unordered layout), True / 1 = compressed indices (stage 1), 2 = and quantised positions (stage 2),
    "auto" = the smallest stage whose pages fit ``page_bytes`` x ``max_pages`` (plain if they do). See the module docstring.
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
    clusters0 = None
    if cluster_order:
        from . import cluster_cache
        clusters0 = cluster_cache.get_clusters(model, None, progress=cluster_progress, use_cache=cluster_cache_use)
    cmp = None
    qp = None
    qplans = None
    plans = None
    stage = 0
    want = "auto" if compress == "auto" else (min(int(compress), 2) if compress else 0)
    if want and clusters0 is not None and clusters0.n_ranges > 0 and anim_src is None:
        if want == "auto":                       # the smallest stage whose pages fit the capacity
            try:
                plans = plan_pages(model, page_bytes, flags, has_anim, max_pages, None)
            except GeometryError:
                cmp = _compress_tables(clusters0, n)
                try:
                    plans = plan_pages(model, page_bytes, flags, has_anim, max_pages, cmp)
                    stage = 1
                except GeometryError:
                    qplans = _quant_plan(model, clusters0, geo_ids, n)
                    qp = (qplans["blocks"], qplans["words"])
                    plans = plan_pages(model, page_bytes, flags, has_anim, max_pages, cmp, qp)
                    stage = 2
        else:
            cmp = _compress_tables(clusters0, n)
            stage = want
            if want >= 2:
                qplans = _quant_plan(model, clusters0, geo_ids, n)
                qp = (qplans["blocks"], qplans["words"])
    if plans is None:
        plans = plan_pages(model, page_bytes, flags, has_anim, max_pages, cmp, qp)

    page_of = np.full(n, -1, dtype=np.int32)
    vbase = np.zeros(n, dtype=np.int64)
    vcount = np.zeros(n, dtype=np.int64)
    stream_base = np.full((n, len(VARIABLE)), -1, dtype=np.int64)
    anim_base = np.full(n, -1, dtype=np.int64)
    ranges = [[(0, 0)] for _ in range(n)]
    qbase = np.zeros(n, dtype=np.int64)
    pages = []
    layouts = []
    nrm_stats = {"max_deg": 0.0, "sum_deg": 0.0, "count": 0, "len_min": math.inf, "len_max": 0.0, "zero": 0}

    for pi, pl in enumerate(plans):
        page = Page(index=pi, v0=pl["v0"], v1=pl["v1"], parts=pl["parts"])
        # ---- layout of the page
        index_layout = []                        # (source array, first, count, dest first index, part index, slot)
        at = 0
        counts = {g: 0 for g in VARIABLE}
        n_anim = 0
        vend = 0
        qat = 0
        for i in pl["parts"]:
            p = parts[i]
            page_of[i] = pi
            if cmp is None:
                vbase[i] = p.vertex_base - page.v0
            else:
                vbase[i] = _align(vend, 64)
                vend = vbase[i] + p.vertex_count
            vcount[i] = p.vertex_count
            if qp is not None:
                qbase[i] = qat
                qat += int(qp[1][i])
            for k, g in enumerate(VARIABLE):
                if flags[i, k]:
                    stream_base[i, k] = counts[g]
                    counts[g] += p.vertex_count
            if has_anim[i]:
                anim_base[i] = n_anim
                n_anim += p.vertex_count
            lv = [(0, p.count)] if p.count else [(0, 0)]
            if p.count:
                if cmp is not None:
                    at = _align(at, CL_POS)
                lv = [(at, p.count)]
                if cmp is None or p.count >= 3:
                    index_layout.append((indices, p.first, p.count, at, i, 0))
                at += p.count if cmp is None else (_padded(p.count) if p.count >= 3 else 0)
            uniq, order = _part_levels(model, p)
            placed = []
            for u, arr in enumerate(uniq):
                if cmp is not None:
                    at = _align(at, CL_POS)
                if cmp is None or len(arr) >= 3:
                    index_layout.append((arr, 0, len(arr), at, i, 1 + u))
                placed.append((at, len(arr)))
                at += len(arr) if cmp is None else (_padded(len(arr)) if len(arr) >= 3 else 0)
            ranges[i] = lv + [placed[o] for o in order]
        if cmp is None:
            page.counts = {"pos": page.nverts, "nrm": page.nverts, **{g: c for g, c in counts.items() if c}, "index": at}
        else:
            page.v0, page.v1 = 0, _align(vend, 64)
            page.nlogical = at
            page.counts = {"nrm": page.nverts, **{g: c for g, c in counts.items() if c},
                           "cdir": at // CL_POS, "idx16": at // CL_POS * CL_WORDS}
            if qp is None:
                page.counts["pos"] = page.nverts
            else:
                page.counts["posb"] = page.nverts // _q.BLOCK
                page.counts["posq"] = qat
            if pl["counts"].get("idxhi"):
                page.counts["idxhi"] = pl["counts"]["idxhi"]
        if n_anim:
            page.counts["anim"] = n_anim
        assert page.counts == pl["counts"], (page.counts, pl["counts"])
        page.offs, page.words = section_layout(page.counts)
        layouts.append((page, index_layout))

    clusters = order = None
    index_range = {}
    if clusters0 is not None:
        clusters = _cl.bind_layout(clusters0, page_of, ranges)
        if qplans is not None:
            clusters = _inflate_bounds(clusters, qplans["err"])
        order = TriangleOrder(clusters)
        if cmp is None:
            index_range = {(int(g), int(f), 3 * int(t)): ri for ri, (g, f, t) in
                           enumerate(zip(clusters.r_page, clusters.r_first, clusters.r_ntri))}
        else:
            index_range = {(int(a), int(b)): ri for ri, (a, b) in enumerate(zip(clusters.r_part, clusters.r_slot))}

    for pi, (page, index_layout) in enumerate(layouts):
        # ---- one buffer for the whole page
        page.buffer = sink.create(page.words * 4, f"page{pi}")
        o = page.offs
        if cmp is None:
            # ---- pos / nrm: one contiguous run of the model's vertices
            for a in range(page.v0, page.v1, SCAN_ROWS):
                b = min(a + SCAN_ROWS, page.v1)
                blk = np.asarray(vertices[a:b])
                sink.write(page.buffer, (o["pos"] + (a - page.v0) * 3) * 4, np.ascontiguousarray(blk[:, 0:3]))
                nrm = np.ascontiguousarray(blk[:, 3:6])
                packed = oct_pack(oct_encode(nrm))
                sink.write(page.buffer, (o["nrm"] + (a - page.v0)) * 4, packed)
                if measure:
                    _measure_normals(nrm, packed, nrm_stats)
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
        else:
            # ---- every stream of every part, gathered in the part's first-use vertex order
            for i in page.parts:
                p = parts[i]
                vo = np.asarray(clusters.vorder[p.vertex_base:p.vertex_base + p.vertex_count]).astype(np.int64)
                for a in range(0, p.vertex_count, SCAN_ROWS):
                    b = min(a + SCAN_ROWS, p.vertex_count)
                    blk = np.asarray(vertices[vo[a:b]])
                    at_v = int(vbase[i]) + a
                    if qp is None:
                        sink.write(page.buffer, (o["pos"] + at_v * 3) * 4, np.ascontiguousarray(blk[:, 0:3]))
                    nrm = np.ascontiguousarray(blk[:, 3:6])
                    packed = oct_pack(oct_encode(nrm))
                    sink.write(page.buffer, (o["nrm"] + at_v) * 4, packed)
                    if measure:
                        _measure_normals(nrm, packed, nrm_stats)
                    for k, g in enumerate(VARIABLE):
                        if flags[i, k]:
                            c0, c1, bpv = STREAMS[g]
                            sink.write(page.buffer, (o[g] + (stream_base[i, k] + a) * (bpv // 4)) * 4,
                                       np.ascontiguousarray(blk[:, c0:c1]))
                if qp is not None:
                    _upload_quantised(sink, page, vertices, vo, int(vbase[i]), int(qbase[i]), qplans["tables"][i])
        for i in page.parts:
            if anim_base[i] >= 0:
                p = parts[i]
                for a in range(0, p.vertex_count, SCAN_ROWS):
                    b = min(a + SCAN_ROWS, p.vertex_count)
                    raw = np.ascontiguousarray(anim_src[p.vertex_base + a:p.vertex_base + b]).view(np.uint8)
                    sink.write(page.buffer, (o["anim"] + (anim_base[i] + a) * (ANIM_BYTES // 4)) * 4, raw)
        # ---- indices
        if cmp is None:
            # rewritten page-local and range-checked
            for src, first, count, dest, i, _slot in index_layout:
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
        else:
            cur_part, newof = -1, None
            for src, first, count, dest, i, slot in index_layout:
                if i != cur_part:
                    p = parts[i]
                    vo = np.asarray(clusters.vorder[p.vertex_base:p.vertex_base + p.vertex_count]).astype(np.int64) - p.vertex_base
                    newof = np.empty(p.vertex_count, dtype=np.int64)
                    newof[vo] = np.arange(p.vertex_count, dtype=np.int64)
                    cur_part = i
                ri = index_range.get((i, slot))
                if ri is None:
                    raise GeometryError(f"part {parts[i].name!r}: no cluster range for index range {slot}")
                _upload_compressed(sink, page, src, first, count, dest, parts[i], clusters, ri, int(vbase[i]), newof)
            if page.nwide * CL_WORDS != page.counts.get("idxhi", 0):
                raise GeometryError(f"page {pi}: {page.nwide} wide clusters, {page.counts.get('idxhi', 0) // CL_WORDS} planned")
        pages.append(page)
        if progress:
            progress(pi + 1, len(layouts))
    sink.finish()

    # ---- statistics
    nv = sum(pg.nverts for pg in pages)
    sec_bytes = lambda pg, names: sum(pg.counts.get(s, 0) * SECTION_WORDS[s] * 4 for s in names)
    stream_bytes = sum(sec_bytes(pg, [s for s in SECTION_ORDER if s not in ("index", "cdir", "idx16", "idxhi")]) for pg in pages)
    index_bytes = sum(pg.index_section_bytes for pg in pages)
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
        "compressed": cmp is not None,
        "stage": stage,
        "wide_clusters": sum(pg.nwide for pg in pages),
        "clusters": sum(pg.counts.get("cdir", 0) for pg in pages),
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
                       page_bytes=page_bytes, anim_base=anim_base, clusters=clusters, order=order, compressed=cmp is not None,
                       stage=stage, quant=(None if qplans is None else {k: v for k, v in qplans.items() if k != "tables"}))


def _measure_normals(nrm, packed, nrm_stats):
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


# ------------------------------------------------------------------------------------------------ decode (tests, checks)
def decode_page_indices(page, words, first, count):
    """Page-local vertex numbers of ``count`` logical index positions starting at ``first`` of a compressed page (numpy twin of
    geom.wgsl g_index)."""
    o = page.offs
    pos = np.arange(first, first + count, dtype=np.int64)
    cl = pos // CL_POS
    j = pos - cl * CL_POS
    e = words[o["cdir"] + cl].astype(np.int64)
    w = words[o["idx16"] + cl * CL_WORDS + (j >> 1)].astype(np.int64)
    lo = (w >> ((j & 1) * 16)) & 0xFFFF
    wide = e >= WIDE
    out = e + lo
    if wide.any():
        hw = words[o["idxhi"] + (e[wide] & 0x7FFFFFFF) * CL_WORDS + (j[wide] >> 1)].astype(np.int64)
        out[wide] = lo[wide] | (((hw >> ((j[wide] & 1) * 16)) & 0xFFFF) << 16)
    return out


def decode_geometry(geom, model):
    """Rebuild (vertices (V,19) float32, index arrays) from the stored data, for comparison with the source model.
    Returns (vertices, indices) where vertices rows not owned by any part stay zero, and indices is
    {(part index, level): global uint32 array}. Normals come back as unit vectors. Compressed geometry: the rows are put back
    at the model's own vertex numbers (clusters.vorder) and the index arrays hold those numbers, in stored triangle order."""
    sink = geom.sink
    parts = model.parts
    V = len(model.vertices)
    out = np.zeros((V, VERTEX_FLOATS), dtype=np.float32)
    idx = {}
    for page in geom.pages:
        words = sink.read(page.buffer).view(np.uint32)
        o = page.offs
        if page.quantised:
            pos = np.zeros((page.nverts, 3), dtype=np.float32)
            tabs = words[o["posb"]:o["posb"] + page.nverts // _q.BLOCK * _q.TABLE_WORDS].reshape(-1, _q.TABLE_WORDS)
            for i in page.parts:
                vb, nvp = int(geom.vbase[i]), parts[i].vertex_count
                nb = -(-nvp // _q.BLOCK)
                pos[vb:vb + nvp] = _q.decode_part(tabs[vb // _q.BLOCK:vb // _q.BLOCK + nb], words[o["posq"]:], nvp)
        else:
            pos = words[o["pos"]:o["pos"] + page.nverts * 3].view(np.float32).reshape(-1, 3)
        nrm = oct_decode(oct_unpack(words[o["nrm"]:o["nrm"] + page.nverts]))
        if not page.compressed:
            out[page.v0:page.v1, 0:3] = pos
            out[page.v0:page.v1, 3:6] = nrm
            index = words[o["index"]:o["index"] + page.nindices]
        for i in page.parts:
            p = parts[i]
            a, b = p.vertex_base, p.vertex_base + p.vertex_count
            rows = slice(a, b)
            vb = int(geom.vbase[i])
            if page.compressed:
                rows = np.asarray(geom.clusters.vorder[a:b]).astype(np.int64)
                out[rows, 0:3] = pos[vb:vb + p.vertex_count]
                out[rows, 3:6] = nrm[vb:vb + p.vertex_count]
            out[rows, 6:19] = geom.const_tail[i]
            for k, g in enumerate(VARIABLE):
                sb = geom.stream_base[i, k]
                if sb < 0:
                    continue
                c0, c1, bpv = STREAMS[g]
                w = c1 - c0
                arr = words[o[g]:o[g] + page.counts[g] * w].view(np.float32).reshape(-1, w)
                out[rows, c0:c1] = arr[sb:sb + p.vertex_count]
            for level, (first, count) in enumerate(geom.ranges[i]):
                if page.compressed:
                    if count < 3:
                        idx[(i, level)] = np.zeros(0, dtype=np.uint32)
                        continue
                    local = decode_page_indices(page, words, first, count) - vb
                    vo = np.asarray(geom.clusters.vorder[a:b]).astype(np.int64)
                    idx[(i, level)] = vo[local].astype(np.uint32)
                else:
                    idx[(i, level)] = index[first:first + count] + np.uint32(page.v0)
    return out, idx
