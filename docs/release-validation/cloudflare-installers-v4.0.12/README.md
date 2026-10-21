# Cloudflare fresh-installer validation: 4.0.12

The small helper and overlay paths passed staged validation on Windows and the
user's physical Apple Silicon Mac. Eight focused tests also passed. No full
installer or PyInstaller build was run, and no GitHub compute was used.

Windows validation did **not** execute Inno or change installer registration.
The original Mac seed disk-image and production network-install run also passed
through direct SSH: all 4,054,495,102 seed bytes came from Cloudflare, the published
overlay hash matched, the complete original and final inventories passed, and
the promoted scratch bundle passed strict signature verification. Real
Applications and the helper UI were untouched. See `mac-network-install.json`.
These validation records are separate from public helper publication.

| Native check | Result and scope |
| --- | --- |
| Windows verified seed → overlay → frozen runtime | Passed. The real approximately 5 GB seed became the exact 4.0.12 application, with Qt 6.11.2, runtime imports and 37 WGSL files available. Original seed files and external user-data sentinel were preserved. |
| Final Windows helper binary | Passed complete inventory verification against the verified final stage. Its only change after the fresh-seed runtime check was recovery guidance. |
| Windows failure cases | The compiled production apply engine rejected corrupt overlay/seed bytes and unlisted files/directories. An OS-denied replacement left both launchers held; mixed partial inventory remained rejected. |
| Native Mac staged path | Passed all file size/hash/mode, symlink and directory inventory checks: 2,428 files, 190 symlinks and 412 directories. Final bundle signature verified. |
| Mac helper DMG and applet | Disk image verified, mounted, applet signature verified, and image detached. This did not launch the helper UI. |
| Mac rejection cases | Corrupt overlay, extra file, extra link, extra empty directory and linked application directory were rejected before overlay extraction or promotion. Outside sentinel and original source trees were preserved. |
| Mac overlay reproducibility | Two independent preparations produced identical 82,497,325-byte ZIPs, including the fixed timestamps and both metadata aliases. |

The Mac run found one portability defect: an unescaped slash inside the
parent-directory `awk` regex character class. The exact native fix is applied
to the authoritative template. Its source hash matches the file used by the
passing native run. A local regression executes the expression extracted from
that template with Git for Windows awk; this is a portability check, not native
Mac execution.

The JSON files preserve the small artifact receipts, native results and source
hashes. `windows-native.json` distinguishes the initial runtime-tested helper
from the final binary check. `mac-native.json` preserves the earlier staged
check; `mac-network-install.json` completes its then-pending original seed and
production network check. `provenance.json` hashes the original local
receipts; large logs, applications, models, disk images and overlays remain
outside this source evidence folder.

See [the build and recovery instructions](../../../packaging/CLOUDFLARE-INSTALLERS.md)
for commands and the remaining disposable-Windows installation acceptance check.
