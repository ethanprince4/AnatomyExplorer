"""Real Qt input and QPainter regressions for the checkpoint 3 label contract.

The CPU picking buffer supplies deterministic visible geometry. These tests run
the production anchor computation, painting, hit testing and input handlers;
they do not require an offscreen OpenGL context.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.config import DEFAULT_SETTINGS
from app.state import SceneState
from app.ui import theme
from app.ui.dock_pair import LabelDockPair
from app.ui.label_rails import LABEL_GOLD, paint_label_rails
from app.viewer.dataset import ModelDataset
from app.viewer.model import Group, Item, Look, Part, ViewerModel
from app.viewer.viewport_core import ViewportCore
from app.viewport import Viewport


APP = QApplication.instance() or QApplication([])


class PickingBuffer:
    """Two solid, separated visible patches, with a cut-face flag on one."""
    size = (800, 600)
    last_vp = np.eye(4)
    frame_ok = True

    def __init__(self):
        self.ids = np.full((600, 800), -1, dtype=np.int32)
        self.ids[320:480, 270:340] = 0
        self.ids[170:290, 460:530] = 1
        self.flags = np.zeros_like(self.ids, dtype=np.uint8)
        self.flags[self.ids == 1] = 2
        self.depth = np.full(self.ids.shape, .5, dtype=np.float32)

    def read_label_samples(self, step):
        ids = self.ids[::step, ::step]
        return ids, self.flags[::step, ::step], self.depth[::step, ::step], ids

    def read_id_image(self, step):
        return self.ids[::step, ::step] + 1

    def world_from_pixel(self, x, y, depth):
        return np.array([x / 400 - 1, 1 - y / 300, depth * 2 - 1])

    def world_at(self, x, y):
        return np.array([x / 400 - 1, y / 300 - 1, 0])

    def pick_many(self, points):
        return [int(self.ids[min(599, max(0, int(y))), min(799, max(0, int(x)))]) for x, y in points]


def specimen():
    model = ViewerModel()
    model.items = [Item(0, "aorta", "Aorta", "vessels"),
                   Item(1, "vein", "Pulmonary vein", "vessels")]
    model.groups = [Group("vessels", "Vessels", [0, 1])]
    ds = ModelDataset(model)
    ds.centroid = np.array([[-.24, .33, 0], [.24, -.23, 0]])
    ds.bbox_min, ds.bbox_max = ds.centroid - .1, ds.centroid + .1
    ds.scene_bbox = (np.full(3, -1.0), np.full(3, 1.0))
    state = SceneState(ds, dict(DEFAULT_SETTINGS))
    return model, ds, state


class ModelHarness(ViewportCore, QWidget):
    def __init__(self, model, state, settings):
        QWidget.__init__(self)
        self._init_core(model, state, settings)
        self.renderer = PickingBuffer()
        self.resize(800, 600)

    def paintEvent(self, event):
        pass


class DockPairLabels(unittest.TestCase):
    def setUp(self):
        theme.apply_theme(APP)
        self.model, self.ds, self.state = specimen()
        self.settings = dict(DEFAULT_SETTINGS)
        self.widgets = []

    def keep(self, widget):
        self.widgets.append(widget)
        return widget

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        APP.processEvents()

    def model_view(self):
        view = self.keep(ModelHarness(self.model, self.state, self.settings))
        view.set_labels_on(True)
        view._compute_labels()
        return view

    def paint(self, view):
        image = QImage(view.size(), QImage.Format_ARGB32)
        image.fill(theme.qc(theme.CANVAS))
        painter = QPainter(image)
        if isinstance(view, Viewport):
            view._paint_section_labels(painter, True)
            view._paint_structure_labels(painter)
        else:
            view.paint_overlay(painter)
        painter.end()
        return image

    def test_models_have_clickable_circles_then_caption_rails_and_live_dock_state(self):
        view = self.model_view()
        pair = self.keep(LabelDockPair())
        view.labelsOpenChanged.connect(pair.set_all_open)
        pair.set_labels_on(True)
        pair.showAllClicked.connect(lambda: view.show_all_labels(not view.labels_all_open()))
        image = self.paint(view)
        self.assertEqual(len(view._label_dot_rects), 2)
        self.assertEqual(view._label_rects, [])
        dot = view._label_dot_rects[0][0].toAlignedRect()
        self.assertTrue(any(image.pixelColor(x, y) != theme.qc(theme.CANVAS)
                            for x in range(dot.left(), dot.right())
                            for y in range(dot.top(), dot.bottom())))
        first = view._label_dot_rects[0][0].center().toPoint()
        QTest.mouseClick(view, Qt.LeftButton, pos=first)
        self.paint(view)
        self.assertEqual(len(view._label_rects), 1)
        pair.show_all.click()
        self.paint(view)
        self.assertEqual(len(view._label_rects), 2)
        self.assertEqual(pair.show_all.text(), "Hide all")
        QTest.mouseClick(view, Qt.LeftButton, pos=first)
        self.assertEqual(pair.show_all.text(), "Show all")
        # A rail selects the underlying structure rather than toggling its circle.
        picked = []
        view.structureClicked.connect(lambda item, modifiers: picked.append(item))
        self.paint(view)
        rect, item = view._label_rects[0]
        QTest.mouseClick(view, Qt.LeftButton, pos=rect.center().toPoint())
        self.assertEqual(picked, [item])

    def test_hide_all_and_escape_keep_selected_captions_closed_after_recompute(self):
        self.state.selected = [0]
        view = self.model_view()
        self.assertIn(0, view._label_open)
        view.show_all_labels(False)
        view._compute_labels()  # exercises the production warm-cache reuse path
        self.assertEqual(view._label_open, set())
        view.show_all_labels(True)
        QTest.keyClick(view, Qt.Key_Escape)
        view._compute_labels()
        self.assertEqual(view._label_open, set())
        self.paint(view)
        self.assertEqual(view._label_rects, [])

    def test_legacy_all_false_flags_still_label_without_selection_and_show_all_can_precede_anchors(self):
        for item in self.model.items:
            item.label = False
        view = self.keep(ModelHarness(self.model, self.state, self.settings))
        view.set_labels_on(True)
        view.show_all_labels(True)
        self.assertFalse(view.label_items)
        view._compute_labels()
        self.paint(view)
        self.assertEqual(len(view._label_dot_rects), 2)
        self.assertEqual(len(view._label_rects), 2)
        self.assertTrue(view.labels_all_open())
        # A nonempty authored subset continues to constrain automatic labels.
        self.model.items[0].label = True
        self.assertEqual(view.label_hosts()[0], [0])

    def test_numbering_survives_camera_motion_and_keyboard_opens_focus_caption(self):
        view = self.model_view()
        self.paint(view)
        numbers = view._label_number_ids
        view.renderer.last_vp = np.diag([-1, -1, 1, 1])
        self.paint(view)
        self.assertEqual(view._label_number_ids, numbers)
        QTest.keyClick(view, Qt.Key_Tab)
        self.assertEqual(view._label_focus, numbers[0])
        QTest.keyClick(view, Qt.Key_Space)
        self.assertIn(numbers[0], view._label_open)
        QTest.keyClick(view, Qt.Key_Backtab)
        self.assertEqual(view._label_focus, numbers[-1])

    def test_cut_faces_and_case_models_use_the_same_interactive_layer(self):
        view = self.model_view()
        view.sections[2] = [0, False]
        view._warm_label_cache = None
        view._compute_labels()
        self.assertTrue(view.section_items)
        view.set_reference_labels([(1, "Aorta", (0,)), (2, "Pulmonary vein", (1,))])
        view._compute_labels()
        self.assertEqual(view.section_items, [])
        self.paint(view)
        self.assertEqual(len(view._label_dot_rects), 2)
        self.assertEqual(view._label_rects, [])

        view.show_all_labels(True)
        self.paint(view)
        self.assertEqual(len(view._label_rects), 2)
        rects = [rect for rect, _item in view._label_rects]
        self.assertFalse(rects[0].intersects(rects[1]))
        view.set_labels_on(False)
        view._compute_labels()
        self.paint(view)
        self.assertEqual(view._label_dot_rects, [])
        self.assertEqual(view._label_rects, [])

    def test_reference_set_is_exclusive_with_exact_numbers_and_independent_repeated_parts(self):
        view = self.model_view()
        self.state.selected = [1]
        entries = [(2, "Nipple", (0,)), (7, "Areola", (0,)), (11, "Areola", (0,))]
        view.set_reference_labels(entries)
        self.assertEqual(view.label_hosts()[0], [0])
        view.show_all_labels(True)
        view._compute_labels()
        self.paint(view)
        self.assertEqual(len(view.label_items), 3)
        self.assertEqual(set(view._label_host_ids.values()), {0})
        self.assertEqual(list(view._label_caption_numbers.values()), [2, 7, 11])
        self.assertEqual(len(view._label_dot_rects), 3)
        self.assertEqual(len(view._label_rects), 3)
        anchors = [np.asarray(row[1]) for row in view.label_items]
        self.assertEqual(len({tuple(anchor) for anchor in anchors}), 3)
        for index, anchor in enumerate(anchors):
            for other in anchors[index + 1:]:
                self.assertGreaterEqual(np.linalg.norm(np.asarray(view.project(anchor)[:2]) - view.project(other)[:2]), 28)
        # Installed case metadata survives a visibility toggle; native selection
        # cannot enter the caption set when the labels return.
        view.set_labels_on(False)
        view.set_labels_on(True)
        view._compute_labels()
        self.assertEqual([row[3] for row in view.label_items], ["Nipple", "Areola", "Areola"])
        view.set_reference_labels([])
        view._compute_labels()
        self.assertEqual(view.label_items, [])

    def test_landmarks_use_the_numbered_layer_and_click_to_open_caption(self):
        view = self.keep(Viewport(self.ds, self.state, self.settings))
        view.resize(800, 600)
        view.renderer = PickingBuffer()
        self.ds.landmarks = [{"name": "Pectoral attachment", "sid": 0},
                             {"name": "Pectoral insertion", "sid": 0},
                             {"name": "Hidden attachment", "sid": 0}]
        view._lm_cache = [(0, (300, 200, .5), False), (1, (320, 240, .5), False),
                          (2, (320, 200, .8), True)]
        view.set_labels_on(True)
        view._update_structure_labels()
        self.paint(view)
        landmark_keys = [key for _rect, key in view._structure_label_dot_rects if isinstance(key, tuple)]
        self.assertEqual(landmark_keys, [("landmark", 0), ("landmark", 1)])
        self.assertEqual(view._structure_label_rects, [])
        rect = next(rect for rect, key in view._structure_label_dot_rects if key == ("landmark", 1))
        QTest.mouseClick(view, Qt.LeftButton, pos=rect.center().toPoint())
        self.paint(view)
        self.assertEqual([key for _rect, key in view._structure_label_rects], [("landmark", 1)])

    def test_atlas_lesson_labels_start_on_without_changing_either_ordinary_preference(self):
        self.ds.landmarks = [{"name": "Pectoral attachment", "sid": 0}]
        for ordinary in (False, True):
            with self.subTest(ordinary=ordinary):
                settings = dict(self.settings, show_structure_labels=ordinary)
                view = self.keep(Viewport(self.ds, self.state, settings))
                view.resize(800, 600)
                view.renderer = PickingBuffer()
                view._lm_cache = [(0, (300, 200, .5), False)]
                mode_changes = []
                view.labelsModeChanged.connect(mode_changes.append)
                view.set_lesson_label_mode(True)
                self.assertTrue(view.lesson_label_mode_active)
                self.assertTrue(view.labels_on)
                self.assertEqual(settings["show_structure_labels"], ordinary)
                view._update_structure_labels()
                self.paint(view)
                self.assertIn(("landmark", 0), [key for _rect, key in view._structure_label_dot_rects])
                view.set_labels_on(False)
                view.set_lesson_label_mode(True)  # repeated workspace-header update
                self.assertFalse(view.labels_on)
                self.assertEqual(settings["show_structure_labels"], ordinary)
                view.set_lesson_label_mode(False)
                self.assertFalse(view.lesson_label_mode_active)
                self.assertEqual(view.labels_on, ordinary)
                self.assertEqual(settings["show_structure_labels"], ordinary)
                self.assertEqual(mode_changes, [True, False, ordinary])
                # A new lesson starts enabled even when the previous lesson's
                # temporary label choice was off.
                view.set_lesson_label_mode(True)
                self.assertTrue(view.labels_on)

    def test_ghost_reference_anchors_use_real_mesh_points_and_reject_nearer_opaque_tissue(self):
        part = Part(id=1, node=0, name="Skin", mesh_name="Skin", material_name="Skin",
                    structure="Skin", structure_id="skin", label="", extras={}, look=Look(),
                    vertex_base=0, vertex_count=3, item=0)
        self.model.items[0].parts = [part]
        self.model.vertices = np.zeros((3, 19), dtype=np.float32)
        self.model.vertices[:, :3] = [[-.25, .25, -.4], [-.2, .2, -.4], [-.1, .2, -.4]]
        self.state.ghost_focus = np.array([False, True])
        view = self.model_view()
        view.renderer.ids[:] = -1
        view.renderer.last_camera = (np.eye(4),)
        view.set_reference_labels([(4, "Skin of breast", (0,))])
        view._compute_labels()
        self.assertEqual(len(view.label_items), 1)
        self.assertEqual(view.label_items[0][3], "Skin of breast")
        anchor = view.label_items[0][1]
        self.assertTrue(any(np.allclose(anchor, point) for point in self.model.vertices[:, :3]))
        view.renderer.ids[:] = 1
        view.renderer.depth[:] = .2  # solid tissue in front of every skin vertex
        view._warm_label_cache = None
        view._compute_labels()
        self.assertEqual(view.label_items, [])

    def test_gold_circle_states_and_rails_stay_beyond_the_specimen_bounds(self):
        image = QImage(800, 500, QImage.Format_ARGB32)
        image.fill(theme.qc(theme.CANVAS))
        painter = QPainter(image)
        rows = [(0, 0, 360, 140, "Left caption"), (1, 1, 480, 220, "Right caption"),
                (2, 2, 480, 280, "Selected caption"), (3, 3, 360, 350, "Closed caption")]
        _order, _dots, captions = paint_label_rails(painter, (800, 500), QFont("Fira Sans", 8),
            rows, (), {0, 1}, {2}, specimen_bounds=(330, 80, 510, 350), insets=(20, 24, 20, 30))
        painter.end()
        by_key = {key: rect for rect, key in captions}
        self.assertLessEqual(by_key[0].right(), 330 - 64 + 2)
        self.assertGreaterEqual(by_key[1].left(), 510 + 64 - 2)
        self.assertGreaterEqual(by_key[0].height(), 20)
        gold = QColor(LABEL_GOLD)
        self.assertEqual(image.pixelColor(365, 144), gold)
        self.assertEqual(image.pixelColor(485, 284), gold)
        self.assertEqual(image.pixelColor(365, 354), theme.qc(theme.CANVAS))
        self.assertTrue(any(image.pixelColor(x, y).red() - image.pixelColor(x, y).blue() > 40
                            for x in range(350, 371) for y in range(340, 361)))

    def test_compact_right_wall_zone_overrides_central_insets_and_wraps_captions(self):
        # A 1280px app leaves a 1196px specimen stage after its navigation rail.
        # The former central inset clamp put this right-hand name on the kidney.
        self.model.items[1].name = "Renal vein, common trunk (middle and upper)"
        view = self.model_view()
        view.resize(1196, 720)
        view.label_stage_insets = (330, 212, 340, 120)
        view.label_caption_zones = {1: (900, 212, 280, 428)}
        view._warm_label_cache = None
        view._compute_labels()
        view.show_all_labels(True)
        self.paint(view)
        rect = next(rect for rect, item in view._label_rects if item == 1)
        self.assertGreaterEqual(rect.left(), 900)
        self.assertLessEqual(rect.right(), 1180)
        self.assertGreaterEqual(rect.top(), 212)
        self.assertLessEqual(rect.bottom(), 640)
        self.assertGreater(rect.left(), view._label_specimen_bounds[2] + 64)
        self.assertGreater(rect.height(), 40)  # full caption wraps to two lines
        picked = []
        view.structureClicked.connect(lambda item, modifiers: picked.append(item))
        QTest.mouseClick(view, Qt.LeftButton, pos=rect.center().toPoint())
        self.assertEqual(picked, [1])

    def test_right_wall_zone_packs_kidney_sized_caption_set_without_overlap(self):
        image = QImage(1196, 720, QImage.Format_ARGB32)
        image.fill(theme.qc(theme.CANVAS))
        painter = QPainter(image)
        names = ["Renal capsule", "Renal artery", "Renal pelvis", "Ureter",
                 "Renal vein, common trunk (middle and upper)", "Renal vein, lower trunk",
                 "Anterior division of the renal artery", "Segmental artery (apical)",
                 "Renal cortex, posterior lip of the hilum"]
        rows = [(index, index, 670 + index * 4, 230 + index * 18, name)
                for index, name in enumerate(names)]
        _ids, dots, captions = paint_label_rails(painter, (1196, 720), QFont("Fira Sans", 8),
            rows, (), set(range(len(rows))), set(), specimen_bounds=(410, 120, 805, 650),
            insets=(330, 212, 340, 120), caption_zones={1: (900, 212, 280, 428)})
        painter.end()
        self.assertEqual(len(captions), len(names))
        self.assertEqual(len(dots), len(names))
        for index, (rect, _key) in enumerate(captions):
            self.assertGreaterEqual(rect.left(), 900)
            self.assertGreaterEqual(rect.top(), 212)
            self.assertLessEqual(rect.right(), 1180)
            self.assertLessEqual(rect.bottom(), 640)
            for other, _other_key in captions[index + 1:]:
                self.assertFalse(rect.intersects(other))

    def test_radiology_atlas_projection_has_independent_pinned_circles_and_no_old_cards(self):
        view = self.keep(Viewport(self.ds, self.state, self.settings))
        view.resize(800, 600)
        view.renderer = PickingBuffer()
        groups = [("1  Upper aorta", [0], False, (-.24, .4, 0)),
                  ("2  Lower aorta", [0], False, (-.24, .2, 0)),
                  ("3  Pulmonary vein", [1], False)]
        view.set_radiology_section_labels(groups)
        view._update_reference_anchors()
        view._reference_pending_at -= 1
        view._update_reference_anchors()
        view._update_structure_labels()
        self.paint(view)
        self.assertEqual(len(view._structure_label_dot_rects), 3)
        self.assertEqual(view._structure_label_rects, [])
        self.assertEqual(view._section_rects, [])
        first = view._structure_label_dot_rects[0][0].center().toPoint()
        QTest.mouseClick(view, Qt.LeftButton, pos=first)
        self.paint(view)
        self.assertEqual(len(view._structure_label_rects), 1)
        view.show_all_labels(True)
        self.paint(view)
        self.assertEqual(len(view._structure_label_rects), 3)
        self.assertTrue(view.labels_all_open())
        QTest.keyClick(view, Qt.Key_Escape)
        view._update_structure_labels()
        self.paint(view)
        self.assertEqual(view._structure_label_rects, [])
        self.assertFalse(view.labels_all_open())
        # Case labels are temporary and do not overwrite ordinary atlas preference.
        view.set_labels_on(False)
        self.assertFalse(view.labels_on)
        view.set_radiology_section_labels(None)
        self.assertFalse(view.labels_on)
        self.assertFalse(self.settings["show_structure_labels"])
        view.set_radiology_section_labels(groups)
        view.show_all_labels(True)  # preserves intent before the new case has anchors
        view._update_reference_anchors()
        view._update_structure_labels()
        self.paint(view)
        self.assertEqual(len(view._structure_label_rects), 3)


if __name__ == "__main__":
    unittest.main()
