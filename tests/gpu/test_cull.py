"""Cluster build invariants (CPU only) and a GPU smoke test of ClusterCuller (skipped without an adapter)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.gpu import clusters as cl            # noqa: E402
from app.gpu import geometry as geo           # noqa: E402
from app.viewer.model import Look             # noqa: E402
from app.viewer import lod                    # noqa: E402


def fake_model(seed=3, parts=((4000, 30), (130, 0), (7, 0)), morph=True):
    """A ViewerModel stand-in: grid-like triangle soups of different sizes, no LOD, optional dpos."""
    rng = np.random.default_rng(seed)
    verts, inds, plist = [], [], []
    vbase = ibase = 0
    for k, (ntri, _unused) in enumerate(parts):
        nv = ntri + 2
        v = np.zeros((nv, 19), dtype=np.float32)
        a = np.arange(nv) * 0.01
        v[:, 0:3] = np.stack([np.cos(a), np.sin(a), a * 0.1], axis=1) + rng.uniform(-0.01, 0.01, (nv, 3)) + 3 * k
        v[:, 3:6] = (0.0, 0.0, 1.0)
        if morph and k == 0:
            v[:, 6:9] = rng.uniform(-0.2, 0.2, (nv, 3))
        t = np.stack([np.arange(ntri), np.arange(ntri) + 1, np.arange(ntri) + 2], axis=1).astype(np.uint32) + vbase
        verts.append(v)
        inds.append(t.reshape(-1))
        plist.append(SimpleNamespace(id=k + 1, name=f"p{k}", first=ibase, count=3 * ntri, vertex_base=vbase,
                                     vertex_count=nv, item=k, material_name="m", look=Look()))
        vbase += nv
        ibase += 3 * ntri
    return SimpleNamespace(parts=plist, vertices=np.concatenate(verts), indices=np.concatenate(inds), lod={},
                           anim_vertices=None)


class ClusterBuildTests(unittest.TestCase):
    def setUp(self):
        self.model = fake_model()
        # geometry.build_geometry needs gl_order_keys (renderer imports); build ranges by hand like it does
        self.geom = SimpleNamespace(page_of=np.zeros(len(self.model.parts), np.int32),
                                    ranges=[[(p.first, p.count)] for p in self.model.parts],
                                    page_bytes=1 << 30)
        self.cd = cl.build_clusters(self.model, self.geom, threads=2)

    def test_every_triangle_in_exactly_one_cluster(self):
        cd = self.cd
        for r in range(cd.n_ranges):
            a, n = int(cd.r_tfirst[r]), int(cd.r_ntri[r])
            self.assertTrue(np.array_equal(np.sort(cd.perm[a:a + n]), np.arange(n, dtype=np.uint32)))
        self.assertEqual(cd.n_tris, sum(p.count // 3 for p in self.model.parts))

    def test_at_most_64_triangles(self):
        cd = self.cd
        sizes = np.array([cd.cluster_tris(c) for c in range(cd.n_clusters)])
        self.assertTrue((sizes >= 1).all() and (sizes <= 64).all())
        self.assertEqual(int(sizes.sum()), cd.n_tris)

    def test_bounds_contain_vertices_with_displacement(self):
        cd, m = self.cd, self.model
        for c in range(cd.n_clusters):
            r = int(cd.cl_range[c])
            p = m.parts[int(cd.r_part[r])]
            tri = cd.cluster_perm(c).astype(np.int64)
            idx = m.indices[p.first:p.first + p.count].reshape(-1, 3)[tri].reshape(-1).astype(np.int64)
            g = cd.cl_geom[c].astype(np.float64)
            centre, dmax, half = g[0:3], g[3], g[4:7]
            pos = m.vertices[idx, 0:3].astype(np.float64)
            self.assertTrue(np.all(np.abs(pos - centre) <= half + 1e-6 * (1 + np.abs(centre))))
            dpos = m.vertices[idx, 6:9].astype(np.float64)
            self.assertLessEqual(float(np.linalg.norm(dpos, axis=1).max()), dmax * (1 + 1e-6) + 1e-12)
            # the shader's box for any weight contains pos + w * dpos
            for w in (-1.7, 0.4, 1.0, 2.5):
                h = half + abs(w) * dmax + 2e-6 * (np.abs(centre) + half)
                self.assertTrue(np.all(np.abs(pos + w * dpos - centre) <= h))

    def test_spatial_coherence(self):
        # Morton runs are tight: the median cluster box is far smaller than the part's box
        cd = self.cd
        sizes = cd.cl_geom[:, 4:7].max(axis=1)
        self.assertLess(float(np.median(sizes)), 0.5)

    def test_capacity_covers_largest_level(self):
        cap = cl.page_capacity(cd := self.cd, 1)
        self.assertEqual(int(cap[0]), int(cd.r_ccount.sum()))

    def test_index_outside_part_is_rejected(self):
        m = fake_model()
        m.indices[5] = m.parts[1].vertex_base + 1          # part 0 now indexes part 1's vertices
        geom = SimpleNamespace(page_of=np.zeros(len(m.parts), np.int32), ranges=[[(p.first, p.count)] for p in m.parts],
                               page_bytes=1 << 30)
        with self.assertRaises(cl.ClusterError):
            cl.build_clusters(m, geom, threads=1)


class ClusterOrderedGeometryTests(unittest.TestCase):
    """geometry.build_geometry(cluster_order=True): same vertex data, triangles of every cullable range in cluster order."""

    def setUp(self):
        m = fake_model(parts=((900, 0), (300, 0), (40, 0)))
        # LOD levels for part 2 (every 2nd / 4th / ... triangle of its range), shared by nothing else
        p = m.parts[1]
        tris = m.indices[p.first:p.first + p.count].reshape(-1, 3)
        m.lod = {p.id: SimpleNamespace(indices=[np.ascontiguousarray(tris[::2 ** (k + 1)]).reshape(-1) for k in range(lod.LEVELS)])}
        self.model = m

    def test_ordered_equals_default_under_perm(self):
        m = self.model
        plain = geo.build_geometry(m, geo.HostSink(), 1 << 20)
        order = geo.build_geometry(m, geo.HostSink(), 1 << 20, cluster_order=True)
        self.assertFalse(plain.cluster_ordered)
        self.assertTrue(order.cluster_ordered)
        self.assertEqual(plain.ranges, order.ranges)
        cd = order.clusters
        for a, b in zip(plain.pages, order.pages):
            wa, wb = a.buffer.view(np.uint32), b.buffer.view(np.uint32)
            i0 = a.offs["index"]
            self.assertTrue(np.array_equal(wa[:i0], wb[:i0]))                        # vertex data untouched
            ia, ib = wa[i0:i0 + a.nindices], wb[i0:i0 + b.nindices]
            for r in range(cd.n_ranges):
                f, n = int(cd.r_first[r]), int(cd.r_ntri[r])
                perm = cd.perm[int(cd.r_tfirst[r]):int(cd.r_tfirst[r]) + n].astype(np.int64)
                self.assertTrue(np.array_equal(ib[f:f + 3 * n].reshape(-1, 3), ia[f:f + 3 * n].reshape(-1, 3)[perm]))

    def test_original_triangle_matches_model_arrays(self):
        m = self.model
        g = geo.build_geometry(m, geo.HostSink(), 1 << 20, cluster_order=True)
        words = g.pages[0].buffer.view(np.uint32)
        i0 = g.pages[0].offs["index"]
        for pi, p in enumerate(m.parts):
            for lv, (first, count) in enumerate(g.ranges[pi]):
                src = m.indices[p.first:p.first + p.count] if lv == 0 else m.lod[p.id].indices[lv - 1]
                stored = np.arange(count // 3)
                orig = g.order.original(pi, lv, stored)
                got = words[i0 + first:i0 + first + count].reshape(-1, 3) + g.pages[0].v0
                self.assertTrue(np.array_equal(got, np.asarray(src).reshape(-1, 3)[orig]))
                self.assertEqual(sorted(orig.tolist()), list(range(count // 3)))

    def test_animated_model_is_not_reordered(self):
        m = fake_model(parts=((300, 0), (50, 0)))
        m.anim_vertices = np.zeros(len(m.vertices), dtype=[("m", np.float16, (16,)), ("phase", np.float32)])
        m.anim_vertices["phase"] = 1.0
        plain = geo.build_geometry(m, geo.HostSink(), 1 << 20)
        order = geo.build_geometry(m, geo.HostSink(), 1 << 20, cluster_order=True)
        self.assertEqual(order.clusters.n_ranges, 0)
        for a, b in zip(plain.pages, order.pages):
            self.assertTrue(np.array_equal(a.buffer, b.buffer))                 # every part is uncullable: byte-identical pages
        self.assertEqual(order.order.original(0, 0, 7).tolist(), 7)

    def test_cpu_id_decode(self):
        from app.gpu.cull import ClusterCuller, CULL_TAG
        m = self.model
        g = geo.build_geometry(m, geo.HostSink(), 1 << 20, cluster_order=True)
        cu = object.__new__(ClusterCuller)
        cu.cd = cd = g.clusters
        rng = np.random.default_rng(2)
        c = rng.integers(0, cd.n_clusters, 500)
        t = np.array([rng.integers(0, cd.cluster_tris(int(x))) for x in c])
        ids = (np.uint32(CULL_TAG) | (c.astype(np.uint32) << np.uint32(6)) | t.astype(np.uint32)).astype(np.uint32)
        cl_, part, tri, rg = cu.decode_ids(np.concatenate([ids, [0x12345]]))
        self.assertTrue(np.array_equal(cl_[:-1], c))
        self.assertEqual(int(cl_[-1]), -1)                                              # a plain id is not decoded
        for k in range(len(c)):
            r = int(cd.cl_range[c[k]])
            stored = 64 * (int(c[k]) - int(cd.r_cfirst[r])) + int(t[k])
            self.assertEqual(int(tri[k]), int(cd.perm[int(cd.r_tfirst[r]) + stored]))
            self.assertEqual(int(part[k]), int(cd.r_part[r]))


def _gpu():
    try:
        from app.gpu.device import GpuUnavailable, get_gpu
        return get_gpu()
    except Exception:
        return None


@unittest.skipIf(_gpu() is None, "no wgpu adapter")
class CullerSmokeTest(unittest.TestCase):
    def test_plain_geometry_is_refused(self):
        from app.gpu.cull import ClusterCuller
        m = fake_model(parts=((300, 0),))
        plain = geo.build_geometry(m, geo.HostSink(), 1 << 20)
        with self.assertRaises(cl.ClusterError):
            ClusterCuller(_gpu(), plain).prepare(m)

    def test_two_phase_matches_unculled_on_a_small_model(self):
        gpu = _gpu()
        from tools.perf.gpu import cull_check as cc
        try:
            H = cc.Harness("eyeball", None, size=(640, 400))
        except Exception as e:                      # no library model / no GL in this environment
            self.skipTest(f"harness unavailable: {e}")
        try:
            cam = H.reset_view()
            fs = H.base_state()
            H.cu.reset()
            for i in range(3):
                r = H.run_frame(cam, fs)
                self.assertEqual(r["false_cull_samples"], 0)
                self.assertEqual(r["nearer_samples"], 0)
                self.assertEqual(r["stray_ids"], 0)
                self.assertEqual(r["stats"]["overflow"], 0)
            self.assertGreater(r["stats"]["p1"], 0)
            self.assertLess(r["stats"]["p1"] + r["stats"]["p2"], r["stats"]["active"])
        finally:
            H.release()


if __name__ == "__main__":
    unittest.main()
