"""Spike: pack clustered geometry into pages, replicate models on a 3D grid, camera maths.

Geometry is shared between copies (instancing); every copy has its own transform and item id.
Packed GPU layout (see gpu.py for the shaders):
  clusters  (C,12) uint32 : centre xyz f32 | radius f32 | cone snorm8x4 | meta | vtx_first | idx_byte_off | half-extent xyz f32 | pad
            meta = vcount | tcount<<7 | vpage<<14 | ipage<<18
  vertex pages: 10 bytes per vertex (x,y,z uint16, octahedral nx,ny int16), page <= page_bytes
  index pages : 3 bytes per triangle (uint8 local indices), cluster start 4-byte aligned
  parts     (P,2,4) f32 : lo, ext
  instances (J,4,4) f32 : three rows [A|t] of the world transform, then (scale, item_id bits, part_id bits, 0)
  ci_table  (N,2) uint32 : (instance, cluster) for every cluster instance
"""
import math

import numpy as np

import clusters as CL

CW = 12  # words per cluster record


class Geometry:
    def __init__(self, cache_dir, names, page_bytes=64 << 20):
        mods = [CL.load_model(f"{cache_dir}/{n}") for n in names]
        self.names = list(names)
        self.stats = [m["stats"] for m in mods]
        self.model_part0 = np.cumsum([0] + [len(m["part_lo"]) for m in mods])
        self.model_bbox = []
        cl_off, v_off, i_off = 0, 0, 0
        lo_all, ext_all, cstart, vfirst, ioff, vtx, idx = [], [], [0], [], [], [], []
        parts_tris = []
        center, radius, cone, vcount, tcount, half = [], [], [], [], [], []
        for m in mods:
            lo, ext = m["part_lo"], m["part_ext"]
            self.model_bbox.append((lo.min(0), (lo + ext).max(0)))
            lo_all.append(lo)
            ext_all.append(ext)
            cs = m["part_cstart"]
            cstart.extend((cs[1:] + cl_off).tolist())
            tc = m["c_tcount"].astype(np.int64)
            parts_tris.append(np.add.reduceat(tc, cs[:-1]))
            vfirst.append(m["c_vfirst"] + v_off)
            ioff.append(m["c_ioff"] + i_off)
            vtx.append(m["vtx16"])
            idx.append(m["idx8"])
            center.append(m["c_center"])
            radius.append(m["c_radius"])
            half.append(m["c_half"])
            cone.append(m["c_cone"])
            vcount.append(m["c_vcount"])
            tcount.append(m["c_tcount"])
            cl_off += len(m["c_tcount"])
            v_off += len(m["vtx16"])
            i_off += len(m["idx8"])
        self.part_lo = np.concatenate(lo_all)
        self.part_ext = np.concatenate(ext_all)
        self.part_cstart = np.array(cstart, dtype=np.int64)
        self.part_tris = np.concatenate(parts_tris)
        vfirst = np.concatenate(vfirst)
        ioff = np.concatenate(ioff)
        vcount = np.concatenate(vcount).astype(np.int64)
        tcount = np.concatenate(tcount).astype(np.int64)
        self.n_clusters = len(vcount)
        self.tcount = tcount
        vtx = np.concatenate(vtx)
        idx = np.concatenate(idx)
        # pages: a cluster never straddles a page
        vpage, vloc, self.vpages = self._pages(vfirst, vcount, vtx, 10, page_bytes)
        ibytes = ((tcount * 3 + 3) // 4) * 4
        ipage, iloc, self.ipages = self._pages(ioff, ibytes, idx, 1, page_bytes)
        rec = np.zeros((self.n_clusters, CW), dtype=np.uint32)
        rec[:, 0:3] = np.concatenate(center).view(np.uint32)
        rec[:, 3] = np.concatenate(radius).view(np.uint32)
        rec[:, 4] = np.ascontiguousarray(np.concatenate(cone)).view(np.uint32).reshape(-1)
        rec[:, 5] = (vcount | (tcount << 7) | (vpage << 14) | (ipage << 18)).astype(np.uint32)
        rec[:, 6] = vloc
        rec[:, 7] = iloc
        rec[:, 8:11] = np.concatenate(half).view(np.uint32)
        self.cluster_rec = rec
        self.total_tris_unique = int(tcount.sum())
        self.total_verts_unique = int(len(vtx))

    @staticmethod
    def _pages(first, count, data, elem_bytes, page_bytes):
        """first: start element of each cluster in data (increasing, contiguous); returns page id, local start, page byte arrays."""
        cap = page_bytes // elem_bytes
        end = first + count
        n = len(first)
        page = np.zeros(n, dtype=np.int64)
        local = np.zeros(n, dtype=np.int64)
        pages = []
        c0 = 0
        p = 0
        while c0 < n:
            base = first[c0]
            c1 = int(np.searchsorted(end, base + cap, side="right"))
            c1 = max(c1, c0 + 1)
            page[c0:c1] = p
            local[c0:c1] = first[c0:c1] - base
            pages.append(np.ascontiguousarray(data[base:end[c1 - 1]]).tobytes())
            c0 = c1
            p += 1
        return page, local, pages

    def bytes_total(self):
        return (sum(len(p) for p in self.vpages) + sum(len(p) for p in self.ipages)
                + self.cluster_rec.nbytes + self.part_lo.nbytes * 2)


class Scene:
    def __init__(self, geo, dims, pitch_gap=0.12, seed=1):
        self.geo = geo
        nx, ny, nz = dims
        self.dims = dims
        M = len(geo.names)
        rng = np.random.default_rng(seed)
        perm = rng.permutation(nx * ny * nz) % M
        pitch = 1.0 + pitch_gap
        self.pitch = pitch
        rows, cell_of, item, part_of = [], [], [], []
        for cell, (iz, iy, ix) in enumerate(np.ndindex(nz, ny, nx)):
            m = int(perm[cell])
            lo, hi = geo.model_bbox[m]
            s = 1.0 / float((hi - lo).max())
            cen = (lo + hi) * 0.5
            k = int(rng.integers(0, 4))
            ca, sa = math.cos(k * math.pi / 2), math.sin(k * math.pi / 2)
            R = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])
            A = s * R
            cell_c = (np.array([ix, iy, iz]) - (np.array(dims) - 1) / 2.0) * pitch
            t = cell_c - A @ cen
            p0, p1 = geo.model_part0[m], geo.model_part0[m + 1]
            for p in range(p0, p1):
                rows.append((A, t, s, cell * 4096 + (p - p0), p))
        J = len(rows)
        inst = np.zeros((J, 4, 4), dtype=np.float32)
        for j, (A, t, s, it, p) in enumerate(rows):
            inst[j, :3, :3] = A
            inst[j, :3, 3] = t
            inst[j, 3, 0] = s
            inst[j, 3, 1:3] = np.array([it, p], dtype=np.uint32).view(np.float32)
        self.instances = inst
        self.item_ids = np.array([r[3] for r in rows], dtype=np.uint32)
        self.part_ids = np.array([r[4] for r in rows], dtype=np.int64)
        self.cell_of_inst = np.array([r[3] // 4096 for r in rows])
        cs = geo.part_cstart
        n_j = cs[self.part_ids + 1] - cs[self.part_ids]
        off = np.cumsum(n_j) - n_j
        self.n_ci = int(n_j.sum())
        inst_of = np.repeat(np.arange(J, dtype=np.uint32), n_j)
        cl = np.repeat(cs[self.part_ids], n_j) + (np.arange(self.n_ci) - np.repeat(off, n_j))
        self.ci_table = np.stack([inst_of, cl.astype(np.uint32)], 1)
        self.n_inst = J
        self.total_tris = int(geo.part_tris[self.part_ids].sum())
        half = (np.array(dims) * pitch) / 2.0
        self.half = half
        self.radius = float(np.linalg.norm(half))
        self.cell_centers = ((np.array(list(np.ndindex(nz, ny, nx)))[:, ::-1] - (np.array(dims) - 1) / 2.0) * pitch)

    def _inst_centers(self):
        c = self.geo.part_lo[self.part_ids] + self.geo.part_ext[self.part_ids] * 0.5
        A = self.instances[:, :3, :3].astype(np.float64)
        t = self.instances[:, :3, 3].astype(np.float64)
        return np.einsum("jab,jb->ja", A, c.astype(np.float64)) + t


# ---- camera ----
def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye, target, up = (np.asarray(v, dtype=np.float64) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    M = np.eye(4)
    M[0, :3], M[1, :3], M[2, :3] = s, u, -f
    M[:3, 3] = -M[:3, :3] @ eye
    return M


def perspective_rz(fov_y_deg, aspect, near):
    """Reverse-Z, infinite far, depth range 0..1 (wgpu clip space). depth = near / distance."""
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2)
    P = np.zeros((4, 4))
    P[0, 0] = f / aspect
    P[1, 1] = f
    P[2, 3] = near
    P[3, 2] = -1.0
    return P


def frustum_planes(VP):
    r = VP
    pl = [r[3] + r[0], r[3] - r[0], r[3] + r[1], r[3] - r[1], r[3] - r[2]]  # left right bottom top near(reverse-Z)
    out = []
    for p in pl:
        out.append(p / np.linalg.norm(p[:3]))
    return np.array(out)


def make_views(scene):
    """name -> (eye, target)."""
    R = scene.radius
    c = np.zeros(3)
    fov = 55.0
    d_far = R / math.sin(math.radians(fov) / 2) * 0.98
    dirn = np.array([0.55, 0.35, 0.76])
    dirn /= np.linalg.norm(dirn)
    views = {
        "outside": (c + dirn * d_far * 1.0, c),
        "near": (c + dirn * (np.max(scene.half) * 1.35), c),
    }
    # inside: at a lattice junction between cells, looking along a diagonal
    junction = np.zeros(3)
    for a in range(3):
        n = scene.dims[a]
        k = n // 2
        junction[a] = (k - (n - 1) / 2.0 - 0.5) * scene.pitch
    views["inside"] = (junction, junction + np.array([1.0, 0.18, 0.55]))
    return views
