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
    import wgpu
    from wgpu.backends import wgpu_native  # noqa: F401 - loads libwgpu_native (no adapter needed)
    from . import renderer, updater
    from .config import DATA_DIR, ROOT
    from .gpu.renderer import WGSL
    app = QApplication([])
    app.setApplicationName("AnatomyExplorerRuntimeCheck")
    app.setOrganizationName("AnatomyExplorerReleaseQA")
    assert QColor("red").isValid()
    assert (DATA_DIR / "anatomy.json").exists()
    # the wgpu model renderer is on by default on macOS; without its shaders it would quietly fall back to OpenGL
    assert (WGSL / "geom.wgsl").is_file() and (WGSL / "resolve.wgsl").is_file()
    report = {"frozen": bool(getattr(sys, "frozen", False)), "qt": qVersion(), "numpy": numpy.__version__,
              "moderngl": moderngl.__version__, "wgpu": wgpu.__version__,
              "wgsl_files": len(list(WGSL.glob("*.wgsl"))), "version": (ROOT / "VERSION").read_text().strip(),
              "platform": sys.platform, "qt_plugins": app.platformName(), "runtime_imports": True}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0
