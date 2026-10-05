"""Application health and prepared-model deployment readiness are separate gates."""
from dataclasses import dataclass
import os
from pathlib import Path
from threading import Event, Thread

from .anatomy_variants.security import SHA, TOKEN, atomic_json, no_symlinks


@dataclass(frozen=True)
class DeploymentRequirement:
    generation_id: str
    catalog_sha256: str
    receipt: Path


def requirement_from_environment(environment=None):
    env = os.environ if environment is None else environment
    values = [env.get(name) for name in ("AE_REQUIRED_MODEL_GENERATION", "AE_REQUIRED_MODEL_CATALOG_SHA256",
                                        "AE_DATASET_READY_FILE")]
    if not any(values):
        return None
    generation, sha, receipt = values
    if not all(values) or not TOKEN.fullmatch(generation) or not SHA.fullmatch(sha):
        raise ValueError("The preparation launcher supplied an incomplete or invalid model readiness request")
    path = Path(receipt)
    if not path.is_absolute():
        raise ValueError("The model readiness receipt must use an absolute user-owned path")
    return DeploymentRequirement(generation, sha, no_symlinks(path, must_exist=False))


def verify_dataset_ready(store, requirement=None):
    """Fresh manifest/payload verification. Run on the readiness worker, never the GUI thread."""
    if getattr(store, "is_local", False):
        return {**store.active_identity(), "dataset_ready": True, "scope": "available local files; no generation proof required"}
    identity = dict(store.active_identity())
    if requirement is not None and identity.get("generation_id") != requirement.generation_id:
        raise ValueError("The active model generation does not match the prepared installation")
    if requirement is not None and identity.get("catalog_sha256") != requirement.catalog_sha256:
        raise ValueError("The prepared model catalog hash does not match the active registration")
    if identity.get("model_count") != len(store.expected_model_ids):
        raise ValueError("The complete required model catalog is not ready")
    return {"schema": "anatomy-dataset-ready", "schema_version": 1,
            **identity, "application_health": "renderer-ready", "dataset_ready": True}


def cancel_dataset_readiness(window):
    cancel = getattr(window, "_dataset_readiness_cancel", None)
    if cancel is not None:
        cancel.set()
    catalog = window.content.micro_models
    catalog.verification_state = "pending"
    catalog.ready = False
    window.catalog._run()


def retry_dataset_readiness(window):
    cancel_dataset_readiness(window)
    worker = getattr(window, "_dataset_readiness_worker", None)
    if worker is not None and worker.is_alive():
        # Never overlap two whole-generation scans. A current file operation
        # finishes, then the same timer starts the requested retry.
        window._dataset_readiness_retry_pending = True
        return
    window._dataset_readiness_started = False
    start_dataset_readiness(window)


def start_dataset_readiness(window, environment=None):
    """Background full proof checks; startup uses only the bounded data index.

    Ordinary updater app-health remains independent. A unified prepared deploy
    additionally requires its exact generation/hash receipt before success.
    """
    if getattr(window, "_dataset_readiness_started", False):
        return
    window._dataset_readiness_started = True
    catalog = window.content.micro_models
    if getattr(catalog.store, "is_local", False):
        catalog.ready = True
        catalog.verification_state = "available"
        window.dataset_ready_identity = verify_dataset_ready(catalog.store)
        window.catalog._run()
        return
    try:
        requirement = requirement_from_environment(environment)
        from ..config import ROOT
        catalog = window.content.micro_models
        if catalog.store is None:
            raise ValueError("Model data registration is unavailable. Run or resume the preparation launcher.")
        receipt = None if requirement is None else requirement.receipt
        if receipt is not None:
            if receipt.is_relative_to(ROOT) or receipt.is_relative_to(catalog.store.root / "generations"):
                raise ValueError("Readiness receipt cannot be inside an immutable application/model payload")
            if receipt.exists():
                raise ValueError("Readiness receipt path must be unique to this launch")
    except (OSError, ValueError) as exc:
        window.notice.show_message(str(exc), "Retry verification", lambda: retry_dataset_readiness(window))
        return
    from PySide6.QtCore import QEvent, QObject, QTimer
    import queue
    results = queue.SimpleQueue()
    store = catalog.store
    closed = Event()
    window._dataset_readiness_cancel = closed
    catalog.verification_state = "verifying"
    window.catalog._run()

    class CloseGuard(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Close:
                closed.set()
            return False

    guard = CloseGuard(window)
    window.installEventFilter(guard)
    window.destroyed.connect(closed.set)
    window._dataset_readiness_guard = guard

    def verify():
        try:
            data = verify_dataset_ready(store, requirement)
            if closed.is_set():
                return
            if receipt is not None:
                no_symlinks(receipt.parent, must_exist=False)
                receipt.parent.mkdir(parents=True, exist_ok=True)
                if closed.is_set():
                    return
                atomic_json(receipt, data)
            results.put((True, data))
        except (OSError, ValueError) as exc:
            results.put((False, str(exc)))

    timer = QTimer(window)
    timer.setInterval(50)

    def poll():
        if closed.is_set():
            if worker.is_alive():
                return
            timer.stop()
            timer.deleteLater()
            if getattr(window, "_dataset_readiness_retry_pending", False) and not getattr(window, "_closing", False):
                window._dataset_readiness_retry_pending = False
                window._dataset_readiness_started = False
                start_dataset_readiness(window, environment)
            return
        try:
            ready, detail = results.get_nowait()
        except queue.Empty:
            return
        timer.stop()
        timer.deleteLater()
        if ready:
            from .catalog import load_active_catalog
            refreshed = load_active_catalog(store=store)
            if refreshed.error:
                catalog.verification_state = "failed"
                window.notice.show_message(refreshed.error, "Retry verification", lambda: retry_dataset_readiness(window))
                return
            refreshed.ready = True
            refreshed.verification_state = "verified"
            window.content.set_model_catalog(refreshed)
            window.index.replace_models(refreshed)
            window.dataset_ready_identity = detail
            window.catalog._run()
        else:
            catalog.ready = False
            catalog.verification_state = "failed"
            window.content.model_catalog_error = "Prepared-model verification failed: " + detail
            window.catalog._run()
            window.notice.show_message(window.content.model_catalog_error,
                                       "Retry verification", lambda: retry_dataset_readiness(window))

    timer.timeout.connect(poll)
    timer.start()
    worker = Thread(target=verify, name="prepared-model-readiness", daemon=True)
    window._dataset_readiness_worker = worker
    worker.start()
