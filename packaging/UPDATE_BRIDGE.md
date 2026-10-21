# Frozen update bridge

`run_update_bridge.py` builds and checks a complete update feed on the user's
native computer by preserving an existing frozen release. It runs no PyInstaller,
procedural model generation, installer registration, Actions jobs, or release
publication. The initial bridge is `v4.0.11` to
`v4.0.12`, using baseline source commit
`3e814b9ddebbcea58e33d7541f6b02b8f890fd42`.

Mac checks run on the user's Apple silicon MacBook. Windows checks run on the
user's Windows computer. Keep the release tag unused until both native runs pass.
The `Release` workflow is manual-only (`workflow_dispatch`). Version tags do not
start installer builds or Mac checks on GitHub Actions. Use the native bridge
tools for snapshot releases; run the full-installer workflow explicitly only
when a rebuilt installer is needed and its hosted checks are authorized.

## Inputs and preserved content

The builder queries the pinned GitHub release API. Every downloaded manifest
and pack must match the API-provided SHA-256 and exact byte length. It downloads
only the selected platform's packs, reconstructs the complete frozen tree, and
verifies each decompressed chunk and file. A reused `--cache` is rehashed.

Only these default source paths are replaced:

- `app/updater.py`
- `app/ui/updates.py`
- `app/https_check.py`

Each original frozen source must exactly match its file in the pinned source
commit. Unchanged selected sources are skipped. Repeat `--patch app/path.py` to
select a different explicit source list for a future source-only bridge.
Arbitrary model/native-file replacement requires a separately reviewed payload
build; this bridge deliberately verifies that all baseline paths, approved
models, and unselected sources remain present and unchanged.

Windows retains both executable names. macOS updates `VERSION`, channel
metadata, and both `Info.plist` version fields, then signs the final candidate
with `codesign --force --deep --sign -` and verifies its strict deep signature
before producing its feed. Changed native binary sections must remain identical
to the baseline. Candidate copies share only immutable `data/` and `models/`
files with the baseline. Code and binaries have independent copies.

## Minimal MacBook transfer

Create the transfer from the intended patched Windows checkout after its source
changes and HTTPS checker are finalized:

```powershell
python packaging/prepare_bridge_transfer.py packaging/build/LayeredHuman-Bridge-v4.0.12-Mac.zip
```

Transfer this ZIP to the MacBook through the authorized local/SSH path. It
contains selected patched sources, standard-library updater helpers, native
check scripts, Cocoa provenance, and source SHA-256 values exported from the
exact pinned Git commit. It omits `.git`, models, installers, and update packs.
The builder authenticates and downloads Mac baseline packs directly from the
pinned GitHub release on the MacBook.

Use Python 3.11 or newer and at least 21 GB free on the work volume. The work
directory retains about 10 GB of baseline/cache/candidate data; the updater also
enforces its unchanged conservative 10 GB free-space reserve. Use a fresh work
directory. The original installed application is not used.

```sh
mkdir -p "$HOME/LayeredHuman-Bridge-v4.0.12"
unzip -n "$HOME/Downloads/LayeredHuman-Bridge-v4.0.12-Mac.zip" -d "$HOME/LayeredHuman-Bridge-v4.0.12"
cd "$HOME/LayeredHuman-Bridge-v4.0.12"
python3 -c 'import hashlib,json,pathlib; r=pathlib.Path("."); checks=json.loads((r/"transfer-sha256.json").read_text()); assert all(hashlib.sha256((r/p).read_bytes()).hexdigest()==h for p,h in checks.items()); print("Transfer hashes verified")'
python3 -m unittest tests.test_update_bridge
python3 packaging/run_update_bridge.py --work "$HOME/LayeredHuman-Bridge-Work-v4.0.12"
```

Verify the ZIP's SHA-256 against the generator's printed hash before extracting
it. The local runner detects `source-baseline.json`, so the transferred project
needs no Git checkout. Return the work directory's `publish/` and `reports/`
folders after success. A failed run retains logs and a failed
`native-checks.json`; `--checks-only` reruns checks on an already built candidate.
Neither command publishes assets or changes an installed application.

