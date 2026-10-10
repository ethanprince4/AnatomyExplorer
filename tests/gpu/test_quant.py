"""Quantised vertex positions (stage 2 of the geometry compression, app/gpu/quant.py, wgsl/geom.wgsl g_pos):
the numpy encode/decode round trip, the error bound, the shader against the CPU decode, and the cluster bounds that must still
contain the decoded vertices.

    python -m pytest tests/gpu/test_quant.py -q -p no:cacheprovider
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests", ROOT / "tests" / "gpu"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from app.gpu import geometry as G                               # noqa: E402
from app.gpu import quant as Q                                  # noqa: E402
from test_geometry import GPU, needs_gpu, synthetic_model       # noqa: E402


def _blocky(n, scale, offset, seed=1):
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.normal(size=(n, 3)) * 0.01, axis=0) * scale + offset
    return base.astype(np.float32)


class QuantRoundTrip(unittest.TestCase):
    def roundtrip(self, pos, budget):
        tab, words, err, st = Q.plan_part(pos, budget)
        data = Q.encode_part(pos, tab)
        self.assertEqual(len(data), words)
        dec = Q.decode_part(tab, data, len(pos))
        e = np.abs(dec.astype(np.float64) - pos.astype(np.float64)).max() if len(pos) else 0.0
        return tab, dec, e, err, st

    def test_error_is_bounded_and_realised_error_is_exact(self):
        for scale, off in ((1.0, 0.0), (1e-3, 0.3), (1e4, 5e3), (1.0, -0.7), (1e-6, 0.0)):
            pos = _blocky(1000, scale, off)
            for budget in (1e-9, 1e-6, 1e-4, 1e-2):
                tab, dec, e, err, st = self.roundtrip(pos, budget)
                self.assertLessEqual(e, budget * (1 + 1e-12), (scale, off, budget))
                self.assertLessEqual(e, max(err, 0.0) + 1e-300 if st["float_blocks"] == 0 else budget)
                if st["float_blocks"] == 0:
                    self.assertEqual(e, err)                      # the planner's realised error is the true one

    def test_values_on_the_grid_decode_bit_exactly(self):
        grid = (np.random.default_rng(2).integers(-1000, 1000, size=(257, 3)) * 2.0 ** -10).astype(np.float32)
        tab, dec, e, err, st = self.roundtrip(grid, 2.0 ** -12)
        self.assertEqual(e, 0.0)
        self.assertEqual(st["float_blocks"], 0)

    def test_float_fallback_blocks_are_exact(self):
        pos = _blocky(300, 1.0, 0.0)
        pos[70] = (1e30, -1e30, 3.0)                                # a block that cannot be quantised within 24 bits
        pos[140] = (np.nan, 0.0, 1.0)
        pos[141] = (np.inf, 0.0, 1.0)
        tab, dec, e, err, st = self.roundtrip(pos, 1e-7)
        self.assertGreaterEqual(st["float_blocks"], 2)
        bad = (tab[:, 1] >> 31) != 0
        for bi in np.nonzero(bad)[0]:
            a, b = bi * 64, min(bi * 64 + 64, len(pos))
            self.assertTrue(np.array_equal(pos[a:b].view(np.uint32), dec[a:b].view(np.uint32)))

    def test_odd_sizes_and_flat_axes(self):
        for n in (1, 2, 63, 64, 65, 129):
            pos = _blocky(n, 1.0, 0.25)
            pos[:, 1] = 0.5                                         # a flat axis: 0 bits
            pos[:, 2] = np.float32(-0.0)
            tab, dec, e, err, st = self.roundtrip(pos, 1e-6)
            self.assertLessEqual(e, 1e-6)
            self.assertEqual(len(dec), n)

    def test_bits_follow_the_budget(self):
        pos = _blocky(640, 1.0, 0.0)
        loose = Q.plan_part(pos, 1e-3)[1]
        tight = Q.plan_part(pos, 1e-7)[1]
        self.assertLess(loose, tight)
        self.assertLess(tight, 640 * 3)                              # still fewer words than float32 (3 words per vertex)


class _LooseBudget(unittest.TestCase):
    """A budget of 1 pixel makes the tiny synthetic models quantise coarsely (the default budget is nearly lossless on them)."""

    def setUp(self):
        self._old = os.environ.get("ANATOMY_GEOM_QERR")
        os.environ["ANATOMY_GEOM_QERR"] = "1.0"

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ANATOMY_GEOM_QERR", None)
        else:
            os.environ["ANATOMY_GEOM_QERR"] = self._old


class QuantGeometry(_LooseBudget):
    def build(self, sink=None, **kw):
        model = synthetic_model(parts=3, n=40)
        geom = G.build_geometry(model, sink or G.HostSink(), 1 << 22, cluster_order=True, compress=2, cluster_cache_use=False, **kw)
        return model, geom

    def test_stage_and_sections(self):
        model, geom = self.build()
        self.assertEqual(geom.stage, 2)
        self.assertTrue(geom.compressed)
        for page in geom.pages:
            self.assertTrue(page.quantised)
            self.assertNotIn("pos", page.counts)
            self.assertEqual(page.counts["posb"] * Q.BLOCK, page.nverts)

    def test_error_bound_per_part(self):
        model, geom = self.build()
        out, _ = G.decode_geometry(geom, model)
        for pi, p in enumerate(model.parts):
            a, b = p.vertex_base, p.vertex_base + p.vertex_count
            e = np.abs(out[a:b, 0:3].astype(np.float64) - model.vertices[a:b, 0:3].astype(np.float64)).max()
            self.assertLessEqual(e, geom.quant["budget"][pi] * (1 + 1e-9))
            self.assertLessEqual(e, geom.quant["err"][pi] * (1 + 1e-9) + 1e-300)
            self.assertTrue(np.array_equal(out[a:b, 6:19].view(np.uint32), model.vertices[a:b, 6:19].view(np.uint32)))

    def test_smaller_than_stage_one(self):
        model, g2 = self.build()
        g1 = G.build_geometry(model, G.HostSink(), 1 << 22, cluster_order=True, compress=1, cluster_cache_use=False)
        self.assertLess(g2.stats["gpu_bytes"], g1.stats["gpu_bytes"])
        self.assertEqual(g1.stage, 1)
        self.assertFalse(g1.pages[0].quantised)

    def test_cluster_bounds_contain_the_decoded_vertices(self):
        model, geom = self.build()
        out, _ = G.decode_geometry(geom, model)
        cd = geom.clusters
        raw_cd = G._cl.build_clusters(model)                        # the boxes of the float positions
        idx = np.asarray(model.indices, dtype=np.int64)
        grown = False
        for c in range(cd.n_clusters):
            ri = int(cd.cl_range[c])
            pi = int(cd.r_part[ri])
            p = model.parts[pi]
            t0 = int(cd.r_tfirst[ri]) + (c - int(cd.r_cfirst[ri])) * 64
            n = min(64, int(cd.r_ntri[ri]) - (c - int(cd.r_cfirst[ri])) * 64)
            src = (idx[p.first:p.first + p.count] if int(cd.r_slot[ri]) == 0 else None)
            if src is None:
                continue
            tris = src.reshape(-1, 3)[np.asarray(cd.perm[t0:t0 + n], dtype=np.int64)].reshape(-1)
            pts = out[np.unique(tris), 0:3].astype(np.float64)
            g = cd.cl_geom[c].astype(np.float64)
            tol = 4e-6 * (np.abs(g[0:3]) + g[4:7]) + 1e-30          # the culler's own slack for float32 centre / extent rounding
            lo, hi = g[0:3] - g[4:7] - tol, g[0:3] + g[4:7] + tol
            self.assertTrue((pts >= lo).all() and (pts <= hi).all(), f"cluster {c}")
            grown = grown or (cd.cl_geom[c, 4:7] > raw_cd.cl_geom[c, 4:7]).any()
        self.assertTrue(grown or float(geom.quant["err"].max()) == 0.0)

    def test_cache_arrays_are_not_modified(self):
        model, geom = self.build()
        raw = G._cl.build_clusters(model)
        self.assertEqual(raw.cl_geom.shape, geom.clusters.cl_geom.shape)
        self.assertTrue(np.all(geom.clusters.cl_geom[:, 4:7] >= raw.cl_geom[:, 4:7]))


class QuantGate(_LooseBudget):
    def test_auto_picks_the_smallest_stage_that_fits(self):
        model = synthetic_model(parts=3, n=40)
        kw = dict(cluster_order=True, cluster_cache_use=False, max_pages=1)
        b = {s: G.build_geometry(model, G.HostSink(), 1 << 22, compress=s, **kw).stats["gpu_bytes"] for s in (False, 1, 2)}
        self.assertGreater(b[False], b[1])
        self.assertGreater(b[1], b[2])
        for want, size in ((0, b[False]), (1, (b[False] + b[1]) // 2), (2, (b[1] + b[2]) // 2)):
            size = size // 256 * 256
            g = G.build_geometry(model, G.HostSink(), size, compress="auto", **kw)
            self.assertEqual(g.stage, want, (want, size, b))
        with self.assertRaises(G.GeometryError):
            G.build_geometry(model, G.HostSink(), b[2] // 2 // 256 * 256, compress="auto", **kw)

    def test_env_budget(self):
        old = os.environ.get("ANATOMY_GEOM_QERR")
        try:
            os.environ["ANATOMY_GEOM_QERR"] = "0.5"
            self.assertEqual(Q.qerr_pixels(), 0.5)
            os.environ["ANATOMY_GEOM_QERR"] = "junk"
            self.assertEqual(Q.qerr_pixels(), Q.QERR_DEFAULT)
        finally:
            if old is None:
                os.environ.pop("ANATOMY_GEOM_QERR", None)
            else:
                os.environ["ANATOMY_GEOM_QERR"] = old


_FETCH = """
@group(0) @binding(10) var<storage, read_write> out_pos: array<f32>;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let n = arrayLength(&out_pos) / 3u;
    if (gid.x < n) {
        let p = g_pos(0u, gid.x);
        out_pos[3u * gid.x] = p.x;
        out_pos[3u * gid.x + 1u] = p.y;
        out_pos[3u * gid.x + 2u] = p.z;
    }
}
"""


@needs_gpu
class QuantGpu(unittest.TestCase):
    def test_shader_decode_is_bit_identical_to_the_cpu_decode(self):
        import wgpu
        model = synthetic_model(parts=3, n=40)
        # a part with a block that has to stay float32, and a wide-range part
        v = model.vertices.copy()
        lo, hi = v[:, 0:3].min(0), v[:, 0:3].max(0)
        v[5, 0:3] = (3e30, -3e30, 1.0)
        model = SimpleNamespace(vertices=v, indices=model.indices, parts=model.parts, lod=None, bounds_min=lo, bounds_max=hi)
        geom = G.build_geometry(model, G.GpuSink(GPU.device, flush_bytes=4096), 1 << 22, cluster_order=True, compress=2,
                                cluster_cache_use=False)
        host = G.build_geometry(model, G.HostSink(), 1 << 22, cluster_order=True, compress=2, cluster_cache_use=False)
        self.assertGreater(geom.quant["float_blocks"], 0)
        d, q = GPU.device, GPU.queue
        pg = geom.pages[0]
        code = (G.geom_prelude(1, 0, 0, uniform_binding=1, compressed=2) + "\n"
                + (ROOT / "app" / "gpu" / "wgsl" / "geom.wgsl").read_text() + _FETCH)
        mod = d.create_shader_module(code=code)
        n = pg.nverts
        ob = d.create_buffer(size=12 * n, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        po = np.ascontiguousarray(geom.page_offsets(0, 1), dtype=np.uint32)
        ub = d.create_buffer_with_data(data=po, usage=wgpu.BufferUsage.UNIFORM)
        pipe = d.create_compute_pipeline(layout="auto", compute={"module": mod, "entry_point": "main"})
        bg = d.create_bind_group(layout=pipe.get_bind_group_layout(0), entries=[
            {"binding": 0, "resource": {"buffer": pg.buffer, "offset": 0, "size": pg.buffer.size}},
            {"binding": 1, "resource": {"buffer": ub, "offset": 0, "size": po.nbytes}},
            {"binding": 10, "resource": {"buffer": ob, "offset": 0, "size": 12 * n}}])
        enc = d.create_command_encoder()
        cp = enc.begin_compute_pass()
        cp.set_pipeline(pipe)
        cp.set_bind_group(0, bg)
        cp.dispatch_workgroups((n + 63) // 64)
        cp.end()
        q.submit([enc.finish()])
        got = np.frombuffer(d.queue.read_buffer(ob), dtype=np.float32).reshape(-1, 3).copy()
        cpu, _ = G.decode_geometry(host, model)
        vo = np.asarray(geom.clusters.vorder, dtype=np.int64)
        for pi, p in enumerate(model.parts):
            vb = int(geom.vbase[pi])
            rows = vo[p.vertex_base:p.vertex_base + p.vertex_count]
            self.assertTrue(np.array_equal(got[vb:vb + p.vertex_count].view(np.uint32), cpu[rows, 0:3].view(np.uint32)), p.name)
        geom.release()


if __name__ == "__main__":
    unittest.main()
