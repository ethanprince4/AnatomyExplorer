"""wgpu host tests: device creation, the Qt presenter round trip, the viewport on a stand-in renderer, and the
backend switch with its OpenGL fallback. Everything that needs a GPU skips when no adapter is available.

    python -m pytest tests/gpu/test_host.py -q -p no:cacheprovider
"""
import math
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402
from PySide6.QtCore import QEventLoop                           # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

from app.config import DEFAULT_SETTINGS                         # noqa: E402
from app.gpu import device as dev                               # noqa: E402

COLOUR = (64, 128, 192, 255)


def qapp():
    return QApplication.instance() or QApplication([])


def _gpu_or_none():
    try:
        return dev.get_gpu()
    except dev.GpuUnavailable:
        return None


GPU = _gpu_or_none()
needs_gpu = unittest.skipIf(GPU is None, "no wgpu adapter available")


def pump(app, seconds=0.0, until=None):
    end = time.perf_counter() + max(seconds, 0.0) + (3.0 if until else 0.0)
    while time.perf_counter() < end:
        app.processEvents(QEventLoop.AllEvents)
        if until is not None and until():
            return True
    return until() if until else True


class DeviceTests(unittest.TestCase):
    @needs_gpu
    def test_gpu_fields(self):
        g = dev.get_gpu()
        self.assertIs(g, dev.get_gpu(), "one device per process")
        self.assertIsNotNone(g.device)
        self.assertIs(g.queue, g.device.queue)
        self.assertIsInstance(g.features, set)
        self.assertIsInstance(g.limits, dict)
        self.assertGreater(g.limits["max-storage-buffer-binding-size"], 128 * 1024 * 1024)
        self.assertIsInstance(g.prim_index, bool)
        self.assertEqual(g.prim_index, "primitive-index" in g.features)
        self.assertTrue(g.info)
        self.assertNotEqual(g.adapter_type, "CPU")

    @needs_gpu
    def test_wait_idle_returns(self):
        dev.wait_idle(dev.get_gpu())

    def test_unknown_adapter_name_raises_and_lists_adapters(self):
        saved = dict(os.environ)
        try:
            os.environ["ANATOMY_WGPU_ADAPTER"] = "no-such-adapter-xyz"
            dev.reset_gpu()
            with self.assertRaises(dev.GpuUnavailable) as cm:
                dev.get_gpu()
            self.assertIn("no-such-adapter-xyz", str(cm.exception))
            with self.assertRaises(dev.GpuUnavailable):               # the failure is remembered, not retried
                dev.get_gpu()
        finally:
            os.environ.clear()
            os.environ.update(saved)
            dev.reset_gpu()
            if GPU is not None:
                dev.get_gpu()

    @needs_gpu
    def test_adapter_choice_by_name_substring(self):
        name = GPU.name.split()[-1]
        picked = dev._choose_adapter(name)
        self.assertIn(name.lower(), dev._describe(picked)[0].lower())


def gradient(w, h):
    a = np.zeros((h, w, 4), np.uint8)
    a[..., 0] = np.arange(w, dtype=np.uint32)[None, :] % 251
    a[..., 1] = np.arange(h, dtype=np.uint32)[:, None] % 241
    a[..., 2] = 77
    a[..., 3] = 255
    return a


