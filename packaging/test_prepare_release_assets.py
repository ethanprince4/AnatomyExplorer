"""Release installer helpers: split parts, the Windows installer program (built and run against a local server on
Windows), and the Mac install.sh run with stub hdiutil/ditto."""
import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_release_assets as prep

TAG = 'v4.0.1'
DMG = 'LayeredHuman-macOS-AppleSilicon.dmg'
BUNDLE = 'Layered Human.app'

# Stands in for hdiutil on Linux: attach copies the fixture app into -mountpoint and records the joined image.
FAKE_HDIUTIL = '''#!/bin/sh
if [ "$1" = attach ]; then
  while [ $# -gt 0 ]; do
    if [ "$1" = -mountpoint ]; then mp="$2"; fi
    dmg="$1"
    shift
  done
  mkdir -p "$mp"
  cp -R "$FAKE_APP" "$mp/"
  cat "$dmg" > "$mp/$(basename "$FAKE_APP")/Contents/Resources/joined.bin"
fi
exit 0
'''
# Stands in for ditto on Linux (only the directory copy used by install.sh).
FAKE_DITTO = '#!/bin/sh\nexec cp -R "$1" "$2"\n'


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (prep.LIMIT, prep.PART)
        prep.LIMIT, prep.PART = 10, 4  # same code path as 2 GiB and 1 GB, at test size

    def tearDown(self):
        prep.LIMIT, prep.PART = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_windows_installer_is_split_and_described(self):
        folder = self.tmp / 'assets'
        folder.mkdir()
        (folder / 'LayeredHuman-Setup-Windows.exe').write_bytes(b'abcdefghijkl')
        if sys.platform != 'win32':
            with self.assertRaises(SystemExit):
                prep.prepare(folder, TAG)
            self.assertTrue((folder / 'LayeredHuman-Setup-Windows.exe.part001').exists())
            return
        prep.prepare(folder, TAG)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted(['LayeredHuman-Setup-Windows.exe.part001', 'LayeredHuman-Setup-Windows.exe.part002',
                          'LayeredHuman-Setup-Windows.exe.part003', 'INSTALL-DOWNLOADS.md',
                          'Install-Layered-Human-Windows.exe']))
        self.assertEqual((folder / 'LayeredHuman-Setup-Windows.exe.part003').read_bytes(), b'ijkl')
        self.assertEqual((folder / prep.WINDOWS_HELPER).read_bytes()[:2], b'MZ')
        notes = (folder / 'INSTALL-DOWNLOADS.md').read_text(encoding='utf-8')
        self.assertIn(f'- {prep.WINDOWS_HELPER} (Windows)', notes)
        self.assertNotIn('PowerShell', notes)

    def test_windows_installer_source_lists_every_part_in_order(self):
        source = prep.windows_installer_source(
            f'{prep.REPO}/{TAG}', TAG, 'Setup.exe', [('Setup.exe.part001', 4, 'a' * 64), ('Setup.exe.part002', 2, 'b' * 64)])
        self.assertIn(f'public const string Base = "https://github.com/ethanprince4/AnatomyExplorer/releases/download/{TAG}";',
                      source)
        self.assertLess(source.index(f'new Part("Setup.exe.part001", 4L, "{"a" * 64}"),'),
                        source.index(f'new Part("Setup.exe.part002", 2L, "{"b" * 64}"),'))
        self.assertIn('public const string AppName = "Layered Human";', source)
        self.assertIn('public const string Version = "4.0.1";', source)
        self.assertIn('[assembly: AssemblyVersion("4.0.1.0")]', source)
        preview = prep.windows_installer_source('https://x.test', 'v4.1.0-preview.2', 'Setup.exe', [])
        self.assertIn('"Layered Human Experimental"', preview)
        self.assertIn('[assembly: AssemblyVersion("4.1.0.0")]', preview)
        for name, digest in [('a"b.part001', 'a' * 64), ('Setup.exe.part001', 'not a digest')]:
            with self.assertRaises(ValueError):
                prep.windows_installer_source('https://x.test', TAG, 'Setup.exe', [(name, 1, digest)])

    def test_each_build_writes_its_own_notes_and_publishing_joins_them(self):
        folder = self.tmp / 'assets'
        folder.mkdir()
        (folder / 'LayeredHuman-Setup-Windows.exe').write_bytes(b'abcdefghijkl')
        with mock.patch.object(prep, 'build_windows_installer'):  # compiled only on Windows; the notes are the same
            prep.prepare(folder, TAG, 'INSTALL-DOWNLOADS-Windows.md')
        (folder / 'INSTALL-DOWNLOADS-macOS.md').write_text(
            '\n'.join(prep.NOTES_HEADER + [f'- {prep.MAC_INSTALLER} (Mac, Apple silicon): reconstructs it.']) + '\n',
            encoding='utf-8')
        prep.combine_notes(folder)
        names = sorted(p.name for p in folder.iterdir())
        self.assertIn('INSTALL-DOWNLOADS.md', names)
        self.assertFalse([n for n in names if n.startswith('INSTALL-DOWNLOADS-')])
        notes = (folder / 'INSTALL-DOWNLOADS.md').read_text(encoding='utf-8')
        self.assertEqual(notes.count('# Installer downloads'), 1)
        self.assertIn(f'- {prep.WINDOWS_HELPER} (Windows)', notes)
        self.assertIn(f'- {prep.MAC_INSTALLER} (Mac', notes)
        prep.combine_notes(folder)          # nothing left to join: the notes stay as they are
        self.assertEqual((folder / 'INSTALL-DOWNLOADS.md').read_text(encoding='utf-8'), notes)

    def test_mac_split_builds_the_installer_app_on_macos_only(self):
        folder = self.tmp / 'assets'
        folder.mkdir()
        (folder / DMG).write_bytes(b'0123456789ABCDEF')
        (folder / 'LayeredHuman-macOS-update.json').write_text(json.dumps(
            {'schema': 1, 'platform': 'macos-arm64', 'files': [{'size': 1024}]}))
        if sys.platform != 'darwin':
            with self.assertRaises(SystemExit):
                prep.prepare(folder, TAG)
            self.assertTrue((folder / f'{DMG}.part001').exists())
            return
        # The real osacompile, codesign and hdiutil, as the publishing job runs them.
        prep.prepare(folder, TAG)
        self.assertFalse((folder / DMG).exists())
        image = folder / prep.MAC_INSTALLER
        self.assertTrue(image.is_file())
        mount = self.tmp / 'mounted'
        mount.mkdir()
        subprocess.run(['hdiutil', 'attach', '-nobrowse', '-readonly', '-mountpoint', str(mount), str(image)], check=True)
        try:
            # Opening the image shows exactly one thing: the installer.
            self.assertEqual(sorted(p.name for p in mount.iterdir() if not p.name.startswith('.')), [prep.MAC_APP])
            applet = mount / prep.MAC_APP
            script = applet / 'Contents/Resources/install.sh'
            self.assertTrue(os.access(script, os.X_OK))
            self.assertTrue((applet / 'Contents/Resources/Scripts/main.scpt').is_file())
            subprocess.run(['codesign', '--verify', '--deep', '--strict', str(applet)], check=True)
            subprocess.run(['/bin/bash', '-n', str(script)], check=True)
            self.assertIn(f'{DMG}.part004', script.read_text(encoding='utf-8'))
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=False)
        self.assertIn(prep.MAC_INSTALLER, (folder / 'INSTALL-DOWNLOADS.md').read_text(encoding='utf-8'))

    def test_front_page_links_name_the_files_a_release_publishes(self):
        # The README links use releases/latest/download/<file>, so they follow each release by themselves; they break
        # only if a published file is renamed without them.
        readme = (Path(__file__).resolve().parent.parent / 'README.md').read_text(encoding='utf-8')
        linked = set(re.findall(r'releases/latest/download/([^)\s]+)\)', readme))
        self.assertEqual(linked, {prep.MAC_INSTALLER, prep.WINDOWS_HELPER})

    def test_installer_app_names_follow_the_channel(self):
        self.assertEqual(prep.mac_app_name('v4.0.1'), 'Layered Human')
        self.assertEqual(prep.mac_app_name('v4.1.0-preview.2'), 'Layered Human Experimental')

    def test_generated_install_script_is_valid_bash(self):
        script = prep.mac_installer_script(f'file:///x/{TAG}', DMG, BUNDLE, 12,
                                           [(f'{DMG}.part001', 'a' * 64), (f'{DMG}.part002', 'b' * 64)],
                                           bundle_bytes=1024)
        path = self.tmp / 'install.sh'
        path.write_text(script, encoding='utf-8')
        result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"'{DMG}.part002 {'b' * 64}'", script)

    def test_applescript_template_has_every_value(self):
        source = prep.fill('Installer.applescript.in', {'@NAME@': 'Layered Human', '@VERSION@': TAG})
        self.assertIn('property appName : "Layered Human"', source)
        self.assertIn('path to resource "install.sh"', source)
        self.assertNotIn('@', source)
        # A variable named after an AppleScript property compiles but fails when it runs (set kind: -10006).
        self.assertNotRegex(source, r'(?m)^\s*(set|copy) (kind|name|class|id|contents|version|properties|text) to\b')

    def test_unsafe_part_names_are_refused(self):
        with self.assertRaises(ValueError):
            prep.mac_installer_script('file:///x', DMG, BUNDLE, 1, [('a b.part001', 'c' * 64)], bundle_bytes=1024)

    def test_mac_helper_uses_actual_uncompressed_bundle_size_and_updates_install_notes(self):
        folder = self.tmp / 'assets'
        folder.mkdir()
        (folder / DMG).write_bytes(b'0123456789ABCDEF')
        uncompressed = 9_000_000_000
        (folder / 'LayeredHuman-macOS-update.json').write_text(json.dumps(
            {'schema': 1, 'platform': 'macos-arm64', 'files': [{'size': uncompressed - 20}, {'size': 20}]}))
        self.assertEqual(prep.mac_bundle_bytes(folder), uncompressed)
        script = prep.mac_installer_script(f'{prep.REPO}/{TAG}', DMG, BUNDLE, 3_000_000_000,
                                           [(f'{DMG}.part001', 'a' * 64)], bundle_bytes=uncompressed)
        self.assertIn('BUNDLE_BYTES=9000000000', script)
        self.assertIn('TOTAL * 2 + BUNDLE_BYTES + 1073741824', script)
        self.assertIn('df -Pk "$dest"', script)
        self.assertEqual(prep.mac_required_bytes(3_000_000_000, uncompressed), 16_073_741_824)
        with mock.patch.object(prep, 'build_mac_installer') as build:
            prep.prepare(folder, TAG)
        self.assertEqual(build.call_args.kwargs['bundle_bytes'], uncompressed)
        self.assertIn('11 GB of free disk space', (folder / prep.NOTES).read_text())

    def test_mac_helper_rejects_missing_or_invalid_bundle_size_metadata(self):
        with self.assertRaisesRegex(ValueError, 'manifest beside'):
            prep.mac_bundle_bytes(self.tmp)
        (self.tmp / 'LayeredHuman-macOS-update.json').write_text(json.dumps(
            {'schema': 1, 'platform': 'macos-arm64', 'files': [{'size': -1}]}))
        with self.assertRaisesRegex(ValueError, 'valid bundle-size'):
            prep.mac_bundle_bytes(self.tmp)

    def test_mac_helper_refuses_tight_disk_before_downloading_a_large_uncompressed_app(self):
        script = self.tmp / 'install.sh'
        text = prep.mac_installer_script('https://example.invalid', DMG, BUNDLE, 3_000_000_000,
                                        [(f'{DMG}.part001', 'a' * 64)], bundle_bytes=9_000_000_000)
        # Functions avoid host-specific PATH rules for stub executables.
        fixture = "df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted\\nfixture 20000000 0 15000000 0%% /\\n'; }\ncurl() { : > \"$DOWNLOAD_MARKER\"; return 1; }\n"
        script.write_text(text.replace('set -euo pipefail\n', 'set -euo pipefail\n' + fixture), encoding='utf-8')
        work = self.tmp / 'work'
        work.mkdir()
        # 15.36 GB available: enough for the former 2*DMG+1 GiB estimate, but
        # insufficient for the real 9 GB extracted app plus retained downloads.
        marker = self.tmp / 'download-started'
        env = dict(os.environ, DOWNLOAD_MARKER=marker.as_posix())
        git_bash = Path(r'C:\Program Files\Git\bin\bash.exe')
        if sys.platform == 'win32' and git_bash.is_file():
            env['PATH'] = str(git_bash.parents[1] / 'usr/bin') + os.pathsep + env['PATH']
        bash = str(git_bash) if sys.platform == 'win32' and git_bash.is_file() else 'bash'
        result = subprocess.run([bash, script.as_posix(), 'install', work.as_posix(),
                                 (self.tmp / 'Applications').as_posix(), 'no'], env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('Not enough free disk space. Free about 17 GB', (work / 'status').read_text())
        self.assertFalse(marker.exists())


class MacInstallScriptTests(unittest.TestCase):
    """Runs the real install.sh on Linux against a file:// release and stub hdiutil/ditto."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.server = self.tmp / 'server'
        self.server.mkdir()
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        for name, body in [('hdiutil', FAKE_HDIUTIL), ('ditto', FAKE_DITTO)]:
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.fixture = self.tmp / 'fixture' / BUNDLE
        (self.fixture / 'Contents/Resources').mkdir(parents=True)
        (self.fixture / 'Contents/Resources/version.txt').write_text('4.0.1')
        self.parts = {'part001': b'AAAA', 'part002': b'BBBB', 'part003': b'CC'}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_release(self, served=None, sums=None):
        """Put the parts on the fake server and build install.sh for them. Returns the script path."""
        pairs = []
        for suffix, body in self.parts.items():
            name = f'{DMG}.{suffix}'
            (self.server / name).write_bytes(served.get(suffix, body) if served else body)
            digest = (sums or {}).get(suffix) or hashlib.sha256(body).hexdigest()
            pairs.append((name, digest))
        total = sum(len(b) for b in self.parts.values())
        script = prep.mac_installer_script(self.server.as_uri(), DMG, BUNDLE, total, pairs,
                                           bundle_bytes=sum(path.stat().st_size for path in self.fixture.rglob('*') if path.is_file()))
        path = self.tmp / 'install.sh'
        path.write_text(script, encoding='utf-8')
        path.chmod(0o755)
        return path

    def run_install(self, script, dest, replace='no'):
        work = self.tmp / 'work'
        work.mkdir(exist_ok=True)
        env = dict(os.environ, PATH=f'{self.bin}{os.pathsep}{os.environ["PATH"]}', FAKE_APP=str(self.fixture))
        result = subprocess.run(['/bin/bash', str(script), 'install', str(work), str(dest), replace],
                                env=env, capture_output=True, text=True)
        status = (work / 'status').read_text(encoding='utf-8').strip() if (work / 'status').exists() else ''
        return result.returncode, status, work

    def test_downloads_checks_joins_and_installs(self):
        script = self.write_release()
        dest = self.tmp / 'Applications'
        code, status, work = self.run_install(script, dest)
        self.assertEqual(code, 0, status)
        self.assertEqual(status, f'done|100|{BUNDLE} is installed in {dest}')
        installed = dest / BUNDLE / 'Contents/Resources'
        self.assertEqual((installed / 'joined.bin').read_bytes(), b'AAAABBBBCC')
        self.assertFalse(list(work.glob('*.part*')))
        self.assertFalse((work / f'{DMG}').exists())

    def test_checksum_mismatch_stops_before_installing(self):
        script = self.write_release(served={'part002': b'XXXX'}, sums={'part002': hashlib.sha256(b'BBBB').hexdigest()})
        dest = self.tmp / 'Applications'
        code, status, _ = self.run_install(script, dest)
        self.assertEqual(code, 1)
        self.assertTrue(status.startswith('failed|0|Part 2 of 3 did not pass its checksum'), status)
        self.assertFalse((dest / BUNDLE).exists())

    def test_missing_part_is_reported(self):
        script = self.write_release()
        (self.server / f'{DMG}.part003').unlink()
        dest = self.tmp / 'Applications'
        code, status, _ = self.run_install(script, dest)
        self.assertEqual(code, 1)
        self.assertTrue(status.startswith('failed|0|Part 3 of 3 could not be downloaded'), status)

    def test_existing_copy_is_kept_unless_replacement_was_confirmed(self):
        script = self.write_release()
        dest = self.tmp / 'Applications'
        (dest / BUNDLE / 'Contents').mkdir(parents=True)
        (dest / BUNDLE / 'Contents/old.txt').write_text('old')
        code, status, _ = self.run_install(script, dest, replace='no')
        self.assertEqual(code, 1)
        self.assertIn(f'{BUNDLE} is already in {dest}', status)
        self.assertTrue((dest / BUNDLE / 'Contents/old.txt').exists())
        code, status, _ = self.run_install(script, dest, replace='yes')
        self.assertEqual(code, 0, status)
        self.assertFalse((dest / BUNDLE / 'Contents/old.txt').exists())
        self.assertTrue((dest / BUNDLE / 'Contents/Resources/joined.bin').exists())

    def test_insufficient_disk_space_is_refused_before_downloading(self):
        script = self.write_release()
        text = re.sub(r'^TOTAL=\d+$', f'TOTAL={10 ** 15}', script.read_text(encoding='utf-8'), flags=re.M)
        script.write_text(text, encoding='utf-8')
        code, status, _ = self.run_install(script, self.tmp / 'Applications')
        self.assertEqual(code, 1)
        self.assertTrue(status.startswith('failed|0|Not enough free disk space'), status)


# Stands in for the Inno Setup installer: notes that it ran and exits with the code the test asks for.
FAKE_SETUP = '''class FakeSetup
{
    static int Main()
    {
        System.IO.File.WriteAllText(System.Environment.GetEnvironmentVariable("FAKE_SETUP_MARK"), "ran");
        return int.Parse(System.Environment.GetEnvironmentVariable("FAKE_SETUP_EXIT"));
    }
}
'''


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the fake release and honours 'Range: bytes=N-' as GitHub's download servers do; logs every request."""

    def __init__(self, log, *args, **kwargs):
        self.log = log
        super().__init__(*args, **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = Path(self.translate_path(self.path))
        self.log.append((self.path.rsplit('/', 1)[-1], self.headers.get('Range')))
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        wanted = re.fullmatch(r'bytes=(\d+)-', self.headers.get('Range') or '')
        start = int(wanted.group(1)) if wanted else 0
        self.send_response(206 if wanted else 200)
        if wanted:
            self.send_header('Content-Range', f'bytes {start}-{len(data) - 1}/{len(data)}')
        self.send_header('Content-Length', str(len(data) - start))
        self.end_headers()
        self.wfile.write(data[start:])


@unittest.skipUnless(sys.platform == 'win32' and prep.CSC.is_file(), 'builds and runs the Windows installer program')
class WindowsInstallerProgramTests(unittest.TestCase):
    """Builds the real Install-Layered-Human-Windows.exe and runs it against a local server and a fake installer."""

    SETUP = 'LayeredHuman-Setup-Windows.exe'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (prep.LIMIT, prep.PART, prep.REPO)
        served = self.tmp / 'server'
        self.release = served / TAG
        self.release.mkdir(parents=True)
        source = self.tmp / 'FakeSetup.cs'
        source.write_text(FAKE_SETUP, encoding='utf-8')
        setup = self.release / self.SETUP
        subprocess.run([str(prep.CSC), '/nologo', '/target:winexe', f'/out:{setup}', str(source)],
                       check=True, capture_output=True)
        self.setup = setup.read_bytes()
        prep.LIMIT, prep.PART = 10, len(self.setup) // 3 + 1  # three parts, like the real 3 GB installer
        self.requests = []
        self.server = http.server.ThreadingHTTPServer(
            ('127.0.0.1', 0), functools.partial(RangeHandler, self.requests, directory=str(served)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        prep.REPO = f'http://127.0.0.1:{self.server.server_address[1]}'
        prep.prepare(self.release, TAG)
        self.work = self.tmp / 'work'
        self.download = self.work / TAG.removeprefix('v') / self.SETUP
        self.mark = self.tmp / 'setup-ran.txt'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        prep.LIMIT, prep.PART, prep.REPO = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_program(self, setup_exit=0):
        status = self.tmp / 'status.txt'
        env = dict(os.environ, FAKE_SETUP_MARK=str(self.mark), FAKE_SETUP_EXIT=str(setup_exit))
        result = subprocess.run([str(self.release / prep.WINDOWS_HELPER), '--work', str(self.work), '--status',
                                 str(status)], env=env, timeout=120)
        return result.returncode, status.read_text(encoding='utf-8') if status.exists() else ''

    def test_downloads_checks_opens_the_installer_and_deletes_the_download(self):
        self.assertEqual(self.run_program(), (0, 'installed'))
        self.assertTrue(self.mark.exists())
        self.assertFalse(self.work.exists())
        self.assertEqual([name for name, _ in self.requests],
                         [f'{self.SETUP}.part001', f'{self.SETUP}.part002', f'{self.SETUP}.part003'])

    def test_carries_on_from_where_an_earlier_download_stopped(self):
        half = prep.PART + prep.PART // 2  # part 1 and half of part 2
        self.download.parent.mkdir(parents=True)
        self.download.write_bytes(self.setup[:half])
        older = self.work / '4.0.0'
        older.mkdir()
        (older / self.SETUP).write_bytes(b'left over from an older version')
        self.assertEqual(self.run_program(), (0, 'installed'))
        self.assertEqual(self.requests, [(f'{self.SETUP}.part002', f'bytes={prep.PART // 2}-'),
                                         (f'{self.SETUP}.part003', None)])
        self.assertFalse(self.work.exists())

    def test_a_damaged_part_is_fetched_again_then_refused_before_the_installer_opens(self):
        part = self.release / f'{self.SETUP}.part002'
        part.write_bytes(b'X' * part.stat().st_size)
        code, status = self.run_program()
        self.assertEqual(code, 1)
        self.assertTrue(status.startswith('failed|Part 2 of 3 arrived damaged twice.'), status)
        self.assertFalse(self.mark.exists())
        self.assertEqual([name for name, _ in self.requests].count(f'{self.SETUP}.part002'), 2)

    def test_installer_closed_early_keeps_the_download_for_another_go(self):
        self.assertEqual(self.run_program(setup_exit=2), (2, 'not installed|2'))
        self.assertTrue(self.mark.exists())
        self.assertEqual(self.download.read_bytes(), self.setup)

    def test_missing_release_says_so(self):
        (self.release / f'{self.SETUP}.part001').unlink()
        code, status = self.run_program()
        self.assertEqual(code, 1)
        self.assertIn('no longer on GitHub', status)


if __name__ == '__main__':
    unittest.main()
