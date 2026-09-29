"""Microanatomy Model Viewer.

    python -m viewer [model.glb]
    python -m viewer --render V1 --out v1.png [--size 1920x1080] [--state teased] [--time 2.4] model.glb
"""
import argparse
import sys
import traceback
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="viewer", description="Offline viewer for microanatomy GLB models")
    ap.add_argument("file", nargs="?", help="a .glb or .gltf file to open")
    ap.add_argument("--render", metavar="VIEW", help="render offscreen at a shared view (V0-V6, A1...) or 'fit'")
    ap.add_argument("--out", help="PNG path for --render")
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--state", default=None, help="assembled | teased (default: the view's own state)")
    ap.add_argument("--time", type=float, default=None, help="clip time in seconds (default: clip start)")
    a = ap.parse_args(argv)

    if a.render:
        if not a.file or not a.out:
            ap.error("--render needs a model file and --out")
        from .offscreen import render_to_png
        w, h = (int(x) for x in a.size.lower().split("x"))
        render_to_png(a.file, a.out, view=None if a.render == "fit" else a.render, size=(w, h),
                      state=a.state, t=a.time)
        return 0

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication, QMessageBox

    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(0)
    fmt.setSamples(0)                 # the renderer does its own MSAA
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Microanatomy Model Viewer")

    log = Path(__file__).resolve().parent / "viewer_error.log"

    def excepthook(t, e, tb):
        text = "".join(traceback.format_exception(t, e, tb))
        try:
            log.write_text(text, encoding="utf-8")
        except OSError:
            pass
        QMessageBox.critical(None, "Viewer error", text[-3000:])

    sys.excepthook = excepthook
    from .window import MainWindow
    win = MainWindow()
    win.show()
    if a.file:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: win.open_path(a.file))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
