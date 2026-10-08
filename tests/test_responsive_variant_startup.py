"""Tiny slow-validator fixture: catalog controls remain usable; no MainWindow/GL."""
import os
from pathlib import Path
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from app.ui.search_panel import ModelCatalogPanel
from app.ui.shell import WorkspaceNotice
from app.variants.catalog import load_active_catalog, DeferredVariantEntry, VariantPreferenceCommit
from app.variants.readiness import start_dataset_readiness, cancel_dataset_readiness
from app.load_control import LoadToken, LoadCancelled
QAPP = QApplication.instance() or QApplication([])


class ResponsiveStartupTests(unittest.TestCase):
    def fixture(self):
        meta = SimpleNamespace(id="spleen", name="Generated fixture", summary="Metadata only", targets={},
            histology=(), related=(), clinical=(), scale_note="Synthetic scale", aliases=(),
            variants={v: SimpleNamespace(generation_id="fixture", variant=v) for v in ("pre", "post")})
        started, release = Event(), Event()
        def slow():
            started.set()
            release.wait(3)
            return {"generation_id": "fixture", "catalog_sha256": "a" * 64, "schema_version": 1,
                    "model_count": 1, "sequence": 1}
        store = SimpleNamespace(root=Path(tempfile.gettempdir()) / "synthetic-store", expected_model_ids={"spleen"},
            catalog_index=Mock(return_value=(meta,)), preferred=Mock(return_value="pre"), active_identity=Mock(side_effect=slow),
            catalog=Mock(side_effect=AssertionError("startup must not scan payloads")),
            resolve=Mock(side_effect=AssertionError("startup/choice must not read payloads")))
        return meta, store, started, release

    def test_bounded_catalog_and_switch_never_call_payload_validation(self):
        meta, store, _, _ = self.fixture()
        catalog = load_active_catalog(store=store)
        self.assertFalse(catalog.ready)
        self.assertEqual(catalog.verification_state, "pending")
        self.assertIsNone(catalog["spleen"].descriptor)
        chosen = catalog["spleen"].for_variant("post")
        self.assertEqual(chosen.variant, "post")
        store.catalog.assert_not_called()
        store.resolve.assert_not_called()
        store.active_identity.assert_not_called()

    def test_slow_whole_store_verifier_does_not_block_controls_and_cancel_is_safe(self):
        meta, store, started, release = self.fixture()
        catalog = load_active_catalog(store=store)
        window = QWidget()
        window._closing = False
        window.content = SimpleNamespace(micro_models=catalog, model_catalog_error="", tissues={})
        window.catalog = ModelCatalogPanel(window.content)
        window.notice = WorkspaceNotice()
        window._show_catalog = Mock()
        window.index = SimpleNamespace(replace_models=Mock())
        begin = time.monotonic()
        start_dataset_readiness(window, {})
        self.assertLess(time.monotonic() - begin, .2)
        self.assertTrue(started.wait(.5))
        beats = []
        QTimer.singleShot(0, lambda: beats.append("responsive"))
        window.catalog.edit.setText("generated")
        QAPP.processEvents()
        self.assertEqual(beats, ["responsive"])
        self.assertEqual(window.catalog.shown, 1)
        self.assertEqual(catalog.verification_state, "verifying")
        cancel_dataset_readiness(window)
        release.set()
        window._dataset_readiness_worker.join(1)
        QAPP.processEvents()
        self.assertFalse(catalog.ready)
        self.assertFalse(hasattr(window, "dataset_ready_identity"))
        window.close(); window.deleteLater(); window.catalog.deleteLater(); window.notice.deleteLater()

    def test_cancelled_preference_checkpoint_cannot_save(self):
        token = LoadToken(); token.cancel()
        store = SimpleNamespace(select=Mock())
        entry = SimpleNamespace(id="spleen", variant="post", store=store, descriptor=SimpleNamespace(token=("fixture",)))
        with self.assertRaises(LoadCancelled):
            VariantPreferenceCommit(entry).prepare_cpu(token)
        store.select.assert_not_called()

    def test_bounded_inset_and_version_choice_does_not_resolve_payload(self):
        meta,store,_,_=self.fixture();meta.id="axillary_skin"
        entry=DeferredVariantEntry(meta,store)
        inset=entry.for_component("cell_inset").for_variant("post")
        self.assertEqual(inset.component,"cell_inset");self.assertEqual(inset.variant,"post")
        self.assertIsNone(inset.descriptor)
        store.resolve.assert_not_called();store.active_identity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
