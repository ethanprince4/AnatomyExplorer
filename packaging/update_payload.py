"""Pack actual frozen files as independently compressed 4 MiB content chunks.

On macOS run after signing; manifests stay outside the sealed .app. Clients only
download missing byte ranges from the approximately 64 MiB HTTPS release packs.
"""
import gzip
import hashlib
import json
import os
import shutil
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import (CHUNK_SIZE, MAC_MANIFEST, MANIFEST, PACK_SIZE, atomic_json,
                         MAX_MANIFEST, PACK_RE, PUBLIC_MAC_MANIFEST, PUBLIC_MANIFEST,
                         UpdateError, file_sha, legacy_manifest, manifest_names,
                         safe_path, sha, unpack_chunk, validate_manifest, write_manifests)


def load_manifest(value):
    """Read a complete local manifest whose provenance the caller authenticated.

    Protocol validation checks paths and inventory consistency, not provenance.
    Release automation must first authenticate a downloaded manifest against its
    trusted release asset digest. This module never fetches remote content.
    """
    if isinstance(value, Mapping):
        data = dict(value)
    else:
        path = Path(value)
        if path.stat().st_size > MAX_MANIFEST:
            raise UpdateError("Manifest too large")
        data = json.loads(path.read_text(encoding="utf-8"))
    return validate_manifest(data)


