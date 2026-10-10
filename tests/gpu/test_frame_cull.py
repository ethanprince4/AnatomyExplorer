"""The cluster culler inside the wgpu frame: a culled frame and an unculled frame of the same model decode to the same
parts and the same ORIGINAL triangles, picks agree, and a source-ordered renderer gives the same triangles as the
cluster-ordered one. Skips without a wgpu adapter.

    python -m pytest tests/gpu/test_frame_cull.py -q -p no:cacheprovider
"""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

W, H = 160, 120


def _gpu_or_none():
    try:
        from app.gpu.device import get_gpu
        return get_gpu()
    except Exception:
        return None


GPU = _gpu_or_none()
needs_gpu = unittest.skipIf(GPU is None, "no wgpu adapter available")


def sphere(n_lat=48, n_lon=96):
    """UV sphere of radius 1: positions, normals, uint32 indices (2 * n_lat * n_lon triangles, a few thousand clusters' worth
    of small ones)."""
    lat = np.linspace(0, np.pi, n_lat + 1)
    lon = np.linspace(0, 2 * np.pi, n_lon + 1)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    pos = np.stack([np.sin(la) * np.cos(lo), np.cos(la), np.sin(la) * np.sin(lo)], axis=-1).reshape(-1, 3).astype("<f4")
    idx = []
    for i in range(n_lat):
        for j in range(n_lon):
            a = i * (n_lon + 1) + j
            b = a + n_lon + 1
            idx += [a, b, a + 1, a + 1, b, b + 1]
    return pos, pos.copy(), np.array(idx, dtype="<u4")


def write_glb(path):
    """Two overlapping spheres (two nodes, two meshes) so that one hides part of the other."""
    pos, nrm, idx = sphere()
    pos2, nrm2, idx2 = sphere(40, 80)
    chunks = [pos.tobytes(), nrm.tobytes(), idx.tobytes(), (pos2 * 0.8).astype("<f4").tobytes(), nrm2.tobytes(), idx2.tobytes()]
    views, off = [], 0
    for c in chunks:
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(c)})
        off += len(c)
    binary = b"".join(chunks)
    acc = [{"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3", "min": pos.min(axis=0).tolist(),
            "max": pos.max(axis=0).tolist()},
           {"bufferView": 1, "componentType": 5126, "count": len(pos), "type": "VEC3"},
           {"bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
           {"bufferView": 3, "componentType": 5126, "count": len(pos2), "type": "VEC3", "min": (pos2 * 0.8).min(axis=0).tolist(),
            "max": (pos2 * 0.8).max(axis=0).tolist()},
           {"bufferView": 4, "componentType": 5126, "count": len(pos2), "type": "VEC3"},
           {"bufferView": 5, "componentType": 5125, "count": len(idx2), "type": "SCALAR"}]
    data = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}],
            "nodes": [{"name": "A", "mesh": 0}, {"name": "B", "mesh": 1, "translation": [0.9, 0.2, 0.3]}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2}]},
                       {"primitives": [{"attributes": {"POSITION": 3, "NORMAL": 4}, "indices": 5}]}],
            "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": acc}
    enc = json.dumps(data).encode("utf-8")
    enc += b" " * (-len(enc) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(enc) + len(binary)) + struct.pack("<I4s", len(enc), b"JSON") + enc +
                     struct.pack("<I4s", len(binary), b"BIN\0") + binary)


def make_model():
    from app.viewer.model import Model
    d = Path(tempfile.mkdtemp())
    write_glb(d / "m.glb")
    m = Model(d / "m.glb")
    m.evaluate(m.clip_range[0], None, 0.0)
    return m


def camera_for(model, yaw=0.4, pitch=0.3):
    from app.viewer.camera import OrbitCamera
    cam = OrbitCamera()
    cam.set_scene(model.bounds_min, model.bounds_max)
    cam.target = cam.scene_centre.copy()
    cam.distance = cam.fit_distance(cam.scene_radius, W / H)
    cam.yaw, cam.pitch = yaw, pitch
    cam.snap()
    return cam


