"""The opt-in live camera feed (app/live_camera.py) and the script that reads it (tools/camera_now.py).

Qt windows stay hidden (offscreen) and all preference fixtures live in a temporary directory."""
import atexit
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app import config, live_camera
from app.__main__ import configure_qt
from app.data import Dataset
from tests.fixture_paths import fixture_root

FIXTURES = tempfile.TemporaryDirectory(prefix="anatomy-livecam-")
atexit.register(FIXTURES.cleanup)
FIXTURE_ROOT = fixture_root(FIXTURES.name)
config.USER_DIR = FIXTURE_ROOT / "study"
config.ORG_NAME = "AnatomyExplorerRegression"
config.APP_NAME = "FixtureLiveCamera"
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(FIXTURE_ROOT))
QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(FIXTURE_ROOT))
configure_qt()
QAPP = QApplication.instance() or QApplication([])

from app.main_window import MainWindow

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "camera_now.py"
_spec = importlib.util.spec_from_file_location("camera_now_under_test", SCRIPT)
camera_now = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(camera_now)

TARGET = [0.12, 0.85, -0.2]


def pump(seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QAPP.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_script(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60,
                          env=env)


class LiveCameraTests(unittest.TestCase):
    dataset = None

    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def make_window(self, env_value):
        env = dict(os.environ)
        env.pop(live_camera.ENV_VAR, None)
        if env_value is not None:
            env[live_camera.ENV_VAR] = env_value
        with patch.dict(os.environ, env, clear=True):
            return MainWindow(self.dataset, restore=False)

    @staticmethod
    def close(win):
        win.close()
        win.deleteLater()
        QAPP.processEvents()

    def test_enabled_feed_follows_the_atlas_camera_and_the_script_reads_it(self):
        with tempfile.TemporaryDirectory(prefix="livecam-") as tmp:
            feed = Path(tmp) / "cam.json"
            jsonl = Path(tmp) / "shots.jsonl"
            win = self.make_window(str(feed))
            try:
                self.assertIsNotNone(win._live_camera)
                self.assertTrue(win._live_camera.timer.isActive())
                self.assertEqual(win._live_camera.path, feed)
                cam = win.viewport.camera
                cam.target = np.array(TARGET)
                cam.distance = 2.5
                cam.yaw = 0.7
                cam.pitch = -0.3

                def current():
                    d = read_json(feed)
                    return d if d and d["camera"]["distance"] == 2.5 and d["camera"]["yaw"] == 0.7 else None

                self.assertTrue(pump(3.0, current), "feed never showed the new camera")
                data = current()
                self.assertEqual(data["schema"], "anatomy.camera.v1")
                self.assertEqual(data["pid"], os.getpid())
                self.assertEqual(data["view"], "atlas")
                self.assertTrue(data["camera_visible"])
                self.assertIsInstance(data["time"], float)
                self.assertTrue(data["time_iso"])
                c = data["camera"]
                np.testing.assert_allclose(c["target"], TARGET)
                self.assertAlmostEqual(c["pitch"], -0.3)
                self.assertAlmostEqual(c["yaw_deg"], np.degrees(0.7))
                self.assertAlmostEqual(c["pitch_deg"], np.degrees(-0.3))
                np.testing.assert_allclose(c["eye"], cam.eye())
                np.testing.assert_allclose(c["look_dir"], -cam.forward_dir())
                np.testing.assert_allclose(np.array(c["eye"]) + c["distance"] * np.array(c["look_dir"]), TARGET)
                self.assertAlmostEqual(c["fov_deg"], cam.fov)
                st, dist, yaw, pitch = data["saved_view_camera"]
                self.assertEqual((st, dist, yaw, pitch), (TARGET, 2.5, 0.7, -0.3))
                self.assertEqual(data["saved_view_camera"], win.capture_view()["camera"])
                self.assertEqual(data["viewport"]["width"], win.viewport.width())
                self.assertIn("cut", data)
                self.assertEqual(data["cut"]["clip_on"], [False, False, False])

                # unchanged camera: heartbeat only, so the seq barely moves in 0.3 s
                seq = data["seq"]
                pump(0.3)
                self.assertLessEqual(read_json(feed)["seq"] - seq, 1)

                # the script prints the same camera
                done = run_script("--path", str(feed), "--label", "femur lateral", "--append", str(jsonl))
                self.assertEqual(done.returncode, 0, done.stderr)
                lines = done.stdout.strip().splitlines()
                self.assertEqual(len(lines), 1)
                out = json.loads(lines[0])
                self.assertEqual(out["camera"], c)
                self.assertEqual(out["label"], "femur lateral")
                saved = jsonl.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(json.loads(saved[0]), out)
                run_script("--path", str(feed), "--append", str(jsonl))
                self.assertEqual(len(jsonl.read_text(encoding="utf-8").strip().splitlines()), 2)

                # --pretty is indented and still the same data; the env var alone finds the file too
                pretty = run_script("--pretty", env=dict(os.environ, **{live_camera.ENV_VAR: str(feed)}))
                self.assertEqual(pretty.returncode, 0, pretty.stderr)
                self.assertGreater(len(pretty.stdout.strip().splitlines()), 10)
                self.assertEqual(json.loads(pretty.stdout)["camera"], c)

                # a moved camera is written again quickly
                cam.yaw = 1.1
                self.assertTrue(pump(3.0, lambda: (read_json(feed) or {}).get("camera", {}).get("yaw") == 1.1))
            finally:
                self.close(win)
            self.assertFalse(feed.exists(), "the feed file must go when the window closes")
            self.assertFalse(Path(str(feed) + ".tmp").exists())

    def test_feed_follows_a_model_tab_and_is_not_visible_on_non_3d_pages(self):
        from PySide6.QtWidgets import QWidget
        from app.viewer.catalog import FileEntry
        from tests.general_fixtures import write_fixture_model
        with tempfile.TemporaryDirectory(prefix="livecam-") as tmp:
            feed = Path(tmp) / "cam.json"
            model = Path(tmp) / "fixture.glb"
            write_fixture_model(model)
            win = self.make_window(str(feed))
            try:
                model_id = FileEntry(model).id
                win.open_model_file(str(model))
                # readiness callbacks wait for a first GPU draw that an offscreen run never makes: wait for the tab
                self.assertTrue(pump(20.0, lambda: model_id in win.micro_tabs), "model tab was not installed")
                view = win.micro_tabs[model_id]
                self.assertIs(win.center.currentWidget(), view)
                cam = view.gl_widget.camera
                cam.target = np.array([0.1, 0.2, 0.3])
                cam.distance = 1.75
                cam.yaw = -0.4
                cam.pitch = 0.25

                def current():
                    d = read_json(feed)
                    return d if d and d["view"] == "model" and d["camera"]["distance"] == 1.75 else None

                self.assertTrue(pump(3.0, current), "feed never showed the model camera")
                data = current()
                self.assertTrue(data["camera_visible"])
                self.assertEqual(data["model"]["id"], view.entry.id)
                self.assertEqual(data["model"]["name"], view.entry.name)
                self.assertEqual(data["model"]["key"], next(k for k, v in win.micro_tabs.items() if v is view))
                np.testing.assert_allclose(data["camera"]["target"], [0.1, 0.2, 0.3])
                np.testing.assert_allclose(data["camera"]["eye"], cam.eye())
                self.assertEqual(data["camera"]["ortho"], bool(cam.ortho))
                self.assertEqual(data["saved_view_camera"][1:], [1.75, -0.4, 0.25])
                self.assertIn("named_view", data)
                self.assertIn("cut_away", data["cut"])
                self.assertEqual(data["page"]["class"], type(view).__name__)

                # back on the atlas tab the feed describes the atlas camera again
                win.center.setCurrentIndex(0)
                self.assertTrue(pump(3.0, lambda: (read_json(feed) or {}).get("view") == "atlas"))

                # a page with no 3D view: still reports a camera, but says it is not on screen
                other = QWidget()
                win.center.addTab(other, "Other page")
                win.center.setCurrentWidget(other)
                self.assertTrue(pump(3.0, lambda: (read_json(feed) or {}).get("page", {}).get("tab") == "Other page"))
                self.assertFalse(read_json(feed)["camera_visible"])
            finally:
                self.close(win)
            self.assertFalse(feed.exists())

    def test_script_reports_a_missing_or_stale_feed_with_exit_code_2(self):
        with tempfile.TemporaryDirectory(prefix="livecam-") as tmp:
            missing = Path(tmp) / "none.json"
            done = run_script("--path", str(missing))
            self.assertEqual(done.returncode, 2)
            self.assertEqual(done.stdout, "")
            self.assertIn("not running", done.stderr)
            stale = Path(tmp) / "stale.json"
            stale.write_text(json.dumps({"time": time.time() - 30, "camera": {}}), encoding="utf-8")
            self.assertEqual(run_script("--path", str(stale)).returncode, 2)
            broken = Path(tmp) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertEqual(run_script("--path", str(broken)).returncode, 2)
            fresh = Path(tmp) / "fresh.json"
            fresh.write_text(json.dumps({"time": time.time(), "camera": {"distance": 1}}), encoding="utf-8")
            self.assertEqual(run_script("--path", str(fresh)).returncode, 0)

    def test_disabled_feed_has_no_timer_and_writes_nothing(self):
        for value in (None, "", "0"):
            with tempfile.TemporaryDirectory(prefix="livecam-") as tmp:
                with patch.object(live_camera.tempfile, "gettempdir", return_value=tmp):
                    win = self.make_window(value)
                    try:
                        self.assertIsNone(win._live_camera, value)
                        win.viewport.camera.yaw = 0.4
                        pump(0.3)
                    finally:
                        self.close(win)
                self.assertEqual(list(Path(tmp).rglob("*camera*.json*")), [], value)

    def test_path_logic_of_the_app_and_the_script_agree(self):
        with tempfile.TemporaryDirectory(prefix="livecam-") as tmp:
            expected = Path(tmp) / "AnatomyExplorer-live_camera.json"
            with patch.object(tempfile, "gettempdir", return_value=tmp):
                self.assertEqual(live_camera.default_path(), expected)
                self.assertEqual(camera_now.default_path(), expected)
                self.assertEqual(live_camera.feed_path({"ANATOMY_CAMERA_FEED": "1"}), expected)
                self.assertEqual(camera_now.feed_path({"ANATOMY_CAMERA_FEED": "1"}), expected)
            # the user dir the launcher may change plays no part
            with patch.object(config, "USER_DIR", Path(tmp) / "elsewhere"):
                self.assertEqual(live_camera.default_path(), camera_now.default_path())
            self.assertEqual(live_camera.feed_path({"ANATOMY_CAMERA_FEED": "x/y.json"}),
                             camera_now.feed_path({"ANATOMY_CAMERA_FEED": "x/y.json"}))
            self.assertEqual(live_camera.feed_path({"ANATOMY_CAMERA_FEED": "x/y.json"}), Path("x/y.json"))
            for off in ({}, {"ANATOMY_CAMERA_FEED": ""}, {"ANATOMY_CAMERA_FEED": "0"}):
                self.assertIsNone(live_camera.feed_path(off))


if __name__ == "__main__":
    unittest.main()
