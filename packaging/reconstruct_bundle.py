"""Rebuild a complete frozen tree from authenticated local feed artifacts.

No network access, installer registration, or updater activation is performed.
Authenticate the manifest (and optional pack hash catalog) before calling this
helper. Manifest paths and symlinks still pass protocol-1 validation, every
compressed chunk and reconstructed file is checked, and output must be absent.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from update_payload import LocalPacks, load_manifest
from app.updater import UpdateError, atomic_json, legacy_manifest, manifest_names


def reconstruct_bundle(manifest, packs, output, pack_hashes=None, install_manifest=True):
    """Reconstruct verified files and safe relative symlinks into a new tree.

    A failed verification leaves a partial output for inspection; the helper
    never removes or overlays an existing destination. File permissions come
    from the manifest. Installed manifest aliases are external to a Mac .app.
    """
    manifest = load_manifest(manifest)
    source = LocalPacks(manifest, packs, pack_hashes)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Reconstruction destination must be absent: {output}")
    metadata = []
    if install_manifest:
        # Mac metadata lives beside the sealed .app. Preserve an existing
        # identical sidecar, and never replace a different bundle's manifest.
        directory = output.parent if manifest["platform"] == "macos-arm64" else output
        public, legacy = manifest_names(manifest["platform"])
        for name, value in ((public, manifest), (legacy, legacy_manifest(manifest))):
            path = directory / name
            if path.is_symlink():
                raise FileExistsError(f"Refusing to replace existing manifest: {path}")
            if path.exists():
                if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != value:
                    raise FileExistsError(f"Refusing to replace existing manifest: {path}")
            else:
                metadata.append((path, value))
    # Check pack identity/length before creating any files. Chunk verification
    # below is mandatory even when the optional full-pack SHA catalog is used.
    for name in manifest["packs"]:
        source.path(name)
    output.mkdir(parents=True, exist_ok=False)
    root = output.resolve(strict=True)
    for entry in manifest["files"]:
        path = root / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.resolve() != path.parent or not path.parent.is_relative_to(root):
            raise UpdateError("Unsafe reconstruction destination")
        digest = hashlib.sha256()
        size = 0
        with open(path, "xb") as destination:
            for chunk in entry["chunks"]:
                block = source.chunk(chunk)
                destination.write(block)
                digest.update(block)
                size += len(block)
        if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
            raise UpdateError(f"Reconstructed file failed integrity verification: {entry['path']}")
        os.chmod(path, entry.get("mode", 0o644))
    for entry in manifest.get("symlinks", []):
        path = root / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.resolve() != path.parent or not path.parent.is_relative_to(root):
            raise UpdateError("Unsafe reconstruction symlink destination")
        path.symlink_to(entry["target"], target_is_directory=(path.parent / entry["target"]).is_dir())
    for entry in manifest.get("symlinks", []):
        path = root / entry["path"]
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise UpdateError("Reconstructed symlink is dangling or cyclic") from exc
        if not target.is_relative_to(root):
            raise UpdateError("Reconstructed symlink escaped the bundle")
    for path, value in metadata:
        atomic_json(path, value)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("packs", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pack-hashes", type=Path,
                        help="Trusted JSON object mapping pack names to SHA-256")
    parser.add_argument("--no-install-manifest", action="store_true")
    args = parser.parse_args()
    manifest = reconstruct_bundle(args.manifest, args.packs, args.output,
                                  pack_hashes=args.pack_hashes,
                                  install_manifest=not args.no_install_manifest)
    print(f"Reconstructed {len(manifest['files'])} verified files for {manifest['platform']} {manifest['version']}")


if __name__ == "__main__":
    main()
