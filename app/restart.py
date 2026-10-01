"""Explicit restart handoff; the normal managed launcher owns activation."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

from .updater import UpdateError, atomic_json, launch_managed, store_for


@dataclass
class RestartRequest:
    path: Path
    process: object

    def arm(self):
        if self.process.poll() is not None:
            raise UpdateError("The restart helper could not start")
        atomic_json(self.path, {"schema": 1, "armed": True})

    def cancel(self):
        self.path.unlink(missing_ok=True)


def prepare_restart(expected_policy):
    """Start an unarmed helper before requesting a normal, saving window close."""
    store = store_for()
    if expected_policy is None or tuple(expected_policy) != store.policy():
        raise UpdateError("The update channel changed; check the selected channel again")
    if not store.state().get("pending"):
        raise UpdateError("There is no downloaded update waiting to apply")
    token = uuid.uuid4().hex
    request = store.root / ("restart-" + token + ".json")
    atomic_json(request, {"schema": 1, "armed": False})
    env = dict(os.environ, AE_INSTALL_BASE=str(store.base), PYINSTALLER_RESET_ENVIRONMENT="1")
    env.pop("AE_READY_FILE", None)
    try:
        process = subprocess.Popen(
            [sys.executable, "--ae-restart-helper", token],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
            start_new_session=(os.name != "nt"))
    except Exception:
        request.unlink(missing_ok=True)
        raise
    return RestartRequest(request, process)


def run_helper(token, timeout=90):
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise UpdateError("Invalid restart request")
    store = store_for()
    request = store.root / ("restart-" + token + ".json")
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                data = json.loads(request.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return 0  # The original window refused to close or cancelled.
            if (not isinstance(data, dict) or data.get("schema") != 1
                    or type(data.get("armed")) is not bool):
                raise UpdateError("Invalid restart handshake")
            if data["armed"]:
                request.unlink(missing_ok=True)
                # Wait for the old supervisor's session lock. Activation, trial
                # readiness and rollback remain on the established launch path.
                return launch_managed([], base=store.base, wait_seconds=timeout)
            time.sleep(0.1)
        raise UpdateError("The application did not finish closing for restart")
    finally:
        request.unlink(missing_ok=True)


def main():
    try:
        index = sys.argv.index("--ae-restart-helper")
        return run_helper(sys.argv[index + 1])
    except Exception as exc:
        # The old process may already be closed; provide an actionable message.
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.warning(None, "Anatomy Explorer restart",
                            "Could not restart automatically. Open Anatomy Explorer normally. "
                            "Your downloaded update and study data are retained.\n\n" + str(exc))
        return 1
