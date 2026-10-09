"""Verify candidate linkage and unchanged wheel, then strict fresh-process matrix."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import PySide6
from PySide6.QtCore import qVersion


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(sys.argv[1]).resolve()
    evidence = root / 'evidence'
    plugin = evidence / 'libqcocoa.dylib'
    wheel = Path(PySide6.__file__).resolve().parent / 'Qt'
    assert PySide6.__version__ == qVersion() == '6.11.2'
    arch = subprocess.check_output(['lipo', '-archs', str(plugin)], text=True).strip()
    assert arch == 'arm64', 'This bounded candidate must be arm64, not mislabeled universal'
    deps = subprocess.check_output(['otool', '-L', str(plugin)], text=True)
    commands = subprocess.check_output(['otool', '-l', str(plugin)], text=True)
    qt_deps = [line.split()[0] for line in deps.splitlines()[1:] if 'Qt' in line]
    assert set(qt_deps) == {'@rpath/QtCore.framework/Versions/A/QtCore', '@rpath/QtGui.framework/Versions/A/QtGui'}
    rpaths = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset', commands)
    assert rpaths and all(path == '@loader_path/../../lib' for path in rpaths), rpaths
    min_os = re.search(r'cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform \d+\s+minos ([0-9.]+)', commands)
    assert min_os and float(min_os.group(1)) <= 13.0
    before = {p.name: digest(p / 'Versions/A' / p.stem) for p in (wheel / 'lib').glob('Qt*.framework')}
    target = wheel / 'plugins/platforms/libqcocoa.dylib'
    shutil.copy2(target, root / 'original-wheel-libqcocoa.dylib')
    original_hash = digest(target)
    # Control: the plugin we ship now, through the same harness. It shows whether the harness reproduces the
    # crash this candidate fixes; it does not decide acceptance.
    previous = Path('packaging/qt-cocoa/libqcocoa.dylib')
    control = None
    if previous.exists():
        shutil.copy2(previous, target)
        control_env = {k: v for k, v in os.environ.items() if k != 'QT_OWNERSHIP_PLUGIN_SHA256'}
        control_env['QT_QPA_PLATFORM'] = 'cocoa'
        try:
            subprocess.run([sys.executable, 'packaging/diagnostics/mac_ax/run_matrix.py', '--single-plain',
                            '--output', str(evidence / 'control-previous-plugin')], env=control_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        except subprocess.TimeoutExpired:
            pass
        summary_path = evidence / 'control-previous-plugin' / 'summary.json'
        control = {'plugin_sha256': digest(previous),
                   'summary': json.loads(summary_path.read_text()) if summary_path.exists() else None}
    shutil.copy2(plugin, target)
    candidate_hash = digest(plugin)
    env = dict(os.environ, QT_QPA_PLATFORM='cocoa', QT_DEBUG_PLUGINS='1', DYLD_PRINT_LIBRARIES='1',
               QT_OWNERSHIP_PLUGIN_SHA256=candidate_hash, QT_OWNERSHIP_WHEEL_ROOT=str(wheel))
    for name in ('DYLD_FRAMEWORK_PATH', 'DYLD_LIBRARY_PATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        assert not env.get(name), f'Unexpected runtime override: {name}'
    report = {'schema': 1, 'release_candidate': False, 'upstream_change_status': 'NEW; unreleased',
              'source_tag': 'v6.11.2', 'source_commit': 'ef55f427f2c8b410d34f8a7681020a3000cf6866',
              'gerrit_patchset': '765434/1', 'patch_commit': 'c7fd3f34b997bb363be15650647665b3b6b8a5f4',
              'corresponding_source': 'https://github.com/qt/qtbase/tree/ef55f427f2c8b410d34f8a7681020a3000cf6866',
              'modified_source_in_artifact': 'modified-cocoa-source; exact full patch and licenses included',
              'sdk_sha1': '898a61de33218d55538721ce35c61f973768cb07',
              'sdk_sha256': digest(root / 'sdk.7z'), 'original_wheel_plugin_sha256': original_hash,
              'candidate_plugin_sha256': candidate_hash, 'architectures': arch,
              'minimum_os': min_os.group(1), 'qt_dependencies': qt_deps, 'rpaths': rpaths,
              'framework_hashes_before': before, 'physical_mac_validated': False, 'passed': False,
              'additional_patches': ['ae-accessibility-bounds.patch'], 'control_previous_plugin': control}
    try:
        # run_matrix collects every case even when an early case crashes.
        raw_log = root / 'private-native-loader.log'
        with raw_log.open('w', encoding='utf-8') as stream:
            result = subprocess.run([sys.executable, 'packaging/diagnostics/mac_ax/run_matrix.py',
                                     '--output', str(evidence / 'matrix'),
                                     '--private-loader-log-dir', str(root / 'private-native-loader')], env=env,
                                    stdout=stream, stderr=stream, timeout=720)
        after = {p.name: digest(p / 'Versions/A' / p.stem) for p in (wheel / 'lib').glob('Qt*.framework')}
        report['framework_hashes_unchanged'] = before == after
        report['exit_code'] = result.returncode
        summary = json.loads((evidence / 'matrix/summary.json').read_text())
        runtime_rows = []
        for path in (evidence / 'matrix').glob('*.jsonl'):
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            runtime_rows.extend(row for row in rows if row.get('event') == 'ownership_runtime')
        runtime_valid = len(runtime_rows) == 5 and all(row.get('candidate_plugin_loaded') is True
                         and row.get('all_qt_frameworks_from_wheel') is True for row in runtime_rows)
        report['isolated_runtime_verified'] = runtime_valid
        report['runtime_evidence'] = runtime_rows
        report['matrix_passed'] = summary['passed']
        report['passed'] = result.returncode == 0 and summary['passed'] and runtime_valid and before == after
    finally:
        shutil.copy2(root / 'original-wheel-libqcocoa.dylib', target)
        (evidence / 'acceptance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'matrix_passed': report.get('matrix_passed'),
                      'isolated_runtime_verified': report.get('isolated_runtime_verified'),
                      'framework_hashes_unchanged': report.get('framework_hashes_unchanged')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
