"""Quiet background delivery; activation waits for the next normal launch."""
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

from ..config import FROZEN
from ..updater import GitHubSource, UpdateError, manifest_channel, read_manifest, store_for


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
            token = None
            try:
                store = store_for()
                token = store.policy()
                source = GitHubSource(channel=token[0])
                state = store.state()
                if state.get("return_to_stable") and state.get("rollback_requested"):
                    result = {"status": "returning"}
                elif state.get("pending"):
                    pending = read_manifest(store.path(state["pending"]))
                    if manifest_channel(pending) != token[0]:
                        raise UpdateError("Pending update differs from the selected channel")
                    result = {"status": "ready", "version": pending["version"], "downloaded": 0}
                else:
                    manifest = source.latest()
                    if manifest is None:
                        result = {"status": "current"}
                    elif (state.get("failed") or "").startswith(manifest["version"] + "-"):
                        result = {"status": "error", "error": "This release was rolled back. The working version is retained; wait for a newer release."}
                    else:
                        result = store.prepare(manifest, source, self.message.emit, policy_token=token)
            except Exception as exc:
                result = {"status": "error", "error": str(exc)}
            result["policy"] = token
            self.completed.emit(result)

        threading.Thread(target=work, name="AnatomyExplorer-update", daemon=True).start()

    def finish(self, result):
        self.busy = False
        if result.get("policy") is not None and tuple(result["policy"]) != store_for().policy():
            self.result = None
            self.show_message("Update channel changed. Checking the selected channel.")
            QTimer.singleShot(0, self.check)
            return
        self.result = result
        channel = "Experimental preview" if store_for().policy()[0] == "experimental" else "Stable"
        if result["status"] == "ready":
            text = f"{channel} version {result['version']} is ready. It will open next time you launch Anatomy Explorer."
            if result.get("downloaded"):
                text += f" Downloaded {result['downloaded'] / 1024**2:.1f} MiB."
            self.window.statusBar().showMessage(text, 20000)
        elif result["status"] == "current":
            text = f"No newer {channel.lower()} update is available."
        elif result["status"] == "returning":
            text = "Your retained stable version will open on the next launch. Your study data will be kept."
        elif result["status"] == "cancelled":
            text = "The download was cancelled because the update channel changed. Your running version is unchanged."
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
        store = store_for()
        current = read_manifest(store.active())
        installed = QLabel(f"Running: {'Experimental preview' if manifest_channel(current) == 'experimental' else 'Stable'} {current['version']}\nUpdate channel: {store.policy()[0].title()}")
        installed.setWordWrap(True)
        lay.addWidget(installed)
        experimental = QCheckBox("Enable experimental stuff (model previews)")
        experimental.setChecked(store.policy()[0] == "experimental")
        experimental.setToolTip("Includes unfinished model previews. Stable is the default. You can return to stable without losing notes or progress.")
        lay.addWidget(experimental)
        warning = QLabel("Experimental previews may be incomplete or change substantially. They are clearly marked prereleases; stable updates never include them. Turning this off cancels pending preview delivery and returns to stable on your next launch.")
        warning.setWordWrap(True)
        lay.addWidget(warning)
        dlg.status = QLabel("Ready to check. An internet connection is needed only for updates.")
        dlg.status.setWordWrap(True)
        lay.addWidget(dlg.status)
        check = QPushButton("Check and download now")
        check.clicked.connect(self.check)
        lay.addWidget(check)

        def change_channel(on):
            try:
                store.set_channel("experimental" if on else "stable")
                self.result = None
                installed.setText(f"Running: {'Experimental preview' if manifest_channel(current) == 'experimental' else 'Stable'} {current['version']}\nUpdate channel: {store.policy()[0].title()}")
                dlg.status.setText("Experimental previews enabled for this installation. Checking for a preview." if on else
                                   "Stable selected. Pending previews are cancelled; your study session keeps running.")
                self.check()
            except (OSError, UpdateError, ValueError) as exc:
                experimental.blockSignals(True)
                experimental.setChecked(store.policy()[0] == "experimental")
                experimental.blockSignals(False)
                dlg.status.setText(str(exc))

        experimental.toggled.connect(change_channel)
        stable = QPushButton("Return to stable on next launch")
        stable.setEnabled(manifest_channel(current) == "experimental" or experimental.isChecked())

        def return_stable():
            if experimental.isChecked():
                experimental.setChecked(False)
            else:
                change_channel(False)  # a fresh preview install defaults to stable

        stable.clicked.connect(return_stable)
        experimental.toggled.connect(lambda on: stable.setEnabled(on or manifest_channel(current) == "experimental"))
        lay.addWidget(stable)
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
        manifest = read_manifest(store_for().active())
        if manifest_channel(manifest) == "experimental":
            window.setWindowTitle(window.windowTitle() + " — Experimental model preview " + manifest["version"])
        window.update_controller = UpdateController(window)
        menu = window.menuBar().addMenu("&Updates")
        menu.addAction("Check for updates…", window.update_controller.open_dialog)
