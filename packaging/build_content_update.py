"""Build an isolated complete content snapshot from authenticated frozen inputs.

No network, installer build, update activation, or publication is performed.
Only explicitly mapped model/preview/lesson files and explicit obsolete content
removals are accepted. Native libraries and runtime source remain unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.macho_sections import section_identity
from app.updater import (HASH_RE, MAX_MANIFEST, PACK_RE, atomic_json, file_sha,
                         manifest_names, release_version, safe_path,
                         validate_manifest, version_tuple)
from update_payload import create_payload

CONTENT_ROOTS = ("data/", "models/", "app/resources/", "app/ui/resources/")
CONTENT_SUFFIXES = {".json", ".npz", ".npy", ".glb", ".gltf", ".bin", ".obj", ".mtl", ".ply", ".stl",
                    ".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".tif", ".tiff",
                    ".md", ".txt", ".html", ".htm", ".csv", ".tsv", ".pdf", ".ktx", ".ktx2"}
NATIVE_MAGIC = {b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
                b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}
MANIFEST_NAMES = {name for platform in ("windows-x64", "macos-arm64") for name in manifest_names(platform)}


def read_json(path, maximum):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError(f"Missing, linked, or oversized JSON: {path.name}")
    raw = path.read_bytes()

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    return raw, json.loads(raw, object_pairs_hook=unique)


def authenticate_inputs(manifest_path, manifest_sha256, catalog_path, catalog_sha256):
    """Expected hashes must come from the caller's already authenticated feed."""
    for digest in (manifest_sha256, catalog_sha256):
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise ValueError("Explicit trusted manifest and catalog SHA-256 values are required")
    raw, previous = read_json(manifest_path, MAX_MANIFEST)
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise ValueError("Previous manifest SHA-256 differs from its trusted identity")
    previous = validate_manifest(previous)
    catalog_raw, catalog = read_json(catalog_path, 2 * 1024**2)
    if hashlib.sha256(catalog_raw).hexdigest() != catalog_sha256:
        raise ValueError("Previous pack catalog SHA-256 differs from its trusted identity")
    if not isinstance(catalog, dict):
        raise ValueError("Previous pack catalog must be an object")
    if "packs" in catalog:
        if (catalog.get("schema") != 1 or catalog.get("platform") != previous["platform"]
                or any(catalog.get(key) != previous.get(key) for key in ("version", "channel", "release_tag"))
                or catalog.get("manifest") != {"sha256": manifest_sha256, "size": len(raw)}):
            raise ValueError("Authenticated release catalog differs from the previous manifest")
        catalog = catalog["packs"]
    if not isinstance(catalog, dict):
        raise ValueError("Previous pack entries must be an object")
    packs = {}
    for name, size in previous["packs"].items():
        item = catalog.get(name)
        if (not isinstance(item, dict) or type(item.get("size")) is not int or item["size"] != size
                or not isinstance(item.get("sha256"), str) or not HASH_RE.fullmatch(item["sha256"])):
            raise ValueError(f"Previous pack has no matching trusted SHA-256/size: {name}")
        packs[name] = {"sha256": item["sha256"], "size": size}
    return previous, packs


def resource_path(name, platform):
    if (not isinstance(name, str) or not name.startswith(CONTENT_ROOTS)
            or PurePosixPath(name).suffix.lower() not in CONTENT_SUFFIXES):
        raise ValueError("Content targets must be model/preview/lesson resources with an allowed content format")
    prefix = "Contents/Resources/" if platform == "macos-arm64" else "_internal/"
    target = safe_path(prefix + name, platform)
    # Namespace checks apply to every component, including disguised native
    # frameworks and runtime code inside an otherwise allowed data directory.
    blocked = {".py", ".pyc", ".pyo", ".pyz", ".pyd", ".dll", ".exe", ".so", ".dylib", ".framework"}
    if any(PurePosixPath(part).suffix.lower() in blocked for part in PurePosixPath(name).parts):
        raise ValueError("Native/runtime replacement is outside a content update")
    return target


def is_native(path):
    with Path(path).open("rb") as source:
        magic = source.read(4)
    return magic in NATIVE_MAGIC or magic[:2] == b"MZ"