def target():
    import wgpu
    return GPU.device.create_texture(size=(W, H, 1), format="rgba8unorm",
                                     usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC
                                     | wgpu.TextureUsage.TEXTURE_BINDING)


@needs_gpu
class CulledFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.gpu.renderer import WgpuRenderer
        from app.viewer.renderer import Settings
        cls.model = make_model()
        cls.s = Settings()
        cls.s.msaa = 4
        cls.tgt = target()
        cls.r = WgpuRenderer(GPU, cull="on")
        cls.r.set_model(cls.model)
        cls.plain = WgpuRenderer(GPU, cull="off")        # source-ordered geometry, never culls
        cls.plain.set_model(cls.model)

    @classmethod
    def tearDownClass(cls):
        cls.r.release()
        cls.plain.release()

    def frame(self, r, mode, cam, fs=None):
        r.cull_mode = mode
        r.render(self.tgt, (W, H), cam, self.s, fs)
        return r.read_ids()[0], r.read_depth(), r.read_model_triangles()

    def test_geometry_is_cluster_ordered_only_when_culling_can_run(self):
        self.assertTrue(self.r.geom.cluster_ordered)
        self.assertIsNotNone(self.r.culler)
        self.assertFalse(self.plain.geom.cluster_ordered)
        self.assertIsNone(self.plain.culler)

    def test_culled_and_unculled_frames_decode_to_the_same_triangles(self):
        for yaw, pitch in ((0.4, 0.3), (2.0, -0.4), (-1.0, 0.9)):
            cam = camera_for(self.model, yaw, pitch)
            for repeat in range(2):                       # the second frame runs with the first one's visibility history
                ids_c, depth_c, (part_c, tri_c) = self.frame(self.r, "on", cam)
                self.assertTrue(self.r.culled_frame)
                ids_u, depth_u, (part_u, tri_u) = self.frame(self.r, "off", cam)
                # compressed geometry has no index buffer: with culling off it still goes through the culler, every cluster accepted
                self.assertEqual(self.r.culled_frame, bool(self.r.geom.compressed))
                self.assertEqual(self.r.cull_accept_all, bool(self.r.geom.compressed))
                ids_s, depth_s, (part_s, tri_s) = self.frame(self.plain, "off", cam)
                self.assertGreater(int((ids_u >= 0).sum()), 500)
                for a, b, what in ((ids_c, ids_u, "items"), (part_c, part_u, "parts"), (ids_u, ids_s, "items (source order)"),
                                   (part_u, part_s, "parts (source order)")):
                    self.assertTrue(np.array_equal(a, b), f"{what} differ (yaw {yaw}, repeat {repeat})")
                # triangles: identical except where two triangles tie in depth (a shared edge) -- allow a handful of pixels
                n = int((part_u >= 0).sum())
                for a, b, what in ((tri_c, tri_u, "culled vs unculled"), (tri_u, tri_s, "ordered vs source order")):
                    bad = int((a != b).sum())
                    self.assertLessEqual(bad, max(2, n // 1000), f"{what}: {bad} of {n} pixels name another triangle")
                self.assertTrue(np.allclose(depth_c, depth_u, rtol=1e-5, atol=1e-5))

    def test_picks_give_the_original_triangle(self):
        cam = camera_for(self.model)
        pts = [(x, y) for y in range(7, H, 9) for x in range(7, W, 11)]
        self.frame(self.r, "on", cam)
        a = self.r.triangles_at(pts)
        items_a = self.r.ids_at(pts)
        self.frame(self.plain, "off", cam)
        b = self.plain.triangles_at(pts)
        items_b = self.plain.ids_at(pts)
        self.assertEqual(items_a, items_b)
        same = sum(1 for p, q in zip(a, b) if p == q)
        self.assertGreaterEqual(same, len(pts) - 2)
        self.assertGreater(sum(1 for p in a if p is not None), 15)
        # every returned triangle exists in the part's index array
        for t in a:
            if t is not None:
                part = self.model.parts[t[0]]
                self.assertLess(t[1], part.count // 3)

    def test_clip_plane_frame(self):
        from app.viewer.renderer import FrameState
        cam = camera_for(self.model)
        fs = FrameState()
        fs.clip_planes = np.array([[1, 0, 0, 0.1], [0, 0, 0, 0], [0, 0, 0, 0]], np.float32)
        fs.clip_on = (1, 0, 0)
        ids_c = self.frame(self.r, "on", cam, fs)
        ids_u = self.frame(self.r, "off", cam, fs)
        self.assertTrue(np.array_equal(ids_c[0], ids_u[0]))
        self.assertTrue(np.array_equal(ids_c[2][0], ids_u[2][0]))


@needs_gpu
class CompressedFrame(unittest.TestCase):
    """Compressed geometry (vertex renumbering + u16 indices) draws the same frame as uncompressed cluster-ordered geometry."""

    @classmethod
    def setUpClass(cls):
        from app.gpu.renderer import WgpuRenderer
        from app.viewer.renderer import Settings
        cls.model = make_model()
        cls.s = Settings()
        cls.s.msaa = 4
        cls.tgt = target()
        cls.cmp = WgpuRenderer(GPU, cull="on")
        cls.cmp.geom_compress = "on"
        cls.cmp.set_model(cls.model)
        cls.raw = WgpuRenderer(GPU, cull="on")
        cls.raw.geom_compress = "off"
        cls.raw.set_model(cls.model)
        cls.dflt = WgpuRenderer(GPU, cull="on")                 # default ANATOMY_GEOM_COMPRESS=auto: this model fits, so it stays plain
        cls.dflt.geom_compress = "auto"
        cls.dflt.set_model(cls.model)
        cls.auto = WgpuRenderer(GPU, cull="on")                 # compressed, culling switched off afterwards: accept-all culler
        cls.auto.geom_compress = "on"
        cls.auto.set_model(cls.model)
        cls.auto.cull_mode = "off"

    @classmethod
    def tearDownClass(cls):
        for r in (cls.cmp, cls.raw, cls.dflt, cls.auto):
            r.release()

    def frame(self, r, cam):
        r.render(self.tgt, (W, H), cam, self.s, None)
        return r.read_ids()[0], r.read_depth(), r.read_model_triangles()

    def test_the_geometry_is_compressed_only_when_asked_and_smaller(self):
        self.assertTrue(self.cmp.geom.compressed)
        self.assertFalse(self.raw.geom.compressed)
        self.assertEqual(self.dflt.geom_compress, "auto")
        self.assertFalse(self.dflt.geom.compressed)
        self.assertTrue(self.raw.geom.cluster_ordered)
        self.assertLess(self.cmp.geom.stats["index_bytes"], self.raw.geom.stats["index_bytes"])

    def test_same_frame_ids_depth_triangles_and_picks(self):
        for yaw, pitch in ((0.4, 0.3), (2.0, -0.4)):
            cam = camera_for(self.model, yaw, pitch)
            ids_r, depth_r, (part_r, tri_r) = self.frame(self.raw, cam)
            for r, what in ((self.cmp, "compressed, culled"), (self.auto, "compressed, accept-all")):
                ids_c, depth_c, (part_c, tri_c) = self.frame(r, cam)
                self.assertGreater(int((ids_c >= 0).sum()), 500)
                self.assertTrue(np.array_equal(ids_c, ids_r), what)
                self.assertTrue(np.array_equal(part_c, part_r), what)
                n = int((part_r >= 0).sum())
                self.assertLessEqual(int((tri_c != tri_r).sum()), max(2, n // 1000), what)
                self.assertTrue(np.allclose(depth_c, depth_r, rtol=1e-5, atol=1e-5), what)
        self.assertTrue(self.auto.geom.compressed and self.auto.culled_frame and self.auto.cull_accept_all)
        pts = [(x, y) for y in range(7, H, 9) for x in range(7, W, 11)]
        self.frame(self.cmp, cam)
        self.frame(self.raw, cam)
        a, b = self.cmp.triangles_at(pts), self.raw.triangles_at(pts)
        self.assertEqual(self.cmp.ids_at(pts), self.raw.ids_at(pts))
        self.assertGreaterEqual(sum(1 for p, q in zip(a, b) if p == q), len(pts) - 2)


if __name__ == "__main__":
    unittest.main()
