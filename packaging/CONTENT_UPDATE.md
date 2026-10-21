# Content snapshots after the updater bridge

`build_content_update.py` creates a complete incremental snapshot from a verified
native bundle and the previous authenticated manifest/catalog. It performs no
network requests, installer build, application activation, or publication. The
initial content release advances `4.0.12` to `4.0.13` for the refined tongue,
thumbnail, model guide and relevant lessons.

## Explicit content map

Map paths are relative to the repository/source transfer. `target` and `remove`
paths are relative to bundled resources: `_internal` on Windows and
`Contents/Resources` on Mac. The same reviewed map therefore supports both.

```json
{
  "schema": 1,
  "files": [
    {
      "source": "data/content/lessons_digestive_upper.json",
      "target": "data/content/lessons_digestive_upper.json",
      "sha256": "the exact 64-character lowercase SHA-256",
      "size": 12345
    }
  ],
  "remove": ["data/local_model_library/models/tongue_papillae/v4/model.npz"]
}
```

Every source requires an exact size/hash and must remain inside `--source-root`.
Targets are restricted to content formats under `data/`, `models/`,
`app/resources/`, and `app/ui/resources/`. Runtime code, native executables,
libraries and frameworks cannot be replaced or removed. A native executable
header disguised with a content extension is rejected too.

Removals must name individual existing entries in the prior managed inventory.
For a map authored against repository history, first filter its explicitly named
removals against the authenticated prior manifest, and record requested paths
that were never shipped. Do not add any inferred removals. The tongue map's
`v4/recipe.json` was absent from both published `4.0.12` inventories; its other
three obsolete files were present.

## Authentication and snapshot boundaries

Supply the previous manifest's expected SHA-256 and its pack catalog's expected
SHA-256 from the already authenticated published channel. The catalog may be the
Cloudflare platform release catalog, which also binds the manifest size/hash and
release identity, or a trusted logical pack descriptor map. Every referenced
prior pack requires its exact SHA-256 and byte size.

The builder verifies every declared baseline file's bytes and every symlink's
target/containment, plus native Unix modes on Mac. Known installed manifest
sidecars and unlisted live Python bytecode are omitted from the new inventory.
Other unlisted files fail the build. It copies only declared files/symlinks,
applies the explicit additions/replacements/removals, and updates numeric
`VERSION` and stable `UPDATE_CHANNEL.json`. Both launcher aliases remain.

Only unchanged nonexecutable model/data files may share hardlinks with the
baseline. Replacements use new inodes, and runtime/native files are independent
copies. The original bundle and external study data are preserved. The output
directory must be absent and outside the original bundle; failed builds retain
their isolated partial output for inspection.

On Mac, the builder updates both `Info.plist` version fields and uses exactly:

```sh
/usr/bin/codesign --verify --deep --strict "$BASE_APP"
/usr/bin/codesign --force --sign - "$CANDIDATE_APP"
/usr/bin/codesign --verify --deep --strict "$CANDIDATE_APP"
```

It never performs a deep re-sign. Every unchanged nested native file's hash and
mode must remain identical. Only the primary outer executable's signature may
change, and its file-backed Mach-O sections must remain identical. A layout that
cannot pass outer-only signing and strict deep verification stops with evidence;
there is no relaxed-verification or native-binary rewriting fallback.

## Windows use

Run from the parent helper checkout with Python 3.11 or newer. Use the exact
authenticated manifest/catalog paths and hashes recorded by the publication
handoff. For example:

```powershell
.venv/Scripts/python.exe packaging/build_content_update.py `
  packaging/build/cloudflare-bridge/windows-final-v4.0.12/candidate/LayeredHuman `
  packaging/build/content-tongue-v4.0.13/windows `
  --previous-manifest prior-windows-manifest.json `
  --manifest-sha256 a2f78d3f8109ba5ed3d52455489bb3a2efa90d16e5aaddd35adbd58a164b00dd `
  --pack-catalog prior-windows-catalog.json `
  --catalog-sha256 9d353b0dcbf8809ecff0cdccc8c1ddb3d0bc7586ff046e85428a7119c82b5204 `
  --patch-map patch-map.json --source-root C:/path/to/reviewed/tongue/source --version 4.0.13
