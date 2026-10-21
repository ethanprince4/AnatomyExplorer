# Cloudflare-only fresh installers

These small helpers install the exact validated 4.0.12 frozen application using
the existing immutable 4.0.11 installer seed fragments on
`https://downloads.layeredhuman.com`. They download a pinned overlay from
`releases/v4.0.12/installers/cf-only-1/`, verify the complete final file inventory,
then open the Cloudflare updater. Neither helper has a GitHub fallback. No
PyInstaller run, model generation, or full installer rebuild is needed.

`cloudflare_installer/seed-v4.0.11.json` preserves the original part SHA-256,
sizes and deployed fragment layout. Its source is the verified website
download-hosting release plan for source commit
`3e814b9ddebbcea58e33d7541f6b02b8f890fd42`. The original helper interfaces and
transport were adapted from that MIT-licensed project; see the repository
LICENSE. Only the standalone helper files in this directory are used; the
older full-installer build templates remain available for deliberate rebuilds.

The builder verifies every source and candidate file against the supplied
complete manifests. Both versions must have identical file/symlink paths, with
the seed at 4.0.11 and final stable snapshot at 4.0.12. It includes every changed
regular file, including Mac signature resources and re-signed native binaries.
Overlay paths, sizes and hashes are fixed at build time. ZIP metadata uses fixed
timestamps so repeated builds reproduce the overlay bytes. Helper EXE/DMG build
timestamps may differ; publish only one reviewed native build at the immutable
prefix, and retain its SHA-256 receipt.

On Windows, the helper rejects existing installations by checking the stable
uninstall registration in both hives/views and the destination path. It runs the
verified Inno seed with `/CURRENTUSER /VERYSILENT /NORESTART /SUPPRESSMSGBOXES` and
an explicit fresh destination under `%LOCALAPPDATA%\Programs\Layered Human`.
The seed's `skipifsilent` flag prevents its app launch. Both executable aliases
are held during the overlay operation and restored only after verification.
The original Inno shortcut/uninstall mechanisms remain. Uninstaller files and
the root license copies are recognized as installer-generated extras; all
frozen application files and both manifest aliases are hashed. Notes,
preferences and external model-library paths are never read or modified.

Download cancellation can resume. An interrupted or failed installation can
leave a disabled, registered copy; uninstall that incomplete copy through
Windows Settings > Apps, then use File Explorer to delete the remaining
incomplete application folder before running the helper again. Held executable
files have temporary names and are outside the original uninstaller's log.
The helper deliberately
does not repair or overwrite an arbitrary existing installation. Study data
remains outside the application folder and is retained by the original
uninstaller.

On Mac, the helper copies the seed into a private Applications staging folder,
verifies it, applies the overlay, checks every file's size/hash/mode and every
symlink, rejects unlisted inventory entries, and runs
`codesign --verify --deep --strict`. It promotes the new bundle only after all
checks pass and refuses to replace an existing app. The signed helper applet
opens the final bundle after the shell script reports success. Manifest aliases
travel in the overlay's metadata directory for provenance; they are not copied
into the sealed app or shared Applications directory. The original Mac app
inventory protocol does not require sidecars there.

## Native builds

Run this in the isolated source tree on the matching native platform, supplying
the exact previously validated seed/candidate trees and complete public
manifests:

```text
python packaging/cloudflare_installers.py windows-x64 --base BASE --candidate CANDIDATE --previous-manifest OLD-MANIFEST --manifest FINAL-MANIFEST --out OUTPUT
python3 packaging/cloudflare_installers.py macos-arm64 --base BASE.app --candidate CANDIDATE.app --previous-manifest OLD-MANIFEST --manifest FINAL-MANIFEST --out OUTPUT
```

Outputs include the overlay ZIP, native helper, generated inputs and
`<platform>-helper-build.json`. Only the small helper and its platform overlay
are published. Source/candidate trees, complete update packs, test stages and
receipts are not installer downloads. Mac tools are `osacompile`, `codesign`,
`ditto` and `hdiutil`. Windows uses the installed .NET Framework C# compiler.

## Safe checks

```text
python -m unittest tests.test_cloudflare_installers -v
python packaging/check_cloudflare_installer.py --helper HELPER.exe --overlay OVERLAY.zip --base VERIFIED-BASE --work NEW-SHORT-TEST-FOLDER
```

The Windows check copies a seed into a new private folder and invokes the
compiled helper's production overlay engine. It then runs the frozen runtime
check, and verifies that original seed files and an external user-data sentinel
are unchanged. It never invokes Inno or touches uninstall registration. The
fixture tests exercise corrupted overlays and seed bytes, unexpected inventory,
interrupted replacement, held launchers and preservation of external data.

For the equivalent Mac check, copy the seed with `ditto` to a new scratch
`Layered Human.app`, then run:

```text
/bin/bash OUTPUT/mac-inputs/install.sh check-staged NEW-CHECK-FOLDER STAGED.app OUTPUT/LayeredHuman-Mac-4.0.12-overlay.zip
codesign --verify --deep --strict STAGED.app
hdiutil verify OUTPUT/Install-Layered-Human-Mac.dmg
```

Also test the original R2 seed disk image and the production shell install flow
into a fresh scratch destination, rather than relying only on a reconstructed
feed tree. The shell `install WORK DEST no` path does not launch the application;
the applet owns that final action. Opening a helper GUI or installing/registering
on Windows is a separate acceptance check and should use a disposable Windows
installation, never an existing user's registered AppId.
