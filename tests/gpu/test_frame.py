"""The wgpu model-viewer frame on a small fixture model: the full pass chain (backdrop, visibility, resolve, SSAO, shade,
composite, final blit) against the OpenGL viewport on the same camera, settings and state; row order; picks. Needs a wgpu
adapter, and an OpenGL context for the comparison part (skipped without them).

    python -m pytest tests/gpu/test_frame.py -q -p no:cacheprovider
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


def _gpu_or_none():
    try:
        from app.gpu.device import get_gpu
        return get_gpu()
    except Exception:
        return None


GPU = _gpu_or_none()
needs_gpu = unittest.skipIf(GPU is None, "no wgpu adapter available")
LW, LH = 160, 120


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def fixture_model():
    from general_fixtures import write_fixture_model
    from app.viewer.model import Model
    d = Path(tempfile.mkdtemp())
    write_fixture_model(d / "m.glb")
    m = Model(d / "m.glb")
    m.evaluate(m.clip_range[0], None, 0.0)
    return m


def make_state(model):
    from app.config import DEFAULT_SETTINGS
    from app.state import SceneState
    from app.viewer.dataset import ModelDataset
    settings = dict(DEFAULT_SETTINGS)
    state = SceneState(ModelDataset(model), settings)
    state.opaque_materials = model.kind == "procedural"
    state.part_alpha = np.ones(len(model.items), dtype=np.float32)
    return settings, state


def gl_viewport(model):
    """(widget, image rows top-first RGB) from the OpenGL viewport, or None without a context."""
    try:
        from app.viewer.viewport import ModelViewport
        settings, state = make_state(model)
        w = ModelViewport(model, state, settings, SimpleNamespace(key="fixture", name="fixture"))
        w.resize(LW, LH)
        w.reset_view(animate=False)
        img = w.grabFramebuffer()
        if w.graphics_error or w.renderer is None:
            return None
        for _ in range(2):
            img = w.grabFramebuffer()
        img = img.convertToFormat(img.Format.Format_RGBA8888)
        arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes()).reshape(
            img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :3].copy()
        return w, arr
    except Exception:                                           # noqa: BLE001 - no OpenGL on this machine
        return None


@needs_gpu
class FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _app()
        from app.gpu.renderer import WgpuRenderer
        cls.model = fixture_model()
        cls.gl = gl_viewport(cls.model)
        cls.r = WgpuRenderer(GPU)
        cls.r.set_model(cls.model)

    def render(self, w, frames=3):
        import wgpu
        pw, ph = w._physical_size()
        rw, rh = w._render_size()
        tex = GPU.device.create_texture(size=(pw, ph, 1), format="rgba8unorm",
                                        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC
                                        | wgpu.TextureUsage.TEXTURE_BINDING)
        w._sync_settings()
        for _ in range(frames):                                  # frame 2 reads frame 1's resolved colour, like GL
            self.r.render(tex, (rw, rh), w.camera, w.rsettings, w.frame_state(), out_size=(pw, ph))
        img = self.r.read_final(tex, (pw, ph))
        tex.destroy()
        return img

    def test_frame_runs_and_shows_the_model_over_the_backdrop(self):
        if self.gl is None:
            self.skipTest("no OpenGL context for the viewport")
        w, ref = self.gl
        img = self.render(w)
        self.assertEqual(img.shape, ref.shape)
        self.assertTrue(self.r.frame_ok)
        self.assertGreater(float(np.abs(img.astype(int) - img[0, 0]).max()), 20, "the model is drawn over the backdrop")

    def test_matches_opengl_on_the_same_view(self):
        if self.gl is None:
            self.skipTest("no OpenGL context for the viewport")
        w, ref = self.gl
        img = self.render(w)
        d = np.abs(img.astype(int) - ref.astype(int))
        self.assertLess(float(d.mean()), 1.0, "mean absolute difference (of 255)")
        self.assertLess(float((d.max(2) > 8).mean()), 0.01, "fraction of pixels over 8/255")
        # top first: the backdrop gradient runs the same way in both
        self.assertLess(int(np.abs(img[0, 0].astype(int) - ref[0, 0].astype(int)).max()), 3)
        self.assertLess(int(np.abs(img[-1, 0].astype(int) - ref[-1, 0].astype(int)).max()), 3)

    def test_picks_agree_with_opengl(self):
        if self.gl is None:
            self.skipTest("no OpenGL context for the viewport")
        from PySide6.QtCore import QPointF
        w, ref = self.gl
        self.render(w)
        lw, lh = w.width(), w.height()                              # the widget may refuse a size this small
        sx, sy = self.r.size[0] / lw, self.r.size[1] / lh
        agree = n = 0
        for j in range(8):
            for i in range(10):
                x, y = (i + 0.5) * lw / 10, (j + 0.5) * lh / 8
                gl_item = int(w.pick_at(QPointF(x, y)))
                wg_item = self.r.pick(int(x * sx), int(y * sy))[0]
                n += 1
                agree += int(gl_item == wg_item)
        self.assertGreaterEqual(agree / n, 0.97, f"{agree}/{n} picks agree")


if __name__ == "__main__":
    unittest.main()
