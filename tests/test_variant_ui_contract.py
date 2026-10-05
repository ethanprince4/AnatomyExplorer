"""Tiny isolated Qt controls and source-extracted routing; no native app or meshes."""
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from app.ui.variant_choice import VariantChoice
from app.variants.readiness import requirement_from_environment, verify_dataset_ready
QAPP = QApplication.instance() or QApplication([])


def extracted(name):
    tree = ast.parse((ROOT / "app/main_window.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {"__name": "app.main_window", "__package__": "app"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "isolated-route", "exec"), scope)
    return scope[name]


class ChoiceTests(unittest.TestCase):
    def setUp(self):
        self.widget = VariantChoice()
        self.addCleanup(self.widget.deleteLater)

    def test_labels_and_one_selected_version(self):
        entry = SimpleNamespace(available_variants=("pre", "post"), variant="pre")
        self.widget.set_entry(entry)
        self.assertEqual([self.widget.choice.itemText(i) for i in range(2)], ["Pre refine", "Post refine"])
        self.assertEqual(self.widget.choice.currentData(), "pre")
        self.assertEqual(self.widget.choice.accessibleName(), "Model version")

    def test_requested_version_is_not_persisted_by_control(self):
        self.widget.set_entry(SimpleNamespace(available_variants=("pre", "post"), variant="pre"))
        choices = []
        self.widget.requested.connect(choices.append)
        self.widget.choice.setCurrentIndex(1)
        self.widget.choice.activated.emit(1)
        self.assertEqual(choices, ["post"])
        self.assertEqual(self.widget.choice.currentData(), "pre", "old preference remains until load succeeds")

    def test_unavailable_version_is_disabled(self):
        self.widget.set_entry(SimpleNamespace(available_variants=("pre",), variant="pre"))
        choices = []
        self.widget.requested.connect(choices.append)
        self.widget.choice.activated.emit(1)
        self.assertFalse(self.widget.choice.model().item(1).isEnabled())
        self.assertEqual(choices, [])

    def test_no_entry_hides_and_disables_control(self):
        self.widget.set_entry(None)
        self.assertTrue(self.widget.isHidden())
        self.assertFalse(self.widget.choice.isEnabled())

    def test_no_change_is_reported_only_from_explicit_selected_post_outcome(self):
        self.widget.set_entry(SimpleNamespace(available_variants=("pre", "post"), variant="post", outcome="no_change"))
        self.assertEqual(self.widget.result_status.text(), "No changes from microrefine")
        self.widget.set_entry(SimpleNamespace(available_variants=("pre", "post"), variant="pre", outcome="no_change"))
        self.assertTrue(self.widget.result_status.isHidden())

    def test_inset_control_is_separate_from_version_and_keeps_old_scene_until_loaded(self):
        self.widget.set_entry(SimpleNamespace(available_variants=("pre", "post"), variant="post",
            available_components=("main", "cell_inset"), component="main"))
        choices=[];versions=[]
        self.widget.componentRequested.connect(choices.append);self.widget.requested.connect(versions.append)
        self.assertEqual([self.widget.scene.itemText(i) for i in range(2)],["Skin","Cell inset"])
        self.widget.scene.setCurrentIndex(1);self.widget.scene.activated.emit(1)
        self.assertEqual(choices,["cell_inset"]);self.assertEqual(versions,[])
        self.assertEqual(self.widget.scene.currentData(),"main")
        self.assertEqual(self.widget.choice.currentData(),"post")

    def test_other_models_have_no_inset_control(self):
        self.widget.set_entry(SimpleNamespace(available_variants=("pre","post"),variant="pre"))
        self.assertTrue(self.widget.scene_row.isHidden())


class RoutingTests(unittest.TestCase):
    def host(self, variant="pre", *, failure=None):
        entry = SimpleNamespace(id="retina", for_variant=Mock())
        chosen = SimpleNamespace(id="retina", variant="post")
        entry.for_variant.side_effect = failure
        entry.for_variant.return_value = chosen
        view = SimpleNamespace(entry=SimpleNamespace(id="retina", variant=variant), hide=Mock(),
                               deleteLater=Mock(), gl_widget=SimpleNamespace(release_gl=Mock()))
        host = SimpleNamespace(_closing=False, content=SimpleNamespace(micro_models={"retina": entry}),
            micro_tabs={"retina": view}, _loading_models={}, center=SimpleNamespace(indexOf=lambda w: 1,
                setCurrentWidget=Mock()), notice=SimpleNamespace(show_message=Mock()), _show_catalog=Mock(),
            catalog=SimpleNamespace(_preview=Mock()), lessons_panel=SimpleNamespace(practice=SimpleNamespace(stop=Mock())),
            quiz=SimpleNamespace(stop=Mock()), _cancel_reference_loads=Mock(), open_micro=Mock(),
            _reference_loads={}, _model_loader=SimpleNamespace(cancel=Mock()),
            viewport=SimpleNamespace(show=Mock()), anatomy_tab=SimpleNamespace(gl_widget=None))
        host._close_center_tab = Mock(side_effect=lambda index: host.micro_tabs.pop("retina", None))
        return host, entry, view, chosen

    def test_verification_failure_preserves_current_view_and_preference(self):
        host, entry, view, _ = self.host(failure=ValueError("hash mismatch"))
        extracted("switch_model_variant")(host, "retina", "post")
        self.assertIs(host.micro_tabs["retina"], view)
        host._close_center_tab.assert_not_called()
        host.open_micro.assert_not_called()
        host.notice.show_message.assert_called_once()

    def test_switch_retires_old_view_before_new_request(self):
        host, entry, view, chosen = self.host()
        extracted("switch_model_variant")(host, "retina", "post")
        self.assertEqual(host.micro_tabs, {})
        host.open_micro.assert_called_once_with("retina", entry=chosen, persist_variant=True)
        host.lessons_panel.practice.stop.assert_called_once()
        host.quiz.stop.assert_called_once()

    def test_same_version_only_focuses_existing_tab(self):
        host, entry, view, _ = self.host(variant="post")
        extracted("switch_model_variant")(host, "retina", "post")
        host.center.setCurrentWidget.assert_called_once_with(view)
        entry.for_variant.assert_not_called()
        host.open_micro.assert_not_called()

    def test_shared_reference_is_released_instead_of_showing_two_variants(self):
        host, entry, view, chosen = self.host()
        host.center.indexOf = lambda w: -1
        host._radiology_model_view = view
        extracted("switch_model_variant")(host, "retina", "post")
        view.hide.assert_called_once()
        view.gl_widget.release_gl.assert_called_once()
        view.deleteLater.assert_called_once()
        self.assertIsNone(host._radiology_model_view)
        self.assertIs(host.anatomy_tab.gl_widget, host.viewport)

    def test_component_switch_retires_previous_scene_without_saving_version_choice(self):
        host,entry,view,chosen=self.host(variant="post")
        entry.for_variant.return_value.for_component=Mock(return_value=chosen)
        extracted("switch_model_variant")(host,"retina","post",component="cell_inset")
        entry.for_variant.return_value.for_component.assert_called_once_with("cell_inset")
        host._close_center_tab.assert_called_once()
        host.open_micro.assert_called_once_with("retina",entry=chosen,persist_variant=False)

    def test_version_switch_preserves_active_inset_space(self):
        host,entry,view,chosen=self.host()
        view.entry.component="cell_inset"
        entry.for_variant.return_value.for_component=Mock(return_value=chosen)
        extracted("switch_model_variant")(host,"retina","post")
        entry.for_variant.return_value.for_component.assert_called_once_with("cell_inset")
        host.open_micro.assert_called_once_with("retina",entry=chosen,persist_variant=True)

    def test_component_route_keeps_selected_version_and_rejects_unrelated_scope(self):
        host=SimpleNamespace(micro_tabs={"axillary_skin":SimpleNamespace(entry=SimpleNamespace(variant="post"))},
                             switch_model_variant=Mock())
        route=extracted("switch_model_component")
        route(host,"retina","cell_inset");route(host,"axillary_skin","unshipped")
        host.switch_model_variant.assert_not_called()
        route(host,"axillary_skin","cell_inset")
        host.switch_model_variant.assert_called_once_with("axillary_skin","post",component="cell_inset")


class ReadinessTests(unittest.TestCase):
    def environment(self):
        return {"AE_REQUIRED_MODEL_GENERATION": "prepared-1", "AE_REQUIRED_MODEL_CATALOG_SHA256": "a" * 64,
                "AE_DATASET_READY_FILE": str(ROOT.parent / "receipt.json")}

    def store(self, **changes):
        identity = dict(generation_id="prepared-1", catalog_sha256="a" * 64, schema_version=1, model_count=39)
        identity.update(changes)
        return SimpleNamespace(active_identity=Mock(return_value=identity), expected_model_ids=range(39))

    def test_ordinary_update_has_no_dataset_deployment_requirement(self):
        self.assertIsNone(requirement_from_environment({}))

    def test_partial_request_fails_closed(self):
        with self.assertRaises(ValueError):
            requirement_from_environment({"AE_REQUIRED_MODEL_GENERATION": "prepared-1"})

    def test_corrupt_identity_never_produces_ready(self):
        requirement = requirement_from_environment(self.environment())
        for fields in ({"generation_id": "wrong"}, {"catalog_sha256": "b" * 64}, {"model_count": 38}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                verify_dataset_ready(self.store(**fields), requirement)

    def test_exact_prepared_generation_produces_separate_receipt(self):
        result = verify_dataset_ready(self.store(), requirement_from_environment(self.environment()))
        self.assertTrue(result["dataset_ready"])
        self.assertEqual(result["schema"], "anatomy-dataset-ready")
        self.assertEqual(result["application_health"], "renderer-ready")
        self.assertNotIn("model_render_acceptance", result)


class CompletionTests(unittest.TestCase):
    def fixture(self, *, requested=False, error="", commit_error=None):
        entry = SimpleNamespace(commit_selection=Mock(), descriptor=SimpleNamespace(token=("fixture", "retina", "post", "a" * 64)))
        old = object()
        pending = SimpleNamespace(serial=7, entry=entry, persist_variant=requested, callbacks=[],
                                  deleteLater=Mock(), prepared_view=None)
        view = SimpleNamespace(runtime_opening_done=True, runtime_opening_error=error,
                               runtime_session=SimpleNamespace(close=Mock()),
                               gl_widget=SimpleNamespace(release_gl=Mock()), deleteLater=Mock(), setParent=Mock(), entry=entry)
        center = SimpleNamespace(indexOf=lambda w: 1, currentWidget=lambda: pending,
            tabText=lambda i: "Loading selected version", blockSignals=Mock(), removeTab=Mock(),
            insertTab=Mock(), setCurrentWidget=Mock(), currentIndex=lambda: 1)
        host = SimpleNamespace(_closing=False, _loading_models={"retina": pending}, micro_tabs={}, center=center,
            content=SimpleNamespace(micro_models={"retina": old}), catalog=SimpleNamespace(_run=Mock()),
            _model_load_error=Mock(), _center_changed=Mock(), _preference_commits={},
            _model_loader=SimpleNamespace(request=Mock(return_value=42, side_effect=commit_error)),
            _publish_model_load=Mock())
        host._fail_prepared_model = lambda *args: extracted("_fail_prepared_model")(host, *args)
        result = SimpleNamespace(key="retina", serial=7)
        return host, pending, view, result, entry, old

    def test_default_open_publishes_pre_without_persisting_a_choice(self):
        host, pending, view, result, entry, _ = self.fixture()
        extracted("_complete_model_load")(host, result, pending, view)
        entry.commit_selection.assert_not_called()
        host._publish_model_load.assert_called_once_with(result, pending, view)
        self.assertEqual(host.micro_tabs, {})

    def test_explicit_choice_persists_after_authored_opening_succeeds(self):
        host, pending, view, result, entry, _ = self.fixture(requested=True)
        extracted("_complete_model_load")(host, result, pending, view)
        entry.commit_selection.assert_not_called()
        host._model_loader.request.assert_called_once()
        self.assertIn("variant-preference:retina", host._preference_commits)
        host._publish_model_load.assert_not_called()

    def test_authored_opening_failure_keeps_retry_and_old_preference(self):
        host, pending, view, result, entry, old = self.fixture(requested=True, error="bound teaching certificate missing")
        extracted("_complete_model_load")(host, result, pending, view)
        entry.commit_selection.assert_not_called()
        self.assertEqual(host.micro_tabs, {})
        self.assertIs(host.content.micro_models["retina"], old)
        host._model_load_error.assert_called_once()
        view.runtime_session.close.assert_called_once()

    def test_generation_change_during_selection_cannot_publish_view(self):
        host, pending, view, result, entry, old = self.fixture(requested=True, commit_error=ValueError("generation changed"))
        extracted("_complete_model_load")(host, result, pending, view)
        self.assertEqual(host.micro_tabs, {})
        self.assertIs(host.content.micro_models["retina"], old)
        host.center.insertTab.assert_not_called()
        view.gl_widget.release_gl.assert_called_once()

    def test_cancelled_and_stale_completions_cannot_persist(self):
        for closing, serial in ((True, 7), (False, 8)):
            host, pending, view, result, entry, old = self.fixture(requested=True)
            host._closing = closing
            pending.serial = serial
            extracted("_complete_model_load")(host, result, pending, view)
            entry.commit_selection.assert_not_called()
            self.assertEqual(host.micro_tabs, {})
            self.assertIs(host.content.micro_models["retina"], old)


if __name__ == "__main__":
    unittest.main()
