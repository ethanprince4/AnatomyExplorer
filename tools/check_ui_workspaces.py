"""Run the focused native UI checks without loading or rendering models.

From an assembled checkout: python -B tools/check_ui_workspaces.py
For a code-only overlay: python -B tools/check_ui_workspaces.py --base SOURCE --overlay OVERLAY
Each test file gets a fresh interpreter. User-data/settings fixtures stay temporary.
"""
import argparse
import ast
import os
from pathlib import Path
import subprocess
import sys

TESTS = (
    'test_shell_ui.py', 'test_catalog_viewer_ui.py', 'test_learning_workspace_ui.py',
    'test_image_workspace_ui.py', 'test_saved_views_ui.py', 'test_main_window_shell_ui.py',
)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=root)
    parser.add_argument('--overlay', type=Path, default=root)
    args = parser.parse_args()
    base, overlay = args.base.resolve(), args.overlay.resolve()
    if not (base / 'app/config.py').is_file():
        parser.error('--base must contain the existing complete app source tree')
    missing = [name for name in TESTS if not (overlay / 'tests' / name).is_file()]
    if missing:
        parser.error('Missing combined-overlay tests: ' + ', '.join(missing))
    for path in sorted((overlay / 'app').rglob('*.py')):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1',
               ANATOMY_UI_BASE=str(base), ANATOMY_UI_OVERLAY=str(overlay))
    env.setdefault('XDG_CACHE_HOME', str(Path(os.environ.get('TMPDIR', '/tmp')) / 'anatomy-ui-qt-cache'))
    code = ('import runpy,sys; from pathlib import Path; '
            'base,overlay,target=sys.argv[1:4]; sys.path.insert(0,base); '
            'import app; app.__path__.insert(0,str(Path(overlay)/"app")); '
            'import app.ui; app.ui.__path__.insert(0,str(Path(overlay)/"app/ui")); '
            'sys.argv=[target,"-v"]; runpy.run_path(target,run_name="__main__")')
    failures = []
    for name in TESTS:
        print('\n=== ' + name + ' ===', flush=True)
        result = subprocess.run([sys.executable, '-B', '-c', code, str(base), str(overlay),
                                 str(overlay / 'tests' / name)], env=env, check=False)
        if result.returncode:
            failures.append(name)
    if failures:
        print('FAILED: ' + ', '.join(failures))
        return 1
    print('\nAll focused UI checks passed. Windows/GPU/DPI/accessibility acceptance is still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
