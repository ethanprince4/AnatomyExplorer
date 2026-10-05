"""Split oversized installers for GitHub; updater packs remain unchanged."""
import argparse
from pathlib import Path

LIMIT = 2_147_483_648
PART = 1_000_000_000


def prepare(folder, tag):
    import re
    if not re.fullmatch(r'v[0-9A-Za-z.+-]+', tag):
        raise ValueError('Invalid release tag')
    base = f'https://github.com/ethanprince4/AnatomyExplorer/releases/download/{tag}'
    notes = ['# Installer downloads', '', 'Existing users: use the in-app updater normally.', '',
             'New installations: download the Windows .ps1 or Mac .command helper below and run it. '
             'It downloads and joins the installer parts in its own folder, then opens the installer. '
             'Windows: right-click the .ps1 and choose Run with PowerShell. '
             'Mac: run bash followed by the downloaded .command file in Terminal.', '']
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in ('.exe', '.dmg') or path.stat().st_size < LIMIT:
            continue
        parts = []
        with path.open('rb') as source:
            number = 1
            while True:
                data = source.read(PART)
                if not data:
                    break
                name = f'{path.name}.part{number:03d}'
                (folder / name).write_bytes(data)
                parts.append(name)
                number += 1
        if path.suffix.lower() == '.exe':
            script = ["$ErrorActionPreference='Stop'", 'Set-Location -LiteralPath $PSScriptRoot']
            for name in parts:
                script.append(f"Invoke-WebRequest -Uri '{base}/{name}' -OutFile '{name}'")
            script += [f"$out=[IO.File]::Create((Join-Path $PSScriptRoot '{path.name}'))", 'try {']
            for name in parts:
                script.append(f"  $src=[IO.File]::OpenRead((Join-Path $PSScriptRoot '{name}')); try {{$src.CopyTo($out)}} finally {{$src.Dispose()}}")
            script += ['} finally {$out.Dispose()}', f"Start-Process -FilePath (Join-Path $PSScriptRoot '{path.name}')"]
            helper = 'Download-Windows-Installer.ps1'
        else:
            script = ['#!/bin/bash', 'set -euo pipefail', 'cd "$(dirname "$0")"']
            for name in parts:
                script.append(f'curl --fail --location --retry 3 "{base}/{name}" --output "{name}"')
            script += ['cat ' + ' '.join(f'"{n}"' for n in parts) + f' > "{path.name}.assembling"',
                       f'mv "{path.name}.assembling" "{path.name}"', f'open "{path.name}"']
            helper = 'Download-Mac-Installer.command'
        (folder / helper).write_text('\n'.join(script) + '\n', encoding='utf-8')
        notes.append(f'- {helper}: reconstructs {path.name} from {len(parts)} parts.')
        path.unlink()  # Only the disposable publish staging copy; build artifacts are retained.
    (folder / 'INSTALL-DOWNLOADS.md').write_text('\n'.join(notes) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('tag')
    args = parser.parse_args()
    prepare(args.folder, args.tag)
