"""Entry point of the packaged app (PyInstaller cannot start a package's __main__ directly).

Runs app/__main__.py exactly as `python -m app` does, including its error dialog."""
import os
import runpy
import sys

# a windowed build has no console: give print() and tracebacks somewhere harmless to go
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
if sys.__stderr__ is None:
    sys.__stderr__ = sys.stderr
sys.dont_write_bytecode = True      # never write __pycache__ into the installed (read-only / signed) app folder

# Test subprocesses redirect Qt registry/preferences as well as LOCALAPPDATA.
# Ordinary installations keep the established identity and settings location.
if os.environ.get("AE_TEST_SETTINGS_DIR"):
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, os.environ["AE_TEST_SETTINGS_DIR"])

if "--runtime-check" in sys.argv:
    from app.runtime_check import main
    sys.exit(main())

if "--pick-diagnostics" in sys.argv:
    from app.picking_diagnostics import main
    sys.exit(main())

if "--ae-managed" in sys.argv:
    sys.argv.remove("--ae-managed")
elif sys.platform in {"win32", "darwin"}:
    from app.updater import launch_managed
    try:
        sys.exit(launch_managed(sys.argv[1:]))
    except Exception as exc:
        from app.updater import UpdateError
        if not isinstance(exc, UpdateError):
            # A read-only/unavailable update store must not prevent offline study.
            runpy.run_module("app", run_name="__main__", alter_sys=True)
            sys.exit(0)
        from PySide6.QtWidgets import QApplication, QMessageBox
        qt = QApplication([])
        QMessageBox.warning(None, "Anatomy Explorer", f"Could not start the app: {exc}")
        sys.exit(1)

runpy.run_module("app", run_name="__main__", alter_sys=True)