@needs_gpu
class HostRoundTripTests(unittest.TestCase):
    SIZE = (301, 203)                       # not a multiple of 64 pixels: the 256-byte row padding is exercised

    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def make(self, mode):
        from app.gpu.host import GpuWidget
        from tools.perf.gpu.present_bench import StandInRenderer
        w = GpuWidget(present_mode=mode, gpu=GPU)
        w.frame_cap_hz = 0
        w.resize(*self.SIZE)
        self.pattern = {}
        r = StandInRenderer(GPU, pattern=True)

        def draw(tex, tw, th):
            self.pattern["n"] = self.pattern.get("n", 0) + 1
            r.render(tex, (tw, th), None, None)
            return True

        w.render_callback = draw
        return w

    def test_both_modes_read_back_exact_pixels(self):
        for mode in ("sync", "async"):
            with self.subTest(mode=mode):
                w = self.make(mode)
                w.show()
                pw, ph = w._physical_size()
                img = w.present_image()
                self.assertEqual(img.shape, (ph, pw, 4))
                self.assertTrue(np.array_equal(img, gradient(pw, ph)))
                w.close()

    def test_flat_colour_through_qpainter(self):
        from tools.perf.gpu.present_bench import StandInRenderer
        for mode in ("sync", "async"):
            with self.subTest(mode=mode):
                w = self.make(mode)
                r = StandInRenderer(GPU, COLOUR)
                w.render_callback = lambda tex, tw, th: r.render(tex, (tw, th), None, None) or True
                w.show()
                image = w.grab().toImage()                      # the real paintEvent and QPainter.drawImage path
                dpr = w.devicePixelRatioF()
                self.assertEqual((image.width(), image.height()), (math.ceil(self.SIZE[0] * dpr), math.ceil(self.SIZE[1] * dpr)))
                iw, ih = image.width(), image.height()
                for x, y in ((0, 0), (iw // 2, ih // 2), (iw - 3, ih - 3)):
                    c = image.pixelColor(x, y)
                    self.assertEqual((c.red(), c.green(), c.blue()), COLOUR[:3], (mode, x, y))
                w.close()

    def test_translucent_child_blends_over_the_gpu_image(self):
        """The model viewer's Overlay is a translucent child widget; half-transparent red over COLOUR must be the 50 % blend."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtWidgets import QWidget
        from tools.perf.gpu.present_bench import StandInRenderer

        class Layer(QWidget):
            def paintEvent(self, event):
                p = QPainter(self)
                p.fillRect(50, 40, 100, 60, QColor(255, 0, 0, 128))
                p.end()

        for mode in ("sync", "async"):
            with self.subTest(mode=mode):
                w = self.make(mode)
                r = StandInRenderer(GPU, COLOUR)
                w.render_callback = lambda tex, tw, th: r.render(tex, (tw, th), None, None) or True
                layer = Layer(w)
                layer.setAttribute(Qt.WA_TranslucentBackground, True)
                layer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                layer.setGeometry(w.rect())
                w.show()
                image = w.grab().toImage()
                inside, outside = image.pixelColor(100, 70), image.pixelColor(10, 10)
                self.assertEqual((outside.red(), outside.green(), outside.blue()), COLOUR[:3])
                expect = tuple(round(COLOUR[i] * (1 - 128 / 255) + (255, 0, 0)[i] * (128 / 255)) for i in range(3))
                got = (inside.red(), inside.green(), inside.blue())
                self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(got, expect)), (got, expect))
                w.close()

    def test_repaint_blits_without_rendering(self):
        for mode in ("sync", "async"):
            with self.subTest(mode=mode):
                w = self.make(mode)
                w.show()
                w.grab()
                pump(self.app, 0.1)
                n = self.pattern["n"]
                for _ in range(5):
                    w.repaint()                                  # what the translucent overlay child causes
                    pump(self.app, 0.02)
                self.assertEqual(self.pattern["n"], n, "a plain repaint must not render the scene again")
                w.update()
                self.assertTrue(pump(self.app, until=lambda: self.pattern["n"] > n))
                w.close()

    def test_async_shows_the_last_frame_when_rendering_stops(self):
        w = self.make("async")
        w.show()
        for _ in range(6):
            w.update()
            pump(self.app, 0.03)
        shown = pump(self.app, until=lambda: w._shown_frame == w._frame - 1)
        self.assertTrue(shown, (w._shown_frame, w._frame))
        w.close()

    def test_resize_recreates_texture_and_never_shows_old_size(self):
        for mode in ("sync", "async"):
            with self.subTest(mode=mode):
                w = self.make(mode)
                w.show()
                w.present_image()
                w.resize(257, 131)
                pump(self.app, 0.05)
                img = w.present_image()
                pw, ph = w._physical_size()
                self.assertEqual(img.shape[:2], (ph, pw))
                self.assertEqual(tuple(w._tex.size[:2]), (pw, ph))
                self.assertTrue(np.array_equal(img, gradient(pw, ph)))
                w.close()

    def test_hide_frees_and_show_renders_again(self):
        w = self.make("async")
        w.show()
        w.present_image()
        w.hide()
        self.assertIsNone(w._tex)
        self.assertEqual(w._slots, [])
        n = self.pattern["n"]
        w.show()
        pump(self.app, 0.2)
        self.assertGreater(self.pattern["n"], n)
        w.close()

    def test_default_mode_is_a_known_mode(self):
        from app.gpu import host
        self.assertIn(host.DEFAULT_PRESENT_MODE, host.PRESENT_MODES)


def _model():
    try:
        from tools.perf.viewer_session import timed_prepare
        entry, model, _ = timed_prepare("eyeball")
        return entry, model
    except Exception:                                           # noqa: BLE001 - no model library on this machine
        return None, None


@needs_gpu
class ViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        cls.entry, cls.model = _model()
        if cls.model is None:
            raise unittest.SkipTest("model library not available")

    def make(self, factory):
        from app.config import DEFAULT_SETTINGS
        from app.gpu.viewport import WgpuModelViewport
        from app.state import SceneState
        from app.viewer.dataset import ModelDataset
        settings = dict(DEFAULT_SETTINGS)
        state = SceneState(ModelDataset(self.model), settings)
        vp = WgpuModelViewport(self.model, state, settings, self.entry, renderer_factory=factory, gpu=GPU)
        vp.frame_cap_hz = 0
        return vp

    def test_probe_paint_and_grab_image_on_stand_in(self):
        from tools.perf.gpu.present_bench import StandInRenderer
        vp = self.make(lambda g: StandInRenderer(g, COLOUR))
        failures = []
        vp.graphicsFailed.connect(failures.append)
        ready = []
        vp.interactiveReady.connect(lambda: ready.append(1))
        vp.probe()
        self.assertIsNotNone(vp.renderer)
        vp.resize(401, 307)
        vp.show()
        self.assertTrue(pump(self.app, until=lambda: bool(ready)), "interactiveReady never fired")
        shot = vp.grab_image(1.0)
        pw, ph = vp._physical_size()
        self.assertEqual(shot.shape, (ph, pw, 3))
        self.assertEqual(tuple(shot[ph // 2, pw // 2]), COLOUR[:3])
        self.assertTrue((shot == np.array(COLOUR[:3], np.uint8)).all())
        self.assertEqual(vp.pick_full(vp.rect().center())[0], -1)
        self.assertEqual(failures, [])
        vp.hide()
        self.assertIsNone(vp.renderer, "a hidden tab frees its renderer like the OpenGL viewport")
        vp.show()
        self.assertTrue(pump(self.app, until=lambda: vp.renderer is not None))
        vp.close()

    def test_failing_factory_emits_graphics_failed(self):
        def boom(gpu):
            raise RuntimeError("renderer exploded")
        vp = self.make(boom)
        failures = []
        vp.graphicsFailed.connect(failures.append)
        vp.resize(200, 150)
        vp.show()
        self.assertTrue(pump(self.app, until=lambda: bool(failures)))
        self.assertIn("renderer exploded", failures[0])
        self.assertEqual(vp.graphics_error, failures[0])
        vp.close()

    def test_missing_renderer_module_is_a_graphics_failure(self):
        from app.config import DEFAULT_SETTINGS
        from app.gpu.viewport import WgpuModelViewport
        from app.state import SceneState
        from app.viewer.dataset import ModelDataset
        settings = dict(DEFAULT_SETTINGS)
        state = SceneState(ModelDataset(self.model), settings)
        vp = WgpuModelViewport(self.model, state, settings, self.entry, gpu=GPU)
        with mock.patch.dict(sys.modules, {"app.gpu.renderer": None}):      # makes "from .renderer import" fail
            with self.assertRaises(RuntimeError):
                vp.probe()
        self.assertTrue(vp.graphics_error)
        vp.close()


class SwitchTests(unittest.TestCase):
    """model_view.make_viewport: setting, environment override and the OpenGL fallback (no GPU needed for these)."""

    def setUp(self):
        qapp()
        from app.ui import model_view
        self.mv = model_view
        model_view._wgpu_fallback_logged = False
        self.saved = os.environ.pop("ANATOMY_RENDERER", None)

    def tearDown(self):
        os.environ.pop("ANATOMY_RENDERER", None)
        if self.saved is not None:
            os.environ["ANATOMY_RENDERER"] = self.saved

    def test_backend_setting_and_environment(self):
        rb = self.mv.renderer_backend
        platform_default = "wgpu" if sys.platform == "darwin" else "opengl"
        self.assertEqual(rb({}), platform_default)
        self.assertEqual(rb({"fast_renderer": True}), "wgpu")
        self.assertEqual(rb({"fast_renderer": False}), "opengl")
        self.assertEqual(rb({"renderer_backend": "wgpu", "fast_renderer": False}), "wgpu")
        self.assertEqual(rb({"renderer_backend": "nonsense"}), platform_default)
        os.environ["ANATOMY_RENDERER"] = "opengl"
        self.assertEqual(rb({"renderer_backend": "wgpu", "fast_renderer": True}), "opengl")
        os.environ["ANATOMY_RENDERER"] = "WGPU"
        self.assertEqual(rb({"renderer_backend": "opengl", "fast_renderer": False}), "wgpu")

    def test_fast_renderer_defaults_on_only_on_macos(self):
        self.assertEqual(DEFAULT_SETTINGS["fast_renderer"], sys.platform == "darwin")

    def test_default_builds_the_opengl_viewport_with_the_same_arguments(self):
        fake = mock.Mock(return_value="gl-viewport")
        settings = {"fast_renderer": False}
        with mock.patch.object(self.mv, "ModelViewport", fake):
            out = self.mv.make_viewport("m", "s", settings, "e", "parent")
        self.assertEqual(out, "gl-viewport")
        fake.assert_called_once_with("m", "s", settings, "e", parent="parent")

    def test_wgpu_failure_falls_back_to_opengl_and_logs_once(self):
        class Broken:
            disposed = 0

            def __init__(self, *a, **k):
                pass

            def probe(self):
                raise RuntimeError("no adapter")

            def dispose(self):
                Broken.disposed += 1

        fake = mock.Mock(return_value="gl-viewport")
        with mock.patch.object(self.mv, "ModelViewport", fake), \
                mock.patch("app.gpu.viewport.WgpuModelViewport", Broken):
            with self.assertLogs(self.mv._LOG, level="WARNING") as logs:
                first = self.mv.make_viewport("m", "s", {"renderer_backend": "wgpu"}, "e", "p")
            self.assertEqual(first, "gl-viewport")
            self.assertEqual(len(logs.records), 1)
            self.assertIn("no adapter", logs.output[0])
            with self.assertNoLogs(self.mv._LOG, level="WARNING"):
                self.assertEqual(self.mv.make_viewport("m", "s", {"renderer_backend": "wgpu"}, "e", "p"), "gl-viewport")
        self.assertEqual(Broken.disposed, 2)
        self.assertEqual(fake.call_count, 2)

    def test_forced_device_failure_falls_back(self):
        """A real WgpuModelViewport whose adapter cannot be found must end as the OpenGL viewport."""
        entry, model = _model()
        if model is None:
            self.skipTest("model library not available")
        from app.config import DEFAULT_SETTINGS
        from app.state import SceneState
        from app.viewer.dataset import ModelDataset
        settings = dict(DEFAULT_SETTINGS, renderer_backend="wgpu")
        state = SceneState(ModelDataset(model), settings)
        fake = mock.Mock(return_value="gl-viewport")
        saved = os.environ.get("ANATOMY_WGPU_ADAPTER")
        os.environ["ANATOMY_WGPU_ADAPTER"] = "no-such-adapter-xyz"
        dev.reset_gpu()
        try:
            with mock.patch.object(self.mv, "ModelViewport", fake), self.assertLogs(self.mv._LOG, level="WARNING"):
                out = self.mv.make_viewport(model, state, settings, entry, None)
        finally:
            if saved is None:
                os.environ.pop("ANATOMY_WGPU_ADAPTER", None)
            else:
                os.environ["ANATOMY_WGPU_ADAPTER"] = saved
            dev.reset_gpu()
        self.assertEqual(out, "gl-viewport")


if __name__ == "__main__":
    unittest.main()
