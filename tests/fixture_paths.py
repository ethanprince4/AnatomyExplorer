"""Canonical roots for owned temporary fixtures on every runner.

macOS /var and /private/var, and Windows short profile names, can identify the
same directory. Resolve the fixture once, before deriving expected child paths,
so path assertions match the updater without weakening its path checks.
"""
from pathlib import Path


def fixture_root(directory):
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The temporary fixture root must be an existing directory")
    return root
