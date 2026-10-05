"""Read-only, serialized CPU loading and bounded result handoff.

One worker owns at most one model. It waits for the GUI to take its result before
starting the next request; pending requests hold metadata, never geometry. No
worker accesses a widget, QObject, OpenGL context, or the shared model registry.
"""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Condition, Thread
from time import perf_counter

from ..load_control import LoadCancelled, LoadToken, checkpoint, load_scope


class ModelCacheUnavailable(RuntimeError):
    pass


def load_cached_procedural(entry):
    """Use the existing readers without editing toolkit bytes/cache digests.

Ordinary stale/missing caches now fail instead of running arbitrary builders
inside an interactive load. Explicit build tools retain their existing behavior.
Protected/custom frozen readers keep their own verification and decoding rules.
"""
    from ..micro.base import MicroModel
    from ..micro.anim import AnimatedModel, load_anim
    from ..micro.cache import load_parts, source_digest
    # The recovered frozen-reader helper is not a current-main dependency.
    # Its absence must not break an ordinary read-only cache request. A shipped
    # helper, when present, keeps its own strict protected-payload checks.
    from importlib import import_module
    try:
        protection = import_module("app.micro.protection")
    except ModuleNotFoundError as exc:
        if exc.name != "app.micro.protection":
            raise
        frozen_parts = lambda _model: None
    else:
        frozen_parts = protection.frozen_parts
    from .procedural import ProceduralModel

    source = entry.micro
    # Do not copy a previous synchronous caller's potentially huge cached arrays.
    # deepcopy rebinds bound methods and the frozen Jejunum reader's partial to
    # the private instance, unlike a shallow copy of that reader.
    memo = {id(value): None for name in ('_parts', '_colors')
            if (value := getattr(source, name, None)) is not None}
    micro = deepcopy(source, memo)
    micro._parts = None
    checkpoint()
    ordinary = ('parts' not in vars(source)
                and type(source).parts in (MicroModel.parts, AnimatedModel.parts))
    if ordinary:
        parts = frozen_parts(micro)
        checkpoint()
        if parts is None:
            digest = source_digest(micro)
            checkpoint()
            parts = load_parts(micro.id, digest)
            checkpoint()
            if parts is not None and isinstance(micro, AnimatedModel):
                if not load_anim(micro.id, parts, digest):
                    parts = None
                checkpoint()
            if not parts:
                raise ModelCacheUnavailable(
                    f'{entry.name}: its prebuilt model cache is missing, damaged or out of date. '
                    'Prepare the cache with the model build tool, then reopen this model.')
        micro._parts = parts
    else:
        # The catalogue's two model-owned frozen readers perform their own
        # hash/encoding/camera/color checks and do not use ordinary rebuilds.
        # New custom reader types must obey this read-only contract too.
        parts = micro.parts()
        checkpoint()
    model = ProceduralModel(micro, parts=parts)
    checkpoint()
    # Geometry and animation were copied into viewer-owned buffers. These source
    # meshes are needed only during conversion, not by playback/labels/picking.
    model._part_sources = []
    micro._parts = None
    if hasattr(micro, '_colors'):
        micro._colors = None
    return model


def prepare_model(entry, token):
    with load_scope(token):
        from ..variants.catalog import DeferredVariantEntry, VariantPreferenceCommit
        if not isinstance(entry, VariantPreferenceCommit):
            # This first import can take hundreds of milliseconds. Do it while
            # the loading indicator is present, on the existing CPU worker.
            from scipy.ndimage import distance_transform_edt  # noqa: F401
            checkpoint()
        if isinstance(entry, (DeferredVariantEntry, VariantPreferenceCommit)):
            return entry.prepare_cpu(token)
        from ..variants.anatomy_runtime_adapters import VariantEntry
        if isinstance(entry, VariantEntry):
            return entry.prepare_cpu(token)
        from .catalog import ProceduralEntry
        if isinstance(entry, ProceduralEntry):
            return load_cached_procedural(entry)
        return entry.load()


@dataclass
class LoadRequest:
    key: str
    serial: int
    entry: object
    token: LoadToken = field(default_factory=LoadToken)


@dataclass
class LoadResult:
    key: str
    serial: int
    model: object = None
    seconds: float = 0.0
    error: str = ''


class ModelLoadQueue:
    """Thread-safe CPU service. Cancellation/reopen uses serial identities.

Close is non-blocking. A read already in a native operation finishes that
operation, reaches a checkpoint, discards its arrays and exits. The daemon has
no Qt objects, writes or external transactions to finish at application exit.
"""
    def __init__(self, prepare=prepare_model):
        self._prepare = prepare
        self._condition = Condition()
        self._pending = {}
        self._waiting = deque()
        self._active = None
        self._result = None
        self._serial = 0
        self._closed = False
        self._thread = None

    @property
    def pending(self):
        with self._condition:
            return bool(self._pending)

    def request(self, key, entry):
        with self._condition:
            if self._closed:
                raise RuntimeError('Model loader is closed')
            existing = self._pending.get(key)
            if existing is not None:
                return existing.serial
            self._serial += 1
            request = LoadRequest(key, self._serial, entry)
            self._pending[key] = request
            self._waiting.append(request)
            if self._thread is None:
                self._thread = Thread(target=self._run, name='model-load', daemon=True)
                try:
                    self._thread.start()
                except Exception:
                    self._thread = None
                    self._waiting.remove(request)
                    del self._pending[key]
                    raise
            self._condition.notify_all()
            return request.serial

    def cancel(self, key):
        with self._condition:
            request = self._pending.pop(key, None)
            if request is None:
                return
            request.token.cancel()
            # Remove queued metadata immediately, including callbacks on entries.
            self._waiting = deque(r for r in self._waiting if r is not request)
            if self._result is not None and self._result.serial == request.serial:
                self._result = None
            self._condition.notify_all()

    def take_result(self):
        with self._condition:
            result, self._result = self._result, None
            if result is None:
                return None
            current = self._pending.get(result.key)
            if current is None or current.serial != result.serial:
                self._condition.notify_all()
                return None
            del self._pending[result.key]
            self._condition.notify_all()
            return result

    def close(self):
        with self._condition:
            self._closed = True
            for request in self._pending.values():
                request.token.cancel()
            self._pending.clear()
            self._waiting.clear()
            self._result = None
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or
                                         (self._waiting and self._result is None))
                if self._closed:
                    return
                request = self._waiting.popleft()
                self._active = request
            start = perf_counter()
            result = None
            try:
                model = self._prepare(request.entry, request.token)
                request.token.check()
                result = LoadResult(request.key, request.serial, model, perf_counter() - start)
                model = None  # never retain the previous result in the idle frame
            except LoadCancelled:
                model = None
                result = LoadResult(request.key, request.serial, error="Model loading was cancelled.")
            except Exception as error:
                # No traceback/exception object crosses the handoff: it can retain
                # every partially decoded array through its stack frames.
                result = LoadResult(request.key, request.serial, seconds=perf_counter() - start,
                                    error=f'{type(error).__name__}: {error}')
            with self._condition:
                if not self._closed and not request.token.cancelled:
                    self._result = result
                self._active = None
                self._condition.notify_all()
            result = request = None