## Individual native commands

Use the user's native Windows computer or Apple silicon MacBook, a fresh work directory, and
the intended patched checkout. The three default source changes must already
be present. Python 3.11 and standard library tools perform the build. The real
Windows update/settings check additionally needs `PySide6==6.11.2`.

```powershell
python packaging/build_update_bridge.py --platform windows-x64 --tag v4.0.12 --work packaging/build/bridge-windows --cache packaging/build/cloudflare-bridge/baseline/packs
python packaging/check_runtime.py packaging/build/bridge-windows/candidate/LayeredHuman/LayeredHuman.exe
python packaging/check_bundle_update.py packaging/build/bridge-windows/base/LayeredHuman packaging/build/bridge-windows/candidate/LayeredHuman packaging/build/bridge-windows/feed
python packaging/check_https.py packaging/build/bridge-windows/candidate/LayeredHuman/LayeredHuman.exe --report packaging/build/bridge-windows/reports/https.json
```

On macOS use `--platform macos-arm64`. The application name is `Layered Human.app`:

```sh
work="$HOME/LayeredHuman-Bridge-Work-v4.0.12"
python packaging/build_update_bridge.py --platform macos-arm64 --work "$work" --source-baseline source-baseline.json
python packaging/check_runtime.py "$work/candidate/Layered Human.app/Contents/MacOS/LayeredHuman"
python packaging/check_cocoa.py "$work/candidate/Layered Human.app/Contents/MacOS/LayeredHuman"
python packaging/check_mac_update.py "$work/candidate/Layered Human.app" "$work/feed" --base "$work/base/Layered Human.app" --report "$work/reports/mac-update.json"
python packaging/check_https.py "$work/candidate/Layered Human.app/Contents/MacOS/LayeredHuman" --report "$work/reports/https.json"
```

The final HTTPS check requires the fixed Cloudflare stable channel to exist.
It may still select the old `v4.0.11` feed during bridge validation; the check
verifies the candidate's actual frozen transport without activating an update.

Both platform checks use the actual historical frozen launcher for activation,
wait for the staged child's healthy UI confirmation, verify the complete stage,
check repeat-update behavior and rollback, and retain synthetic study data and
Qt preferences under a disposable profile. Cocoa and runtime checks use the
preserved native libraries already in the frozen bundle.

The Windows check places its disposable profile in a short system temporary
directory and preflights both candidate/staged native Qt DLL paths before opening
an app window. Nesting that profile under a deep checkout can exceed the Windows
DLL loader's path limit even when all file hashes and direct candidate checks
pass. Launch output and the DLL preflight results remain in the evidence folder;
any timed-out owned supervisor/child process tree is stopped before cleanup.

## Output and publication handoff

`feed/` is the complete local feed, including verified reused packs, for native
checks. `publish/` contains only new packs, both manifest names, and a platform
pack catalog listing every complete-feed pack with its SHA-256, size, and reuse
source. `reports/` records authenticated baseline identities, exact changed
files, byte totals, and native results, including Cocoa evidence.

The build report alone is numerical packaging evidence. Both local native runs and
their final `native-checks.json` must pass before publication. Artifacts do not
publish a release or move a channel pointer. The original Cocoa evidence report
names its limited diagnostics; record execution on the user's actual MacBook
separately from its original CI-oriented report fields.

An old GitHub client requires **every** pack referenced by its complete bridge
manifest to be attached to the bridge GitHub release under its original logical
filename, including unchanged packs from `v4.0.11`. Publishing only the small
new-pack artifacts is insufficient. Reuse sources in `*-pack-catalog.json`
identify the immutable old assets for the separate publisher. Keep the complete
Cloudflare immutable objects/catalogs available before publishing its channel
pointer. Publish the bridge's legacy/public manifests and all GitHub assets
before exposing it to old clients; no installer assets are generated here.
