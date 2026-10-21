# Cloudflare incremental updates

Git remains the source repository. Cloudflare R2 distributes the complete update
snapshots directly through its custom domain
`https://downloads.layeredhuman.com`. A model or app change needs a new numeric
patch snapshot; it does not need another installer. The original installation,
managed activation/rollback, and external notes, progress, settings, caches, and
user model library retain their existing behavior.

Version tags do not trigger the full-installer GitHub Actions workflow. That
workflow retains its checks and can be dispatched manually when a new installer
is needed. Ordinary app/model snapshot releases use the native packaging and
publication steps below.

`packaging/cloudflare_updates.py` stages and publishes existing protocol-1 feeds.
It does not build or sign an application, change source models, create a release
tag, install dependencies, configure Cloudflare, or obtain credentials.

## Object contract

The only mutable update object is `updates/channels/{channel}.json`, served with
`Cache-Control: no-store`. A populated channel has this shape; both platforms
must identify the same channel, numeric version, and exact release tag:

```json
{"schema":1,"channel":"stable","release_tag":"v4.0.12","version":"4.0.12","platforms":{"windows-x64":{"sha256":"<catalog SHA-256>","size":1234},"macos-arm64":{"sha256":"<catalog SHA-256>","size":1234}}}
```

An explicitly empty channel is exactly:

```json
{"schema":1,"channel":"experimental","platforms":{}}
```

The catalog is
`updates/releases/{release_tag}/{platform}/{catalog_sha256}.json`:

```json
{"schema":1,"channel":"stable","platform":"windows-x64","release_tag":"v4.0.12","version":"4.0.12","manifest":{"sha256":"<manifest SHA-256>","size":1234},"packs":{"AnatomyExplorer-Windows-pack-0000.bin":{"sha256":"<whole pack SHA-256>","size":1234}}}
```

The complete, validated protocol-1 manifest is beside its catalog at
`updates/releases/{release_tag}/{platform}/{manifest_sha256}.json`. Pack bytes
are shared across releases at `updates/packs/{pack_sha256}.bin`. The catalog
maps the protocol's original logical pack names to these content identities.
Neither channel nor catalog supplies arbitrary download URLs.

All staged JSON uses UTF-8, sorted keys, compact separators, and no trailing
newline. Hashes and lengths describe these exact bytes. Immutable objects use
`Cache-Control: public, max-age=31536000, immutable`.

This trusts verified TLS to the fixed Cloudflare origin. The channel pins the
catalog hash, the catalog pins manifest/pack hashes, and the manifest binds
application paths, files, chunks, and pack ranges. It is not a detached digital
signature: control of the distribution account/origin remains a trust boundary.

## Stage and review locally

Put both platform manifests and only the new local packs in one feed directory.
The preferred names are `LayeredHuman-Windows-update.json` and
`LayeredHuman-macOS-update.json`; legacy manifest names are accepted when their
public counterpart is absent. Each manifest must be complete, including reused
files, blobs, and packs, with explicit `channel` and `release_tag` fields. A local
pack is streamed through SHA-256 and its actual length must equal the manifest.

Supply an authenticated prior pack catalog for packs absent from this directory:

```json
{"AnatomyExplorer-Windows-pack-0000.bin":{"sha256":"<64 lowercase hexadecimal characters>","size":1234}}
```

This catalog must come from previously verified distribution metadata, not an
untrusted list of filenames. Every referenced pack needs either its local bytes
or a matching entry here. Unreferenced known packs are harmless and omitted.

For the initial `v4.0.11` seed, use the authenticated baseline manifests and
known packs already prepared by the migration:

```powershell
.venv/Scripts/python.exe packaging/cloudflare_updates.py stage packaging/build/cloudflare-bridge/baseline packaging/build/cloudflare-bridge/cloudflare-baseline --known-packs packaging/build/cloudflare-bridge/baseline/known-packs.json
```

For a later release:

```powershell
.venv/Scripts/python.exe packaging/cloudflare_updates.py stage packaging/build/combined-feed packaging/build/cloudflare-v4.0.12 --known-packs packaging/build/prior-known-packs.json
.venv/Scripts/python.exe packaging/cloudflare_updates.py stage-empty packaging/build/cloudflare-empty-experimental --channel experimental
```

