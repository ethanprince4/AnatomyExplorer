"""Headless 2D UI evidence only; never imports a model or GL viewport."""
import importlib.util
import json
import os
from pathlib import Path
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve()
OVERLAY = HERE.parents[1]
BASE = Path(os.environ.get("ANATOMY_UI_BASE", HERE.parents[3] / "integration-azure-handoff/candidate/AnatomyExplorer"))
sys.path.insert(0, str(BASE))
import app.ui
app.ui.__path__.insert(0, str(OVERLAY / "app/ui"))
THEME_OVERLAY = HERE.parents[2] / "lead/app/ui"
if THEME_OVERLAY.exists():
    app.ui.__path__.insert(0, str(THEME_OVERLAY))
from app.ui import theme
spec = importlib.util.spec_from_file_location("workspace_tests", HERE.with_name("test_image_workspace_ui.py"))
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)
from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import QCoreApplication, QEvent
QAPP = tests.QAPP
OUT = OVERLAY / "evidence"
OUT.mkdir(exist_ok=True)
results = []
for route, width, height, scale in (("radiology", 1180, 850, 1.0), ("radiology", 880, 740, 1.25),
                                   ("histology", 1280, 850, 1.5), ("histology", 1050, 740, 1.25)):
    theme.apply_theme(QAPP, scale=scale)
    window = QWidget()
    window.setWindowTitle("2D workspace verification")
    layout = QHBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    if route == "radiology":
        cases = tests.load_cases(include_missing=True)
        browser = tests.RadiologyBrowser(cases)
        viewer = tests.RadiologyPanel()
        case = next(c for c in cases if c.id == "ct_abdo_kidney")
        viewer.show_case(case)
        browser.set_current_case(case.id)
        predicate = lambda: not viewer.view.pixmap.isNull()
    else:
        content = tests.content_fixture()
        ds = tests.dataset_fixture()
        browser = tests.HistologyBrowser(ds, content)
        browser.filter.setText("nerve")
        viewer = tests.HistologyViewer(ds, content)
        tid = next(t["id"] for t in content.histology["tissues"] if "nerve" in t["name"].lower() and t.get("images"))
        viewer.show_tissue(tid, 0)
        predicate = lambda: not viewer.view.item.pixmap().isNull()
    browser.setFixedWidth(300 if scale <= 1.25 else 330)
    layout.addWidget(browser)
    layout.addWidget(viewer, 1)
    window.resize(width, height)
    window.show()
    tests.settle(predicate)
    QAPP.processEvents()
    path = OUT / f"{route}-{width}-{int(scale*100)}pct.png"
    assert window.grab().save(str(path))
    results.append(dict(route=route, requested=[width,height], actual=[window.width(),window.height()],
                        viewer=[viewer.width(),viewer.height()], scale=scale, screenshot=path.name,
                        environment="Linux Qt offscreen; 2D widgets only; no GL/model rendering"))
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QAPP.processEvents()
(OUT / "capture-matrix.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