def load_pack_hashes(value):
    """Accept {pack_name: SHA256}, optionally using GitHub's sha256: prefix."""
    if value is None:
        return None
    data = value if isinstance(value, Mapping) else json.loads(Path(value).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("Pack hash catalog must be an object")
    result = {}
    for name, digest in data.items():
        if not isinstance(name, str) or not PACK_RE.fullmatch(name) or not isinstance(digest, str):
            raise ValueError("Invalid pack hash catalog entry")
        digest = digest.removeprefix("sha256:")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid pack SHA-256")
        result[name] = digest
    return result


class LocalPacks:
    """Bounded local pack reads with optional trusted whole-file SHA checks."""

    def __init__(self, manifest, directory, hashes=None):
        self.manifest = manifest
        self.directory = Path(directory).resolve(strict=True)
        if not self.directory.is_dir():
            raise ValueError("Previous packs must be a directory")
        self.hashes = load_pack_hashes(hashes)
        self.checked = set()

    def path(self, name):
        if name not in self.manifest["packs"] or not PACK_RE.fullmatch(name):
            raise UpdateError("Unknown local update pack")
        path = self.directory / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != self.directory:
            raise UpdateError(f"Missing or unsafe local pack: {name}")
        if name not in self.checked:
            if path.stat().st_size != self.manifest["packs"][name]:
                raise UpdateError(f"Local pack size differs: {name}")
            if self.hashes is not None:
                if name not in self.hashes:
                    raise UpdateError(f"Pack SHA-256 missing from catalog: {name}")
                if file_sha(path) != self.hashes[name]:
                    raise UpdateError(f"Local pack SHA-256 differs: {name}")
            self.checked.add(name)
        return path

    def chunk(self, digest):
        blob = self.manifest["blobs"][digest]
        with open(self.path(blob["pack"]), "rb") as source:
            source.seek(blob["offset"])
            compressed = source.read(blob["size"])
        return unpack_chunk(compressed, blob["raw_size"], digest)

    def verify_reuse(self, digest):
        blob = self.manifest["blobs"][digest]
        self.path(blob["pack"])
        # A trusted full-pack digest authenticates its bytes in one streaming
        # pass. Without it, verify each referenced gzip member before reuse.
        if self.hashes is None:
            self.chunk(digest)

    def materialize(self, name, output):
        source, destination = self.path(name), Path(output) / name
        if destination.is_symlink():
            raise FileExistsError(f"Refusing to replace existing pack: {destination}")
        if destination.exists():
            if (not destination.is_file() or destination.stat().st_size != source.stat().st_size or
                    (not source.samefile(destination) and file_sha(destination) != file_sha(source))):
                raise FileExistsError(f"Refusing to replace existing pack: {destination}")
            return
        try:
            os.link(source, destination)
        except FileExistsError:
            raise
        except OSError:
            # Exclusive creation keeps reruns or concurrent builds from
            # replacing any immutable pack already present at this location.
            with open(source, "rb") as incoming, open(destination, "xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK_SIZE)


def create_payload(bundle, output, version, platform="windows-x64", install_manifest=True,
                   channel="stable", release_tag=None, previous_manifest=None,
                   previous_packs=None, previous_pack_hashes=None):
    """Build a complete feed, appending only chunks absent from a trusted feed.

    previous_packs materializes referenced prior packs into output. Omit it only
    when those immutable packs are already hosted and will remain available;
    then output contains the new packs and complete manifest only. A supplied
    hash catalog must cover every reused pack. Without a catalog, local reused
    chunks are decompressed and checked against their SHA-256 before reuse.
    """
    bundle, output = Path(bundle), Path(output)
    if not bundle.is_dir():
        raise ValueError("Bundle must be an existing directory")
    previous = load_manifest(previous_manifest) if previous_manifest is not None else None
    if previous is not None and previous["platform"] != platform:
        raise ValueError("Previous manifest platform differs from bundle")
    if previous is None and (previous_packs is not None or previous_pack_hashes is not None):
        raise ValueError("Previous packs require a previous manifest")
    if previous_pack_hashes is not None and previous_packs is None:
        raise ValueError("Pack verification requires a previous packs directory")
    local = LocalPacks(previous, previous_packs, previous_pack_hashes) if previous_packs is not None else None
    previous_blobs = previous["blobs"] if previous else {}
    next_pack_index = max((int(name.rsplit("-", 1)[1][:-4]) for name in previous["packs"]), default=-1) + 1 if previous else 0
    release_tag = release_tag or f"v{version}"
    metadata_path = bundle / ("Contents/Resources/UPDATE_CHANNEL.json" if platform == "macos-arm64"
                              else "_internal/UPDATE_CHANNEL.json")
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata != {"channel": channel, "release_tag": release_tag}:
            raise ValueError("Bundle channel metadata differs from release")
    elif channel != "stable":
        raise ValueError("Experimental metadata must be embedded before signing")
    output.mkdir(parents=True, exist_ok=True)
    label = "macOS" if platform == "macos-arm64" else "Windows"
    files, links, blobs, packs = [], [], {}, {}
    pack_file = None
    pack_name = None
    new_packs = set()
    try:
        for directory, dirs, names in os.walk(bundle, followlinks=False):
            dirs.sort()
            names.sort()
            for name in list(dirs):
                p = Path(directory) / name
                if p.is_symlink():
                    links.append({"path": p.relative_to(bundle).as_posix(), "target": os.readlink(p)})
                    dirs.remove(name)
            for name in names:
                p = Path(directory) / name
                rel = p.relative_to(bundle).as_posix()
                if name in {MANIFEST, MAC_MANIFEST, PUBLIC_MANIFEST, PUBLIC_MAC_MANIFEST}:
                    continue
                safe_path(rel, platform)
                if p.is_symlink():
                    links.append({"path": rel, "target": os.readlink(p)})
                    continue
                chunks = []
                h = hashlib.sha256()
                size = 0
                with open(p, "rb") as source:
                    for block in iter(lambda: source.read(CHUNK_SIZE), b""):
                        digest = sha(block)
                        h.update(block)
                        size += len(block)
                        chunks.append(digest)
                        if digest in blobs:
                            continue
                        if digest in previous_blobs:
                            blob = previous_blobs[digest]
                            if blob["raw_size"] != len(block):
                                raise UpdateError("Previous chunk size differs from target")
                            if local:
                                local.verify_reuse(digest)
                            blobs[digest] = dict(blob)
                            packs[blob["pack"]] = previous["packs"][blob["pack"]]
                            continue
                        compressed = gzip.compress(block, compresslevel=6, mtime=0)
                        if pack_file is None or pack_file.tell() + len(compressed) > PACK_SIZE:
                            if pack_file:
                                packs[pack_name] = pack_file.tell()
                                pack_file.close()
                            # Immutable installed validators require this protocol-1 prefix.
                            pack_name = f"AnatomyExplorer-{label}-pack-{next_pack_index:04d}.bin"
                            next_pack_index += 1
                            pack_file = open(output / pack_name, "xb")
                            new_packs.add(pack_name)
                        blobs[digest] = {"pack": pack_name, "offset": pack_file.tell(), "size": len(compressed), "raw_size": len(block)}
                        pack_file.write(compressed)
                mode = 0o755 if p.stat().st_mode & stat.S_IXUSR else 0o644
                files.append({"path": rel, "size": size, "sha256": h.hexdigest(), "chunks": chunks, "mode": mode})
        if pack_file:
            packs[pack_name] = pack_file.tell()
    finally:
        if pack_file:
            pack_file.close()
    manifest = validate_manifest({"schema": 1, "launcher": 1, "platform": platform, "version": version,
                                  "channel": channel, "release_tag": release_tag,
                                  "files": files, "symlinks": links, "blobs": blobs, "packs": packs})
    if local:
        for name in sorted(packs.keys() - new_packs):
            local.materialize(name, output)
    public, legacy = manifest_names(platform)
    atomic_json(output / public, manifest)
    atomic_json(output / legacy, legacy_manifest(manifest))
    if install_manifest and platform == "windows-x64":
        write_manifests(bundle, manifest)
    print(f"{platform}: {len(files)} files, {len(links)} symlinks, {sum(f['size'] for f in files)} bundle bytes, {sum(packs.values())} feed bytes in {len(packs)} packs; {sum(packs[name] for name in new_packs)} new bytes in {len(new_packs)} packs", flush=True)
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", choices=["windows-x64", "macos-arm64"], default="windows-x64")
    parser.add_argument("--channel", choices=["stable", "experimental"], default="stable")
    parser.add_argument("--release-tag")
    parser.add_argument("--previous-manifest", type=Path,
                        help="Complete previous manifest already authenticated against its trusted release digest")
    parser.add_argument("--previous-packs", type=Path,
                        help="Local previous packs to verify and link/copy into the complete output feed")
    parser.add_argument("--previous-pack-hashes", type=Path,
                        help="Trusted JSON object mapping old pack names to SHA-256")
    args = parser.parse_args()
    create_payload(args.bundle, args.output, args.version, args.platform,
                   channel=args.channel, release_tag=args.release_tag,
                   previous_manifest=args.previous_manifest, previous_packs=args.previous_packs,
                   previous_pack_hashes=args.previous_pack_hashes)
