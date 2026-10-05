"""Atomic writes for disposable derived atlas NPZ caches."""
import os
import tempfile
from pathlib import Path

import numpy as np


def save_npz(path, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".npz")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            np.savez(stream, **arrays)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def format_matches(value, expected):
    """Cache versions must be scalar integers, never coercible strings/arrays."""
    value = np.asarray(value)
    return value.shape == () and value.dtype.kind in "iu" and int(value) == expected
