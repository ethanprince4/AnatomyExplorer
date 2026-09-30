"""Pack actual frozen files as independently compressed 4 MiB content chunks.

On macOS run after signing; manifests stay outside the sealed .app. Clients only
download missing byte ranges from the approximately 64 MiB HTTPS release packs.
"""
import gzip
import hashlib
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import (CHUNK_SIZE, MAC_MANIFEST, MANIFEST, PACK_SIZE, atomic_json,
                         manifest_path, safe_path, sha, validate_manifest)


def create_payload(bundle, output, version, platform="windows-x64", install_manifest=True):
    bundle, output = Path(bundle), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    label = "macOS" if platform == "macos-arm64" else "Windows"
    files, links, blobs, packs = [], [], {}, {}
    pack_file = None
    pack_name = None
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
                if name in {MANIFEST, MAC_MANIFEST}:
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
                        compressed = gzip.compress(block, compresslevel=6, mtime=0)
                        if pack_file is None or pack_file.tell() + len(compressed) > PACK_SIZE:
                            if pack_file:
                                packs[pack_name] = pack_file.tell()
                                pack_file.close()
                            pack_name = f"AnatomyExplorer-{label}-pack-{len(packs):04d}.bin"
                            pack_file = open(output / pack_name, "wb")
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
                                  "files": files, "symlinks": links, "blobs": blobs, "packs": packs})
    name = MAC_MANIFEST if platform == "macos-arm64" else MANIFEST
    atomic_json(output / name, manifest)
    if install_manifest and platform == "windows-x64":
        atomic_json(manifest_path(bundle), manifest)
    print(f"{platform}: {len(files)} files, {len(links)} symlinks, {sum(f['size'] for f in files)} bundle bytes, {sum(packs.values())} feed bytes in {len(packs)} packs", flush=True)
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", choices=["windows-x64", "macos-arm64"], default="windows-x64")
    args = parser.parse_args()
    create_payload(args.bundle, args.output, args.version, args.platform)
