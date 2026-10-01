"""Exercise a real frozen restart using disposable stores and the shipped UI.

python packaging/check_restart.py BUNDLE FEED --report REPORT.json
The copied baseline has test-only version 0.0.0; the update is the actual feed.
No distribution bytes, registry installation, or real study preferences change.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import (MAC_MANIFEST, MANIFEST, UpdateError, UpdateStore,
                         atomic_json, lock, manifest_path, sha)


class Packs:
    def __init__(self, root):
        self.root = root
    def chunk(self, blob, total):
        with open(self.root / blob['pack'], 'rb') as source:
            source.seek(blob['offset'])
            return source.read(blob['size'])


def until(predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError('Frozen restart did not reach the expected condition')


def stop_owned_tree(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    listing = subprocess.check_output(['ps', '-axo', 'pid=,ppid='], text=True)
    children = {}
    for line in listing.splitlines():
        child, parent = map(int, line.split())
        children.setdefault(parent, []).append(child)
    def terminate(process):
        for child in children.get(process, []):
            terminate(child)
        try:
            os.kill(process, signal.SIGTERM)
        except ProcessLookupError:
            pass
    terminate(pid)


UI_PROBE = '''
import json
import os
from pathlib import Path
from PySide6.QtCore import QTimer
from app import restart
from app.config import FROZEN
from app.updater import atomic_json, store_for

probe = Path(os.environ['AE_RESTART_PROBE'])
controller = w.update_controller
controller.automatic_timer.stop()
assert FROZEN

def wait_for_baseline_frame():
    renderer = w.viewport.renderer
    if not w.viewport.isValid() or renderer is None or not renderer.frame_ok:
        QTimer.singleShot(100, wait_for_baseline_frame)
        return
    atomic_json(probe / 'baseline-ui.json', {'frozen': True, 'pid': os.getpid()})
    wait_for_stage()

def wait_for_stage():
    if not (probe / 'prepared').exists():
        QTimer.singleShot(100, wait_for_stage)
        return
    w.qsettings.setValue('updates/automatic', True)
    w.qsettings.setValue('updates/last_success', 9999999999.0)
    controller.automatic()
    wait_for_ready()

def wait_for_ready():
    if controller.busy or controller.result is None:
        QTimer.singleShot(100, wait_for_ready)
        return
    assert controller.result['status'] == 'ready', controller.result
    notice = controller.ready_notice
    assert notice is not None and notice.isVisible()
    next(button for button in notice.buttons() if button.text() == 'Not now').click()
    assert not controller.closed.is_set()
    assert store_for().state().get('pending')
    w.qsettings.setValue('test/restart-preserved', 'keep-me')
    # The restarted normal UI need not use the public release API in this test.
    w.qsettings.setValue('updates/automatic', False)
    original_prepare = restart.prepare_restart
    def observed_prepare(policy):
        request = original_prepare(policy)
        assert json.loads(request.path.read_text())['armed'] is False
        atomic_json(probe / 'helper.json', {'pid': request.process.pid,
                    'unarmed_before_close': True, 'not_now_kept_session': True})
        return request
    restart.prepare_restart = observed_prepare
    controller.restart_now()

wait_for_baseline_frame()
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('feed', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    bundle, feed, report = args.bundle.resolve(), args.feed.resolve(), args.report.resolve()
    mac = bundle.suffix == '.app'
    assert (sys.platform == 'darwin') == mac
    manifest = json.loads((feed / (MAC_MANIFEST if mac else MANIFEST)).read_text())
    output = report.parent
    output.mkdir(parents=True, exist_ok=True)
    fixture_parent = Path(tempfile.gettempdir()).resolve()
    temporary = tempfile.TemporaryDirectory(prefix='ae-restart-', dir=fixture_parent)
    root = Path(temporary.name).resolve()
    assert root.is_relative_to(fixture_parent)  # recursive cleanup stays inside temp
    supervisor = None
    helper = None
    try:
        base = root / 'base' / ('Anatomy Explorer.app' if mac else 'AnatomyExplorer')
        def copy_file(src, dst):
            relative = Path(src).relative_to(bundle).as_posix()
            if relative.startswith(('Contents/Resources/data/', 'Contents/Resources/models/',
                                    '_internal/data/', '_internal/models/')):
                try:
                    os.link(src, dst)
                    return dst
                except OSError:
                    pass
            return shutil.copy2(src, dst)
        shutil.copytree(bundle, base, symlinks=True, copy_function=copy_file)
        resources = base / ('Contents/Resources' if mac else '_internal')
        (resources / 'VERSION').write_text('0.0.0')
        atomic_json(resources / 'UPDATE_CHANNEL.json', {'channel': 'stable', 'release_tag': 'v0.0.0'})
        if mac:
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(base)], check=True)
        else:
            baseline = json.loads(json.dumps(manifest))
            baseline.update(version='0.0.0', channel='stable', release_tag='v0.0.0')
            for item in baseline['files']:
                if item['path'] in {'_internal/VERSION', '_internal/UPDATE_CHANNEL.json'}:
                    raw = (base / item['path']).read_bytes()
                    item.update(size=len(raw), sha256=sha(raw), chunks=[])
            # Baseline inventories must satisfy protocol chunk-count validation.
            for item in baseline['files']:
                if item['path'] in {'_internal/VERSION', '_internal/UPDATE_CHANNEL.json'}:
                    raw = (base / item['path']).read_bytes()
                    item['chunks'] = [sha(raw)]
                    baseline['blobs'][sha(raw)] = {'pack': next(iter(baseline['packs'])),
                                                 'offset': 0, 'size': 1, 'raw_size': len(raw)}
            atomic_json(manifest_path(base), baseline)
        profile = root / ('home/Library/Application Support' if mac else 'profile')
        settings_dir = root / 'qt-settings'
        env = dict(os.environ, AE_TEST_SETTINGS_DIR=str(settings_dir), AE_RESTART_PROBE=str(root))
        env.pop('AE_INSTALL_BASE', None)
        env.pop('AE_READY_FILE', None)
        env.pop('QT_QPA_PLATFORM', None)
        if mac:
            env['HOME'] = str(root / 'home')
        else:
            env['LOCALAPPDATA'] = str(profile)
        from PySide6.QtCore import QSettings
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(settings_dir))
        settings = QSettings('AnatomyExplorer', 'Anatomy Explorer')
        settings.setValue('updates/automatic', False)
        settings.setValue('test/restart-preserved', 'keep-me')
        settings.sync()
        user = profile / 'AnatomyExplorer/user'
        user.mkdir(parents=True)
        notes = user / 'notes.json'
        notes.write_bytes(b'{"1":"Keep this isolated restart note"}')
        note_bytes = notes.read_bytes()
        script_file = root / 'ui-probe.py'
        script_file.write_text(UI_PROBE, encoding='utf-8')
        script = 'wait:1000;eval:exec(open(' + repr(str(script_file)) + ", encoding='utf-8').read())"
        executable = base / ('Contents/MacOS/AnatomyExplorer' if mac else 'AnatomyExplorer.exe')
        supervisor = subprocess.Popen([str(executable), '--script', script], env=env)
        until(lambda: (root / 'baseline-ui.json').exists())
        store = UpdateStore(base, profile / 'AnatomyExplorer/updates' / sha(str(base).casefold().encode())[:16])
        try:
            with lock(store.root / 'session.lock'):
                raise AssertionError('Real old supervisor failed to hold its session lock')
        except UpdateError:
            pass
        if manifest.get('channel') == 'experimental':
            store.set_channel('experimental')
        result = store.prepare(manifest, Packs(feed))
        assert result['status'] == 'ready' and store.active() == base
        (root / 'prepared').write_text('prepared')
        until(lambda: (root / 'helper.json').exists())
        helper_info = json.loads((root / 'helper.json').read_text())
        helper = helper_info['pid']
        assert supervisor.wait(timeout=120) == 0, 'Original UI did not close normally'
        until(lambda: store.state().get('current') is not None and store.state().get('trial') is False)
        active = store.active()
        store.verify(active)
        assert active != base and store.policy()[0] == manifest.get('channel', 'stable')
        settings.sync()
        assert settings.value('test/restart-preserved') == 'keep-me'
        assert settings.contains('geometry'), 'Normal close did not save window settings'
        assert notes.read_bytes() == note_bytes
        stop_owned_tree(helper)
        helper = None
        until(lambda: acquire_after_exit(store.root / 'session.lock'))
        assert store.prepare(manifest, Packs(feed))['status'] == 'current'
        store.request_rollback()
        assert store.rollback() and store.active() == base
        store.verify(base)
        assert notes.read_bytes() == note_bytes
        result.update(frozen=True, baseline_ui=True, old_supervisor_lock=True,
                      explicit_restart=True, original_base_identity=True, verified_trial=True,
                      study_data_and_settings_preserved=True, no_update=True, rollback=True,
                      **{key: value for key, value in helper_info.items() if key != 'pid'})
        atomic_json(report, result)
        print(json.dumps(result, indent=2), flush=True)
    finally:
        if helper is not None:
            stop_owned_tree(helper)
        if supervisor is not None and supervisor.poll() is None:
            stop_owned_tree(supervisor.pid)
        temporary.cleanup()


def acquire_after_exit(path):
    try:
        with lock(path):
            return True
    except UpdateError:
        return False


if __name__ == '__main__':
    main()
