"""Compact GPU geometry: the packing is exact where it must be (positions, constants, indices), bounded where it is lossy
(normals), paged without a part crossing a page, and uploaded through a sink. The GPU round trip skips without an adapter.

    python -m pytest tests/gpu/test_geometry.py -q -p no:cacheprovider
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from app.gpu import geometry as G                               # noqa: E402
from app.viewer.model import Look                               # noqa: E402


def _gpu_or_none():
    try:
        from app.gpu.device import get_gpu
        return get_gpu()
    except Exception:
        return None


GPU = _gpu_or_none()
needs_gpu = unittest.skipIf(GPU is None, "no wgpu adapter available")


def fixture_model():
    from general_fixtures import write_fixture_model
    from app.viewer.model import Model
    d = Path(tempfile.mkdtemp())
    write_fixture_model(d / "m.glb")
    return Model(d / "m.glb")


def synthetic_model(parts=3, n=12, seed=3):
    """Parts of a sphere grid with per-part varying and constant extra attributes (a cheap stand-in for a real model)."""
    rng = np.random.default_rng(seed)
    th, ph = np.meshgrid(np.linspace(0, np.pi, n + 1), np.linspace(0, 2 * np.pi, n + 1), indexing="ij")
    pos = np.stack([np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)], -1).reshape(-1, 3).astype(np.float32)
    i = np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]
    tris = np.stack([i, i + n + 1, i + 1, i + 1, i + n + 1, i + n + 2], -1).reshape(-1).astype(np.uint32)
    nv = len(pos)
    verts, idx, plist = [], [], []
    for k in range(parts):
        v = np.zeros((nv, G.VERTEX_FLOATS), dtype=np.float32)
        v[:, 0:3] = pos * (1.0 + 0.1 * k)
        nrm = rng.normal(size=(nv, 3)).astype(np.float32)
        v[:, 3:6] = nrm / np.linalg.norm(nrm, axis=1, keepdims=True)
        v[:, 6:19] = (0.25, 0.5, 0.75, 0, 0, 0, 0.5, 0.2, 0.3, 0.4, 1.0, 0, 0)       # constants of the part
        if k == 1:
            v[:, 17:19] = rng.random((nv, 2)).astype(np.float32)                         # varying uv
        if k == 2:
            v[:, 6:9] = rng.normal(size=(nv, 3)).astype(np.float32)                      # varying morph delta
        plist.append(SimpleNamespace(id=k + 1, name=f"part{k}", first=k * len(tris), count=len(tris),
                                     vertex_base=k * nv, vertex_count=nv, item=k, look=Look(),
                                     material_name="mat"))
        verts.append(v)
        idx.append(tris + np.uint32(k * nv))
    return SimpleNamespace(vertices=np.concatenate(verts), indices=np.concatenate(idx), parts=plist, lod=None)


class NormalPacking(unittest.TestCase):
    def test_octahedral_round_trip_is_tight(self):
        rng = np.random.default_rng(1)
        n = rng.normal(size=(200000, 3)).astype(np.float32)
        n = np.concatenate([n, np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1],
                                         [1, 1, 1], [-1, -1, -1], [1e-4, 0, -1]], dtype=np.float32)])
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        packed = G.oct_pack(G.oct_encode(n))
        err = G.normal_error_degrees(n, packed)
        self.assertLess(float(np.nanmax(err)), 0.01)
        d = G.oct_decode(G.oct_unpack(packed))
        np.testing.assert_allclose(np.linalg.norm(d, axis=1), 1.0, atol=2e-6)

    def test_zero_normal_decodes_to_a_unit_vector(self):
        d = G.oct_decode(G.oct_unpack(G.oct_pack(G.oct_encode(np.zeros((1, 3), np.float32)))))
        self.assertAlmostEqual(float(np.linalg.norm(d)), 1.0, places=5)


class HostRoundTrip(unittest.TestCase):
    def check(self, model, page_bytes):
        sink = G.HostSink()
        geom = G.build_geometry(model, sink, page_bytes, measure=True)
        out, idx = G.decode_geometry(geom, model)
        src = model.vertices
        for p in model.parts:
            a, b = p.vertex_base, p.vertex_base + p.vertex_count
            self.assertTrue(np.array_equal(src[a:b, 0:3].view(np.uint32), out[a:b, 0:3].view(np.uint32)), p.name)
            self.assertTrue(np.array_equal(src[a:b, 6:19].view(np.uint32), out[a:b, 6:19].view(np.uint32)), p.name)
            err = G.normal_error_degrees(src[a:b, 3:6], G.oct_pack(G.oct_encode(src[a:b, 3:6])))
            self.assertLess(float(np.nanmax(err)), 0.01)
        for i, p in enumerate(model.parts):
            self.assertTrue(np.array_equal(idx[(i, 0)], model.indices[p.first:p.first + p.count]), p.name)
        self.assertLess(geom.stats["normals"]["max_angle_deg"], 0.01)
        return geom

    def test_fixture_model(self):
        geom = self.check(fixture_model(), 1 << 20)
        self.assertEqual(len(geom.pages), 1)

    def test_synthetic_model_with_varying_and_constant_attributes(self):
        model = synthetic_model()
        geom = self.check(model, 1 << 20)
        # constants are stored per part: the constant streams of a part take no per-vertex bytes
        self.assertEqual(geom.stats["bytes_per_vertex_before"], 76)
        self.assertLess(geom.stats["bytes_per_vertex_after"], 76 / 2)

    def test_a_small_page_limit_splits_pages_without_crossing_a_part(self):
        model = synthetic_model()
        nv = model.parts[0].vertex_count
        # the biggest single part (the one with a varying morph delta) fills a page, two parts never fit one
        need = G.section_layout({"pos": nv, "nrm": nv, "dpos": nv, "index": model.parts[0].count})[1] * 4
        geom = self.check(model, need)
        self.assertEqual(len(geom.pages), len(model.parts))
        for page in geom.pages:
            self.assertEqual(len(page.parts), 1)
            self.assertLessEqual(page.words * 4, need)
            self.assertEqual(page.index_byte_offset % 256, 0)
            self.assertTrue(all(o % 64 == 0 for o in page.offs.values()))

    def test_more_pages_than_the_pipelines_bind_are_refused(self):
        model = synthetic_model()
        nv = model.parts[0].vertex_count
        need = G.section_layout({"pos": nv, "nrm": nv, "dpos": nv, "index": model.parts[0].count})[1] * 4
        with self.assertRaises(G.GeometryError) as cm:
            G.build_geometry(model, G.HostSink(), need, max_pages=2)
        self.assertIn("at most 2 pages", str(cm.exception))
        self.assertEqual(len(G.build_geometry(model, G.HostSink(), need, max_pages=3).pages), 3)

    def test_a_part_larger_than_a_page_is_refused(self):
        with self.assertRaises(G.GeometryError):
            G.build_geometry(synthetic_model(parts=1), G.HostSink(), 256)

    def test_gl_order_keys_follow_the_part_order_without_lod(self):
        model = fixture_model()
        base, lods = G.gl_order_keys(model)
        self.assertEqual(lods, {})
        self.assertEqual(base, {p.id: p.first for p in model.parts})


@needs_gpu
class GpuRoundTrip(unittest.TestCase):
    def test_gpu_sink_matches_host_sink(self):
        model = synthetic_model()
        host = G.build_geometry(model, G.HostSink(), 1 << 20)
        gpu = G.build_geometry(model, G.GpuSink(GPU.device, flush_bytes=4096), 1 << 20)
        a, ia = G.decode_geometry(host, model)
        b, ib = G.decode_geometry(gpu, model)
        self.assertTrue(np.array_equal(a.view(np.uint32), b.view(np.uint32)))
        self.assertEqual(sorted(ia), sorted(ib))
        for k in ia:
            self.assertTrue(np.array_equal(ia[k], ib[k]))
        gpu.release()


if __name__ == "__main__":
    unittest.main()
