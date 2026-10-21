# v4.0.11 Cloudflare download helpers

This isolated derivative builds only the small download helpers. It uses the exact original installer part
names, sizes, SHA-256 values and GitHub URLs recorded in `../release-plan.json`. It embeds the immutable
`https://downloads.layeredhuman.com/` fragment URLs at build time. There is no runtime manifest, app rebuild,
payload repackaging, updater change, or modification to the original release.

The original Windows Forms interface, progress reporting, installed-program launch and cleanup remain in
`windows_installer/Installer.cs`. The separate `FragmentDownloader.cs` maps an original-part resume offset
to the corresponding fragment and validates HTTP Content-Length and Content-Range before appending. A
failed mirror connection falls back to GitHub at the current original-part offset. A failed original SHA-256
discards that entire part and downloads it again from GitHub. A server that ignores a GitHub Range request
causes the part to restart. Reads are bounded by the object and part length.

The Mac AppleScript interface is unchanged. Its shell script assembles each original part from the recorded
fragments, verifies its size and original SHA-256, and downloads the original GitHub part if any mirror fetch,
fragment size, or final part hash fails. The existing disk-space checks, image mounting, Applications copy,
replacement handling, cleanup and app launch are retained. The original uncompressed bundle size,
4,934,408,979 bytes, was calculated from the original release's update manifest after verifying that manifest
against its GitHub asset digest. It is used only for the existing space check.

## Build

From the website repository root, on Windows:

```powershell
python download-hosting/installers/build_helpers.py windows
python download-hosting/installers/tests/verify_helpers.py
```

The output is `download-hosting/installers/out/Install-Layered-Human-Windows.exe`. The compiler is the
Windows .NET Framework `csc.exe`; the original icon and application manifest are preserved.

On macOS, with Python 3, `osacompile`, `codesign`, `ditto` and `hdiutil` available:

```bash
python3 download-hosting/installers/build_helpers.py mac --out website-qa/download-hosting/helpers
python3 download-hosting/installers/tests/verify_helpers.py --platform mac --report website-qa/download-hosting/helpers/mac-transport-verification.json
hdiutil verify website-qa/download-hosting/helpers/Install-Layered-Human-Mac.dmg
hdiutil imageinfo website-qa/download-hosting/helpers/Install-Layered-Human-Mac.dmg
```

This compiles the original AppleScript applet, embeds the derived shell script, signs it ad hoc, verifies the
signature, and creates the helper DMG. It does not rebuild the application. `prepare` can replace `windows`
or `mac` to write only the frozen inputs. Both prepared input folders and `build-record.json` are written
inside `--out`. For a portable source handoff, copy this entire `installers` folder and `../release-plan.json`.

## Download verification without installation

Windows provides an explicit mode that creates no window and never starts the reconstructed installer:

```powershell
$helper = (Resolve-Path 'download-hosting/installers/out/Install-Layered-Human-Windows.exe').Path
$work = Join-Path $PWD 'website-qa/download-hosting/windows-helper-check'
$status = Join-Path $PWD 'website-qa/download-hosting/windows-helper-check-status.txt'
$run = Start-Process -WindowStyle Hidden -Wait -PassThru -FilePath $helper -ArgumentList @('--headless-download', '--work', ('"' + $work + '"'), '--status', ('"' + $status + '"'))
$run.ExitCode
Get-Content -LiteralPath $status
```

The reconstructed original installer is `<work>/4.0.11/LayeredHuman-Setup-Windows.exe`. The normal UI and
the existing `--download-only` mode remain available; the latter still opens the download window. Headless
mode uses the same embedded metadata and transport. Exit code 0 plus status `downloaded` means every
original part passed its embedded SHA-256.

Mac download-only verification runs the generated shell script without the applet, mounting, copying, or
launching anything:

```bash
/bin/bash website-qa/download-hosting/helpers/mac-inputs/install.sh download-only "$PWD/website-qa/download-hosting/mac-helper-check"
hdiutil verify website-qa/download-hosting/mac-helper-check/LayeredHuman-macOS-AppleSilicon.dmg
hdiutil imageinfo website-qa/download-hosting/mac-helper-check/LayeredHuman-macOS-AppleSilicon.dmg
```

Successful download-only checks retain the payload for inspection and consume about 3.87 GB on Windows,
or 8.11 GB on Mac (the original parts plus joined DMG). They do not prove a native installation or UI flow.

## Verification and provenance

`tests/verify_helpers.py` compiles a console entry point using the real Windows transport and tiny local
HTTP fixtures. It checks mirror success, resumes before/at/after fragment boundaries, resumed original
parts behind an existing verified prefix, full cached parts, timeouts, early EOF, oversized lengths,
unexpected Content-Range, ignored Range, corrupt mirror and cached bytes, GitHub fallback and rejection
when both sources are corrupt. The Mac download functions run under Git Bash against the same local
server, with a test-only `sha256sum` shim for macOS `shasum` and reduced timeout/retry limits. The
production limits and scripts are unchanged by testing. The report is `out/transport-verification.json`.
The local Windows/Git Bash run passed all 30 cases, including both public download-only entry points.

These checks do not execute the installer UI, copy an application, or establish native Mac acceptance.
Native Mac compilation/signature/image inspection and complete downloads from the published domain
are separate evidence. A successful native installation on each platform remains a release acceptance
check.

`upstream/` retains the original sources and resources exported byte-for-byte using `git show` from
AnatomyExplorer commit `3e814b9ddebbcea58e33d7541f6b02b8f890fd42`, plus the verified original Mac update
manifest and its digest record. `upstream-provenance.json` records the exported source hashes. Original
source repository: https://github.com/ethanprince4/AnatomyExplorer, tag `v4.0.11`.

Copyright (c) 2026 Ethan Prince. The original MIT license and its scope/attribution text are preserved in
`upstream/LICENSE`; the helper derivatives are under the same MIT terms. Generated EXE/DMG helpers
remain unsigned/ad hoc signed as in the original build and do not acquire a paid platform certificate.
