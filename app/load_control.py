"""Cooperative cancellation for CPU-only model readers; no Qt or global hooks.

A scope belongs to the calling thread. Cancellation never interrupts native code
or kills a thread: readers check at safe boundaries and discard incomplete work.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event


class LoadCancelled(Exception):
    """Expected cancellation, distinct from malformed content or a missing cache."""


class LoadToken:
    def __init__(self):
        self._cancelled = Event()

    def cancel(self):
        self._cancelled.set()

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    def check(self):
        if self.cancelled:
            raise LoadCancelled()


_current = ContextVar('model_load_token', default=None)


def checkpoint():
    token = _current.get()
    if token is not None:
        token.check()


@contextmanager
def load_scope(token):
    previous = _current.set(token)
    try:
        checkpoint()
        yield
        checkpoint()
    finally:
        _current.reset(previous)
