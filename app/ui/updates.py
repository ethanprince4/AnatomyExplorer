"""Quiet background delivery; activation waits for the next normal launch."""
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

from ..config import FROZEN
from ..updater import GitHubSource, UpdateError, read_manifest, store_for


class UpdateController(QObject):
    completed = Signal(object)
    message = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.result = None
        self.dialog = None
        self.completed.connect(self.finish)
        self.message.connect(self.show_message)
        QTimer.singleShot(30000, self.automatic)

    def show_message(self, message):
        if self.dialog:
            self.dialog.status.setText(message)

    def automatic(self):
        if not self.window.qsettings.value("updates/automatic", True, type=bool):
            return
        last = self.window.qsettings.value("updates/last_check", 0, type=float)
        if time.time() - last > 24 * 3600:
            self.check()

    def check(self):
        if self.busy:
            return
        self.busy = True
        self.window.qsettings.setValue("updates/last_check", time.time())
        self.message.emit("Checking for updates… You can keep studying.")

        def work():
            try:
                source = GitHubSource()
                manifest = source.latest()
                store = store_for()
                state = store.state()
                if state.get("pending"):
                    result = {"status": "ready", "version": read_manifest(store.path(state["pending"]))["version"], "downloaded": 0}
                elif manifest is None:
                    result = {"status": "current"}
                elif (state.get("failed") or "").startswith(manifest["version"] + "-"):
                    result = {"status": "error", "error": "This release was rolled back. The working version is retained; wait for a newer release."}
                else:
                    result = store.prepare(manifest, source, self.message.emit)
            except Exception as exc:
                result = {"status": "error", "error": str(exc)}
            self.completed.emit(result)

        threading.Thread(target=work, name="AnatomyExplorer-update", daemon=True).start()

    def finish(self, result):
        self.busy = False
        self.result = result
        if result["status"] == "ready":
            text = f"Version {result['version']} is ready. It will open next time you launch Anatomy Explorer."
            if result.get("downloaded"):
                text += f" Downloaded {result['downloaded'] / 1024**2:.1f} MiB."
            self.window.statusBar().showMessage(text, 20000)
        elif result["status"] == "current":
            text = "You have the latest available update."
        else:
            text = "Update unavailable: " + result["error"] + "\nYour installed version and study data are unchanged. You can retry later."
        self.show_message(text)

    def open_dialog(self):
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Anatomy Explorer updates")
        dlg.setMinimumWidth(460)
        lay = QVBoxLayout(dlg)
        intro = QLabel("Updates download changed parts in the background. They open on your next launch; your current study session keeps running. Some releases change large assets and need a larger download.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        automatic = QCheckBox("Check and download automatically (at most once a day)")
        automatic.setChecked(self.window.qsettings.value("updates/automatic", True, type=bool))
        automatic.toggled.connect(lambda on: self.window.qsettings.setValue("updates/automatic", on))
        lay.addWidget(automatic)
        dlg.status = QLabel("Ready to check. An internet connection is needed only for updates.")
        dlg.status.setWordWrap(True)
        lay.addWidget(dlg.status)
        check = QPushButton("Check and download now")
        check.clicked.connect(self.check)
        lay.addWidget(check)
        revert = QPushButton("Use the previous version on next launch")
        revert.setEnabled(store_for().state().get("current") is not None)

        def rollback():
            try:
                store_for().request_rollback()
                dlg.status.setText("The previous version will open on your next launch. Your study data will be kept.")
                revert.setEnabled(False)
            except (OSError, UpdateError) as exc:
                dlg.status.setText(str(exc))

        revert.clicked.connect(rollback)
        lay.addWidget(revert)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        self.dialog = dlg
        if self.result:
            self.finish(self.result)
        dlg.exec()
        self.dialog = None


def attach_updates(window):
    import sys
    if FROZEN and sys.platform in {"win32", "darwin"}:
        window.update_controller = UpdateController(window)
        menu = window.menuBar().addMenu("&Updates")
        menu.addAction("Check for updates…", window.update_controller.open_dialog)
