"""Split oversized installers for GitHub; updater packs remain unchanged.

Each release build job runs this on its own installer (the Mac installer app needs macOS, the Windows installer program
needs Windows), writing its part of the install notes to INSTALL-DOWNLOADS-<platform>.md; the publishing job joins those
with --combine-notes."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LIMIT = 2_147_483_648
PART = 1_000_000_000
REPO = 'https://github.com/ethanprince4/AnatomyExplorer/releases/download'
PAGE = 'https://github.com/ethanprince4/AnatomyExplorer/releases/latest'
HERE = Path(__file__).resolve().parent
MAC_APP = 'Install Layered Human.app'
MAC_INSTALLER = 'Install-Layered-Human-Mac.dmg'
WINDOWS_HELPER = 'Install-Layered-Human-Windows.exe'
# The .NET Framework C# compiler that comes with Windows (and the windows-latest runners): no SDK to install.
CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'


def run(*cmd):
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def split(path, folder):
    """Write path.partNNN files into folder and return their names in order."""
    names = []
    with path.open('rb') as source:
        number = 1
        while True:
            data = source.read(PART)
            if not data:
                break
            name = f'{path.name}.part{number:03d}'
            (folder / name).write_bytes(data)
            names.append(name)
            number += 1
    return names


def mac_app_name(tag):
    """The app name build.py gives the bundle (the experimental channel is the '-preview.' tags)."""
    return 'Layered Human Experimental' if '-preview.' in tag else 'Layered Human'


def fill(template_name, values, folder='mac_installer'):
    text = (HERE / folder / template_name).read_text(encoding='utf-8')
    for key, value in values.items():
        text = text.replace(key, value)
    leftover = re.search(r'@[A-Z]+@', text)
    if leftover:
        raise ValueError(f'{template_name}: no value for {leftover.group(0)}')
    return text


def mac_bundle_bytes(folder):
    """Actual installed bytes from the feed next to the DMG, including aliases."""
    for name in ('LayeredHuman-macOS-update.json', 'AnatomyExplorer-macOS-update.json'):
        path = Path(folder) / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        files = data.get('files')
        if (data.get('schema') != 1 or data.get('platform') != 'macos-arm64' or
                not isinstance(files, list) or not files or
                any(not isinstance(entry, dict) or type(entry.get('size')) is not int or entry['size'] < 0
                    for entry in files)):
            raise ValueError('Mac download helper requires a valid bundle-size manifest')
        total = sum(entry['size'] for entry in files)
        if not 0 < total <= 20 * 1024**3:
            raise ValueError('Invalid Mac bundle size')
        return total
    raise ValueError('Mac download helper requires the update manifest beside its DMG')


def mac_required_bytes(total, bundle_bytes):
    if type(total) is not int or total <= 0 or type(bundle_bytes) is not int or bundle_bytes <= 0:
        raise ValueError('Mac installer sizes must be positive byte counts')
    return total * 2 + bundle_bytes + 1024**3


def mac_installer_script(base, dmg_name, bundle, total, parts, *, bundle_bytes):
    """install.sh for the applet. parts is [(file name, sha256)] in join order."""
    for name, _ in parts:
        if not re.fullmatch(r'[A-Za-z0-9._-]+', name):
            raise ValueError(f'Unsafe part name: {name}')
    lines = [f"  '{name} {digest}'" for name, digest in parts]
    mac_required_bytes(total, bundle_bytes)
    return fill('install.sh.in', {'@BASE@': base, '@DMG@': dmg_name, '@BUNDLE@': bundle,
                                  '@TOTAL@': str(total), '@BUNDLEBYTES@': str(bundle_bytes), '@PARTS@': '\n'.join(lines)})


def build_mac_installer(folder, tag, dmg_name, total, parts, *, bundle_bytes):
    """Create folder/Install-Layered-Human-Mac.dmg: a disk image holding an ad-hoc signed AppleScript applet that
    runs install.sh. Opening the image shows the installer in its own Finder window (a zip unpacked silently into
    Downloads, where people had to go and find it)."""
    if sys.platform != 'darwin':
        raise SystemExit('An oversized Mac installer needs macOS to build the installer app (osacompile, codesign, hdiutil)')
    name = mac_app_name(tag)
    work = Path(tempfile.mkdtemp(prefix='ae-installer-'))
    try:
        source = work / 'installer.applescript'
        source.write_text(fill('Installer.applescript.in', {'@NAME@': name, '@VERSION@': tag}), encoding='utf-8')
        applet = work / MAC_APP
        run('osacompile', '-x', '-o', applet, source)
        if not (applet / 'Contents/Resources').is_dir():
            raise SystemExit(f'osacompile did not produce an application bundle at {applet}')
        script = applet / 'Contents/Resources/install.sh'
        script.write_text(mac_installer_script(f'{REPO}/{tag}', dmg_name, name + '.app', total, parts,
                                               bundle_bytes=bundle_bytes), encoding='utf-8')
        script.chmod(0o755)
        # Written after osacompile, so the signature covers the embedded script.
        run('codesign', '--force', '--deep', '--sign', '-', applet)
        run('codesign', '--verify', '--deep', '--strict', applet)
        stage = work / 'image'
        stage.mkdir()
        run('ditto', applet, stage / MAC_APP)
        out = folder / MAC_INSTALLER
        out.unlink(missing_ok=True)
        run('hdiutil', 'create', '-volname', MAC_APP[:-4], '-srcfolder', stage, '-format', 'UDZO', '-ov', out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def windows_installer_source(base, tag, setup, parts):
    """Release.cs for the Windows installer program. parts is [(file name, size, sha256)] in join order."""
    for value in [base, tag, setup] + [name for name, _, _ in parts]:
        if not re.fullmatch(r'[A-Za-z0-9._:/+-]+', value):
            raise ValueError(f'Unsafe value for the Windows installer program: {value}')
    for _, _, digest in parts:
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError(f'Not a SHA-256: {digest}')
    number = re.match(r'v?(\d+)\.(\d+)\.(\d+)', tag)
    entries = [f'        new Part("{name}", {size}L, "{digest}"),' for name, size, digest in parts]
    return fill('Release.cs.in', {'@APP@': mac_app_name(tag), '@VERSION@': tag.removeprefix('v'), '@TAG@': tag,
                                  '@NUMBER@': '.'.join(number.groups()) + '.0' if number else '0.0.0.0',
                                  '@BASE@': base, '@PAGE@': PAGE, '@SETUP@': setup, '@PARTS@': '\n'.join(entries)},
                'windows_installer')


def build_windows_installer(folder, tag, setup, parts):
    """Compile WINDOWS_HELPER into folder: it downloads the parts of `setup`, checks them and opens the installer."""
    source = windows_installer_source(f'{REPO}/{tag}', tag, setup, parts)
    if sys.platform != 'win32' or not CSC.is_file():
        raise SystemExit(f'{WINDOWS_HELPER} is compiled with the C# compiler that comes with Windows ({CSC}); '
                         'prepare the Windows installer on Windows')
    work = Path(tempfile.mkdtemp())
    try:
        release = work / 'Release.cs'
        release.write_text(source, encoding='utf-8')
        out = folder / WINDOWS_HELPER
        out.unlink(missing_ok=True)
        run(CSC, '/nologo', '/target:winexe', '/optimize+', f'/out:{out}',
            f'/win32icon:{HERE.parent / "app" / "resources" / "icon.ico"}',
            f'/win32manifest:{HERE / "windows_installer" / "app.manifest"}',
            '/r:System.dll', '/r:System.Drawing.dll', '/r:System.Windows.Forms.dll',
            HERE / 'windows_installer' / 'Installer.cs', release)
    finally:
        shutil.rmtree(work, ignore_errors=True)


NOTES = 'INSTALL-DOWNLOADS.md'
NOTES_HEADER = ['# Installer downloads', '', 'Existing users: use the in-app updater normally.', '',
                'New installations: installers larger than GitHub\'s file limit are split into parts. Use the helper '
                'below. It downloads and checks the parts in its own folder, joins them and then starts the installer.',
                '']


def prepare(folder, tag, notes_name=NOTES):
    if not re.fullmatch(r'v[0-9A-Za-z.+-]+', tag):
        raise ValueError('Invalid release tag')
    notes = list(NOTES_HEADER)
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in ('.exe', '.dmg') or path.stat().st_size < LIMIT:
            continue
        total = path.stat().st_size
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            from release_storage import require_space
            require_space(folder, total + 256 * 1024**2, 'Installer release-part split')
        parts = split(path, folder)
        if path.suffix.lower() == '.exe':
            build_windows_installer(folder, tag, path.name,
                                    [(name, (folder / name).stat().st_size, sha256(folder / name)) for name in parts])
            notes.append(f'- {WINDOWS_HELPER} (Windows): downloads {path.name} ({total / 1e9:.1f} GB, in {len(parts)} '
                         'parts) with one progress bar, checks every part and opens the installer. Double-click it; if '
                         'the download stops, open it again and it carries on. The first time, Windows may say it '
                         'protected your PC, because the project has no paid code-signing certificate: click More '
                         'info, then Run anyway.')
        else:
            bundle_bytes = mac_bundle_bytes(folder)
            build_mac_installer(folder, tag, path.name, total, [(name, sha256(folder / name)) for name in parts],
                                bundle_bytes=bundle_bytes)
            notes.append(f'- {MAC_INSTALLER} (Mac, Apple silicon): reconstructs {path.name} from {len(parts)} parts. '
                         f'Open it and double-click "{MAC_APP[:-4]}" in the window that appears. It downloads about {total / 1e9:.1f} GB, checks '
                         f'each part, copies the app into Applications and opens it. It needs about '
                         f'{(mac_required_bytes(total, bundle_bytes) + 999_999_999) // 1_000_000_000} GB of free disk space while it runs; if it stops, run it '
                         'again. The first time, macOS may say it cannot be opened, because the project has no paid '
                         'Apple developer certificate: open System Settings > Privacy & Security, scroll down and click '
                         'Open Anyway (on macOS 14 and earlier, right-click it and choose Open also works).')
        path.unlink()  # Only the disposable publish staging copy; build artifacts are retained.
    (folder / notes_name).write_text('\n'.join(notes) + '\n', encoding='utf-8')


def combine_notes(folder):
    """Join the platforms' INSTALL-DOWNLOADS-*.md into one INSTALL-DOWNLOADS.md (their helper lines under one header)."""
    pieces = sorted(folder.glob('INSTALL-DOWNLOADS-*.md'))
    if not pieces:
        return
    lines = [line for piece in pieces for line in piece.read_text(encoding='utf-8').splitlines() if line.startswith('- ')]
    (folder / NOTES).write_text('\n'.join(NOTES_HEADER + lines) + '\n', encoding='utf-8')
    for piece in pieces:
        piece.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('tag', nargs='?')
    parser.add_argument('--notes', default=NOTES, help='file name for the install notes (one per platform when the '
                                                       'build jobs prepare their own installers)')
    parser.add_argument('--combine-notes', action='store_true',
                        help='only join INSTALL-DOWNLOADS-*.md in the folder into INSTALL-DOWNLOADS.md')
    args = parser.parse_args()
    if args.combine_notes:
        combine_notes(args.folder)
    elif not args.tag:
        parser.error('a release tag is required')
    else:
        prepare(args.folder, args.tag, args.notes)
