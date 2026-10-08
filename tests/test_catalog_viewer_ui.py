"""Metadata-only/native-widget regressions. No datasets, model files or OpenGL rendering.

Run against the assembled source with QT_QPA_PLATFORM=offscreen and python -B -m unittest.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QWidget

from app.config import DEFAULT_SETTINGS
from app.search import SearchEntry
from app.state import SceneState
from app.ui.search_panel import ModelCatalogPanel, SearchPanel, ResultDelegate, ROLE_ENTRY
from app.ui.tree_panel import TreePanel
from app.ui.systems_panel import SystemsPanel, RegionsPanel
from app.ui.view_panel import ViewPanel
from app.ui.model_loading import ModelLoadingTab
from app.ui.info_panel import InfoPanel
from app.ui.model_view import ModelView

QAPP = QApplication.instance() or QApplication([])


def dataset():
    systems = [{"key": "skeletal", "name": "Skeletal system", "default_visible": True,
                "color": [0.7, 0.7, 0.7], "subsystems": [{"name": "Bones"}]}]
    nodes = {
        "root": {"name": "Upper limb", "latin": "Membrum superius", "kind": "group", "count": 2,
                 "children": ["a", "b"], "system": "skeletal"},
        "a": {"name": "Radius", "latin": "Radius Latin", "kind": "structure", "sid": 0,
              "children": [], "system": "skeletal"},
        "b": {"name": "Ulna", "latin": "Ulna Latin", "kind": "structure", "sid": 1,
              "children": [], "system": "skeletal"},
    }
    ds = SimpleNamespace(n=2, systems=systems, regions=[{"key": "arm_l", "name": "Left arm"},
                                                     {"key": "arm_r", "name": "Right arm"}],
        system_index={"skeletal": 0}, system_of=np.array([0, 0]), subsystem_of=np.array([0, 0]),
        subsystems=[("skeletal", "Bones")], subsystem_index={("skeletal", "Bones"): 0},
        subsystem_system=np.array([0]), subsystem_default=[True], subsystems_by_system=[np.array([0])],
        region_mask=np.array([1, 2]), nodes=nodes, tree_roots=["root"], node_of_structure={0: "a", 1: "b"},
        counts={"triangles": 0}, attribution=[], landmarks=[], definitions={})
    ds.node_structures = lambda nid: [0, 1] if nid == "root" else [0 if nid == "a" else 1]
    ds.structures = [{"name": "Radius", "side": "Left"}, {"name": "Ulna", "side": "Right"}]
    return ds


def entry(mid, kind="procedural", name=None):
    return SimpleNamespace(id=mid, kind=kind, name=name or mid, summary="A source-authored model overview.",
        kind_name={"procedural": "3D microanatomy model", "glb": "3D model", "downloaded": "Downloaded model"}[kind],
        order=100, targets={"structures": ["Upper limb"]}, histology=[], related=[], clinical=[],
        scale_note="Schematic enlargement.", credit_html="", load=Mock(side_effect=AssertionError("No model load")))


class Widgets(unittest.TestCase):
    def keep(self, widget):
        self.addCleanup(widget.deleteLater)
        return widget

    def tearDown(self):
        QAPP.processEvents()


class CatalogTests(Widgets):
    def panel(self):
        self.entries = [entry("p"), entry("heart", "glb", "Whole heart"), entry("d", "downloaded")]
        content = SimpleNamespace(micro_models={e.id: e for e in self.entries}, tissues={})
        return self.keep(ModelCatalogPanel(content))

    def test_all_catalog_kinds_and_metadata_do_not_load_models(self):
        panel = self.panel()
        self.assertEqual(panel.shown, 3)
        self.assertIn("Schematic enlargement", panel.preview.toPlainText())
        for e in self.entries:
            e.load.assert_not_called()

    def test_filter_linked_structure_and_kind(self):
        panel = self.panel()
        panel.edit.setText("upper limb")
        self.assertEqual(panel.shown, 3)
        panel.kind_filter.setCurrentIndex(panel.kind_filter.findData("procedural"))
        self.assertEqual(panel.shown, 1)
        self.assertEqual(panel.list.currentItem().data(ROLE_ENTRY).id, "p")

    def test_no_match_disables_open_then_select_model_clears_filters(self):
        panel = self.panel()
        panel.edit.setText("does not exist")
        self.assertEqual(panel.shown, 0)
        self.assertFalse(panel.open_button.isEnabled())
        self.assertIn("No models match", panel.info.text())
        self.assertTrue(panel.select_model("heart"))
        self.assertTrue(panel.open_button.isEnabled())
        self.assertEqual(panel.list.currentItem().data(ROLE_ENTRY).id, "heart")
        self.assertFalse(panel.select_model("missing"))

    def test_selection_does_not_open_but_enter_and_button_do(self):
        panel = self.panel()
        opened = []
        panel.activated.connect(opened.append)
        panel.list.setCurrentRow(1)
        self.assertEqual(opened, [])
        QTest.keyClick(panel.edit, Qt.Key_Return)
        panel.open_button.click()
        self.assertEqual(opened, ["p", "p"])

    def test_arrow_navigation_escape_and_empty_catalog(self):
        panel = self.panel()
        QTest.keyClick(panel.edit, Qt.Key_Down)
        self.assertEqual(panel.list.currentRow(), 1)
        panel.edit.setText("Whole")
        QTest.keyClick(panel.edit, Qt.Key_Escape)
        self.assertEqual(panel.shown, 3)
        empty = self.keep(ModelCatalogPanel(SimpleNamespace(micro_models={}, tissues={})))
        self.assertFalse(empty.open_button.isEnabled())
        self.assertIn("No validated new models", empty.info.text())


class SearchTests(Widgets):
    def panel(self):
        entries = [SearchEntry("structure", "Radius", "Skeletal", [0], "skeletal"),
                   SearchEntry("micro", "Radius model", "3D model", [], node="radius-model")]
        index = SimpleNamespace(entries=entries, search=Mock(return_value=entries))
        panel = self.keep(SearchPanel(dataset(), index))
        return panel, index

    def test_kind_filter_applies_before_limit_and_empty_query_browses_type(self):
        panel, index = self.panel()
        panel.kind_filter.setCurrentIndex(panel.kind_filter.findData("micro"))
        panel._timer.stop(); panel._run()
        self.assertEqual(panel.shown, 1)
        self.assertEqual(panel.list.item(0).data(ROLE_ENTRY).kind, "micro")
        panel.edit.setText("radius")
        panel._timer.stop(); panel._run()
        self.assertEqual(index.search.call_args.kwargs["limit"], 150)

    def test_enter_flushes_debounce_and_clear_removes_stale_results(self):
        panel, _ = self.panel()
        opened, active = [], []
        panel.activated.connect(opened.append); panel.queryActive.connect(active.append)
        panel.edit.setText("radius")
        QTest.keyClick(panel.edit, Qt.Key_Return)
        self.assertEqual(len(opened), 1)
        panel.edit.clear()
        panel._activate_current()
        self.assertEqual(len(opened), 1)
        self.assertEqual(panel.shown, 0)
        self.assertFalse(active[-1])

    def test_failure_has_recovery_message_and_no_stale_activation(self):
        panel, index = self.panel()
        index.search.side_effect = ValueError("invalid index")
        panel.edit.setText("radius"); panel._timer.stop(); panel._run()
        self.assertIn("retry", panel.info.text())
        self.assertEqual(panel.shown, 0)

    def test_rows_grow_with_font_scale(self):
        delegate = ResultDelegate()
        opt = QStyleOptionViewItem()
        h1 = delegate.sizeHint(opt, None).height()
        from PySide6.QtGui import QFontMetrics
        font = opt.font; font.setPointSize(28)
        opt.fontMetrics = QFontMetrics(font)
        self.assertGreater(delegate.sizeHint(opt, None).height(), h1)


class TreeAndSystemsTests(Widgets):
    def setUp(self):
        self.ds = dataset()
        self.state = SceneState(self.ds, dict(DEFAULT_SETTINGS))

    def test_latin_and_group_matches_retain_children_and_restore_expansion(self):
        panel = self.keep(TreePanel(self.ds, self.state))
        root = panel.items["root"]
        root.setExpanded(False)
        panel.filter.setText("membrum")
        self.assertFalse(panel.items["a"].isHidden())
        self.assertFalse(panel.items["b"].isHidden())
        panel.filter.clear()
        self.assertFalse(root.isExpanded())
        panel.filter.setText("Radius Latin")
        self.assertTrue(panel.items["b"].isHidden())
        panel.reveal(1)
        self.assertEqual(panel.filter.text(), "")
        self.assertEqual(panel.tree.currentItem(), panel.items["b"])
        self.assertTrue(root.isExpanded())

    def test_empty_filter_and_keyboard_tree_activation(self):
        panel = self.keep(TreePanel(self.ds, self.state))
        panel.filter.setText("missing")
        self.assertIn("No matches", panel.info.text())
        panel.filter.clear()
        activated = []; panel.nodeActivated.connect(activated.append)
        panel.tree.itemActivated.emit(panel.items["a"], 0)
        self.assertEqual(activated, ["a"])

    def test_system_counts_opacity_and_regions_follow_state(self):
        panel = self.keep(SystemsPanel(self.ds, self.state))
        self.assertEqual(panel.count_labels[0].text(), "2/2")
        self.state.set_hidden([1], True)
        self.assertEqual(panel.count_labels[0].text(), "1/2")
        self.state.set_system_alpha(0, .45)
        self.assertEqual(panel.sliders[0].value(), 45)
        self.assertEqual(panel.opacity_values[0].text(), "45%")
        regions = self.keep(RegionsPanel(self.ds, self.state))
        regions._set_all(False)
        self.assertIn("No regions", regions.summary.text())
        regions._side("_l")
        self.assertEqual(self.state.region_on.tolist(), [True, False])


class FakeAtlasViewport:
    def __init__(self):
        self.clip_on = [False] * 3; self.clip_pos = [.5] * 3; self.clip_flip = [False] * 3
        self.set_radiology_slice = Mock()

    def scene_bounds(self):
        return (0, 0, 0), (1, 1, 1)


class ViewControlTests(Widgets):
    def test_empty_cross_section_row_is_disabled_and_cannot_activate(self):
        panel = self.keep(ViewPanel(dict(DEFAULT_SETTINGS), FakeAtlasViewport()))
        picked = []; panel.sectionPicked.connect(picked.append)
        panel._pick_section(panel.section_list.item(0))
        self.assertEqual(picked, [])
        self.assertFalse(panel.section_list.item(0).flags() & Qt.ItemIsEnabled)
        panel.show_section([(1, None, 1)], dataset())
        panel._pick_section(panel.section_list.item(0))
        self.assertEqual(picked, [1])

    def test_dissection_and_section_controls_have_honest_enabled_states(self):
        panel = self.keep(ViewPanel(dict(DEFAULT_SETTINGS), FakeAtlasViewport()))
        self.assertFalse(panel.depth_in.isEnabled())
        panel.enable_depth(True)
        self.assertTrue(panel.depth_in.isEnabled())
        panel.set_clip(0, True, .25, True)
        self.assertTrue(panel.clip_widgets[0][1].isEnabled())
        self.assertEqual(panel.vp.clip_pos[0], .25)
        panel.reset_clips()
        self.assertFalse(panel.clip_widgets[0][1].isEnabled())


class LoadingAndDetailsTests(Widgets):
    def test_loading_error_retry_contract_and_plain_text(self):
        panel = self.keep(ModelLoadingTab(entry("<Fixture>")))
        retries = []; panel.retryRequested.connect(lambda: retries.append(True))
        panel.set_error("Missing <model> file")
        self.assertTrue(panel.progress.isHidden())
        self.assertFalse(panel.retry.isHidden())
        self.assertEqual(panel.note.textFormat(), Qt.PlainText)
        panel.retry.click(); self.assertEqual(retries, [True])
        panel.set_loading()
        self.assertTrue(panel.retry.isHidden())
        self.assertEqual(panel.cancel.text(), "Cancel loading")

    def test_details_actions_are_native_fixed_and_clear_for_unrelated_view(self):
        content = SimpleNamespace(histology={"tissues": []}, clinical=[], micro_models={})
        panel = self.keep(InfoPanel(dataset(), content))
        actions = []; panel.linkActivated.connect(lambda a, b: actions.append((a, b)))
        panel._set(panel._actions([("Focus", "frame"), ("Hide", "hide")]) + "<p>A description</p>")
        panel._action_buttons["frame"].click()
        self.assertEqual(actions, [("act", "frame")])
        self.assertFalse(panel.actions_bar.isHidden())
        panel.show_html("<h1>Model</h1>", "<p>Metadata</p>")
        self.assertTrue(panel.actions_bar.isHidden())
        panel.set_font_scale(1.5)
        self.assertIn("Metadata", panel.browser.toPlainText())
        self.assertGreater(panel.browser.document().defaultFont().pointSizeF(), 12)


class FakeModelViewport(QWidget):
    structureClicked = Signal(int, object)
    structureDoubleClicked = Signal(int)
    contextMenuRequested = Signal(int, object)
    animChanged = Signal(float)
    viewChanged = Signal(object)
    measureChanged = Signal(str)

    def __init__(self, model, state, settings, entry, parent=None):
        super().__init__(parent)
        self.measure_mode = False
        self.measure_points = []
        self.cut_planes = None
        self.cut_on = False
        self.sections = [None] * 3
        self.rsettings = SimpleNamespace(shadows=False, stripes=False, tonemap=True, studio=.3, exposure=0)
        self.orientation_axes_on = False
        self.camera = SimpleNamespace(ortho=False)
        self.reset_view = Mock()
        self.frame_structures = Mock()
        self.invalidate_labels = Mock()
        self.set_explode = Mock()
        self.set_named_view = Mock()

    def set_measure(self, on):
        self.measure_mode = bool(on)
        if not on:self.measure_points = []
        self.measureChanged.emit("Measure distance" if on else "")

    def anim_kind(self):
        return None


class ModelViewerTests(Widgets):
    def panel(self):
        e = entry("fixture")
        m = SimpleNamespace(items=[SimpleNamespace(index=i, key=key, name=name, description="", group="Bones", bulk=False,
                                  atlas=[], parts=[]) for i, key, name in [(0, "radius", "Radius"), (1, "ulna", "Ulna")]],
            groups=[SimpleNamespace(key="bones", title="Bones", items=[0, 1])], camera_order=[],
            cameras={}, has_teased=False, parts=[], states={}, triangle_count=0, kind="procedural",
            bounds_min=np.zeros(3), bounds_max=np.ones(3), sidecar={}, metres_per_unit=None)
        m.group_of = lambda sid: m.groups[0]
        content = SimpleNamespace(tissues={}, micro_models={})
        with patch('app.ui.model_view.ModelDataset', return_value=dataset()), \
             patch('app.ui.model_view.ModelViewport', FakeModelViewport):
            view = self.keep(ModelView(e, content, dict(DEFAULT_SETTINGS), prepared=SimpleNamespace(model=m, seconds=0)))
        return view, e

    def test_model_widget_constructs_without_model_load_or_gpu(self):
        view, e = self.panel()
        e.load.assert_not_called()
        self.assertEqual(len(view.part_items), 2)
        self.assertEqual("Check to show or hide", view.parts_status.text())
        self.assertFalse(view.selection_buttons[0].isEnabled())

    def test_single_parts_group_is_flat_and_filters_and_toggles(self):
        view, _ = self.panel()
        view.vmodel.groups[0].title = 'Parts'
        view.tree.clear()
        view._build_tree()
        self.assertTrue(view.flat_parts)
        self.assertEqual(view.tree.topLevelItemCount(), 2)
        self.assertFalse(view.group_items)
        view.filter.setText('radius')
        self.assertFalse(view.part_items[0].isHidden())
        self.assertTrue(view.part_items[1].isHidden())
        view.filter.clear()
        view.part_items[0].setCheckState(0, Qt.Unchecked)
        self.assertTrue(view.state.hidden[0])
        view.show_all()
        self.assertEqual(view.part_items[0].checkState(0), Qt.Checked)

    def test_cardiac_lesson_restores_every_part_without_ghosting(self):
        view, e = self.panel()
        e.id = 'cardiac_muscle'
        view.vmodel.kind = 'glb'
        e.resolve = lambda model, names: ([0], [])
        view.state.set_hidden([1], True)
        view.state.isolate([0])
        view.state.set_ghost_focus([0])
        view.state.part_alpha = np.array([0.1, 0.2], dtype=np.float32)
        self.assertEqual(view.show_lesson_parts(['Radius']), [])
        self.assertTrue(view.state.visible_mask().all())
        self.assertIsNone(view.state.ghost_focus)
        self.assertIsNone(view.state.isolated)
        self.assertFalse(view.state.opaque_materials)
        self.assertTrue((view.state.part_alpha == 1).all())
        self.assertEqual(view.state.selected, [0])

    def test_studio_measure_controls_use_viewport_api(self):
        view, _ = self.panel()
        view.studio.measure.click()
        self.assertTrue(view.gl_widget.measure_mode)
        view.gl_widget.set_measure(False)
        self.assertFalse(view.studio.measure.isChecked())

    def test_lesson_model_hides_and_restores_library_instruments(self):
        view, _ = self.panel()
        studio = view.studio
        before = {key: not card.isHidden() for key, card in studio.cards.items()}
        studio.set_lesson_mode(True)
        view.state.select([0])
        view._show_selection()
        studio.arrange()
        self.assertTrue(studio.subject.isHidden())
        self.assertTrue(studio.selection.isHidden())
        self.assertTrue(studio.dock.isHidden())
        self.assertTrue(all(card.isHidden() for card in studio.cards.values()))
        studio.set_lesson_mode(False)
        self.assertEqual({key: not card.isHidden() for key, card in studio.cards.items()}, before)
        view._show_selection()
        self.assertFalse(studio.selection.isHidden())

    def test_part_filter_keyboard_selection_and_related_lessons(self):
        view, _ = self.panel()
        view.filter.setText("bones")
        self.assertFalse(view.part_items[1].isHidden())
        view.filter.setText("radius")
        self.assertTrue(view.part_items[1].isHidden())
        view._clicked(1, Qt.NoModifier)
        self.assertEqual(view.filter.text(), "")
        self.assertTrue(view.selection_buttons[0].isEnabled())
        self.assertIn("Ulna", view.selection_status.text())
        requested = []; view.lessonsRequested.connect(requested.append)
        view.set_lessons_available(2)
        view.lessons_button.click()
        self.assertEqual(requested, ["fixture"])
        view.set_lessons_available(0)
        self.assertTrue(view.lessons_button.isHidden())

    def test_lesson_selection_does_not_isolate_stale_tree_selection(self):
        view, _ = self.panel()
        view._clicked(0, Qt.NoModifier)
        view.state.select([1])
        self.assertEqual(view._current_or_selected(), [1])
        self.assertEqual(view.tree.currentItem(), view.part_items[1])
        view.state.select([0, 1])
        self.assertEqual(view._current_or_selected(), [0, 1])

    def test_empty_model_filter_and_clear_selection_have_safe_actions(self):
        view, _ = self.panel()
        view.filter.setText("missing")
        self.assertIn("No matching", view.parts_status.text())
        view.filter.clear()
        view.state.select([0])
        view.state.clear_selection()
        self.assertFalse(view.selection_buttons[0].isEnabled())
        self.assertFalse(view.tree.selectedItems())


if __name__ == "__main__":
    unittest.main()
