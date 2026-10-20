"""Native GLB conversion retains canonical buffers and native teaching behavior."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np

from app.variants.local_runtime import decode_local_npz, prepare_local_model
from app.viewer.model import Model
from tools.export_native_glb import export_native_glb, sha256


class NativeGlbTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.output = self.root / "model.npz", self.root / "model.glb"
        self.row = dict(name="Cell \u03b1", group="Cells", color="#f1aabb", description="Authored cell",
                        alpha=.7, category="organ", label=False, clip=True, bulk=True, rank=3,
                        detail=[.025, 0, 0, 0])
        self.metadata = dict(parts=[self.row], viewer_cameras={"Front": {
            "position": [0, 0, 3], "target": [0, 0, 0], "hidden": [self.row["name"]], "labels_on": False}},
            start_view="Front", metres_per_unit=.001, home_view=[.1, .2], cut_on=True,
            cutaway=[[1, 0, 0], [0, 0, 1]], cut_at=[0, 0])
        self.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)

    def fixture(self, quantized=False):
        payload = dict(meta=np.frombuffer(json.dumps(self.metadata, ensure_ascii=False).encode("utf-8"), np.uint8),
                       p0=self.vertices, n0=np.tile([0, 0, 2.], (3, 1)).astype(np.float32),
                       i0=np.array([0, 1, 1], np.int32),
                       c0=np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], np.uint8))
        if quantized:
            payload.update(p0=(self.vertices * 65535).astype(np.uint16),
                           b0=np.array([[0, 0, 0], [1, 1, 1]]), n0=np.tile([0, 0, 127], (3, 1)).astype(np.int8))
        np.savez_compressed(self.source, **payload)
        return self.source

    def export(self, quantized=False):
        self.fixture(quantized)
        return export_native_glb(self.source, self.output, "native_fixture")

    def test_quantized_and_float_canonical_buffers_roundtrip(self):
        for quantized in (False, True):
            with self.subTest(quantized=quantized):
                output = self.output.with_name(f"q{quantized}.glb")
                self.fixture(quantized)
                before = sha256(self.source)
                report = export_native_glb(self.source, output, "native_fixture")
                self.assertEqual(report["verification"]["status"], "passed")
                self.assertEqual(sha256(self.source), before)
                model = Model(output)
                _, rows = decode_local_npz(self.source)
                np.testing.assert_array_equal(model.vertices[:, :3], rows[0][1])
                np.testing.assert_array_equal(model.vertices[:, 3:6], rows[0][2])
                np.testing.assert_array_equal(model.indices, rows[0][3].ravel())

    def test_native_semantics_and_look_survive_bare_glb_open(self):
        self.export()
        # Embedded metadata is sufficient when a GLB is opened without sidecars.
        self.output.with_suffix(".viewer.json").unlink()
        model = Model(self.output)
        item, part = model.items[0], model.parts[0]
        self.assertEqual(item.name, self.row["name"])
        self.assertFalse(item.label)
        self.assertTrue(item.clip)
        self.assertTrue(item.bulk)
        self.assertEqual(item.category, "organ")
        self.assertAlmostEqual(part.look.detail[0], .04)
        self.assertEqual(part.look.alpha, .7)
        self.assertEqual(part.look.sss, .15)
        self.assertTrue(part.look.use_vcol)
        self.assertEqual(model.home, (.1, .2))
        self.assertEqual(model.cutaway["on"], True)
        self.assertEqual(model.look_defaults, {"exposure": .35, "studio": .45})
        model.set_explode(1.)
        np.testing.assert_allclose(model.item_offsets, [[0, 1.05, 0]])
        self.assertEqual(model.cameras, self.metadata["viewer_cameras"])

    def test_local_library_open_uses_transport_controls(self):
        self.export()
        descriptor = SimpleNamespace(primary=SimpleNamespace(path=self.output), root=self.root,
                                     companions={}, record={"static_recipe": True})
        entry = SimpleNamespace(id="native_fixture", name="Fixture", variant="post", label="After",
                                descriptor=descriptor, summary="", scale_note="")
        model = prepare_local_model(entry)
        self.assertEqual(model.runtime_controls["native"]["start_view"], "Front")
        self.assertEqual(model.cameras["Front"]["hidden"], [self.row["name"]])
        self.assertEqual(model.metres_per_unit, .001)
        self.assertEqual(model.sidecar["start_view"], "Front")
        self.assertFalse(model.items[0].label)

    def test_source_and_previous_delivery_are_never_overwritten(self):
        self.export()
        before = sha256(self.output)
        with self.assertRaises(FileExistsError):
            export_native_glb(self.source, self.output, "native_fixture")
        self.assertEqual(sha256(self.output), before)
        with self.assertRaises(ValueError):
            export_native_glb(self.source, self.source, "native_fixture")


if __name__ == "__main__":
    unittest.main()
