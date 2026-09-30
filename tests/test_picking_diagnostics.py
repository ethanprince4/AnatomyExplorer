"""Independent controls for the picking diagnostic, not a Mac fix assertion."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from app.picking_diagnostics import SENTINELS, control_localization, json_safe, sentinel_vertex_bytes
from tests.fixture_paths import fixture_root


class DiagnosticOracleTests(unittest.TestCase):
    def test_known_values_exercise_both_uint16_bytes(self):
        self.assertEqual(SENTINELS, (2, 257, 3922))
        self.assertEqual(len(sentinel_vertex_bytes(3922)), 84)
        for encoded in SENTINELS:
            payload = sentinel_vertex_bytes(encoded)
            for offset in (0, 28, 56):
                self.assertEqual(struct.unpack_from("<H", payload, offset + 24)[0], encoded - 1)
                self.assertEqual(struct.unpack_from("<H", payload, offset + 26)[0], 73)

    def test_uniform_failure_prevents_attribute_cause_claim(self):
        self.assertIn("target/readback", control_localization(False, False))
        self.assertIn("inference withheld", control_localization(False, True))
        self.assertIn("integer VAO", control_localization(True, False))
        self.assertIn("actual mesh IDs", control_localization(True, True))
        self.assertIn("production shader", control_localization(True, True, False))
        self.assertIn("all_three_passed", control_localization(True, True, True))

    def test_failed_raw_reads_stay_valid_json(self):
        encoded = json.dumps(json_safe({"rgba": [float("nan"), float("inf"), 0.0, 1.0]}), allow_nan=False)
        self.assertEqual(json.loads(encoded)["rgba"], [None, None, 0, 1])


@unittest.skipUnless(os.environ.get("ANATOMY_GPU_DIAGNOSTICS") == "1", "opt-in real GPU subprocess")
class IndependentGPUControlsTests(unittest.TestCase):
    def test_actual_production_attachment_preserves_independent_ids(self):
        # A new process ensures a real Qt context and excludes other test windows.
        with tempfile.TemporaryDirectory() as directory:
            path = fixture_root(directory) / "controls.json"
            result = subprocess.run([sys.executable, "-m", "app.picking_diagnostics", "--gpu-controls-only",
                                     "--report", str(path)], cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=60)
            report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr + str(report.get("error")))
            self.assertTrue(report["passed"])
            controls = report["controls"]
            self.assertEqual(controls["expected_source"], "fixed CPU constants")
            self.assertEqual(controls["attachment"]["TEXTURE_INTERNAL_FORMAT"], 0x822E)  # R32F
            self.assertEqual(controls["attachment"]["FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE"], 0x1406)  # FLOAT
            self.assertEqual(controls["attachment"]["completeness"], 0x8CD5)
            for kind in ("uniform", "integer_attribute"):
                self.assertEqual([row["expected_encoded"] for row in controls[kind]], [2, 257, 3922])
                for row, expected in zip(controls[kind], (2, 257, 3922)):
                    self.assertEqual(row["occupied"]["raw_rgba"][0], expected)
                    self.assertEqual(row["occupied"]["production_scalar"], expected)
                    self.assertEqual(row["occupied"]["production_pick"], expected - 1)
                    self.assertEqual(row["background"]["raw_rgba"][0], 0)
                    self.assertEqual(row["background"]["production_pick"], -1)
                    for region in ("occupied", "background"):
                        self.assertFalse(row[region]["errors"])
                        native = row[region]["native_unclamped"]
                        self.assertFalse(native["errors"])
                        self.assertEqual(native["bound_state"]["READ_FRAMEBUFFER_BINDING"], controls["same_renderer_attachment"])
                        self.assertEqual(native["bound_state"]["READ_BUFFER"], 0x8CE2)
                        self.assertEqual(native["bound_state"]["CLAMP_READ_COLOR"], 0)
                        self.assertEqual(native["rgba"][0], expected if region == "occupied" else 0)
            production = report["production_controls"]
            self.assertTrue(production["passed"], str(production.get("error")))
            self.assertEqual(production["same_renderer_attachment"], controls["same_renderer_attachment"])
            self.assertEqual(production["vao_format"], "3f 3f u2 u2")
            self.assertEqual([row["expected_encoded"] for row in production["rows"]], [2, 257, 3922])
            for row, expected in zip(production["rows"], (2, 257, 3922)):
                self.assertEqual(row["occupied"]["raw_rgba"][0], expected)
                self.assertEqual(row["occupied"]["production_pick"], expected - 1)
                self.assertEqual(row["background"]["raw_rgba"][0], 0)
                self.assertEqual(row["background"]["production_pick"], -1)
                self.assertAlmostEqual(row["raw_depth"], 0.5, places=5)
                self.assertFalse(row["render_errors"])


if __name__ == "__main__":
    unittest.main()
