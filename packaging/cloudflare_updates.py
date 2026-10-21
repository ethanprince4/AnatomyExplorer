"""Stage and publish immutable protocol-1 feeds to the fixed Cloudflare origin.

Staging is entirely local. Publication uses an existing authenticated Wrangler
installation, verifies public objects, and writes the mutable channel last.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import (CHANNELS, CHUNK_SIZE, CLOUDFLARE_ORIGIN, HASH_RE,
                         MAX_CATALOG, MAX_CHANNEL, MAX_MANIFEST, PACK_RE,
                         PACK_SIZE, CloudflareRedirect, UpdateError, file_sha, manifest_names,
                         release_version, sha, validate_manifest)

PLATFORMS = ("windows-x64", "macos-arm64")
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
CHANNEL_CACHE = "no-store"
SMALL_OBJECT = 1024 * 1024
PLAN_NAME = "publication-plan.json"


class PublicationError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def read_json(path, maximum=MAX_MANIFEST):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise PublicationError(f"Missing, unsafe or oversized JSON: {path.name}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PublicationError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_bytes(), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PublicationError(f"Invalid JSON: {path.name}") from exc


def descriptor(value, maximum=PACK_SIZE + CHUNK_SIZE):
    if (not isinstance(value, dict) or set(value) != {"sha256", "size"} or
            not isinstance(value["sha256"], str) or not HASH_RE.fullmatch(value["sha256"]) or
            type(value["size"]) is not int or not 0 < value["size"] <= maximum):
        raise PublicationError("Invalid SHA-256/size descriptor")
    return dict(value)


def known_packs(value):
    data = {} if value is None else (value if isinstance(value, dict) else read_json(value))
    if not isinstance(data, dict):
        raise PublicationError("Known packs must be an object")
    result = {}
    for name, item in data.items():
        if not isinstance(name, str) or not PACK_RE.fullmatch(name):
            raise PublicationError("Invalid known pack name")
        result[name] = descriptor(item)
    return result


def checked_manifest(data, platform):
    try:
        validate_manifest(data)
        if (type(data.get("schema")) is not int or type(data.get("launcher")) is not int or
                data["platform"] != platform or "channel" not in data or "release_tag" not in data or
                release_version(data["release_tag"], data["channel"]) != data["version"]):
            raise PublicationError("Manifest platform, channel, release tag or version differs")
    except (UpdateError, TypeError, KeyError) as exc:
        raise PublicationError("Invalid complete protocol-1 manifest") from exc
    return data


def _write_once(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise PublicationError(f"Unsafe staged object: {path.name}")
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            raise PublicationError(f"Refusing to replace staged object: {path.name}")
    else:
        with path.open("xb") as output:
            output.write(raw)


def _object(output, key, raw=None, source=None, expected=None):
    item = {"key": key, **(expected or {"sha256": sha(raw), "size": len(raw)})}
    if raw is not None or source is not None:
        relative = "objects/" + key
        path = output / relative
        if raw is not None:
            _write_once(path, raw)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or (path.exists() and (
                    not path.is_file() or path.stat().st_size != item["size"] or
                    file_sha(path) != item["sha256"])):
                raise PublicationError(f"Refusing to replace staged pack: {path.name}")
            if not path.exists():
                with Path(source).open("rb") as incoming, path.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, CHUNK_SIZE)
            if path.stat().st_size != item["size"] or file_sha(path) != item["sha256"]:
                raise PublicationError("Pack changed while staging")
        item["path"] = relative
    return item


def stage_feed(feed, output, known=None):
    """Create a reviewable object tree from both complete platform manifests."""
    feed, output = Path(feed).resolve(strict=True), Path(output).resolve()
    if not feed.is_dir() or feed == output or feed in output.parents:
        raise PublicationError("Use a separate staging directory outside the feed")
    known = known_packs(known)
    manifests, identity = {}, None
    for platform in PLATFORMS:
        candidates = [feed / name for name in manifest_names(platform)]
        path = next((path for path in candidates if path.exists()), None)
        if path is None:
            raise PublicationError(f"Missing complete manifest for {platform}")
        data = checked_manifest(read_json(path), platform)
        current = {key: data[key] for key in ("channel", "release_tag", "version")}
        if identity is not None and current != identity:
            raise PublicationError("Both platform manifests must have the same channel, release tag and version")
        identity = current
        manifests[platform] = data
    objects, packs = {}, {}
    # Validate every pack before creating the stage or its channel pointer.
    for data in manifests.values():
        for name, size in data["packs"].items():
            path = feed / name
            if path.is_symlink():
                raise PublicationError(f"Unsafe local pack: {name}")
            if path.exists():
                if not path.is_file() or path.stat().st_size != size:
                    raise PublicationError(f"Local pack size differs from manifest: {name}")
                item = {"sha256": file_sha(path), "size": size}
                if name in known and known[name] != item:
                    raise PublicationError(f"Local pack differs from known pack: {name}")
                source = path
            else:
                item, source = known.get(name), None
                if item is None:
                    raise PublicationError(f"Missing local or known pack: {name}")
                if item["size"] != size:
                    raise PublicationError(f"Known pack size differs from manifest: {name}")
            if name in packs and packs[name][0] != item:
                raise PublicationError(f"Inconsistent pack across platforms: {name}")
            packs[name] = (item, source)
    for item, source in packs.values():
        key = f"updates/packs/{item['sha256']}.bin"
        existing = objects.get(key)
        if existing is not None and existing["size"] != item["size"]:
            raise PublicationError("One pack hash has inconsistent sizes")
        if existing is None or source is not None:
            objects[key] = _object(output, key, source=source, expected=item)
    channel = {"schema": 1, **identity, "platforms": {}}
    for platform, data in manifests.items():
        prefix = f"updates/releases/{identity['release_tag']}/{platform}/"
        raw = canonical_json(data)
        if len(raw) > MAX_MANIFEST:
            raise PublicationError("Canonical manifest is too large")
        manifest = _object(output, prefix + sha(raw) + ".json", raw=raw)
        objects[manifest["key"]] = manifest
        catalog = {"schema": 1, **identity, "platform": platform,
                   "manifest": {key: manifest[key] for key in ("sha256", "size")},
                   "packs": {name: packs[name][0] for name in data["packs"]}}
        raw = canonical_json(catalog)
        if len(raw) > MAX_CATALOG:
            raise PublicationError("Release catalog is too large")
        item = _object(output, prefix + sha(raw) + ".json", raw=raw)
        objects[item["key"]] = item
        channel["platforms"][platform] = {key: item[key] for key in ("sha256", "size")}
    pointer = _object(output, f"updates/channels/{identity['channel']}.json", raw=canonical_json(channel))
    plan = {"schema": 1, "origin": CLOUDFLARE_ORIGIN, **identity,
            "immutable_objects": [objects[key] for key in sorted(objects)], "channel_object": pointer}
    _write_once(output / PLAN_NAME, canonical_json(plan))
    validate_stage(output)
    return plan


def stage_empty(output, channel):
    if channel not in CHANNELS:
        raise PublicationError("Unsupported channel")
    output = Path(output).resolve()
    raw = canonical_json({"schema": 1, "channel": channel, "platforms": {}})
    pointer = _object(output, f"updates/channels/{channel}.json", raw=raw)
    plan = {"schema": 1, "origin": CLOUDFLARE_ORIGIN, "channel": channel,
            "immutable_objects": [], "channel_object": pointer}
    _write_once(output / PLAN_NAME, canonical_json(plan))
    validate_stage(output)
    return plan


def local_path(root, item):
    relative = item.get("path")
    if relative != "objects/" + item["key"]:
        raise PublicationError("Staged path differs from object key")
    path = root / relative
    if (path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(root) is False or
            any(parent.is_symlink() for parent in path.parents if parent != root)):
        raise PublicationError("Missing or unsafe staged object")
    if path.stat().st_size != item["size"] or file_sha(path) != item["sha256"]:
        raise PublicationError(f"Staged object hash or size differs: {item['key']}")
    return path


def validate_stage(stage):
    """Rebuild the dependency graph; a modified plan cannot omit required packs."""
    root = Path(stage).resolve(strict=True)
    plan = read_json(root / PLAN_NAME)
    base = {"schema", "origin", "channel", "immutable_objects", "channel_object"}
    if (not isinstance(plan, dict) or set(plan) not in (base, base | {"version", "release_tag"}) or
            type(plan.get("schema")) is not int or plan["schema"] != 1 or
            plan.get("origin") != CLOUDFLARE_ORIGIN or plan.get("channel") not in CHANNELS or
            not isinstance(plan.get("immutable_objects"), list)):
        raise PublicationError("Invalid publication plan")
    items = plan["immutable_objects"] + [plan["channel_object"]]
    objects = {}
    for item in items:
        if not isinstance(item, dict) or set(item) not in (
                {"key", "sha256", "size"}, {"key", "sha256", "size", "path"}):
            raise PublicationError("Invalid publication object")
        descriptor({key: item[key] for key in ("sha256", "size")}, max(MAX_MANIFEST, PACK_SIZE + CHUNK_SIZE))
        key = item["key"]
        if not isinstance(key, str) or key in objects:
            raise PublicationError("Duplicate or invalid publication key")
        if "path" in item:
            local_path(root, item)
        objects[key] = item
    pointer = plan["channel_object"]
    if pointer["key"] != f"updates/channels/{plan['channel']}.json" or pointer["size"] > MAX_CHANNEL:
        raise PublicationError("Invalid channel object")
    channel = read_json(local_path(root, pointer), MAX_CHANNEL)
    if (not isinstance(channel, dict) or type(channel.get("schema")) is not int or
            channel["schema"] != 1 or channel.get("channel") != plan["channel"] or
            not isinstance(channel.get("platforms"), dict)):
        raise PublicationError("Invalid channel pointer")
    expected = {pointer["key"]}
    if not channel["platforms"]:
        if set(channel) != {"schema", "channel", "platforms"} or set(plan) != base:
            raise PublicationError("Invalid empty channel pointer")
    else:
        identity = {key: plan.get(key) for key in ("channel", "release_tag", "version")}
        if (set(channel) != {"schema", *identity, "platforms"} or
                any(channel[key] != value for key, value in identity.items()) or
                release_version(identity["release_tag"], identity["channel"]) != identity["version"] or
                set(channel["platforms"]) != set(PLATFORMS)):
            raise PublicationError("Channel must describe both matching platform releases")
        for platform in PLATFORMS:
            catalog_ref = descriptor(channel["platforms"][platform], MAX_CATALOG)
            prefix = f"updates/releases/{identity['release_tag']}/{platform}/"
            key = prefix + catalog_ref["sha256"] + ".json"
            expected.add(key)
            catalog = _dependency_json(root, objects, key, catalog_ref, MAX_CATALOG)
            if (not isinstance(catalog, dict) or set(catalog) != {
                    "schema", *identity, "platform", "manifest", "packs"} or
                    type(catalog.get("schema")) is not int or catalog["schema"] != 1 or
                    catalog["platform"] != platform or
                    any(catalog[k] != v for k, v in identity.items()) or
                    not isinstance(catalog["packs"], dict)):
                raise PublicationError("Catalog identity differs from channel")
            manifest_ref = descriptor(catalog["manifest"], MAX_MANIFEST)
            key = prefix + manifest_ref["sha256"] + ".json"
            expected.add(key)
            manifest = checked_manifest(_dependency_json(root, objects, key, manifest_ref, MAX_MANIFEST), platform)
            if (any(manifest[k] != v for k, v in identity.items()) or
                    manifest["packs"] != {name: item["size"] for name, item in catalog["packs"].items()}):
                raise PublicationError("Manifest differs from catalog")
            for name, item in catalog["packs"].items():
                if not isinstance(name, str) or not PACK_RE.fullmatch(name):
                    raise PublicationError("Invalid catalog pack name")
                item = descriptor(item)
                key = f"updates/packs/{item['sha256']}.bin"
                expected.add(key)
                if key not in objects or any(objects[key][k] != v for k, v in item.items()):
                    raise PublicationError("Pack missing from publication plan or inconsistent")
    if set(objects) != expected:
        raise PublicationError("Publication plan has missing or unexpected objects")
    return plan


def _dependency_json(root, objects, key, expected, maximum):
    item = objects.get(key)
    if item is None or any(item[k] != value for k, value in expected.items()):
        raise PublicationError("Required metadata missing from publication plan")
    return read_json(local_path(root, item), maximum)


class PublicObjects:
    """Verify the real public origin without trusting ETags as SHA-256 hashes."""
    def __init__(self):
        from app.tls import https_context
        self.opener = urllib.request.build_opener(
            CloudflareRedirect(), urllib.request.HTTPSHandler(context=https_context()))

    def _open(self, item, method="GET", headers=None, missing=False):
        url = CLOUDFLARE_ORIGIN + "/" + item["key"]
        request = urllib.request.Request(url, method=method, headers={
            "Accept-Encoding": "identity", "User-Agent": "LayeredHuman-Publisher/1",
            "Cache-Control": "no-cache", **(headers or {})})
        try:
            response = self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing:
                return None
            raise PublicationError(f"Public {method} failed ({exc.code}): {item['key']}") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise PublicationError(f"Public {method} failed: {item['key']}") from exc
        if response.url != url or response.headers.get("Content-Encoding", "identity").lower() != "identity":
            response.close()
            raise PublicationError("Public object redirected or changed its encoding")
        return response

    def probe(self, item, full=False, require_no_store=False):
        response = self._open(item, "HEAD", missing=True)
        if response is None:
            return False
        with response:
            if response.status != 200 or response.headers.get("Content-Length") != str(item["size"]):
                raise PublicationError(f"Existing public object size differs: {item['key']}")
            directives = {value.strip().lower() for value in response.headers.get("Cache-Control", "").split(",")}
            if require_no_store and "no-store" not in directives:
                raise PublicationError("Public channel pointer must have Cache-Control: no-store")
        if item["key"].endswith(".bin"):
            with self._open(item, headers={"Range": "bytes=0-0"}) as response:
                if (response.status != 206 or response.headers.get("Content-Range") != f"bytes 0-0/{item['size']}" or
                        response.headers.get("Content-Length") != "1" or len(response.read(2)) != 1):
                    raise PublicationError(f"Public pack does not support exact ranges: {item['key']}")
        if full or item["key"].endswith(".json") or item["size"] <= SMALL_OBJECT:
            digest, size = hashlib.sha256(), 0
            with self._open(item) as response:
                if response.status != 200:
                    raise PublicationError("Unexpected public object response status")
                while True:
                    block = response.read(min(CHUNK_SIZE, item["size"] - size + 1))
                    if not block:
                        break
                    size += len(block)
                    if size > item["size"]:
                        raise PublicationError(f"Public object exceeds expected size: {item['key']}")
                    digest.update(block)
            if size != item["size"] or digest.hexdigest() != item["sha256"]:
                raise PublicationError(f"Existing public object hash differs; refusing overwrite: {item['key']}")
        return True


class WranglerUploader:
    def __init__(self, wrangler, bucket="layeredhuman-downloads"):
        self.wrangler = Path(wrangler).resolve(strict=True)
        if not self.wrangler.is_file() or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", bucket):
            raise PublicationError("Invalid existing Wrangler path or R2 bucket")
        self.bucket = bucket

    def put(self, item, path, cache_control):
        content_type = "application/json" if item["key"].endswith(".json") else "application/octet-stream"
        command = ["node", str(self.wrangler), "r2", "object", "put",
                   self.bucket + "/" + item["key"], "--remote", "--file", str(path),
                   "--content-type", content_type, "--cache-control", cache_control]
        result = subprocess.run(command, cwd=path.parent, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=1800,
                                env={**os.environ, "WRANGLER_SEND_METRICS": "false",
                                     "WRANGLER_WRITE_LOGS": "false"})
        if result.returncode:
            # Wrangler output can include account details; do not echo credentials or environment.
            raise PublicationError(f"Wrangler upload failed (exit {result.returncode}): {item['key']}")


def publish_stage(stage, uploader, remote=None, full_pack_verification=False):
    """Refuse missing/conflicting dependencies; publish and verify channel last."""
    root = Path(stage).resolve(strict=True)
    plan = validate_stage(root)
    remote = remote or PublicObjects()
    pending = []
    def probe(item):
        return remote.probe(item, full=full_pack_verification or "path" in item)
    # Read-only independent probes can overlap; uploads remain ordered and wait
    # until every preflight check has completed successfully.
    with ThreadPoolExecutor(max_workers=4) as pool:
        existing = list(pool.map(probe, plan["immutable_objects"]))
    for item, exists in zip(plan["immutable_objects"], existing):
        if not exists:
            if "path" not in item:
                raise PublicationError(f"Reused pack is not public: {item['key']}")
            pending.append(item)
    for item in pending:
        uploader.put(item, local_path(root, item), IMMUTABLE_CACHE)
        if not remote.probe(item, full=True):
            raise PublicationError(f"Uploaded object is not publicly available: {item['key']}")
        print("Verified " + item["key"], flush=True)
    pointer = plan["channel_object"]
    uploader.put(pointer, local_path(root, pointer), CHANNEL_CACHE)
    if not remote.probe(pointer, full=True, require_no_store=True):
        raise PublicationError("Published channel pointer is not publicly available")
    print("Published and verified " + pointer["key"], flush=True)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage", help="Locally stage both platform feeds and a publication plan")
    stage.add_argument("feed", type=Path)
    stage.add_argument("output", type=Path)
    stage.add_argument("--known-packs", type=Path, help="Trusted JSON logical pack names -> {sha256,size}")
    empty = commands.add_parser("stage-empty", help="Locally stage an explicitly empty channel")
    empty.add_argument("output", type=Path)
    empty.add_argument("--channel", required=True, choices=sorted(CHANNELS))
    publish = commands.add_parser("publish", help="Upload missing objects and publish channel last")
    publish.add_argument("stage", type=Path)
    publish.add_argument("--wrangler", type=Path, required=True, help="Existing node_modules/wrangler/bin/wrangler.js")
    publish.add_argument("--bucket", default="layeredhuman-downloads")
    publish.add_argument("--full-pack-verification", action="store_true", help="Also download/hash all reused large packs")
    args = parser.parse_args(argv)
    try:
        if args.command == "stage":
            plan = stage_feed(args.feed, args.output, args.known_packs)
        elif args.command == "stage-empty":
            plan = stage_empty(args.output, args.channel)
        else:
            publish_stage(args.stage, WranglerUploader(args.wrangler, args.bucket),
                          full_pack_verification=args.full_pack_verification)
            return 0
        print(f"Staged {len(plan['immutable_objects'])} immutable objects; channel last: {plan['channel_object']['key']}")
        return 0
    except (PublicationError, UpdateError, OSError, ValueError) as exc:
        parser.exit(1, f"Publication refused: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
