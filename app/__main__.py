import argparse
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description="Anatomy Explorer")
    parser.add_argument("--script", help="semicolon-separated automation commands (testing)")
    parser.add_argument("--no-restore", action="store_true", help="ignore saved window layout")
    args = parser.parse_args()

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QSurfaceFormat
    from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(0)
    fmt.setSamples(0)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    from .config import APP_NAME, DATA_DIR, LOG_DIR, ORG_NAME, ROOT

    log_dir = LOG_DIR

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "errors.log", "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        sys.__stderr__ and sys.__stderr__.write(text)

    sys.excepthook = excepthook

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    icon_path = ROOT / "app" / "resources" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    from .ui.theme import apply_theme
    apply_theme(app)

    if not (DATA_DIR / "anatomy.json").exists():
        QMessageBox.critical(None, APP_NAME, f"Dataset not found in {DATA_DIR}.\n\nRun tools\\build_all.bat first.")
        return 1

    from .ui import theme
    pix = QPixmap(520, 220)
    pix.fill(QColor(theme.CANVAS))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.fillRect(0, pix.height() - 3, pix.width(), 3, QColor(theme.ACCENT))
    p.setPen(QColor(theme.TEXT_STRONG))
    f = QFont(theme.font_family(), 22)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect().adjusted(0, -30, 0, 0), Qt.AlignCenter, APP_NAME)
    p.setPen(QColor(theme.ACCENT_TEXT))
    p.setFont(QFont(theme.font_family(), 10))
    p.drawText(pix.rect().adjusted(0, 50, 0, 0), Qt.AlignCenter, "Loading 3D anatomy…")
    p.end()
    splash = QSplashScreen(pix)
    splash.show()
    app.processEvents()

    from .data import Dataset
    from .main_window import MainWindow

    if args.no_restore:
        from PySide6.QtCore import QSettings
        QSettings(ORG_NAME, APP_NAME).clear()

    ds = Dataset(DATA_DIR)
    win = MainWindow(ds, script=args.script)
    win.show()
    splash.finish(win)
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                QMessageBox.critical(None, "Anatomy Explorer", traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