Staging requires no network or account access. Use a separate output directory
outside the feed. It contains an `objects/updates/...` tree and a canonical
`publication-plan.json`. The plan lists `immutable_objects` as
`{key,size,sha256,path}` entries; reused packs have no local `path`. Its final
`channel_object` is the sole mutable publication step. Existing differing staged
files are refused, so use a fresh output directory for a different snapshot.

The native [update bridge](../packaging/UPDATE_BRIDGE.md) preserves the approved
frozen runtime while changing selected updater sources. Combine the Windows and
macOS `publish/` artifacts after both native jobs pass. Those artifacts include
only new packs; provide prior trusted pack descriptors for all reused packs.
The old GitHub client still needs the bridge's complete logical pack set attached
to its GitHub release, as described in that handoff. Later Cloudflare snapshots
can reuse the same R2 objects without reuploading those bytes.

## Publish explicitly

Use the existing website's locally installed Wrangler and authenticated account.
The publisher never reads or prints account tokens, and passes arguments to Node
without invoking a shell. Its Python environment needs the project's `certifi`
dependency so public verification uses the same verified TLS policy as the app.

```powershell
.venv/Scripts/python.exe packaging/cloudflare_updates.py publish packaging/build/cloudflare-bridge/cloudflare-baseline --wrangler C:/Users/Ethan/Desktop/LayeredHuman-Website/node_modules/wrangler/bin/wrangler.js --bucket layeredhuman-downloads
```

Run one publisher at a time. The publisher first revalidates every local hash and
the full channel → catalogs → manifests → packs graph. It then preflights the
public origin with up to four concurrent read-only checks. Existing conflicting immutable objects are refused. Missing
reused packs fail before any upload. Only missing local objects are uploaded,
using Wrangler's `r2 object put --remote`, explicit content type, and cache
headers. There is no automatic package installation or local-storage fallback.

Every referenced pack must answer HEAD with its exact byte length and an exact
`bytes=0-0` request with HTTP 206 and the matching `Content-Range`. Every JSON
object and every pack up to 1 MiB is downloaded and SHA-256 checked. Every local
new pack is also fully downloaded and hashed after upload, or before skipping
an existing copy. Existing large reused packs rely on their earlier authenticated
whole-file verification; public ETags are not assumed to be SHA-256 values.
Add `--full-pack-verification` to redownload and hash those packs too.

Only after all immutable objects verify does the publisher upload the channel.
It reads the channel back, verifies its exact SHA-256 and byte length, and
requires `Cache-Control: no-store`. An upload or verification failure before this
step leaves the existing channel in place. A failed pointer readback is reported
as a failure even if the R2 write itself completed. Keep the last known good
stage available to recover from that case. Wrangler uploads do not provide an
atomic compare-and-create across competing publishers, hence the single-publisher
requirement.

Wrangler flags were checked against the existing website's installed Wrangler
4.151.3 and the [Cloudflare R2 command reference](https://developers.cloudflare.com/workers/wrangler/commands/r2/).

## Future model patches and rollback

1. Edit the intended source/model files in Git and prepare the real frozen
   application snapshot for each platform. Assign a new numeric patch version
   and matching release tag. Preserve approved model content outside the change.
2. Generate complete protocol-1 manifests from the actual frozen bytes with
   `packaging/update_payload.py`, reusing the authenticated previous manifest.
   New/changed chunks append new immutable packs; unchanged chunks keep their
   previous logical pack references. macOS packing follows final signing.
3. Combine both platform feeds and stage with trusted known descriptors for
   reused packs. Run the applicable native reconstruction, activation, signature,
   rollback, and user-data-preservation checks before publication.
4. Publish missing packs and immutable JSON first, then the verified channel
   pointer. Keep prior releases and packs available so users can skip versions.
   Commit the source changes and retain the build/verification evidence.

To stop distributing a bad snapshot, publish its earlier saved stage again. The
publisher rechecks its dependencies and moves only the channel when all immutable
objects are already present. This stops new uptake; a numerically newer installed
client does not silently downgrade through an ordinary update check. Its existing
Updates-menu rollback and original-installation fallback remain available. An
empty experimental channel can similarly withdraw a preview. None of these
publication operations writes local application files or external user data.

The local publisher checks are:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_cloudflare_publication -v
```
