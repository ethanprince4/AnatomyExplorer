"""The shaded resolve's two exact speed-ups: direct reads of the look record (no private ShadeU copy) and the FEAT_*
pipeline overrides set from the looks of the drawn parts; plus the ANATOMY_AO_SCALE switch of the AO/GI resolution.

    python -m pytest tests/gpu/test_feat_overrides.py -q -p no:cacheprovider
"""
import os
import re
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from app.gpu import renderer as R                                # noqa: E402


def _gpu_or_none():
    try:
        from app.gpu.device import get_gpu
        return get_gpu()
    except Exception:
        return None


GPU = _gpu_or_none()
needs_gpu = unittest.skipIf(GPU is None, "no wgpu adapter available")


class TextTests(unittest.TestCase):
    def test_su_reads_routes_per_part_fields_to_the_look_and_the_rest_to_sg(self):
        out = R._su_reads("a = su.u_stripe_p.x + su.u_clip0.y; if (su.u_has_tex == 1) { }")
        self.assertEqual(out, "a = lk_u_stripe_p().x + sg.u_clip0.y; if (lk_u_has_tex() == 1) { }")
        self.assertNotIn("u_clip0", R.PER_PART)

    def test_look_features_bits(self):
        self.assertEqual(R._look_features({}), 0)
        self.assertEqual(R._look_features({"u_stripe": 1, "u_has_tex": 1}), R.FEAT_STRIPE | R.FEAT_TEX)
        self.assertEqual(R._look_features({"u_stripe": 2, "u_mottle": 1, "u_detail_on": 1}), R.FEAT_MOTTLE | R.FEAT_DETAIL)
        self.assertEqual(R.FEAT_ALL, R.FEAT_STRIPE | R.FEAT_MOTTLE | R.FEAT_TEX | R.FEAT_DETAIL)

    def test_every_per_part_field_has_a_reader(self):
        code = R._apply_look_wgsl()
        for n in R.PER_PART:
            self.assertIn(f"fn lk_{n}()", code)
        self.assertNotRegex(re.sub(r"//.*", "", code), r"\bsu\b")

    def test_feature_overrides_exist_in_the_shader_with_true_defaults(self):
        src = R._read_text("shading.wgsl")
        for name, _ in R._FEAT_NAMES:
            self.assertRegex(src, rf"override {name}: bool = true;")

    def test_morph_anim_overrides_exist_and_variant_follows_the_frame_feat(self):
        src = R._read_text("morph.wgsl")
        for name, _ in R._MORPH_NAMES:
            self.assertRegex(src, rf"override {name}: bool = true;")
        for frame_feat, want in ((0, (0.0, 0.0)), (R.FEAT_MORPH, (1.0, 0.0)), (R.FEAT_ANIM, (0.0, 1.0)),
                                 (R.FEAT_FRAME_ALL, (1.0, 1.0)), (R.FEAT_ALL, (0.0, 0.0))):
            dev = mock.MagicMock()
            fake = SimpleNamespace(_frame_feat=frame_feat, id_format="r32uint", _pipes={}, device=dev, bgl0_vis=0, bgl_vispage=0, bgl0_res=0,
                                   bgl_shade=0, _layout=lambda *a: 0, _bgl_vis=lambda s: 0, _bgl_pages=lambda n: 0,
                                   _vis_module=lambda: "m", _resolve_module=lambda *a: "m")
            R.WgpuRenderer._vis_pipe(fake, 4, False)
            R.WgpuRenderer._geom_pipe(fake, 4, 1, 0)
            R.WgpuRenderer._shade_pipe(fake, 4, 1, 0, frame_feat)
            for call, stage in zip(dev.create_render_pipeline.call_args_list, ("vertex", "fragment", "fragment")):
                c = call.kwargs[stage]["constants"]
                self.assertEqual((c["FEAT_MORPH"], c["FEAT_ANIM"]), want, (frame_feat, stage))
            self.assertEqual(len(fake._pipes), 3)

    def test_ao_scale_env(self):
        for v, want in (("", (1, 2)), ("gi", (1, 2)), ("full", (1, 1)), ("half", (2, 2)), ("FULL", (1, 1)), ("bogus", (1, 2))):
            with mock.patch.dict(os.environ, {"ANATOMY_AO_SCALE": v}):
                self.assertEqual(R.ao_gi_scales(), want, v)
        with mock.patch.dict(os.environ):
            os.environ.pop("ANATOMY_AO_SCALE", None)
            self.assertEqual(R.ao_gi_scales(), (1, 2))


@needs_gpu
class FeatureOverrideRenderTests(unittest.TestCase):
    """The same frame with the feature mask derived from the drawn looks and with every feature compiled in is identical."""

    def grab(self, vp, app, force_all):
        orig = R.WgpuRenderer._build_table

        def build(rr, *a, **k):
            out = orig(rr, *a, **k)
            if force_all:
                rr._frame_feat = R.FEAT_ALL
            seen.append(rr._frame_feat)
            return out
        seen = []
        with mock.patch.object(R.WgpuRenderer, "_build_table", build):
            for _ in range(3):
                vp.update()
                end = time.perf_counter() + 0.3
                while time.perf_counter() < end:
                    app.processEvents()
            img = vp.grab_image(1.0)
        return img, seen

    def test_masked_and_full_pipelines_draw_the_same_picture(self):
        from PySide6.QtWidgets import QApplication
        from test_frame import fixture_model
        from app.config import DEFAULT_SETTINGS
        from app.gpu.viewport import WgpuModelViewport
        from app.state import SceneState
        from app.viewer.dataset import ModelDataset
        app = QApplication.instance() or QApplication([])
        model = fixture_model()
        settings = dict(DEFAULT_SETTINGS)
        state = SceneState(ModelDataset(model), settings)
        vp = WgpuModelViewport(model, state, settings, SimpleNamespace(key="fixture", name="fixture"),
                               renderer_factory=lambda g: R.WgpuRenderer(g), gpu=GPU)
        vp.frame_cap_hz = 0
        vp.resize(200, 150)
        vp.show()
        vp.probe()
        end = time.perf_counter() + 5
        while vp.renderer is None and time.perf_counter() < end:
            app.processEvents()
        self.assertIsNotNone(vp.renderer)
        a, seen_a = self.grab(vp, app, False)
        b, seen_b = self.grab(vp, app, True)
        vp.close()
        self.assertTrue(seen_a and seen_b, "the draw table was built")
        self.assertTrue(set(seen_b) == {R.FEAT_ALL})
        self.assertNotIn(R.FEAT_ALL, seen_a, f"the fixture draws some looks without every feature: {set(seen_a)}")
        self.assertEqual(a.shape, b.shape)
        self.assertLessEqual(int(np.abs(a.astype(int) - b.astype(int)).max()), 2)


if __name__ == "__main__":
    unittest.main()
