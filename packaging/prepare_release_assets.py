"""Split oversized installers for GitHub; updater packs remain unchanged.

Each release build job runs this on its own installer (the Mac installer app needs macOS), writing its part of the
install notes to INSTALL-DOWNLOADS-<platform>.md; the publishing job joins those with --combine-notes."""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LIMIT = 2_147_483_648
PART = 1_000_000_000
REPO = 'https://github.com/ethanprince4/AnatomyExplorer/releases/download'
HERE = Path(__file__).resolve().parent
MAC_APP = 'Install Anatomy Explorer.app'
MAC_INSTALLER = 'Install-Anatomy-Explorer-Mac.dmg'
WINDOWS_HELPER = 'Download-Windows-Installer.ps1'


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
    return 'Anatomy Explorer Experimental' if '-preview.' in tag else 'Anatomy Explorer'


def fill(template_name, values):
    text = (HERE / 'mac_installer' / template_name).read_text(encoding='utf-8')
    for key, value in values.items():
        text = text.replace(key, value)
    leftover = re.search(r'@[A-Z]+@', text)
    if leftover:
        raise ValueError(f'{template_name}: no value for {leftover.group(0)}')
    return text


def mac_installer_script(base, dmg_name, bundle, total, parts):
    """install.sh for the applet. parts is [(file name, sha256)] in join order."""
    for name, _ in parts:
        if not re.fullmatch(r'[A-Za-z0-9._-]+', name):
            raise ValueError(f'Unsafe part name: {name}')
    lines = [f"  '{name} {digest}'" for name, digest in parts]
    return fill('install.sh.in', {'@BASE@': base, '@DMG@': dmg_name, '@BUNDLE@': bundle,
                                  '@TOTAL@': str(total), '@PARTS@': '\n'.join(lines)})


def build_mac_installer(folder, tag, dmg_name, total, parts):
    """Create folder/Install-Anatomy-Explorer-Mac.dmg: a disk image holding an ad-hoc signed AppleScript applet that
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
        script.write_text(mac_installer_script(f'{REPO}/{tag}', dmg_name, name + '.app', total, parts), encoding='utf-8')
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


NOTES = 'INSTALL-DOWNLOADS.md'
NOTES_HEADER = ['# Installer downloads', '', 'Existing users: use the in-app updater normally.', '',
                'New installations: installers larger than GitHub\'s file limit are split into parts. Use the helper '
                'below. It downloads and checks the parts in its own folder, joins them and then starts the installer.',
                '']


def prepare(folder, tag, notes_name=NOTES):
    if not re.fullmatch(r'v[0-9A-Za-z.+-]+', tag):
        raise ValueError('Invalid release tag')
    base = f'{REPO}/{tag}'
    notes = list(NOTES_HEADER)
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in ('.exe', '.dmg') or path.stat().st_size < LIMIT:
            continue
        total = path.stat().st_size
        parts = split(path, folder)
        if path.suffix.lower() == '.exe':
            script = ["$ErrorActionPreference='Stop'", 'Set-Location -LiteralPath $PSScriptRoot']
            for name in parts:
                script.append(f"Invoke-WebRequest -Uri '{base}/{name}' -OutFile '{name}'")
            script += [f"$out=[IO.File]::Create((Join-Path $PSScriptRoot '{path.name}'))", 'try {']
            for name in parts:
                script.append(f"  $src=[IO.File]::OpenRead((Join-Path $PSScriptRoot '{name}')); try {{$src.CopyTo($out)}} finally {{$src.Dispose()}}")
            script += ['} finally {$out.Dispose()}', f"Start-Process -FilePath (Join-Path $PSScriptRoot '{path.name}')"]
            helper = WINDOWS_HELPER
            (folder / helper).write_text('\n'.join(script) + '\n', encoding='utf-8')
            notes.append(f'- {helper} (Windows): reconstructs {path.name} from {len(parts)} parts. Right-click it and '
                         'choose Run with PowerShell.')
        else:
            build_mac_installer(folder, tag, path.name, total, [(name, sha256(folder / name)) for name in parts])
            notes.append(f'- {MAC_INSTALLER} (Mac, Apple silicon): reconstructs {path.name} from {len(parts)} parts. '
                         f'Open it and double-click "{MAC_APP[:-4]}" in the window that appears. It downloads about {total / 1e9:.1f} GB, checks '
                         f'each part, copies the app into Applications and opens it. It needs about '
                         f'{(2 * total + 2 ** 30) / 1e9:.0f} GB of free disk space while it runs; if it stops, run it '
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
