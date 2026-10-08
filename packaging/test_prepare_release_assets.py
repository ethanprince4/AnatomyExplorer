"""Release installer helpers: split parts, Windows helper, and the Mac install.sh run with stub hdiutil/ditto."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_release_assets as prep

TAG = 'v4.0.1'
DMG = 'AnatomyExplorer-macOS-AppleSilicon.dmg'
BUNDLE = 'Anatomy Explorer.app'

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
        (folder / 'AnatomyExplorer-Setup-Windows.exe').write_bytes(b'abcdefghijkl')
        prep.prepare(folder, TAG)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ['AnatomyExplorer-Setup-Windows.exe.part001', 'AnatomyExplorer-Setup-Windows.exe.part002',
                          'AnatomyExplorer-Setup-Windows.exe.part003', 'Download-Windows-Installer.ps1',
                          'INSTALL-DOWNLOADS.md'])
        self.assertEqual((folder / 'AnatomyExplorer-Setup-Windows.exe.part003').read_bytes(), b'ijkl')
        ps1 = (folder / 'Download-Windows-Installer.ps1').read_text(encoding='utf-8')
        self.assertIn(f"https://github.com/ethanprince4/AnatomyExplorer/releases/download/{TAG}/"
                      "AnatomyExplorer-Setup-Windows.exe.part003", ps1)
        notes = (folder / 'INSTALL-DOWNLOADS.md').read_text(encoding='utf-8')
        self.assertIn('Download-Windows-Installer.ps1', notes)
        self.assertNotIn('.command', notes)

    def test_each_build_writes_its_own_notes_and_publishing_joins_them(self):
        folder = self.tmp / 'assets'
        folder.mkdir()
        (folder / 'AnatomyExplorer-Setup-Windows.exe').write_bytes(b'abcdefghijkl')
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
        self.assertIn('- Download-Windows-Installer.ps1 (Windows)', notes)
        self.assertIn(f'- {prep.MAC_INSTALLER} (Mac', notes)
        prep.combine_notes(folder)          # nothing left to join: the notes stay as they are
        self.assertEqual((folder / 'INSTALL-DOWNLOADS.md').read_text(encoding='utf-8'), notes)

    def test_mac_split_builds_the_installer_app_on_macos_only(self):
        folder = self.tmp / 'assets'
        folder.mkdir()
        (folder / DMG).write_bytes(b'0123456789ABCDEF')
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
        self.assertEqual(prep.mac_app_name('v4.0.1'), 'Anatomy Explorer')
        self.assertEqual(prep.mac_app_name('v4.1.0-preview.2'), 'Anatomy Explorer Experimental')

    def test_generated_install_script_is_valid_bash(self):
        script = prep.mac_installer_script(f'file:///x/{TAG}', DMG, BUNDLE, 12,
                                           [(f'{DMG}.part001', 'a' * 64), (f'{DMG}.part002', 'b' * 64)])
        path = self.tmp / 'install.sh'
        path.write_text(script, encoding='utf-8')
        result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"'{DMG}.part002 {'b' * 64}'", script)

    def test_applescript_template_has_every_value(self):
        source = prep.fill('Installer.applescript.in', {'@NAME@': 'Anatomy Explorer', '@VERSION@': TAG})
        self.assertIn('property appName : "Anatomy Explorer"', source)
        self.assertIn('path to resource "install.sh"', source)
        self.assertNotIn('@', source)
        # A variable named after an AppleScript property compiles but fails when it runs (set kind: -10006).
        self.assertNotRegex(source, r'(?m)^\s*(set|copy) (kind|name|class|id|contents|version|properties|text) to\b')

    def test_unsafe_part_names_are_refused(self):
        with self.assertRaises(ValueError):
            prep.mac_installer_script('file:///x', DMG, BUNDLE, 1, [('a b.part001', 'c' * 64)])


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
        script = prep.mac_installer_script(self.server.as_uri(), DMG, BUNDLE, total, pairs)
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


if __name__ == '__main__':
    unittest.main()