```

The pinned hashes above are the published `4.0.12` inputs, not values to reuse for
later baselines. Source hashing and inventory checks are numerical packaging
validation; actual native checks remain separate.

## Minimal MacBook transfer and use

Create a ZIP preserving these relative paths:

- `packaging/build_content_update.py`, `packaging/update_payload.py`,
  `packaging/release_storage.py`, `packaging/check_runtime.py`,
  `packaging/check_mac_update.py`; optionally `packaging/check_https.py`.
- `app/__init__.py`, `app/updater.py`, `app/macho_sections.py`, `app/tls.py`.
- All eight exact source files named by the reviewed patch map, retaining their
  repository-relative paths.
- The filtered `patch-map.json`, `prior-mac-manifest.json`,
  `prior-mac-catalog.json`, and a transfer SHA-256 catalog.

This is about 40 MB for the tongue update. No Git database, GitHub access,
installers, complete model library, native runtime SDK, or baseline update packs
are needed in this transfer. The already verified complete `4.0.12` app remains
on the MacBook. Use the authorized SSH/local transfer path; for an established
SSH destination the command shape is:

```sh
scp LayeredHuman-Content-v4.0.13-Mac.zip "$MAC_SSH:~/Downloads/"
```

On the MacBook, use the actual verified baseline bundle path for `BASE_APP`:

```sh
mkdir -p "$HOME/LayeredHuman-Content-v4.0.13"
unzip -n "$HOME/Downloads/LayeredHuman-Content-v4.0.13-Mac.zip" -d "$HOME/LayeredHuman-Content-v4.0.13"
cd "$HOME/LayeredHuman-Content-v4.0.13"
python3 -c 'import hashlib,json,pathlib; r=pathlib.Path("."); checks=json.loads((r/"transfer-sha256.json").read_text()); assert all(hashlib.sha256((r/p).read_bytes()).hexdigest()==h for p,h in checks.items()); print("Transfer verified")'
BASE_APP="$HOME/LayeredHuman-Bridge-Work-v4.0.12/candidate/Layered Human.app"
NEW_WORK="$HOME/LayeredHuman-Content-Work-v4.0.13"
python3 packaging/build_content_update.py "$BASE_APP" "$NEW_WORK" \
  --previous-manifest prior-mac-manifest.json \
  --manifest-sha256 d1a3dd906099c3363b7af61ebe57cb0e667cd64fadc17b84d437a11b2301c0de \
  --pack-catalog prior-mac-catalog.json \
  --catalog-sha256 fda1a4838fc2fa88e75f567ca9eeb6ea38dcc574e4381ef12e97c189f8017da1 \
  --patch-map patch-map.json --source-root . --version 4.0.13
python3 packaging/check_runtime.py "$NEW_WORK/candidate/Layered Human.app/Contents/MacOS/LayeredHuman"
```

Then perform the separately authorized native update/rollback check with the
actual prior bundle:

```sh
python3 packaging/check_mac_update.py "$NEW_WORK/candidate/Layered Human.app" \
  "$NEW_WORK/feed" --base "$BASE_APP" --report "$NEW_WORK/mac-update.json"
```

The local check's pack reader needs any old pack ranges it cannot reuse from the
prior bundle. If necessary, supply `--previous-packs /path/to/verified/old/feed`
when building to materialize the complete feed. Alternatively, hardlink verified
old packs into `feed/` under their logical names; verify each SHA-256 and size
against `known-packs.json` first. Never rewrite old pack bytes. Publication can
reuse remotely hosted immutable old packs without having their bytes locally.

## Output and release handoff

`candidate/<original bundle name>` is the isolated complete native snapshot.
`feed/` contains both complete manifest names and new packs; optional prior pack
materialization adds unchanged packs too. `known-packs.json` authenticates every
pack referenced by the complete feed, including old packs absent locally.
`content-build.json` records authenticated inputs, explicit changed/removed
paths, preserved nested-native count and incremental byte totals.

Return those artifacts plus native results through the established authorized
handoff. Reuse the Cloudflare publisher to stage/verify immutable objects before
moving its stable channel pointer. No GitHub update release or GitHub installer
build is required after the already published `4.0.12` bridge. The content
builder itself does not publish or move a channel pointer.
