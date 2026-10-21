"""Patch a verified frozen release and produce a feed without rebuilding installers.

Only explicitly selected plain app sources change. Models and native runtimes come
from the pinned public release, whose manifest and packs are authenticated using
GitHub's release asset SHA-256 metadata before reconstruction.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.updater import file_sha, manifest_names, validate_manifest
from release_storage import require_space

BASE_COMMIT = "3e814b9ddebbcea58e33d7541f6b02b8f890fd42"
DEFAULT_PATCHES = ("app/updater.py", "app/ui/updates.py", "app/https_check.py")
REPOSITORIES = {"ethanprince4/AnatomyExplorer", "ethanprince4/LayeredHuman"}
IMMUTABLE_PREFIXES = ("_internal/data/", "_internal/models/",
                      "Contents/Resources/data/", "Contents/Resources/models/")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def checked_asset(asset, repository, tag, expected_size=None):
    """Accept only a named immutable asset with GitHub-provided size and hash."""
    name, size, digest = (asset.get(key) for key in ("name", "size", "digest"))
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
            or type(size) is not int or size <= 0
            or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
        raise ValueError("Release asset has no bounded SHA-256 identity")
    expected_url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
    if asset.get("browser_download_url") != expected_url or (expected_size is not None and size != expected_size):
        raise ValueError(f"Release asset URL or size differs: {name}")
    return {"name": name, "size": size, "sha256": digest.split(":", 1)[1], "url": expected_url}


def fetch_release(repository, tag):
    if repository not in REPOSITORIES or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Expected a pinned stable release in a trusted repository")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LayeredHuman-Bridge/1",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/repos/{repository}/releases/tags/{tag}", headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read(16 * 1024**2 + 1)
    if len(raw) > 16 * 1024**2:
        raise ValueError("Release API metadata is too large")
    release = json.loads(raw)
    if (release.get("tag_name") != tag or release.get("draft") is not False
            or release.get("prerelease") is not False or not isinstance(release.get("assets"), list)):
        raise ValueError("Pinned release is not a published stable release")
    names = [entry.get("name") for entry in release["assets"]]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate release asset names")
    return release


def download_asset(asset, directory):
    """Verify cache hits, and atomically publish only complete verified downloads."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / asset["name"]
    if target.is_file() and target.stat().st_size == asset["size"] and file_sha(target) == asset["sha256"]:
        return target
    temporary = target.with_name(target.name + ".bridge-download")
    for attempt in range(4):
        try:
            request = urllib.request.Request(asset["url"], headers={"User-Agent": "LayeredHuman-Bridge/1"})
            digest, count = hashlib.sha256(), 0
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                # GitHub's public download redirects use only its asset CDN.
                final = urllib.parse.urlsplit(response.url)
                if (final.scheme != "https" or final.hostname not in {
                        "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
                        or final.username or final.password or final.port not in (None, 443)):
                    raise ValueError("Untrusted release download redirect")
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    count += len(block)
                    if count > asset["size"]:
                        raise ValueError("Release download exceeds declared size")
                    digest.update(block)
                    output.write(block)
            if count != asset["size"] or digest.hexdigest() != asset["sha256"]:
                raise ValueError(f"Release asset failed SHA-256 verification: {asset['name']}")
            os.replace(temporary, target)
            print(f"Verified {asset['name']} ({count:,} bytes)", flush=True)
            return target
        except (OSError, urllib.error.URLError):
            if attempt == 3:
                raise RuntimeError(f"Release download failed: {asset['name']}") from None
            time.sleep(2 ** attempt)
        finally:
            temporary.unlink(missing_ok=True)


def clone_bundle(source, target):
    """Share only immutable model/data files; always copy code and signed binaries."""
    source, target = Path(source), Path(target)

    def copy_file(src, dst):
        relative = Path(src).relative_to(source).as_posix()
        if relative.startswith(IMMUTABLE_PREFIXES):
            try:
                os.link(src, dst)
                return dst
            except OSError:
                pass
        return shutil.copy2(src, dst)

    shutil.copytree(source, target, symlinks=True, copy_function=copy_file)


def patch_name(name):
    path = PurePosixPath(name)
    if (not isinstance(name, str) or "\\" in name or path.as_posix() != name
            or path.is_absolute() or ".." in path.parts or len(path.parts) < 2
            or path.parts[0] != "app" or path.suffix != ".py"):
        raise ValueError("Bridge patches must name explicit app/*.py source files")
    return name


def replace_bytes(path, data):
    """Replace the candidate inode rather than modifying a shared source inode."""
    path = Path(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temporary = path.with_name(path.name + ".bridge-new")
    try:
        temporary.write_bytes(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def patch_bundle(base, candidate, source_root, patches, base_commit, version, platform, release_tag,
                 source_baseline=None):
    resources = "Contents/Resources" if platform == "macos-arm64" else "_internal"
    changed = []
    for name in patches:
        patch_name(name)
        prior, target = Path(base) / resources / name, Path(candidate) / resources / name
        source = Path(source_root) / name
        if not source.is_file() or not source.resolve().is_relative_to(Path(source_root).resolve()):
            raise ValueError(f"Source patch is missing or outside the checkout: {name}")
        if source_baseline is not None:
            identity = source_baseline["files"].get(name)
            if (source_baseline.get("base_commit") != base_commit or not isinstance(identity, dict)
                    or type(identity.get("size")) is not int or not isinstance(identity.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])):
                raise ValueError("Transferred baseline catalog differs from selected source commit or files")
        else:
            old = subprocess.run(["git", "show", f"{base_commit}:{name}"], cwd=source_root,
                                 capture_output=True, check=True).stdout
            identity = {"size": len(old), "sha256": hashlib.sha256(old).hexdigest()}
        if not prior.is_file() or prior.stat().st_size != identity["size"] or file_sha(prior) != identity["sha256"]:
            raise ValueError(f"Frozen source differs from the pinned source commit: {name}")
        data = source.read_bytes()
        compile(data, name, "exec")
        if len(data) == identity["size"] and hashlib.sha256(data).hexdigest() == identity["sha256"]:
            continue
        if not target.resolve().is_relative_to(Path(candidate).resolve()):
            raise ValueError(f"Patch target escapes candidate bundle: {name}")
        replace_bytes(target, data)
        changed.append(f"{resources}/{name}")
    if not changed:
        raise ValueError("No selected app source differs from the pinned release")
    replace_bytes(Path(candidate) / resources / "VERSION", version.encode())
    replace_bytes(Path(candidate) / resources / "UPDATE_CHANNEL.json", json.dumps(
        {"channel": "stable", "release_tag": release_tag}, separators=(",", ":")).encode())
    changed.extend(f"{resources}/{name}" for name in ("VERSION", "UPDATE_CHANNEL.json"))
    if platform == "macos-arm64":
        path = Path(candidate) / "Contents/Info.plist"
        raw = path.read_bytes()
        info = plistlib.loads(raw)
        info.update(CFBundleVersion=version, CFBundleShortVersionString=version)
        replace_bytes(path, plistlib.dumps(info, fmt=plistlib.FMT_BINARY if raw.startswith(b"bplist") else plistlib.FMT_XML))
        changed.append("Contents/Info.plist")
    return changed


def verify_delta(base, candidate, previous, manifest, allowed):
    """Require unchanged assets/source, accepting only native signing differences."""
    old = {entry["path"]: entry for entry in previous["files"]}
    new = {entry["path"]: entry for entry in manifest["files"]}
    if old.keys() != new.keys() or previous.get("symlinks", []) != manifest.get("symlinks", []):
        raise ValueError("A source-only bridge must preserve every baseline path and symlink")
    differences, signed = [], []
    for name, entry in new.items():
        if entry["sha256"] == old[name]["sha256"] and entry.get("mode", 0o644) == old[name].get("mode", 0o644):
            continue
        differences.append(name)
        if name in allowed:
            continue
        if manifest["platform"] == "macos-arm64":
            if "_CodeSignature" in PurePosixPath(name).parts or PurePosixPath(name).name == "CodeResources":
                signed.append(name)
                continue
            prior, target = Path(base) / name, Path(candidate) / name
            with prior.open("rb") as stream:
                magic = stream.read(4)
            if magic in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                from app.macho_sections import section_identity
                if section_identity(prior) == section_identity(target):
                    signed.append(name)
                    continue
        raise ValueError(f"Unexpected frozen bundle change outside selected sources: {name}")
    return {"changed_files": differences, "native_signing_changes": signed,
            "baseline_assets_and_unselected_sources_preserved": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("windows-x64", "macos-arm64"), required=True)
    parser.add_argument("--repository", default="ethanprince4/AnatomyExplorer")
    parser.add_argument("--base-tag", default="v4.0.11")
    parser.add_argument("--base-commit", default=BASE_COMMIT)
    parser.add_argument("--tag", default="v4.0.12")
    parser.add_argument("--work", type=Path, default=ROOT / "packaging/build/update-bridge")
    parser.add_argument("--cache", type=Path, help="Verified baseline manifest/pack cache; existing files are rehashed")
    parser.add_argument("--source-baseline", type=Path, help="Transferred pinned-source SHA catalog (no git checkout required)")
    parser.add_argument("--patch", action="append", help="Explicit app/*.py path; repeat to replace the default bridge patch list")
    parser.add_argument("--download-jobs", type=int, default=4)
    args = parser.parse_args(argv)
    if (not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.tag)
            or not re.fullmatch(r"[0-9a-f]{40}", args.base_commit)
            or not 1 <= args.download_jobs <= 8):
        parser.error("Expected numeric stable tags, a full base commit, and 1-8 download jobs")
    version = args.tag[1:]
    if tuple(map(int, version.split("."))) <= tuple(map(int, args.base_tag[1:].split("."))):
        parser.error("The bridge must be numerically newer than its baseline")
    if (args.platform == "macos-arm64" and sys.platform != "darwin") or (args.platform == "windows-x64" and sys.platform != "win32"):
        parser.error("Use the native platform runner for frozen signing and verification")
    patches = list(dict.fromkeys(patch_name(name) for name in (args.patch or DEFAULT_PATCHES)))
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    for name in ("base", "candidate", "feed", "publish"):
        if (work / name).exists():
            raise ValueError(f"Use a fresh bridge work directory; {name} already exists")
    release = fetch_release(args.repository, args.base_tag)
    assets = {asset["name"]: asset for asset in release["assets"]}
    public, legacy = manifest_names(args.platform)
    manifest_asset = checked_asset(assets[public], args.repository, args.base_tag)
    if manifest_asset["size"] > 32 * 1024**2:
        raise ValueError("Baseline manifest is too large")
    cache = args.cache.resolve() if args.cache else work / "baseline-feed"
    path = download_asset(manifest_asset, cache)
    previous = validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    if (previous["platform"] != args.platform or previous["version"] != args.base_tag[1:]
            or previous.get("release_tag") != args.base_tag or previous.get("channel", "stable") != "stable"):
        raise ValueError("Pinned manifest release identity differs")
    pack_assets = [checked_asset(assets[name], args.repository, args.base_tag, size)
                   for name, size in previous["packs"].items()]
    require_space(work, sum(previous["packs"].values()) + sum(e["size"] for e in previous["files"]) * 3 + 1024**3,
                  "Verified baseline, candidate code copies, and unmodified native update reserve")
    with ThreadPoolExecutor(max_workers=args.download_jobs) as pool:
        list(pool.map(lambda asset: download_asset(asset, cache), pack_assets))
    hashes = {asset["name"]: asset["sha256"] for asset in pack_assets}
    write_json(work / "baseline-pack-hashes.json", hashes)
    write_json(work / "reports/baseline-release.json", {
        "repository": args.repository, "tag": args.base_tag, "release_id": release["id"],
        "source_commit": args.base_commit, "manifest": manifest_asset, "packs": pack_assets})
    bundle_name = "Layered Human.app" if args.platform == "macos-arm64" else "LayeredHuman"
    base, candidate = (work / name / bundle_name for name in ("base", "candidate"))
    from reconstruct_bundle import reconstruct_bundle
    reconstruct_bundle(previous, cache, base, pack_hashes=hashes)
    if args.platform == "macos-arm64":
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(base)], check=True)
    clone_bundle(base, candidate)
    source_baseline = json.loads(args.source_baseline.read_text(encoding="utf-8")) if args.source_baseline else None
    changed = patch_bundle(base, candidate, ROOT, patches, args.base_commit, version, args.platform, args.tag,
                           source_baseline=source_baseline)
    if args.platform == "macos-arm64":
        subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(candidate)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(candidate)], check=True)
    from update_payload import create_payload
    manifest = create_payload(candidate, work / "feed", version, args.platform, channel="stable", release_tag=args.tag,
                              previous_manifest=previous, previous_packs=cache, previous_pack_hashes=hashes)
    delta = verify_delta(base, candidate, previous, manifest, set(changed))
    catalog = {}
    publish = work / "publish"
    publish.mkdir()
    for name, size in manifest["packs"].items():
        reused = name in hashes
        digest = hashes[name] if reused else file_sha(work / "feed" / name)
        catalog[name] = {"size": size, "sha256": digest, "reused": reused}
        if reused:
            catalog[name].update(source_release=args.base_tag, source_url=assets[name]["browser_download_url"])
        else:
            shutil.copy2(work / "feed" / name, publish / name)
    for name in (public, legacy):
        shutil.copy2(work / "feed" / name, publish / name)
    write_json(publish / f"{args.platform}-pack-catalog.json", catalog)
    if source_baseline is not None:
        candidate_commit = source_baseline.get("candidate_source_commit")
    else:
        source_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        candidate_commit = source_commit.stdout.strip() if source_commit.returncode == 0 else None
    report = {"schema": 1, "platform": args.platform, "version": version, "release_tag": args.tag,
              "base_release": args.base_tag, "base_source_commit": args.base_commit,
              "candidate_source_commit": candidate_commit,
              "candidate_patch_sha256": {name: file_sha(ROOT / name) for name in patches},
              "selected_source_patches": patches, "actual_source_and_metadata_patches": changed,
              "new_pack_bytes": sum(entry["size"] for entry in catalog.values() if not entry["reused"]),
              "reused_pack_bytes": sum(entry["size"] for entry in catalog.values() if entry["reused"]),
              "complete_feed_bytes": sum(manifest["packs"].values()), **delta,
              "native_checks": "Run local native checks before publication",
              "publication": "Artifacts only; GitHub bridge release also needs every reused pack"}
    write_json(work / "reports/bridge-build.json", report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
