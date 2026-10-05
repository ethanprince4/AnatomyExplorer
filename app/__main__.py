import argparse
import sys
import traceback


def configure_qt():
    """The OpenGL context every 3D view needs (4.1 core, shared between the atlas and the model tabs). Call it
    before the QApplication exists; tools that drive the app headless call it too, so they test what users run."""
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QSurfaceFormat

    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(0)
    fmt.setSamples(0)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)


def main():
    if "--pick-diagnostics" in sys.argv:
        from .picking_diagnostics import main as diagnostics
        return diagnostics()
    parser = argparse.ArgumentParser(description="Anatomy Explorer")
    parser.add_argument("--script", help="semicolon-separated automation commands (testing)")
    parser.add_argument("--no-restore", action="store_true", help="ignore saved window layout and scene for this launch")
    args = parser.parse_args()

    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

    configure_qt()

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
    preferences = QSettings(QSettings.defaultFormat(), QSettings.UserScope, ORG_NAME, APP_NAME)
    apply_theme(app, mode=str(preferences.value("ui_theme", "porcelain")))

    if not (DATA_DIR / "anatomy.json").exists():
        QMessageBox.critical(None, APP_NAME, f"The anatomy dataset is missing from:\n{DATA_DIR}\n\n"
                             "Restore the complete Anatomy Explorer data folder, then restart. "
                             "For a source checkout, follow LOCAL_SETUP.md.")
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

    try:
        ds = Dataset(DATA_DIR)
        splash.showMessage("Preparing workspaces…", Qt.AlignBottom | Qt.AlignHCenter, QColor(theme.MUTED))
        app.processEvents()
        win = MainWindow(ds, script=args.script, restore=not args.no_restore)
    except Exception as exc:
        splash.close()
        excepthook(type(exc), exc, exc.__traceback__)
        dialog = QMessageBox(QMessageBox.Critical, APP_NAME,
                             "Anatomy Explorer could not finish opening.\n\n"
                             "Check that the application, content and data folders belong to the same install.",
                             QMessageBox.Close)
        dialog.setInformativeText(f"Details were written to {log_dir / 'errors.log'} when possible.")
        dialog.setDetailedText(str(exc))
        dialog.exec()
        return 1
    win.show()
    splash.finish(win)
    from .ui.updates import attach_updates
    from .updater import UpdateError, mark_ready
    attach_updates(win)
    from PySide6.QtCore import QTimer
    def confirm_ready():
        renderer = win.viewport.renderer
        if win.viewport.isValid() and renderer is not None and renderer.frame_ok:
            try:
                mark_ready()
            except (OSError, UpdateError):
                pass
            from .variants.readiness import start_dataset_readiness
            start_dataset_readiness(win)
        else:
            QTimer.singleShot(500, confirm_ready)
    QTimer.singleShot(500, confirm_ready)
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
