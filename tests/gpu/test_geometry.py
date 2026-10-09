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


def _compressed(model, sink, page_bytes=1 << 22):
    return G.build_geometry(model, sink, page_bytes, cluster_order=True, compress=True, cluster_cache_use=False)


def _check_compressed(test, model, geom, sink_read=None):
    """Vertex data equal to the model (renumbered back through the cluster data), every index range equal to the model's
    triangles in cluster order."""
    out, idx = G.decode_geometry(geom, model)
    cd = geom.clusters
    for pi, p in enumerate(model.parts):
        a, b = p.vertex_base, p.vertex_base + p.vertex_count
        test.assertTrue(np.array_equal(model.vertices[a:b, 0:3].view(np.uint32), out[a:b, 0:3].view(np.uint32)), p.name)
        test.assertTrue(np.array_equal(model.vertices[a:b, 6:19].view(np.uint32), out[a:b, 6:19].view(np.uint32)), p.name)
        r = int(cd.level_range[pi, 0])
        t0, n = int(cd.r_tfirst[r]), int(cd.r_ntri[r])
        want = model.indices[p.first:p.first + p.count].reshape(-1, 3)[cd.perm[t0:t0 + n].astype(np.int64)].reshape(-1)
        test.assertTrue(np.array_equal(want, idx[(pi, 0)]), p.name)


class CompressedHost(unittest.TestCase):
    def test_vertex_reorder_and_u16_indices_round_trip(self):
        model = synthetic_model(parts=3, n=40)
        geom = _compressed(model, G.HostSink())
        self.assertTrue(geom.compressed)
        for page in geom.pages:
            self.assertTrue(page.compressed)
            self.assertEqual(page.nlogical % 192, 0)
            with self.assertRaises(G.GeometryError):
                page.index_byte_offset
        _check_compressed(self, model, geom)

    def test_index_bytes_shrink(self):
        model = synthetic_model(parts=3, n=40)
        plain = G.build_geometry(model, G.HostSink(), 1 << 22, cluster_order=True, cluster_cache_use=False)
        geom = _compressed(model, G.HostSink())
        self.assertFalse(plain.compressed)
        self.assertLess(geom.stats["index_bytes"], 0.6 * plain.stats["index_bytes"])

    def test_vorder_is_a_permutation_per_part(self):
        model = synthetic_model(parts=3, n=40)
        geom = _compressed(model, G.HostSink())
        vo = np.asarray(geom.clusters.vorder, dtype=np.int64)
        for p in model.parts:
            a, b = p.vertex_base, p.vertex_base + p.vertex_count
            self.assertTrue(np.array_equal(np.sort(vo[a:b]), np.arange(a, b)))