def load_patch_map(path, source_root, previous):
    _, data = read_json(path, 2 * 1024**2)
    if (not isinstance(data, dict) or set(data) != {"schema", "files", "remove"} or data["schema"] != 1
            or not isinstance(data["files"], list) or not isinstance(data["remove"], list)
            or not data["files"] and not data["remove"]):
        raise ValueError("Patch map requires schema=1, explicit files and explicit remove lists")
    source_root = Path(source_root).resolve(strict=True)
    prior_files = {entry["path"]: entry for entry in previous["files"]}
    prior_links = {entry["path"]: entry for entry in previous.get("symlinks", [])}
    selected, files, removals = set(), [], []
    for item in data["files"]:
        if (not isinstance(item, dict) or set(item) != {"source", "target", "sha256", "size"}
                or not isinstance(item["source"], str) or not isinstance(item["sha256"], str)
                or not HASH_RE.fullmatch(item["sha256"]) or type(item["size"]) is not int or item["size"] < 0):
            raise ValueError("Each mapped file requires source, target, SHA-256 and byte size")
        target = resource_path(item["target"], previous["platform"])
        # Reuse protocol path rules for repository-relative source components.
        safe_path("_internal/" + item["source"], "windows-x64")
        source = source_root / item["source"]
        if (source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(source_root)
                or source.suffix.lower() not in CONTENT_SUFFIXES
                or source.stat().st_size != item["size"] or file_sha(source) != item["sha256"]):
            raise ValueError(f"Mapped source is unsafe or differs from its declared identity: {item['source']}")
        if is_native(source):
            raise ValueError("A mapped content file contains a native executable header")
        if target.casefold() in selected or target in prior_links:
            raise ValueError("Duplicate content target or replacement of a declared symlink")
        if target in prior_files and prior_files[target].get("mode", 0o644) != 0o644:
            raise ValueError("Executable resources cannot be replaced by a content update")
        selected.add(target.casefold())
        files.append({**item, "path": target, "source_path": source})
    all_prior = {**prior_files, **prior_links}
    for name in data["remove"]:
        target = resource_path(name, previous["platform"])
        if target.casefold() in selected or target not in all_prior:
            raise ValueError("Obsolete removals must name distinct existing managed content files/symlinks")
        selected.add(target.casefold())
        removals.append(target)
    # New paths must not collide with existing file/symlink ancestors, with a
    # different case spelling, or with another mapped path's directory.
    paths = [name for name in all_prior if name not in removals and name not in {item["path"] for item in files}]
    paths.extend(item["path"] for item in files)
    lowered = {name.casefold() for name in paths}
    if len(lowered) != len(paths) or any("/".join(name.split("/")[:i]) in lowered
                                       for name in lowered for i in range(1, len(name.split("/")))):
        raise ValueError("Mapped content paths conflict with the declared inventory")
    return files, set(removals)


def verify_baseline(bundle, previous):
    """Authenticate listed bytes/modes/links; ignore only known sidecars/bytecode."""
    bundle = Path(bundle).resolve(strict=True)
    expected = {entry["path"] for entry in previous["files"] + previous.get("symlinks", [])}
    ignored, native = [], {}
    for entry in previous["files"]:
        path = bundle / entry["path"]
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(bundle)
                or path.stat().st_size != entry["size"] or file_sha(path) != entry["sha256"]):
            raise ValueError(f"Prior bundle file differs from authenticated manifest: {entry['path']}")
        actual_mode = path.stat().st_mode & 0o777
        if previous["platform"] == "macos-arm64" and actual_mode != entry.get("mode", 0o644):
            raise ValueError(f"Prior bundle file mode differs: {entry['path']}")
        if is_native(path):
            native[entry["path"]] = {"sha256": entry["sha256"], "mode": actual_mode}
    for entry in previous.get("symlinks", []):
        path = bundle / entry["path"]
        if not path.is_symlink() or os.readlink(path) != entry["target"]:
            raise ValueError(f"Prior bundle symlink differs: {entry['path']}")
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ValueError(f"Prior bundle symlink is dangling or cyclic: {entry['path']}") from None
        if not resolved.is_relative_to(bundle):
            raise ValueError("Prior bundle symlink escapes its application")
    for directory, dirs, names in os.walk(bundle, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                names.append(name)
                dirs.remove(name)
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(bundle).as_posix()
            if relative in expected:
                continue
            bytecode = "__pycache__" in PurePosixPath(relative).parts or path.suffix in {".pyc", ".pyo"}
            sidecar = relative in MANIFEST_NAMES
            if path.is_symlink() or not (bytecode or sidecar):
                raise ValueError(f"Unlisted source bundle file is outside the explicit snapshot: {relative}")
            ignored.append(relative)
    return native, ignored


def copy_inventory(base, candidate, previous, removals):
    candidate.mkdir(parents=True, exist_ok=False)
    immutable = ("_internal/data/", "_internal/models/", "Contents/Resources/data/", "Contents/Resources/models/")
    for entry in previous["files"]:
        if entry["path"] in removals:
            continue
        source, target = base / entry["path"], candidate / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry["path"].startswith(immutable) and entry.get("mode", 0o644) == 0o644 and not is_native(source):
            try:
                os.link(source, target)
                continue
            except OSError:
                pass
        shutil.copy2(source, target)
    for entry in previous.get("symlinks", []):
        if entry["path"] in removals:
            continue
        target = candidate / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(entry["target"], target_is_directory=(base / entry["path"]).is_dir())


def replace_file(path, source=None, data=None, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".content-new")
    digest, size = hashlib.sha256(), 0
    try:
        with temporary.open("xb") as output:
            if source is None:
                output.write(data)
                digest.update(data)
                size = len(data)
            else:
                with Path(source).open("rb") as incoming:
                    for block in iter(lambda: incoming.read(4 * 1024**2), b""):
                        output.write(block)
                        digest.update(block)
                        size += len(block)
        if expected is not None and (size != expected["size"] or digest.hexdigest() != expected["sha256"]):
            raise ValueError("Mapped source changed while its candidate copy was written")
        # Every user-selected content file is nonexecutable. Replacing the inode
        # protects the original even if its immutable bytes were hardlinked.
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sign_outer_app(base, candidate):
    if sys.platform != "darwin":
        raise ValueError("Mac content snapshots must be signed on the user's Mac")
    try:
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(base)], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(candidate)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(candidate)], check=True)
    except subprocess.CalledProcessError:
        raise RuntimeError("Outer-only Mac signing or strict deep verification failed; no deep re-sign fallback was attempted") from None


