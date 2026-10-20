"""Prepare storage only in a fresh, disposable GitHub-hosted release checkout.

Keep exactly the selected model inputs, fetch only needed LFS objects, and share
their immutable bytes with the checkout. Never run cleanup on a developer copy.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from model_library_seed import post_library_data
from release_storage import immutable_copy, require_space


def run(*command, **kwargs):
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def hosted_checkout():
    root = Path(os.environ.get('GITHUB_WORKSPACE', '')).resolve()
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            not os.environ.get('GITHUB_RUN_ID', '').isdigit() or
            root != Path.cwd().resolve() or not (root / '.git').is_dir()):
        raise SystemExit('Storage cleanup requires a fresh GitHub-hosted Actions checkout')
    return root


def selected_inputs(root):
    library = root / 'data/local_model_library'
    if not (library / 'library.json').is_file():
        return None
    _, assets = post_library_data(library)
    return {source.resolve() for source in assets.values()} | {library / 'library.json'}


def required_lfs(root, rows, selected):
    if selected is None:
        return rows
    return [row for row in rows if (
        (root / row['name']).resolve() in selected
        if row['name'].startswith('data/local_model_library/')
        else not row['name'].startswith(('models/', 'data/micro_cache/', 'data/models/')))]


def prune_unselected_models(root, selected):
    if selected is None:
        return
    library = (root / 'data/local_model_library').resolve()
    freed = 0
    for path in library.rglob('*'):
        if path.is_file() and path.resolve() not in selected:
            if path.is_symlink() or not path.resolve().is_relative_to(library):
                raise ValueError('Unexpected link in disposable model checkout')
            freed += path.stat().st_size
            path.unlink()
    print(f'Removed {freed:,} bytes of unselected model inputs from disposable CI checkout', flush=True)


def cleanup_unused_tools(root, target):
    before = shutil.disk_usage(root)
    print(f'Runner volume: total={before.total:,} free={before.free:,}; target free={target:,}', flush=True)
    if before.free >= target:
        return
    if sys.platform == 'darwin':
        developer = Path(run('xcode-select', '-p', capture_output=True, text=True).stdout.strip()).resolve()
        selected = next((parent for parent in developer.parents if parent.suffix == '.app'), None)
        if selected is None or selected.parent != Path('/Applications'):
            raise ValueError('Cannot establish the selected Xcode app; refusing toolchain cleanup')
        for path in sorted(Path('/Applications').glob('Xcode_*.app')):
            # Skip aliases and keep the active compiler/SDK/toolchain completely intact.
            if path.is_symlink() or path.resolve() == selected:
                continue
            if path.resolve().parent != Path('/Applications') or not path.is_dir():
                raise ValueError('Unexpected Xcode cleanup path')
            print(f'Removing unused preinstalled toolchain {path}', flush=True)
            run('sudo', 'rm', '-rf', path)
            if shutil.disk_usage(root).free >= target:
                break
    elif sys.platform == 'win32':
        run('pwsh', '-NoProfile', '-File', Path(__file__).with_name('free_windows_runner.ps1'),
            '-Workspace', root, '-TargetFree', target)
    elif sys.platform.startswith('linux'):
        # The final publish job only needs Python, Git and GitHub CLI.
        for path in map(Path, ('/usr/local/lib/android', '/usr/share/dotnet', '/opt/ghc')):
            if path.is_symlink() or path.resolve() != path or not path.is_dir():
                continue
            print(f'Removing unused preinstalled toolchain {path}', flush=True)
            run('sudo', 'rm', '-rf', path)
            if shutil.disk_usage(root).free >= target:
                break
    require_space(root, target, 'After unused-toolchain cleanup')


def checkout_lfs(root, storage, rows):
    for row in rows:
        digest = row['oid']
        if row.get('oid_type') != 'sha256' or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Unsupported Git LFS object identity')
        source = storage / digest[:2] / digest[2:4] / digest
        target = root / row['name']
        if not source.is_file() or source.stat().st_size != row['size']:
            raise ValueError(f'Missing or incomplete selected LFS object: {row["name"]}')
        checksum = hashlib.sha256()
        with source.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024**2), b''):
                checksum.update(block)
        if checksum.hexdigest() != digest:
            raise ValueError(f'Selected LFS object failed its SHA-256 check: {row["name"]}')
        if not target.resolve().is_relative_to(root) or target.is_symlink():
            raise ValueError('Unsafe LFS checkout destination')
        temporary = target.with_name(target.name + '.release-lfs')
        if temporary.exists():
            raise ValueError('Unexpected existing temporary LFS checkout')
        try:
            immutable_copy(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-lfs', action='store_true')
    parser.add_argument('--key', default='.lfs-assets-id')
    args = parser.parse_args()
    root = hosted_checkout()
    selected = selected_inputs(root)
    all_lfs = json.loads(run('git', 'lfs', 'ls-files', '--json', capture_output=True, text=True).stdout)['files']
    rows = required_lfs(root, all_lfs, selected)
    if args.fetch_lfs:
        names = [row['name'] for row in rows]
        if names:
            if any(not re.fullmatch(r'[A-Za-z0-9_./-]+', name) for name in names):
                raise ValueError('Unsupported filename in selected LFS include list')
            run('git', 'lfs', 'fetch', '--include=' + ','.join(names), '--exclude=', 'origin', os.environ['GITHUB_SHA'])
            media = next(line.split('=', 1)[1] for line in run('git', 'lfs', 'env', capture_output=True, text=True).stdout.splitlines()
                         if line.startswith('LocalMediaDir='))
            checkout_lfs(root, Path(media).resolve(), rows)
        print(f'Fetched/materialized {len(rows)} required LFS files; unselected historical objects were not fetched', flush=True)
        return
    prune_unselected_models(root, selected)
    declared = {row['name']: row['size'] for row in rows}
    model_bytes = sum(declared.get(path.relative_to(root).as_posix(), path.stat().st_size)
                      for path in selected or [])
    # Source/bundle share model bytes. Budget includes worst-case compressed
    # outputs, a full native installation, and the unmodified updater reserve.
    target = max(40 * 1024**3, model_bytes * 5 + 8 * 1024**3)
    cleanup_unused_tools(root, target)
    key = root / args.key
    if key.resolve().parent != root:
        raise ValueError('LFS cache key must stay at the checkout root')
    key.write_text('\n'.join(sorted(row['oid'] for row in rows)) + '\n', encoding='ascii')
    print(f'Selected model bytes={model_bytes:,}; required LFS bytes={sum(row["size"] for row in rows):,}', flush=True)


if __name__ == '__main__':
    main()