class CompressGate(unittest.TestCase):
    """compress="auto" (the renderer's default): compressed pages only when the plain pages exceed max_pages x page_bytes."""

    def test_auto_compresses_only_what_does_not_fit(self):
        model = synthetic_model(parts=3, n=40)
        kw = dict(cluster_order=True, cluster_cache_use=False, max_pages=1)
        plain = G.build_geometry(model, G.HostSink(), 1 << 22, **kw)
        comp = G.build_geometry(model, G.HostSink(), 1 << 22, compress=True, **kw)
        pb, cb = plain.stats["gpu_bytes"], comp.stats["gpu_bytes"]
        self.assertLess(cb, pb)
        auto = G.build_geometry(model, G.HostSink(), 1 << 22, compress="auto", **kw)
        self.assertFalse(auto.compressed)                           # fits: exactly the plain layout
        self.assertEqual(auto.stats["gpu_bytes"], pb)
        tight = (pb + cb) // 2 // 256 * 256
        with self.assertRaises(G.GeometryError):
            G.build_geometry(model, G.HostSink(), tight, **kw)
        auto = G.build_geometry(model, G.HostSink(), tight, compress="auto", **kw)
        self.assertTrue(auto.compressed)
        _check_compressed(self, model, auto)
        with self.assertRaises(G.GeometryError):                     # too small even compressed
            G.build_geometry(model, G.HostSink(), cb // 2 // 256 * 256, compress="auto", **kw)


_FETCH = """
@group(1) @binding(10) var<storage, read_write> out_idx: array<u32>;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let n = arrayLength(&out_idx);
    if (gid.x < n) { out_idx[gid.x] = g_index(0u, gid.x); }
}
@compute @workgroup_size(64)
fn tri(@builtin(global_invocation_id) gid: vec3<u32>) {
    let n = arrayLength(&out_idx) / 3u;
    if (gid.x < n) {
        let t = g_tri(0u, 3u * gid.x);
        out_idx[3u * gid.x] = t.x;
        out_idx[3u * gid.x + 1u] = t.y;
        out_idx[3u * gid.x + 2u] = t.z;
    }
}
"""


@needs_gpu
class CompressedGpu(unittest.TestCase):
    def test_gpu_sink_matches_host_sink_and_the_shader_decodes_every_index(self):
        model = synthetic_model(parts=3, n=40)
        host = _compressed(model, G.HostSink())
        gpu = _compressed(model, G.GpuSink(GPU.device, flush_bytes=4096))
        _check_compressed(self, model, gpu)
        a, ia = G.decode_geometry(host, model)
        b, ib = G.decode_geometry(gpu, model)
        self.assertTrue(np.array_equal(a.view(np.uint32), b.view(np.uint32)))
        for k in ia:
            self.assertTrue(np.array_equal(ia[k], ib[k]))
        # g_index in geom.wgsl against the CPU decode, for every logical position of the page
        import wgpu
        d, q = GPU.device, GPU.queue
        pg = gpu.pages[0]
        code = (G.geom_prelude(1, 0, 0, uniform_binding=1, compressed=True) + "\n"
                + (ROOT / "app" / "gpu" / "wgsl" / "geom.wgsl").read_text() + _FETCH.replace("@group(1)", "@group(0)"))
        mod = d.create_shader_module(code=code)
        n = pg.nlogical
        ob = d.create_buffer(size=4 * n, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        po = np.ascontiguousarray(gpu.page_offsets(0, 1), dtype=np.uint32)
        ub = d.create_buffer_with_data(data=po, usage=wgpu.BufferUsage.UNIFORM)
        outs = {}
        for entry in ("main", "tri"):
            pipe = d.create_compute_pipeline(layout="auto", compute={"module": mod, "entry_point": entry})
            bg = d.create_bind_group(layout=pipe.get_bind_group_layout(0), entries=[
                {"binding": 0, "resource": {"buffer": pg.buffer, "offset": 0, "size": pg.buffer.size}},
                {"binding": 1, "resource": {"buffer": ub, "offset": 0, "size": po.nbytes}},
                {"binding": 10, "resource": {"buffer": ob, "offset": 0, "size": 4 * n}}])
            enc = d.create_command_encoder()
            cp = enc.begin_compute_pass()
            cp.set_pipeline(pipe)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups((n + 63) // 64)
            cp.end()
            q.submit([enc.finish()])
            outs[entry] = np.frombuffer(d.queue.read_buffer(ob), dtype=np.uint32).copy()
        got = outs["main"]
        self.assertTrue(np.array_equal(outs["tri"], got), "g_tri differs from three g_index fetches")
        # the shader returns page-local NEW vertex numbers; decode_geometry returns the model's numbers (through cluster data vorder)
        vo = np.asarray(gpu.clusters.vorder, dtype=np.int64)
        for pi, p in enumerate(model.parts):
            first, count = gpu.ranges[pi][0]
            local = got[first:first + count].astype(np.int64) - int(gpu.vbase[pi])
            self.assertTrue(np.array_equal(vo[p.vertex_base + local], ia[(pi, 0)].astype(np.int64)), p.name)
        gpu.release()


if __name__ == "__main__":
    unittest.main()