def build_content_update(bundle, previous_manifest, manifest_sha256, pack_catalog, catalog_sha256,
                         patch_map, source_root, output, version="4.0.13", previous_packs=None):
    previous, trusted_packs = authenticate_inputs(previous_manifest, manifest_sha256, pack_catalog, catalog_sha256)
    platform = previous["platform"]
    channel, tag = previous.get("channel", "stable"), "v" + version
    if channel != "stable" or release_version(tag, channel) != version or version_tuple(version) <= version_tuple(previous["version"]):
        raise ValueError("Content snapshots require a numerically newer stable version")
    base, output = Path(bundle).resolve(strict=True), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Content update output must be a fresh absent directory")
    output = output.resolve()
    if output == base or base in output.parents:
        raise ValueError("Content output must be outside the original bundle")
    patches, removals = load_patch_map(patch_map, source_root, previous)
    native, ignored = verify_baseline(base, previous)
    if ({item["path"] for item in patches} | removals) & set(native):
        raise ValueError("Native files cannot be replaced or removed by a content update")
    required = ({"Contents/MacOS/LayeredHuman", "Contents/MacOS/AnatomyExplorer"} if platform == "macos-arm64"
                else {"LayeredHuman.exe", "AnatomyExplorer.exe"})
    prior_files = {entry["path"]: entry for entry in previous["files"]}
    if not required.issubset(prior_files):
        raise ValueError("The prior public manifest must preserve both launcher aliases")
    prefix = "Contents/Resources/" if platform == "macos-arm64" else "_internal/"
    metadata = {prefix + "VERSION", prefix + "UPDATE_CHANNEL.json"}
    if not metadata.issubset(prior_files):
        raise ValueError("The prior bridge must declare its version and channel metadata")
    primary = None
    if platform == "macos-arm64":
        info = plistlib.loads((base / "Contents/Info.plist").read_bytes())
        executable = info.get("CFBundleExecutable")
        if not isinstance(executable, str) or "/" in executable or "\\" in executable:
            raise ValueError("Invalid outer app executable identity")
        primary = "Contents/MacOS/" + executable
        if primary not in native:
            raise ValueError("Outer app executable is not a declared native file")
    if previous_packs is not None:
        from update_payload import LocalPacks
        local = LocalPacks(previous, previous_packs, {name: item["sha256"] for name, item in trusted_packs.items()})
        for name in previous["packs"]:
            local.path(name)
    output.mkdir(parents=True, exist_ok=False)
    candidate = output / "candidate" / base.name
    copy_inventory(base, candidate, previous, removals)
    for item in patches:
        replace_file(candidate / item["path"], source=item["source_path"], expected=item)
    for entry in previous.get("symlinks", []):
        if entry["path"] in removals:
            continue
        try:
            resolved = (candidate / entry["path"]).resolve(strict=True)
        except (OSError, RuntimeError):
            raise ValueError("Content removal would leave a dangling or cyclic bundle symlink") from None
        if not resolved.is_relative_to(candidate.resolve()):
            raise ValueError("Candidate symlink escapes its isolated bundle")
    replace_file(candidate / (prefix + "VERSION"), data=version.encode())
    replace_file(candidate / (prefix + "UPDATE_CHANNEL.json"), data=json.dumps({"channel": channel, "release_tag": tag},
                 separators=(",", ":")).encode())
    allowed = {item["path"] for item in patches} | metadata
    if platform == "macos-arm64":
        plist = candidate / "Contents/Info.plist"
        raw = plist.read_bytes()
        info.update(CFBundleVersion=version, CFBundleShortVersionString=version)
        replace_file(plist, data=plistlib.dumps(info, fmt=plistlib.FMT_BINARY if raw.startswith(b"bplist") else plistlib.FMT_XML))
        allowed.update({"Contents/Info.plist", "Contents/_CodeSignature/CodeResources", primary})
        sign_outer_app(base, candidate)
        for name, identity in native.items():
            target = candidate / name
            if target.stat().st_mode & 0o777 != identity["mode"] or (name != primary and file_sha(target) != identity["sha256"]):
                raise ValueError(f"Outer signing changed a preserved nested native file: {name}")
        if file_sha(candidate / primary) != native[primary]["sha256"] and section_identity(base / primary) != section_identity(candidate / primary):
            raise ValueError("Outer signing changed native executable sections")
    kwargs = {"previous_manifest": previous}
    if previous_packs is not None:
        kwargs.update(previous_packs=previous_packs,
                      previous_pack_hashes={name: item["sha256"] for name, item in trusted_packs.items()})
    manifest = create_payload(candidate, output / "feed", version, platform, channel=channel, release_tag=tag, **kwargs)
    actual = {entry["path"]: entry for entry in manifest["files"]}
    expected = (set(prior_files) - removals) | {item["path"] for item in patches}
    if set(actual) != expected or manifest.get("symlinks", []) != [link for link in previous.get("symlinks", []) if link["path"] not in removals]:
        raise ValueError("Generated snapshot differs from its explicitly declared complete inventory")
    changed = []
    for name, entry in actual.items():
        prior = prior_files.get(name)
        if prior is None or any(entry.get(key, 0o644) != prior.get(key, 0o644) for key in ("sha256", "size", "mode")):
            if name not in allowed:
                raise ValueError(f"Undeclared managed file changed: {name}")
            changed.append(name)
    catalog = {}
    for name, size in manifest["packs"].items():
        catalog[name] = trusted_packs[name] if name in trusted_packs else {"sha256": file_sha(output / "feed" / name), "size": size}
    atomic_json(output / "known-packs.json", catalog)
    report = {"schema": 1, "platform": platform, "base_version": previous["version"], "version": version,
              "release_tag": tag, "previous_manifest_sha256": manifest_sha256, "previous_catalog_sha256": catalog_sha256,
              "changed_files": sorted(changed), "removed_files": sorted(removals), "ignored_unlisted_bytecode_or_sidecars": ignored,
              "complete_file_count": len(actual), "complete_symlink_count": len(manifest.get("symlinks", [])),
              "new_pack_bytes": sum(size for name, size in manifest["packs"].items() if name not in trusted_packs),
              "reused_pack_bytes": sum(size for name, size in manifest["packs"].items() if name in trusted_packs),
              "old_pack_bytes_materialized": previous_packs is not None,
              "nested_native_files_preserved": len(native) - (1 if primary else 0),
              "mac_signing": "outer-only; strict deep verification" if primary else None,
              "native_checks": "Separate native runtime, launch/update, and HTTPS checks are still required",
              "publication": "Local artifacts only; no remote writes"}
    atomic_json(output / "content-build.json", report)
    return manifest, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--previous-manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--pack-catalog", type=Path, required=True)
    parser.add_argument("--catalog-sha256", required=True)
    parser.add_argument("--patch-map", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--version", default="4.0.13")
    parser.add_argument("--previous-packs", type=Path)
    args = parser.parse_args(argv)
    _, report = build_content_update(args.bundle, args.previous_manifest, args.manifest_sha256,
        args.pack_catalog, args.catalog_sha256, args.patch_map, args.source_root, args.output,
        version=args.version, previous_packs=args.previous_packs)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
