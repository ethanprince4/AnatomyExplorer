"""Capture the assembled native UI without showing a desktop window or changing user data."""
from pathlib import Path
import json
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["AE_LOCAL_MODEL_LIBRARY"] = str(ROOT / "data/local_model_library")
from app.__main__ import configure_qt
configure_qt()
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication
from app import config

scratch = tempfile.TemporaryDirectory(prefix="layered-human-review-")
config.USER_DIR = Path(scratch.name) / "user"
config.USER_DIR.mkdir()
config.LOG_DIR = Path(scratch.name) / "logs"
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, scratch.name)
app = QApplication([])
from app.data import Dataset
from app.main_window import MainWindow

out = ROOT / "Reports/checkpoint3-alignment/correction-review"
out.mkdir(parents=True, exist_ok=True)
errors = []
geometry = {}
sys.excepthook = lambda _t, value, _tb: (errors.append(str(value)), __import__("traceback").print_exception(_t,value,_tb))
win = MainWindow(Dataset(config.DATA_DIR), restore=False)
win.settings["restore_session"] = False
win.setAttribute(Qt.WA_DontShowOnScreen, True)
win.setAttribute(Qt.WA_ShowWithoutActivating, True)
win.resize(1920, 1080)
win.show()

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QWidget

checks = {}
steps = []
model = None


def save(name):
    app.processEvents()
    shot = win.grab()
    shot.save(str(out / (name + '.png')))
    current = win.active_model_view()
    if current is not None or name in ('lessons', 'histology', 'lesson-cover'):
        from app.ui import theme
        from PySide6.QtGui import QColor
        from app.ui.wall_background import viewport_background
        probe = QWidget(win.workspace)
        probe.setGeometry(10, 700, 1, 1)
        palette = theme.palette()
        expected = QColor(viewport_background(probe, {'custom_background': True,
            'bg_top': palette['stage_top'], 'bg_bottom': palette['stage_bottom']})['bg_top'])
        point = probe.mapTo(win, QPoint(0, 0))
        actual = shot.toImage().pixelColor(round(point.x()*shot.devicePixelRatio()),
                                           round(point.y()*shot.devicePixelRatio()))
        assert max(abs(a-b) for a,b in zip(actual.getRgb(),expected.getRgb())) <= 1, (name, actual.name(), expected.name())
        probe.deleteLater()
    vp = current.gl_widget if current is not None else win.viewport
    checks[name] = {'viewport': [vp.x(), vp.y(), vp.width(), vp.height()],
                    'frame_ok': bool(getattr(vp.renderer, 'frame_ok', False)),
                    'labels_on': bool(vp.labels_on),
                    'captions': len(getattr(vp, '_label_rects', getattr(vp, '_structure_label_rects', []))),
                    'rail_width': win.studio_header.rail.width()}
    if current is not None:
        checks[name]['opacity_min'] = float(current.state.part_alpha.min())
        checks[name]['opacity_enabled'] = bool(current.opacity is not None and current.opacity.isEnabled())
        checks[name]['number_dots'] = len(vp._label_dot_rects)
        if vp.labels_on and name in ('cardiac-zoom', 'kidney-labels'):
            assert len(vp._label_dot_rects) > 0, name + ': missing numbered model labels'
            assert len(vp._label_rects) > 0, name + ': Show all did not open captions'


def atlas():
    win._studio_explore()
    win.view_panel.set_depth(.26)
    win.on_setting('show_structure_labels', True)


def quick_hover():
    button = next(b for b in win.atlas_wall.findChildren(QPushButton) if not b.property('wallAction'))
    QTest.mouseMove(button, button.rect().center())


def atlas_heart_step(step):
    return ('right atrium' in str(step.get('focus', [])).lower()
            and step.get('lesson_view') not in ('diagram', 'reading'))


heart = next(lesson for lesson in win.lessons_panel.lessons if any(atlas_heart_step(s) for s in lesson.steps))
heart_index = next(i for i, step in enumerate(heart.steps) if atlas_heart_step(step))
case = next(c for c in win.radiology_cases if c.has_image and c.labels and not c.scene.get('model'))


