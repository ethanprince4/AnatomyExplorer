"""Cut faces (caps.py) with cluster masks on and off: the cap targets are identical bit for bit, and every mask is sound.

A cut part of a cluster-ordered geometry gets three masked copies of its index range (app/gpu/wgsl/caps_cull.wgsl): clusters wholly
on the removed side are turned into zero-area triangles in all of them, clusters wholly on the kept side are drawn without the clip
test in the parity pass. None of it may change a pixel, and the claims must hold for the vertices themselves: a REMOVED cluster has
no vertex-hull point on the kept side, a KEPT one none on the removed side. Both page layouts (u32 indices, compressed pages).
The scene is the cap parity scene (tools/perf/gpu/caps_parity.py). Needs a wgpu adapter only (no GL).

    python -m pytest tests/gpu/test_caps_cluster.py -q -p no:cacheprovider
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

SIZE = (256, 192)


def _setup():
    try:
        from app.gpu.device import get_gpu
        gpu = get_gpu()
        from tools.perf.gpu import caps_parity as cp
        model = cp.build_scene(1.0)
        return gpu, cp, model, {"order": cp.WGSide(gpu, model, SIZE, order=True, compress=False),
                                "compressed": cp.WGSide(gpu, model, SIZE, order=True, compress=True)}
    except Exception as exc:
        return exc


STATE = _setup()
needs = unittest.skipIf(isinstance(STATE, Exception), f"no wgpu adapter or scene: {STATE!r}")

PL1 = [(-1, 0, 0, 0.15), (0, 0, 0, 0), (0, 0, 0, 0)]               # removes x > 0.15
PL2 = [(-1, 0, 0, 0.15), (0, -1, 0, 0.25), (0, 0, 0, 0)]
PL3 = [(-1, 0, 0, 0.15), (0, -1, 0, 0.25), (0, 0, -1, 0.3)]
FLIP = [(1, 0, 0, 0.1), (0, 0, 0, 0), (0, 0, 0, 0)]                # flipped: removes x < -0.1
CASES = [(PL1, (1, 0, 0), 0, 0.4, 0.3, False), (FLIP, (1, 0, 0), 0, -0.5, 0.2, False),
         (PL2, (1, 1, 0), 0, 0.5, 0.45, False), (PL2, (1, 1, 0), 1, 0.55, 0.5, False),
         (PL3, (1, 1, 1), 0, 0.6, 0.5, False), (PL3, (1, 1, 1), 1, 0.6, 0.55, False),
         (PL1, (1, 0, 0), 0, 0.35, 0.25, True)]


@needs
class CapCluster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gpu, cls.cp, cls.model, cls.sides = STATE

    def plan(self, wg, planes, on, mode, yaw, pitch, ortho, compact=True):
        from app.viewer.renderer import FrameState, Settings
        cp, model = self.cp, self.model
        w, h = SIZE
        cam = cp.make_camera(model, w, h, yaw, pitch, ortho)
        V, P = cam.view_matrix(), cam.proj_matrix(w / h)
        fs = FrameState(clip_planes=planes, clip_on=tuple(bool(x) for x in on), clip_mode=mode)
        s = Settings(msaa=1, ao=False, shadows=False)
        clip = (np.array(planes, np.float32), tuple(int(x) for x in on), mode)
        draws = [p for p in model.parts if not p.look.translucent]
        wg.caps.compact = compact
        wg.caps.min_density = 0
        wg.caps.compact_min = 1
        plan = wg.caps.plan(model, wg.geom, draws, P @ V, V, SIZE, fs, s, clip, cam)
        return plan, clip

    def targets(self, wg, plan):
        enc = wg.dev.create_command_encoder()
        wg.caps.encode_gather(enc, plan)
        wg.dev.queue.submit([enc.finish()])
        t = wg.caps.t
        return {"zp": wg.read(t["zp"], np.float32, 1), "albedo": wg.read(t["albedo"], np.float16, 4),
                "normal": wg.read(t["normal"], np.float16, 4), "id": wg.read(t["id"], np.float32, 2),
                "key": wg.read(t["key"], np.float32, 1)}

    def lists(self, wg, plan, disable=False):
        """(out (2, slots, 192) uint32, args (parts, 16) uint32) of the cull dispatches; disable: planes off (every cluster KEPT)."""
        caps = wg.caps
        if disable:
            caps.device.queue.write_buffer(caps._cc_ub, 48, np.zeros(4, np.uint32).tobytes())
        enc = wg.dev.create_command_encoder()
        caps.encode_gather(enc, plan)
        wg.dev.queue.submit([enc.finish()])
        n = 2 * plan.mask.slots * 192 * 4
        out = np.frombuffer(bytes(wg.dev.queue.read_buffer(caps._mb["out"], 0, n)), np.uint32).reshape(2, plan.mask.slots, 192)
        args = np.frombuffer(bytes(wg.dev.queue.read_buffer(caps._mb["args"], 0, len(plan.mask.table) * 64)), np.uint32).reshape(-1, 16)
        return out, args

    def check_same(self, side, planes, on, mode, yaw, pitch, ortho):
        wg = self.sides[side]
        pa, _ = self.plan(wg, planes, on, mode, yaw, pitch, ortho, True)
        a = self.targets(wg, pa)
        pb, _ = self.plan(wg, planes, on, mode, yaw, pitch, ortho, False)
        b = self.targets(wg, pb)
        self.assertIsNotNone(pa.mask, "no part got cluster masks")
        self.assertIsNone(pb.mask)
        self.assertGreater(int((a["zp"] > 0).sum()), 100)
        for k in a:
            self.assertTrue(np.array_equal(a[k], b[k]), f"{side} {k} differs")
        return pa

    def test_same_targets_u32_pages(self):
        for case in CASES:
            with self.subTest(case=case[1:]):
                self.check_same("order", *case)

    def test_same_targets_compressed_pages(self):
        for case in CASES:
            with self.subTest(case=case[1:]):
                self.check_same("compressed", *case)

    def vertex_world(self, wg, pi, words):
        """World positions (f64) of page-local vertex numbers of part index pi."""
        geom, model = wg.geom, self.model
        part = model.parts[pi]
        local = words.astype(np.int64) - int(geom.vbase[pi])
        if geom.compressed:
            mv = geom.clusters.vorder[part.vertex_base + local].astype(np.int64)
        else:
            mv = part.vertex_base + local
        pos = np.asarray(model.vertices[mv, 0:3], np.float64)
        M = np.asarray(model.part_matrix(part), np.float64)
        return pos @ M[:3, :3].T + M[:3, 3]

    def test_lists_are_sound(self):
        seen = {0: 0, 1: 0, 2: 0}
        for side in ("order", "compressed"):
            wg = self.sides[side]
            for planes, on, mode, yaw, pitch, ortho in CASES:
                plan, clip = self.plan(wg, planes, on, mode, yaw, pitch, ortho)
                mk = plan.mask
                self.assertIsNotNone(mk)
                out0, args0 = self.lists(wg, plan, disable=True)               # planes off: the cap list holds every cluster
                plan, clip = self.plan(wg, planes, on, mode, yaw, pitch, ortho)    # planes back (plan rewrites the uniform)
                out, args = self.lists(wg, plan)
                P = np.asarray(planes, np.float64)
                for t in range(len(mk.table)):
                    di, cl0, ncl, first, count, slot = (int(x) for x in mk.table[t, :6])
                    self.assertEqual(int(args0[t, 0]), 192 * ncl)
                    full = out0[0, slot:slot + ncl]
                    n_cap, n_k, n_s = (int(args[t, i]) // 192 for i in (0, 5, 10))
                    cap = out[0, slot:slot + n_cap]
                    kept = out[1, slot:slot + n_k]
                    strad = out[1, slot + ncl - n_s:slot + ncl][::-1]
                    self.assertEqual(n_cap, n_k + n_s)
                    self.assertEqual([int(args[t, i]) for i in (1, 6, 11)], [1, 1, 1])
                    row = {full[j].tobytes(): j for j in range(ncl)}
                    kj = [row[r.tobytes()] for r in kept]
                    sj = [row[r.tobytes()] for r in strad]
                    cj = [row[r.tobytes()] for r in cap]
                    self.assertEqual(kj, sorted(kj))
                    self.assertEqual(sj, sorted(sj))
                    self.assertEqual(cj, sorted(kj + sj))                         # the cap list: both classes in the part's cluster order
                    cls = np.full(ncl, 2)
                    cls[kj] = 0
                    cls[sj] = 1
                    pi = plan.parts[di]
                    for j in range(ncl):
                        ntri = min(64, count // 3 - 64 * j)
                        words = full[j][:3 * ntri]
                        seen[int(cls[j])] += 1
                        d = self.vertex_world(wg, pi, words) @ P[:, :3].T + P[:, 3]            # (verts, 3) distances
                        d = d[:, [i for i in range(3) if on[i]]]
                        if cls[j] == 2:
                            ok = (d < 0).all() if mode == 1 else (d < 0).all(0).any()
                            self.assertTrue(ok, f"{side}: cluster {j} of draw {di} called REMOVED but has kept points")
                        if cls[j] == 0:
                            ok = (d >= 0).all(0).any() if mode == 1 else (d >= 0).all()
                            self.assertTrue(ok, f"{side}: cluster {j} of draw {di} called KEPT but has removed points")
        self.assertTrue(all(v > 0 for v in seen.values()), seen)

    def part_of_draw(self, plan, di):
        """Part index (model order) of cap draw di: the plan lists its records in part order of the cut items."""
        return plan.parts[di]


if __name__ == "__main__":
    unittest.main()
