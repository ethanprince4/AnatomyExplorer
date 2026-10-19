"""A .npz model dropped on the window (or chosen in File -> Open 3D model file) opens in the model viewer."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import time
import traceback
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
import numpy as np
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from app.ui.model_view import ModelView
from app.variants.catalog import DeferredVariantEntry
from app.variants.local_library import SingleFileLibrary
from app.variants.local_runtime import prepare_local_model


def write_npz(path, name="Wall"):
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    meta = {"parts": [dict(name=name, group="Tissue", color="#bb7777", description="", clip=False, bulk=True)],
            "metres_per_unit": .002, "cut_on": True}
    np.savez(path, meta=np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8), p0=verts,
             n0=np.tile([0., 0., 1.], (3, 1)).astype(np.float32), i0=np.array([0, 1, 1], dtype=np.int32))
    return Path(path)


def mime(*paths):
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return data


class SingleFileLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def entry(self, path):
        store = SingleFileLibrary(path)
        return DeferredVariantEntry(store.metadata(store.model_id), store)

    def test_bare_npz_prepares_through_the_library_path(self):
        entry = self.entry(write_npz(self.root / "thing_one.npz"))
        self.assertEqual(entry.name, "thing one")
        self.assertEqual(entry.descriptor.companions, {})
        model = prepare_local_model(entry)
        self.assertEqual([it.name for it in model.items], ["Wall"])

    def test_upper_case_extension_opens_too(self):
        # np.savez appends ".npz" to any other ending, so write lower case and rename
        entry = self.entry(write_npz(self.root / "scan.npz").rename(self.root / "SCAN.NPZ"))
        self.assertEqual(prepare_local_model(entry).items[0].name, "Wall")

    def test_companions_beside_the_file_are_picked_up(self):
        path = write_npz(self.root / "model.npz")
        (self.root / "recipe.json").write_text("{}", encoding="utf-8")
        (self.root / "catalog.json").write_text("{}", encoding="utf-8")
        entry = self.entry(path)
        self.assertEqual(entry.descriptor.companions, {"teaching_recipe": "recipe.json", "catalog": "catalog.json"})
        self.assertEqual(prepare_local_model(entry).items[0].name, "Wall")

    def test_opening_never_writes_next_to_the_file(self):
        path = write_npz(self.root / "model.npz")
        before, size = sorted(p.name for p in self.root.iterdir()), path.stat().st_size
        entry = self.entry(path)
        entry.commit_selection()
        prepare_local_model(entry)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        self.assertEqual(path.stat().st_size, size)

    def test_missing_file_and_non_model_files_give_readable_errors(self):
        with self.assertRaises(ValueError):
            self.entry(self.root / "absent.npz")
        np.savez(self.root / "other.npz", values=np.arange(3))
        (self.root / "text.npz").write_text("not an archive", encoding="utf-8")
        for name in ("other.npz", "text.npz"):
            with self.assertRaises(ValueError) as caught:
                self.entry(self.root / name).prepare_cpu(None)
            self.assertIn(f"{name} is not a 3D model file", str(caught.exception))


class NpzDropWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        fixture_root = Path(config.USER_DIR).resolve().parent
        self.assertTrue(fixture_root.name.startswith("anatomy-regression-"))
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(fixture_root))
        prefs.clear()
        self.errors = []
        hook = patch("sys.excepthook", lambda kind, value, tb:
                     self.errors.append("".join(traceback.format_exception(kind, value, tb))))
        hook.start()
        self.addCleanup(hook.stop)
        self.win = MainWindow(self.dataset, restore=False)
        self.addCleanup(self._close)
        self.dir = Path(config.USER_DIR) / "npz-drop"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _close(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()

    def _wait_until(self, predicate, message, timeout=8.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QAPP.processEvents()
            time.sleep(0.01)
        self.assertTrue(predicate(), f"{message}; errors={self.errors}")

    def drop(self, *paths):
        data = mime(*paths)
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, data, Qt.LeftButton, Qt.NoModifier)
        enter.ignore()
        self.win.dragEnterEvent(enter)
        if enter.isAccepted():
            self.win.dropEvent(QDropEvent(QPointF(5, 5), Qt.CopyAction, data, Qt.LeftButton, Qt.NoModifier))
        return enter.isAccepted()

    def test_drop_opens_the_first_npz_in_the_model_viewer(self):
        first, second = write_npz(self.dir / "a_model.npz", "Alpha"), write_npz(self.dir / "b_model.npz", "Beta")
        (self.dir / "notes.txt").write_text("x", encoding="utf-8")
        self.assertTrue(self.drop(self.dir / "notes.txt", first, second))
        model_id = f"file:{first.resolve()}"
        self._wait_until(lambda: model_id in self.win.micro_tabs, "the .npz tab was not installed")
        view = self.win.micro_tabs[model_id]
        self.assertIsInstance(view, ModelView)
        self.assertEqual([it.name for it in view.vmodel.items], ["Alpha"])
        self.assertNotIn(f"file:{second.resolve()}", self.win.micro_tabs)
        self.assertEqual(self.errors, [])

    def test_drop_of_other_files_is_still_refused_and_glb_still_accepted(self):
        (self.dir / "notes.txt").write_text("x", encoding="utf-8")
        self.assertFalse(self.drop(self.dir / "notes.txt"))
        from general_fixtures import write_fixture_model
        from app.viewer.catalog import FileEntry
        glb = self.dir / "dropped.glb"
        write_fixture_model(glb)
        self.assertTrue(self.drop(glb))
        self._wait_until(lambda: FileEntry(glb).id in self.win.micro_tabs, "the .glb tab was not installed")

    def test_file_that_is_not_a_model_shows_an_error_in_its_tab(self):
        bad = self.dir / "broken.npz"
        bad.write_text("not an archive", encoding="utf-8")
        self.assertTrue(self.drop(bad))
        pending = self.win._loading_models[f"file:{bad.resolve()}"]
        self._wait_until(lambda: pending.serial is None, "the failure was not reported")
        self.assertIn("broken.npz is not a 3D model file", pending.note.text())

    def test_missing_file_is_reported_in_the_status_bar(self):
        self.win.open_model_file(str(self.dir / "gone.npz"))
        self.assertIn("Could not open gone.npz", self.win.statusBar().currentMessage())
        self.assertFalse(self.win.micro_tabs)


if __name__ == "__main__":
    unittest.main()
