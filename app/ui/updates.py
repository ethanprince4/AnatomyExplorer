"""Quiet background delivery; activation waits for the next normal launch."""
import threading
import time

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from shiboken6 import isValid
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

from ..config import FROZEN
from ..updater import GitHubSource, UpdateError, installed_metadata, manifest_channel, read_manifest, store_for


class UpdateController(QObject):
    completed = Signal(object)
    message = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.worker_generation = 0
        self.result = None
        self.dialog = None
        self.closed = threading.Event()
        window.installEventFilter(self)
        # Event.set remains safe even after the QObject wrappers are destroyed.
        window.destroyed.connect(self.closed.set)
        self.completed.connect(self.finish)
        self.message.connect(self.show_message)
        self.automatic_timer = QTimer(self)
        self.automatic_timer.setSingleShot(True)
        self.automatic_timer.timeout.connect(self.automatic)
        self.automatic_timer.start(30000)

    def eventFilter(self, watched, event):
        # Cocoa can deliver a final event while the Python wrapper's fields
        # are being cleared. Never dereference absent state or call a deleted
        # QObject's base implementation from that callback.
        window = getattr(self, "window", None)
        closed = getattr(self, "closed", None)
        if window is None or closed is None:
            return False
        if watched is window and event.type() == QEvent.Close:
            closed.set()
            timer = getattr(self, "automatic_timer", None)
            if timer is not None and isValid(timer):
                timer.stop()
            if isValid(watched) and isValid(self):
                watched.removeEventFilter(self)
            self.dialog = None
        return False

    def deliver(self, signal, payload):
        if not self.closed.is_set():
            try:
                signal.emit(payload)
            except RuntimeError:
                # Qt may delete the wrapper between the guard and emission.
                self.closed.set()

    def show_message(self, message):
        if not self.closed.is_set() and self.dialog and isValid(self.dialog):
            self.dialog.status.setText(message)

    def automatic(self):
        if self.closed.is_set():
            return
        if not self.window.qsettings.value("updates/automatic", True, type=bool):
            self.automatic_timer.stop()
            return
        settings = self.window.qsettings
        now = time.time()
        success = settings.value("updates/last_success", 0, type=float)
        attempt = settings.value("updates/last_attempt", 0, type=float)
        failures = max(0, settings.value("updates/consecutive_failures", 0, type=int))
        if failures and attempt >= success:
            due = attempt + min(15 * 60 * 2 ** min(failures - 1, 5), 6 * 3600)
        else:
            due = success + 24 * 3600 if success else 0
        if due > now:
            self.automatic_timer.start(max(1000, min(round((due - now) * 1000), 24 * 3600 * 1000)))
        else:
            self.check()

    def check(self):
        if self.closed.is_set() or self.busy:
            return
        self.busy = True
        self.worker_generation += 1
        generation = self.worker_generation
        self.result = None
        self.window.qsettings.setValue("updates/last_attempt", time.time())
        self.message.emit("Checking for updates… You can keep studying.")

        def work():
            if self.closed.is_set():
                return
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
                        result = store.prepare(manifest, source, lambda text: self.deliver(self.message, text), policy_token=token)
            except Exception as exc:
                result = {"status": "error", "error": str(exc)}
            result["policy"] = token
            if not self.closed.is_set():
                try:
                    self.deliver(self.completed, (generation, result))
                except RuntimeError:
                    self.closed.set()

        threading.Thread(target=work, name="AnatomyExplorer-update", daemon=True).start()

    def finish(self, completion):
        if self.closed.is_set():
            return
        generation, result = completion
        if generation != self.worker_generation or not self.busy:
            return
        self.busy = False
        if result.get("policy") is not None and tuple(result["policy"]) != store_for().policy():
            self.result = None
            self.show_message("Update channel changed. Checking the selected channel.")
            QTimer.singleShot(0, self.check)
            return
        self.result = result
        settings = self.window.qsettings
        if result["status"] in {"ready", "current", "returning"}:
            settings.setValue("updates/last_success", time.time())
            settings.setValue("updates/consecutive_failures", 0)
        elif result["status"] == "error":
            settings.setValue("updates/consecutive_failures", settings.value("updates/consecutive_failures", 0, type=int) + 1)
        self.render_result(result)
        self.automatic()

    def render_result(self, result):
        """Display only; reopening never completes a running worker."""
        if self.closed.is_set():
            return
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
        if self.closed.is_set():
            return
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Anatomy Explorer updates")
        dlg.setMinimumWidth(460)
        lay = QVBoxLayout(dlg)
        intro = QLabel("Updates download changed parts in the background. They open on your next launch; your current study session keeps running. Some releases change large assets and need a larger download.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        automatic = QCheckBox("Check and download automatically (at most once a day)")
        automatic.setChecked(self.window.qsettings.value("updates/automatic", True, type=bool))
        def change_automatic(on):
            self.window.qsettings.setValue("updates/automatic", on)
            if on:
                self.automatic()
            else:
                self.automatic_timer.stop()

        automatic.toggled.connect(change_automatic)
        lay.addWidget(automatic)
        store = store_for()
        current = installed_metadata(store.active())
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
        if self.busy:
            self.show_message("Checking for updates. You can keep studying.")
        elif self.result:
            self.render_result(self.result)
        dlg.exec()
        self.dialog = None


def attach_updates(window):
    import sys
    if FROZEN and sys.platform in {"win32", "darwin"}:
        manifest = installed_metadata(store_for().active())
        if manifest_channel(manifest) == "experimental":
            window.setWindowTitle(window.windowTitle() + " — Experimental model preview " + manifest["version"])
        window.update_controller = UpdateController(window)
        menu = window.menuBar().addMenu("&Updates")
        menu.addAction("Check for updates…", window.update_controller.open_dialog)
