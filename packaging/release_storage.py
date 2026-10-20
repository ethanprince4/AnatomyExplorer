"""Bounded storage helpers for read-only release inputs on disposable CI."""
import os
from pathlib import Path
import shutil

RESERVE = 256 * 1024**2


def ci_links_enabled():
    enabled = os.environ.get('AE_RELEASE_HARDLINKS') == '1'
    if enabled and (os.environ.get('GITHUB_ACTIONS') != 'true' or
                    os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise ValueError('Release hardlinks are restricted to disposable GitHub Actions builds')
    return enabled


def require_space(directory, needed, operation):
    free = shutil.disk_usage(directory).free
    print(f'{operation}: {free:,} bytes free; {needed:,} bytes required', flush=True)
    if free < needed:
        raise OSError(f'{operation} needs {needed:,} free bytes, but this runner has {free:,}. '
                      'No release assets were omitted. Use a runner with sufficient free storage.')
    return free


def immutable_copy(source, destination):
    """Share immutable bytes on the same filesystem; otherwise make a real copy.

    Callers must not subsequently modify either path. Code and signed binaries
    that will be rewritten by packaging must continue to use independent copies.
    """
    source, destination = Path(source), Path(destination)
    try:
        os.link(source, destination)
    except OSError:
        require_space(destination.parent, source.stat().st_size + RESERVE, 'Immutable copy fallback')
        shutil.copy2(source, destination)
    return str(destination)
