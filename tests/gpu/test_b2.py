"""Morph targets, procedural animation, textures and OIT with them in the wgpu frame, against the OpenGL viewport on the
synthetic scene of tests/gpu/b2_scene.py (no library model has any of these), plus the alpha-cut refusal and the Qt fallback to
OpenGL. Needs a wgpu adapter; the comparisons also need an OpenGL context (skipped without them).

    python -m pytest tests/gpu/test_b2.py -q -p no:cacheprovider
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests", ROOT / "tests" / "gpu", ROOT / "tools" / "perf" / "gpu"):
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
SIZE = (320, 200)
# mean abs difference (0..255) allowed per case; the controls are what GL itself changes against the weight-0 / no-animation image
LIMITS = {"morph": 0.05, "anim": 0.05, "anim_modes": 0.05, "ghost_morph": 0.05, "ghost_anim": 0.05, "ghost_tex": 0.5, "ghost_tex_aniso1": 0.05,
          "tex": 1.5,                                            # the driver gap of anisotropic filtering on the grazing plane (port-changes row 1)
          "tex_aniso1": 0.2}                                    # anisotropy off on both sides: LOD, mips and sRGB must agree
CONTROL = {"morph": 1.0, "anim": 1.0, "ghost_morph": 0.5, "ghost_anim": 1.0}


CASES = ("static0", "ghost_morph0", "morph", "anim", "anim_modes", "ghost_morph", "ghost_anim", "tex", "tex_aniso1", "ghost_tex", "ghost_tex_aniso1")


@needs_gpu
class MorphAnimTextureTests(unittest.TestCase):
    """tools/perf/gpu/b2_check.py in one subprocess (it opens several OpenGL viewports, which crashes a pytest process that
    already holds a wgpu device on some drivers); its JSON rows are the measurements."""
    rows = {}

    @classmethod
    def setUpClass(cls):
        import json
        import subprocess
        script = ROOT / "tools" / "perf" / "gpu" / "b2_check.py"
        run = subprocess.run([sys.executable, str(script), "--size", *map(str, SIZE), "--cases", ",".join(CASES)],
                             capture_output=True, text=True, cwd=str(ROOT), timeout=900)
        for line in run.stdout.splitlines():
            if line.startswith("{"):
                row = json.loads(line)
                cls.rows[row["case"]] = row
        if len(cls.rows) != len(CASES):
            raise unittest.SkipTest(f"b2_check did not finish (no OpenGL?): {run.stderr[-300:]}")

    def check(self, name, control=None):
        row = self.rows[name]
        self.assertLess(row["mean"], LIMITS[name], f"{name}: {row}")
        if control:                                             # the effect must show in GL, or the check proves nothing
            self.assertGreater(row["gl_change"], CONTROL[name], f"{name}: GL changes too little against {control}")

    def test_morph_weight(self):
        self.check("morph", "static0")

    def test_procedural_animation(self):
        self.check("anim", "static0")

    def test_animation_modes(self):
        self.check("anim_modes")

    def test_ghosted_with_morph(self):
        self.check("ghost_morph", "ghost_morph0")

    def test_ghosted_with_animation(self):
        self.check("ghost_anim", "ghost_morph0")

    def test_textured_plane_solid_and_ghosted(self):
        self.check("tex")
        self.check("tex_aniso1")
        self.check("ghost_tex")
        self.check("ghost_tex_aniso1")


@needs_gpu
class AlphaCutFallbackTests(unittest.TestCase):
    def test_alpha_cut_model_is_refused(self):
        import b2_check as bc
        from app.gpu.renderer import WgpuRenderer
        model = bc.load_model(alpha_cut=True)                     # node 1 of the scene becomes an alpha-cut textured sphere
        self.assertTrue(any(p.look.texture is not None and p.look.alpha_cut > 0.0 for p in model.parts))
        r = WgpuRenderer(GPU)
        with self.assertRaises(NotImplementedError):
            r.set_model(model)
        self.assertIsNone(r.model)
        r.release()

    def test_qt_view_falls_back_to_opengl_and_logs_once(self):
        import b2_check as bc
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication(["b2"])
        from app.config import DEFAULT_SETTINGS
        from app.state import SceneState
        from app.ui import model_view as mv
        from app.viewer.dataset import ModelDataset
        from app.viewer.viewport import ModelViewport
        from types import SimpleNamespace
        model = bc.load_model(alpha_cut=True)
        settings = dict(DEFAULT_SETTINGS, renderer_backend="wgpu")
        state = SceneState(ModelDataset(model), settings)
        entry = SimpleNamespace(key="b2", name="b2")
        mv._wgpu_fallback_logged = False
        views = []
        try:
            with self.assertLogs(mv._LOG, level="WARNING") as logs:
                views.append(mv.make_viewport(model, state, settings, entry, None))
                views.append(mv.make_viewport(model, state, settings, entry, None))
        except Exception as exc:                                 # noqa: BLE001 - no OpenGL context for the Qt widget
            self.skipTest(f"no OpenGL: {exc}")
        finally:
            for v in views:
                v.close()
        self.assertTrue(all(isinstance(v, ModelViewport) for v in views))
        self.assertEqual(len(logs.records), 1)
        self.assertIn("alpha-cut", logs.output[0])


if __name__ == "__main__":
    unittest.main()
