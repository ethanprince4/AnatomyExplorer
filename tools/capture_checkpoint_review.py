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

out = ROOT / "Reports/checkpoint3-alignment/native-after"
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


def atlas_scene():
    win._studio_explore()
    selected = [s["id"] for s in win.ds.structures if s["system"] == "muscular" and "long head of biceps brachii" in s["base"].casefold()]
    win.state.select(selected[:1])
    win.view_panel.set_depth(.26)
    win.on_setting("show_structure_labels", True)


def practice_scene():
    win._start_practice_room("mixed")
    win.quiz.start()
    win._update_workspace_header()


pages = [
    ("atlas", atlas_scene),
    ("lessons", win._show_lesson_library),
    ("models", win._show_catalog),
    ("histology", win.show_histology_tab),
    ("practice", win._show_practice),
    ("practice-live", practice_scene),
    ("search", lambda: (win._studio_explore(), win._studio_search("biceps"))),
    ("atlas-1280", lambda: (win._clear_studio_search(), win.resize(1280,800))),
]


if '--compact-check' in sys.argv:
    pages=[('atlas',atlas_scene),('models',win._show_catalog),
           ('atlas-1280',lambda:(win._studio_explore(),win.resize(1280,800)))]

def save(name):
    app.processEvents()
    from PySide6.QtGui import QFontInfo
    geometry[name]={"font":QFontInfo(win.studio_header.search.font()).family(),'window':[win.width(),win.height()], 'minimum':[win.minimumWidth(),win.minimumHeight()],
                    'dock':[win.studio_tools.x(),win.studio_tools.y(),win.studio_tools.width(),win.studio_tools.height()],
                    'pair':[win.studio_tools.label_pair.width(),win.studio_tools.label_pair.sizeHint().width()],
                    'pages':[ [win.collection_workspace.pages.widget(i).objectName(),win.collection_workspace.pages.widget(i).minimumSizeHint().height()] for i in range(win.collection_workspace.pages.count())]}
    if not win.grab().save(str(out / f"{name}.png")):
        errors.append("Capture failed: " + name)


def capture_next(index=0):
    try:
        if index >= len(pages):
            win.resize(1920,1080)
            model = next((key for key in ("kidney_nephron", "eyeball", "heart")
                          if key in win.content.micro_models), None)
            if model:
                win.open_micro(model, on_ready=model_ready)
                QTimer.singleShot(25000, finish)
            else:
                finish()
            return
        name, route = pages[index]
        route()
        QTimer.singleShot(900, lambda: (save(name), capture_next(index + 1)))
    except Exception as exc:
        errors.append(str(exc))
        finish()


def model_ready(view):
    if view is None:
        errors.append("Review model failed to load")
        finish()
    else:
        if 'Kidney' in view._view_names:view.set_named_view('Kidney')
        QTimer.singleShot(2200, lambda: (save("model-viewer"), finish()))


done = False


def finish():
    global done
    if done:
        return
    done = True
    report = {"errors": errors, "geometry":geometry, "atlas_gl_valid": win.viewport.isValid(),
              "atlas_frame_ok": bool(getattr(win.viewport.renderer, "frame_ok", False)),
              "gl": win.viewport.gl_info, "captures": sorted(p.name for p in out.glob("*.png"))}
    model = win.active_model_view()
    if model is not None:
        report["model_viewport"] = type(model.gl_widget).__name__
        report["model_frame_ok"] = bool(getattr(model.gl_widget.renderer, "frame_ok", False))
    (out / "capture.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    win.close()
    QTimer.singleShot(500, app.quit)


QTimer.singleShot(6000, capture_next)
QTimer.singleShot(55000, finish)
app.exec()
sys.exit(1 if errors else 0)