def heart_lesson():
    win.lessons_panel.open_lesson(heart.id)
    win.lessons_panel.go(heart_index, force=True)
    assert win.state.selected, 'Heart step did not select anatomy'
    def ready(view):
        if view is not None:
            view.labels.setChecked(True)
            view.gl_widget.show_all_labels(True)
        QTimer.singleShot(1200, lambda: (save('heart-lesson'), next_step()))
    win.when_model_ready(heart.steps[heart_index]['micro'], ready)


def return_atlas():
    win.studio_header.navigation['atlas'].click()
    st = win.state
    assert list(st.system_on) == [s['default_visible'] for s in win.ds.systems]
    assert st.region_on.all() and not st.hidden.any() and not st.forced.any()
    assert st.isolated is None and st.ghost_focus is None and not st.selected
    assert st.depth_cut == 0 and not any(win.viewport.clip_on)
    assert win.lesson_reader.isHidden()
    checks['atlas_return'] = {'systems_reset': True, 'lesson': heart.id,
                             'body_bounds': [v.tolist() for v in win.viewport.scene_bounds()]}


def radio_library():
    win._studio_radiology()
    win.radiology_browser.set_current_case(case.id)


def radio_open():
    win.radiology_browser.open_case.click()
    win._show_radiology_labels(True)


def radio_all():
    win.studio_tools.label_pair.show_all.click()


def card_zoom():
    model.labels.setChecked(True)
    model.gl_widget.show_all_labels(True)
    model.gl_widget.camera.distance *= .48
    model.gl_widget.update()


def cardiac_reset():
    model._opacity(70)
    model.show_lesson_parts(['Cardiomyocytes'])
    assert float(model.state.part_alpha.min()) < .3
    model.reset_view(animate=False)


def load_card():
    global model
    win._clear_studio_search()
    def ready(view):
        global model
        model = view
        if model is None:
            errors.append('Cardiac load failed')
            finish()
            return
        QTimer.singleShot(1800, lambda: (save('cardiac-initial'), next_step()))
    win.open_micro('cardiac_muscle', on_ready=ready)


def load_kidney():
    def ready(view):
        if view is None:
            errors.append('Kidney load failed')
            finish()
            return
        if 'Kidney' in view._view_names:
            view.set_named_view('Kidney')
        view.labels.setChecked(True)
        view.gl_widget.show_all_labels(True)
        QTimer.singleShot(1800, lambda: (save('kidney-labels'), next_step()))
    win.open_micro('kidney_nephron', on_ready=ready)


steps = [
    ('atlas', atlas), ('quick-hover', quick_hover),
    ('lessons', win._show_lesson_library),
    ('lesson-cover', lambda: win.lessons_panel.open_cover(heart.id)),
    (None, heart_lesson), ('atlas-return', return_atlas),
    ('histology', win.show_histology_tab),
    ('radiology-library', radio_library), ('radiology-numbers', radio_open),
    ('radiology-rails', radio_all), ('atlas-search', lambda: (win._studio_explore(), win._studio_search('biceps'))),
    (None, load_card), ('cardiac-zoom', card_zoom), ('cardiac-lesson-reset', cardiac_reset),
    (None, load_kidney), ('model-1280', lambda: win.resize(1280, 800)),
]

if '--final-check' in sys.argv:
    steps = [(None, heart_lesson), ('atlas-return', return_atlas),
             (None, load_card), ('cardiac-zoom', card_zoom), (None, load_kidney)]


def next_step():
    if not steps:
        finish()
        return
    name, route = steps.pop(0)
    try:
        route()
        if name:
            QTimer.singleShot(1300, lambda: (save(name), next_step()))
    except Exception as exc:
        errors.append(str(exc))
        __import__('traceback').print_exc()
        finish()


done = False


def finish():
    global done
    if done:
        return
    done = True
    result = {'errors': errors, 'checks': checks, 'remaining': [s[0] for s in steps], 'gl': win.viewport.gl_info}
    (out / 'capture.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)
    win.close()
    QTimer.singleShot(500, app.quit)


QTimer.singleShot(6000, next_step)
QTimer.singleShot(150000, finish)
app.exec()
sys.exit(1 if errors or steps else 0)
