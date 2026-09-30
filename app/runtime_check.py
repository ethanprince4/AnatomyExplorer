"""Frozen-release import/plugin smoke check, with no study files or settings."""
import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-check", action="store_true")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    from PySide6.QtCore import qVersion
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    import moderngl
    import numpy
    from . import renderer, updater
    from .config import DATA_DIR, ROOT
    app = QApplication([])
    app.setApplicationName("AnatomyExplorerRuntimeCheck")
    app.setOrganizationName("AnatomyExplorerReleaseQA")
    assert QColor("red").isValid()
    assert (DATA_DIR / "anatomy.json").exists()
    report = {"frozen": bool(getattr(sys, "frozen", False)), "qt": qVersion(), "numpy": numpy.__version__,
              "moderngl": moderngl.__version__, "version": (ROOT / "VERSION").read_text().strip(),
              "platform": sys.platform, "qt_plugins": app.platformName(), "runtime_imports": True}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0
