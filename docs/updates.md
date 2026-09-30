# Desktop updates

Windows and Apple silicon Mac releases starting with 3.1.0 have incremental
updates. Earlier versions require one full updater-enabled installer/DMG. The
Windows installer keeps its AppId and usual install locations; Mac users drag
the new app into Applications once. That original installation stays available
as a fallback. Mac Intel builds are not distributed by this project.

The app checks at most daily and downloads quietly while you study. The Updates
menu lets you disable automatic checks, check manually, or return to the previous
version on the next launch. It never forces a restart during a study session.
Offline checks fail without interrupting the installed app.

## Delivery and trust

`packaging/update_payload.py` inventories the actual frozen package. Each file
has a SHA-256 hash and independent 4 MiB chunks, each gzip-compressed and stored
in approximately 64 MiB release packs. A full feed is published with every
release so people may skip versions. The client reuses verified unchanged files
and same-offset blocks, requests only missing compressed byte ranges, and checks
both chunk and complete-file hashes. It refuses servers that ignore Range;
there is no automatic whole-installer fallback. Inserting bytes may shift many
chunks, and new runtimes, changed models or broad content edits can still be big.

The trust root is HTTPS to the hard-coded repository's GitHub release API. The
API's SHA-256 asset digest authenticates the manifest to that trusted source; the
manifest binds version, platform, protocol, exact file paths, hashes and pack
ranges. Only that repository's exact release URLs and GitHub's HTTPS release
CDN hosts are accepted. No token is stored or sent. Downloads have bounded sizes
and bounded decompression. Paths reject traversal, Windows aliases, duplicate
case-folded names, mutable/personal folders and conflicting directory entries.
This is trusted GitHub-account delivery, not a separate publisher signature:
compromise of the repository/GitHub or local user account remains a trust limit.

The project currently has no Windows certificate or Apple Developer ID and is
not notarized. Existing initial-install confirmation requirements remain. Mac
packs are generated *after* the existing build-time ad-hoc signing. Symlinks,
executable permissions and signed bytes are reconstructed exactly, and the
client requires `codesign --verify --deep --strict` before activation. It does
not re-sign bundles, clear quarantine, change Gatekeeper, or change system policy.
The update manifest is outside the `.app` to preserve its resource seal.

## Activation and recovery

Update versions live under the current user's AnatomyExplorer application-data
folder, in a store keyed to the original installation path. They do not write
Program Files or Applications, need no UAC, and do not touch `user/`, caches,
logs or Qt study/settings data. Unchanged shipped data may be hardlinked on the
same volume; code and runtime files are copied. The updater never writes into a
live version. It reserves conservative disk space for staging and rollback,
including filesystems where links are unavailable.

Partial downloads retain verified chunks/files for retry. A complete verified
stage is renamed to a new immutable version directory before an atomic pending
pointer is written. A stable launcher holds a per-install session lock until
the study process exits. Only a later ordinary launch activates the pending
version. It starts a separate PyInstaller process with a reset bootloader
environment, and keeps the previous version and original installation. If the
new process exits before showing its UI, or a trial is interrupted before the
ready marker, the launcher returns to the previous version. UI readiness is
not proof every feature is correct; the Updates menu also permits manual rollback.
Obsolete completed versions are removed after successful startup; the original,
current, previous and pending versions are retained. Incomplete staging is
retained for resume. Moving an original installation creates a separate store.

## Release checks

`python -m unittest discover -s tests -p test_updater.py -v` exercises first
install/no update/downgrade, file and chunk reuse, interrupted/corrupt downloads,
low disk, permission failure, manifest/path attacks, activation and rollback,
and data preservation. macOS CI additionally signs a real Mach-O fixture,
reconstructs its bundle and checks its signature and symlinks. Picking tests
cover backing/logical pixel mapping and failed driver reads on Windows/macOS;
the bundled `--pick-diagnostics --report <file>` runs actual GPU/input checks.
Windows tests and Mac CI must not be described as physical Mac trackpad testing.

The Release workflow builds both real distribution formats for PR review and
only publishes on a release tag or explicit tagged dispatch. A release must
include both platform manifests and all their packs, as well as the full
installer and DMG. Existing release history remains untouched.
