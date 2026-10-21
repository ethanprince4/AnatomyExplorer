"""Protocol 1 updater; also used by the stable launcher.

Active updates trust the fixed Cloudflare HTTPS origin, then content-addressed
catalog/manifest metadata and SHA-256 file/chunk hashes. This is same-origin TLS
trust, not detached release signing. GitHubSource remains for bridge compatibility.
Installation files and study data are never changed.
"""
import contextlib
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
import zlib
from pathlib import Path
from urllib.parse import urlsplit

# Keep this feed address until existing installations have received the bridge
# updater. Their immutable launchers reject assets from a renamed repository.
LEGACY_REPO = "ethanprince4/AnatomyExplorer"
REPO = LEGACY_REPO
TRUSTED_REPOS = (LEGACY_REPO, "ethanprince4/LayeredHuman")
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
CHANNELS = {"stable", "experimental"}
# Reserved numeric cores keep protocol-1 immutable launchers compatible. They
# only accept numeric VERSION files and only activate a numerically newer app.
PREVIEW_TAG_RE = re.compile(r"v([0-9]+)\.90\.([1-9][0-9]*)-preview\.([1-9][0-9]*)")
# Immutable launchers still read these legacy protocol names.
MANIFEST = "AnatomyExplorer-Windows-update.json"
MAC_MANIFEST = "AnatomyExplorer-macOS-update.json"
PUBLIC_MANIFEST = "LayeredHuman-Windows-update.json"
PUBLIC_MAC_MANIFEST = "LayeredHuman-macOS-update.json"
LEGACY_MAC_BUNDLE = "Anatomy Explorer.app"
CHUNK_SIZE = 4 * 1024 * 1024
PACK_SIZE = 64 * 1024 * 1024
MAX_MANIFEST = 16 * 1024 * 1024
MAX_TOTAL = 20 * 1024**3
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ID_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{16}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
PACK_RE = re.compile(r"AnatomyExplorer-(Windows|macOS)-pack-[0-9]{4}\.bin")
CLOUDFLARE_ORIGIN = "https://downloads.layeredhuman.com"
MAX_CHANNEL = 32 * 1024
MAX_CATALOG = 512 * 1024
MAX_STAGE_ENTRIES = 200000
MAX_STAGE_PRUNE = 4096


class UpdateError(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(block)
    return h.hexdigest()


def version_tuple(value):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise UpdateError("Unsupported release version")
    return tuple(map(int, value.split(".")))


def release_version(tag, channel="stable"):
    if not isinstance(channel, str) or channel not in CHANNELS or not isinstance(tag, str):
        raise UpdateError("Unsupported update channel or release tag")
    if channel == "experimental":
        match = PREVIEW_TAG_RE.fullmatch(tag)
        if not match or match[2] != match[3]:
            raise UpdateError("Unsupported experimental release tag")
        return f"{match[1]}.90.{match[2]}"
    version = tag[1:] if tag.startswith("v") else tag
    if version_tuple(version)[1] == 90:
        raise UpdateError("Experimental version cannot enter the stable channel")
    return version


def manifest_channel(manifest):
    return manifest.get("channel", "stable")


def safe_path(value, platform="windows-x64"):
    if not isinstance(value, str) or len(value) > 220 or "\\" in value:
        raise UpdateError("Invalid update path")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
    if any(not p or p in {".", ".."} or p[-1] in " ." or
           any(c in p for c in ':<>"|?*') or any(ord(c) < 32 for c in p) or
           p.split(".")[0].upper() in reserved for p in parts):
        raise UpdateError("Unsafe update path")
    if platform == "macos-arm64":
        if parts[0] != "Contents" or len(parts) < 2:
            raise UpdateError("Update attempted to write outside the app bundle")
    elif parts[0] not in {"_internal", "LayeredHuman.exe", "AnatomyExplorer.exe", "LICENSE.txt", "THIRD_PARTY_LICENSES.md"}:
        raise UpdateError("Update attempted to write outside the application")
    if platform != "macos-arm64" and parts[0] != "_internal" and len(parts) != 1:
        raise UpdateError("Invalid application file")
    if any(p.casefold() in {"user", "logs", "updates", "model-library", "__pycache__"} for p in parts):
        raise UpdateError("Personal or mutable files must not be shipped")
    return value


def validate_manifest(data):
    if (not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1 or
            data.get("platform") not in {"windows-x64", "macos-arm64"} or
            type(data.get("launcher")) is not int or data["launcher"] != 1):
        raise UpdateError("This update needs a newer installer")
    version_tuple(data.get("version"))
    channel = manifest_channel(data)
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise UpdateError("Unsupported update channel")
    tag = data.get("release_tag")
    if channel == "experimental" or tag is not None:
        if release_version(tag, channel) != data["version"]:
            raise UpdateError("Update channel, release tag and version differ")
    elif version_tuple(data["version"])[1] == 90:
        raise UpdateError("Preview metadata is required for experimental versions")
    files, blobs, packs = data.get("files"), data.get("blobs"), data.get("packs")
    if not isinstance(files, list) or not 1 <= len(files) <= 50000 or not isinstance(blobs, dict) or not isinstance(packs, dict):
        raise UpdateError("Invalid update manifest")
    if len(blobs) > 100000 or len(packs) > 1000:
        raise UpdateError("Update manifest is too large")
    for name, size in packs.items():
        if not PACK_RE.fullmatch(name) or type(size) is not int or not 0 < size <= PACK_SIZE + CHUNK_SIZE:
            raise UpdateError("Invalid update pack")
    for digest, b in blobs.items():
        if not HASH_RE.fullmatch(digest) or not isinstance(b, dict):
            raise UpdateError("Invalid chunk digest")
        if b.get("pack") not in packs or any(type(b.get(k)) is not int for k in ("offset", "size", "raw_size")):
            raise UpdateError("Invalid chunk location")
        if not 0 < b["raw_size"] <= CHUNK_SIZE or not 0 < b["size"] <= CHUNK_SIZE + 65536 or b["offset"] < 0 or b["offset"] + b["size"] > packs[b["pack"]]:
            raise UpdateError("Invalid chunk bounds")
    names, total = set(), 0
    for entry in files:
        if not isinstance(entry, dict):
            raise UpdateError("Invalid file entry")
        name = safe_path(entry.get("path"), data["platform"])
        if name.casefold() in names or type(entry.get("size")) is not int or entry["size"] < 0 or not isinstance(entry.get("sha256"), str) or not HASH_RE.fullmatch(entry["sha256"]):
            raise UpdateError("Invalid or duplicate update file")
        names.add(name.casefold())
        if type(entry.get("mode", 0o644)) is not int or entry.get("mode", 0o644) not in {0o644, 0o755}:
            raise UpdateError("Invalid file permissions")
        chunks = entry.get("chunks")
        if not isinstance(chunks, list) or any(not isinstance(c, str) or c not in blobs for c in chunks):
            raise UpdateError("Missing update chunk")
        if sum(blobs[c]["raw_size"] for c in chunks) != entry["size"] or any(blobs[c]["raw_size"] != CHUNK_SIZE for c in chunks[:-1]):
            raise UpdateError("Invalid file chunks")
        total += entry["size"]
    required = {"contents/macos/anatomyexplorer", "contents/resources/version"} if data["platform"] == "macos-arm64" else {"anatomyexplorer.exe", "_internal/version"}
    if total > MAX_TOTAL or not required.issubset(names):
        raise UpdateError("Incomplete or oversized application")
    links = data.get("symlinks", [])
    if not isinstance(links, list) or len(links) > 50000 or (links and data["platform"] != "macos-arm64"):
        raise UpdateError("Invalid bundle symlinks")
    for link in links:
        if not isinstance(link, dict):
            raise UpdateError("Invalid symlink")
        name = safe_path(link.get("path"), data["platform"])
        target = link.get("target")
        if not isinstance(target, str) or not target or "\\" in target or target.startswith("/") or ":" in target or len(target) > 220:
            raise UpdateError("Invalid symlink target")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
        safe_path(resolved, data["platform"])
        if name.casefold() in names:
            raise UpdateError("Duplicate symlink path")
        names.add(name.casefold())
    # A file cannot also be a directory, even with Windows case folding.
    for name in names:
        if any("/".join(name.split("/")[:i]) in names for i in range(1, len(name.split("/")))):
            raise UpdateError("Conflicting file paths")
    return data


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with open(tmp, "x", encoding="utf-8") as f:
            json.dump(value, f, separators=(",", ":"), sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def manifest_path(root):
    root = Path(root)
    return root.parent / MAC_MANIFEST if root.suffix == ".app" else root / MANIFEST


def manifest_names(platform):
    """Prefer the public name, accepting immutable protocol-1 feeds as well."""
    return ((PUBLIC_MAC_MANIFEST, MAC_MANIFEST) if platform == "macos-arm64"
            else (PUBLIC_MANIFEST, MANIFEST))


def installed_manifest_path(root):
    root = Path(root)
    directory = root.parent if root.suffix == ".app" else root
    names = manifest_names("macos-arm64" if root.suffix == ".app" else "windows-x64")
    return next((directory / name for name in names if (directory / name).exists()), manifest_path(root))


def legacy_manifest(manifest):
    """Old Windows validators allow only the original root executable name.

    Both binaries have identical bytes. The legacy feed omits the public alias;
    unchanged packs and hashes still let old launchers stage the complete app.
    """
    if manifest["platform"] != "windows-x64":
        return manifest
    return {**manifest, "files": [entry for entry in manifest["files"] if entry["path"] != "LayeredHuman.exe"]}


def write_manifests(root, manifest):
    root = Path(root)
    directory = root.parent if root.suffix == ".app" else root
    public, legacy = manifest_names(manifest["platform"])
    atomic_json(directory / public, manifest)
    atomic_json(directory / legacy, legacy_manifest(manifest))


def application_executable(root, mac=False):
    root = Path(root)
    directory = root / "Contents/MacOS" if mac else root
    public, legacy = ("LayeredHuman", "AnatomyExplorer") if mac else ("LayeredHuman.exe", "AnatomyExplorer.exe")
    return directory / public if (directory / public).is_file() else directory / legacy


def read_manifest(root):
    root = Path(root)
    path = installed_manifest_path(root)
    if root.suffix == ".app" and (not ID_RE.fullmatch(root.parent.name) and not root.parent.name.endswith(".staging") or not path.exists()):
        # Initial DMG install: inventory signed bytes locally, with no extra file
        # inserted into the signed bundle (that would break its resource seal).
        return local_inventory(root)
    if path.stat().st_size > MAX_MANIFEST:
        raise UpdateError("Manifest too large")
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def set_staged_mode(path, mode):
    """Apply staging permissions without changing a shared live-version inode."""
    stat = path.stat()
    if stat.st_mode & 0o777 == mode:
        return
    if stat.st_nlink > 1:
        # A resumed stage can contain hardlinks from an earlier prepare.
        temporary = path.with_name(path.name + '.mode-copy')
        try:
            shutil.copyfile(path, temporary)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    os.chmod(path, mode)


def installed_metadata(root):
    """Cheap display/channel identity; never a substitute for integrity checks.

    Original signed Mac bundles have VERSION/channel metadata, no external
    manifest. Version/channel reads must not inventory gigabytes; verify still checks the staged update.
    """
    root = Path(root)
    path = installed_manifest_path(root)
    original_mac = root.suffix == ".app" and (
        not ID_RE.fullmatch(root.parent.name) and not root.parent.name.endswith(".staging") or not path.exists())
    if not original_mac:
        manifest = read_manifest(root)
        return {key: manifest[key] for key in ("version", "channel", "release_tag") if key in manifest}
    resources = root / "Contents/Resources"
    version_path = resources / "VERSION"
    if version_path.stat().st_size > 128:
        raise UpdateError("Installed version metadata too large")
    version = version_path.read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise UpdateError("Invalid installed version metadata")
    result = {"version": version, "channel": "stable"}
    channel_path = resources / "UPDATE_CHANNEL.json"
    if channel_path.exists():
        if channel_path.stat().st_size > 4096:
            raise UpdateError("Installed channel metadata too large")
        info = json.loads(channel_path.read_text(encoding="utf-8"))
        if not isinstance(info, dict) or release_version(info.get("release_tag"), info.get("channel")) != version:
            raise UpdateError("Installed channel metadata differs")
        result.update(channel=info["channel"], release_tag=info["release_tag"])
    return result


def local_inventory(root):
    """Local baseline only. Remote manifests always pass the full protocol validator."""
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in names:
            p = Path(directory) / name
            if p.is_symlink():
                continue
            files.append({"path": p.relative_to(root).as_posix(), "size": p.stat().st_size, "sha256": file_sha(p)})
    inventory = {"schema": 1, "platform": "macos-arm64", "version": (root / "Contents/Resources/VERSION").read_text().strip(), "files": files}
    metadata = root / "Contents/Resources/UPDATE_CHANNEL.json"
    if metadata.exists():
        info = json.loads(metadata.read_text(encoding="utf-8"))
        inventory.update(channel=info["channel"], release_tag=info["release_tag"])
        if release_version(info["release_tag"], info["channel"]) != inventory["version"]:
            raise UpdateError("Installed channel metadata differs")
    return inventory


@contextlib.contextmanager
def lock(path):
    """Nonblocking cross-process lock. Windows releases it after a crash as well."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if f.tell() == 0:
                f.write(b"0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        f.close()
        raise UpdateError("Another Layered Human operation is still running") from exc
    try:
        yield
    finally:
        f.close()


def trusted_url(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443) or u.hostname not in {
        "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }:
        raise UpdateError("Untrusted update download location")
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubSource:
    def __init__(self, platform=None, channel="stable"):
        if not isinstance(channel, str) or channel not in CHANNELS:
            raise UpdateError("Unsupported update channel")
        from .tls import https_context
        self.opener = urllib.request.build_opener(
            SafeRedirect(), urllib.request.HTTPSHandler(context=https_context()))
        self.urls = {}
        self.platform = platform or ("macos-arm64" if sys.platform == "darwin" else "windows-x64")
        self.channel = channel

    def read(self, url, limit, headers=None, expected_range=None):
        req = urllib.request.Request(trusted_url(url), headers={"User-Agent": "LayeredHuman-Updater/1", **(headers or {})})
        # Diagnostic API credentials must never follow a redirect to asset hosts.
        authorization = req.get_header("Authorization")
        if authorization:
            req.remove_header("Authorization")
            req.add_unredirected_header("Authorization", authorization)
        with self.opener.open(req, timeout=30) as response:
            trusted_url(response.url)
            if expected_range is not None and (response.status != 206 or response.headers.get("Content-Range") != expected_range):
                raise UpdateError("Server does not support incremental downloads; the installed app is unchanged")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise UpdateError("Update response exceeds its expected size")
            return data

    def latest(self):
        if self.channel == "stable":
            release = json.loads(self.read(API, 2 * 1024 * 1024))
            if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                raise UpdateError("Stable updates require a published stable release")
        else:
            releases = json.loads(self.read(RELEASES_API, 8 * 1024 * 1024))
            if not isinstance(releases, list):
                raise UpdateError("Invalid experimental release list")
            names = manifest_names(self.platform)
            candidates = []
            for item in releases:
                if not isinstance(item, dict) or item.get("draft") or item.get("prerelease") is not True:
                    continue
                try:
                    version = release_version(item.get("tag_name"), "experimental")
                except UpdateError:
                    continue  # unrelated prereleases are never experimental feeds
                if any(a.get("name") in names for a in item.get("assets", []) if isinstance(a, dict)):
                    candidates.append((version_tuple(version), item))
            if not candidates:
                return None
            release = max(candidates, key=lambda candidate: candidate[0])[1]
        return self.from_release(release)

    def from_release(self, release):
        if release.get("draft") or bool(release.get("prerelease")) != (self.channel == "experimental"):
            raise UpdateError("Release publication status differs from update channel")
        assets = {a["name"]: a for a in release.get("assets", [])}
        name = next((name for name in manifest_names(self.platform) if name in assets), None)
        if name is None:
            return None  # Older release or Mac-only release. No installer fallback download.
        asset = assets[name]
        tag = release.get("tag_name", "")
        version = release_version(tag, self.channel)
        prefixes = [f"https://github.com/{repo}/releases/download/{tag}/" for repo in TRUSTED_REPOS]
        prefix = next((prefix for prefix in prefixes if asset.get("browser_download_url") == prefix + name), None)
        if prefix is None:
            raise UpdateError("Manifest is not from the trusted repository release")
        digest = asset.get("digest", "")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise UpdateError("GitHub did not provide a manifest integrity digest")
        raw = self.read(asset["browser_download_url"], MAX_MANIFEST)
        if sha(raw) != digest[7:] or len(raw) != asset.get("size"):
            raise UpdateError("Release manifest integrity check failed")
        manifest = validate_manifest(json.loads(raw))
        if (manifest["version"] != version or manifest["platform"] != self.platform or
                manifest_channel(manifest) != self.channel or
                (manifest.get("release_tag") is not None and manifest["release_tag"] != tag)):
            raise UpdateError("Release, manifest or update channel differs")
        for name, size in manifest["packs"].items():
            a = assets.get(name, {})
            if a.get("size") != size or a.get("browser_download_url") != prefix + name:
                raise UpdateError("Missing or untrusted release pack")
            self.urls[name] = prefix + name
        self.manifest_name, self.release_prefix = asset["name"], prefix
        return manifest

    def chunk(self, blob, total):
        start, length = blob["offset"], blob["size"]
        end = start + length - 1
        raw = self.read(self.urls[blob["pack"]], length, {"Range": f"bytes={start}-{end}"}, f"bytes {start}-{end}/{total}")
        if len(raw) != length:
            raise UpdateError("Interrupted update download; retry to resume")
        return raw


def cloudflare_url(url):
    """Only canonical updater routes on the compiled-in HTTPS origin are read."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "downloads.layeredhuman.com" or
                parsed.netloc.lower() not in {"downloads.layeredhuman.com", "downloads.layeredhuman.com:443"} or
                parsed.port not in (None, 443) or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or
                "?" in url or "#" in url or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
            raise ValueError("origin")
        path = parsed.path
        if re.fullmatch(r"/updates/channels/(stable|experimental)\.json", path):
            return url
        if re.fullmatch(r"/updates/packs/[0-9a-f]{64}\.bin", path):
            return url
        match = re.fullmatch(r"/updates/releases/([^/]+)/(windows-x64|macos-arm64)/[0-9a-f]{64}\.json", path)
        if match:
            tag = match[1]
            release_version(tag, "experimental" if "-preview." in tag else "stable")
            return url
    except (TypeError, ValueError) as exc:
        raise UpdateError("Untrusted Cloudflare update download location") from exc
    raise UpdateError("Untrusted Cloudflare update download location")


class CloudflareRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        cloudflare_url(newurl)
        # A content-addressed request must keep its identity at every hop. There
        # is no CDN-host exception or metadata-supplied redirect destination.
        if urlsplit(newurl).path != urlsplit(req.full_url).path:
            raise UpdateError("Cloudflare update redirect changed the requested path")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _update_json(raw):
    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise UpdateError("Duplicate update metadata field")
            value[key] = item
        return value

    try:
        return json.loads(raw, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UpdateError("Invalid update metadata JSON") from exc


def _object_descriptor(value, maximum):
    if (not isinstance(value, dict) or set(value) != {"sha256", "size"} or
            not isinstance(value["sha256"], str) or not HASH_RE.fullmatch(value["sha256"]) or
            type(value["size"]) is not int or not 0 < value["size"] <= maximum):
        raise UpdateError("Invalid content-addressed update object")
    return value


class CloudflareSource:
    """Protocol-1 payloads discovered only through the fixed Cloudflare channel.

    Catalog and manifest bytes are authenticated by hashes obtained over verified
    HTTPS. Pack URLs are derived from catalog hashes; only bounded byte ranges
    are fetched and the existing manifest's raw chunk hashes verify their bytes.
    """
    def __init__(self, platform=None, channel="stable"):
        if not isinstance(channel, str) or channel not in CHANNELS:
            raise UpdateError("Unsupported update channel")
        self.platform = platform or ("macos-arm64" if sys.platform == "darwin" else "windows-x64")
        if self.platform not in {"windows-x64", "macos-arm64"}:
            raise UpdateError("Unsupported update platform")
        from .tls import https_context
        self.opener = urllib.request.build_opener(
            CloudflareRedirect(), urllib.request.HTTPSHandler(context=https_context()))
        self.channel = channel
        self.channel_url = f"{CLOUDFLARE_ORIGIN}/updates/channels/{channel}.json"
        self._reset_release()

    def _reset_release(self):
        self.urls = {}
        self.pack_sizes = {}
        self.catalog_url = self.manifest_url = None
        self.manifest_digest = self.manifest_size = None

    def read(self, url, limit, headers=None, expected_range=None):
        if type(limit) is not int or not 0 < limit <= MAX_MANIFEST:
            raise UpdateError("Invalid update response size limit")
        req = urllib.request.Request(cloudflare_url(url), headers={
            "User-Agent": "LayeredHuman-Updater/1", "Accept-Encoding": "identity", **(headers or {})})
        with self.opener.open(req, timeout=30) as response:
            cloudflare_url(response.url)
            if urlsplit(response.url).path != urlsplit(url).path:
                raise UpdateError("Cloudflare update response changed the requested path")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise UpdateError("Unexpected update response encoding")
            if expected_range is None:
                if response.status != 200:
                    raise UpdateError("Unexpected update metadata response status")
            elif response.status != 206 or response.headers.get("Content-Range") != expected_range:
                raise UpdateError("Server does not support incremental downloads; the installed app is unchanged")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise UpdateError("Update response exceeds its expected size")
            return data

    def latest(self):
        self._reset_release()
        channel = _update_json(self.read(self.channel_url, MAX_CHANNEL))
        if (not isinstance(channel, dict) or type(channel.get("schema")) is not int or
                channel["schema"] != 1 or channel.get("channel") != self.channel or
                not isinstance(channel.get("platforms"), dict)):
            raise UpdateError("Invalid Cloudflare update channel")
        if not channel["platforms"]:
            if set(channel) != {"schema", "channel", "platforms"}:
                raise UpdateError("Invalid empty Cloudflare update channel")
            return None
        if set(channel) != {"schema", "channel", "release_tag", "version", "platforms"}:
            raise UpdateError("Invalid Cloudflare update channel fields")
        tag, version = channel["release_tag"], channel["version"]
        if release_version(tag, self.channel) != version:
            raise UpdateError("Update channel, release tag and version differ")
        for platform, descriptor in channel["platforms"].items():
            if platform not in {"windows-x64", "macos-arm64"}:
                raise UpdateError("Unsupported update platform")
            _object_descriptor(descriptor, MAX_CATALOG)
        selected = channel["platforms"].get(self.platform)
        if selected is None:
            return None
        prefix = f"{CLOUDFLARE_ORIGIN}/updates/releases/{tag}/{self.platform}/"
        self.catalog_url = prefix + selected["sha256"] + ".json"
        raw = self.read(self.catalog_url, selected["size"])
        if len(raw) != selected["size"] or sha(raw) != selected["sha256"]:
            raise UpdateError("Release catalog integrity check failed")
        catalog = _update_json(raw)
        if (not isinstance(catalog, dict) or set(catalog) != {
                "schema", "channel", "platform", "release_tag", "version", "manifest", "packs"} or
                type(catalog.get("schema")) is not int or catalog["schema"] != 1 or
                catalog["channel"] != self.channel or catalog["platform"] != self.platform or
                catalog["release_tag"] != tag or catalog["version"] != version or
                not isinstance(catalog["packs"], dict) or len(catalog["packs"]) > 1000):
            raise UpdateError("Release catalog identity or fields differ")
        descriptor = _object_descriptor(catalog["manifest"], MAX_MANIFEST)
        for name, pack in catalog["packs"].items():
            if not PACK_RE.fullmatch(name):
                raise UpdateError("Invalid catalog pack name")
            _object_descriptor(pack, PACK_SIZE + CHUNK_SIZE)
        self.manifest_url = prefix + descriptor["sha256"] + ".json"
        raw = self.read(self.manifest_url, descriptor["size"])
        if len(raw) != descriptor["size"] or sha(raw) != descriptor["sha256"]:
            raise UpdateError("Release manifest integrity check failed")
        manifest = validate_manifest(_update_json(raw))
        if (manifest["version"] != version or manifest["platform"] != self.platform or
                manifest_channel(manifest) != self.channel or manifest.get("release_tag") != tag):
            raise UpdateError("Release, manifest or update channel differs")
        if manifest["packs"] != {name: pack["size"] for name, pack in catalog["packs"].items()}:
            raise UpdateError("Release catalog and manifest packs differ")
        self.urls = {name: f"{CLOUDFLARE_ORIGIN}/updates/packs/{pack['sha256']}.bin"
                     for name, pack in catalog["packs"].items()}
        self.pack_sizes = dict(manifest["packs"])
        self.manifest_digest, self.manifest_size = descriptor["sha256"], descriptor["size"]
        return manifest

    def chunk(self, blob, total):
        if (not isinstance(blob, dict) or blob.get("pack") not in self.urls or type(total) is not int or
                self.pack_sizes[blob["pack"]] != total or
                any(type(blob.get(key)) is not int for key in ("offset", "size")) or
                not 0 < blob["size"] <= CHUNK_SIZE + 65536 or blob["offset"] < 0 or
                blob["offset"] + blob["size"] > total):
            raise UpdateError("Invalid update chunk request")
        start, length = blob["offset"], blob["size"]
        end = start + length - 1
        raw = self.read(self.urls[blob["pack"]], length, {"Range": f"bytes={start}-{end}"},
                        f"bytes {start}-{end}/{total}")
        if len(raw) != length:
            raise UpdateError("Interrupted update download; retry to resume")
        return raw


def unpack_chunk(raw, size, digest):
    try:
        dec = zlib.decompressobj(31)  # gzip, bounded output; reject bombs/trailing data
        data = dec.decompress(raw, size + 1)
        if len(data) != size or not dec.eof or dec.unused_data or dec.unconsumed_tail or sha(data) != digest:
            raise UpdateError("Downloaded chunk failed integrity verification")
        return data
    except zlib.error as exc:
        raise UpdateError("Corrupt compressed update chunk") from exc


def check_private_inventory(root, manifest, prune=False, allow_runtime_cache=False):
    """Bounded inventory for a private stage/version, never the running app.

    Resumed stages may contain abandoned temporary files. Remove only regular
    extras inside this private directory; never follow a symlink or junction.
    Existing completed versions may have Python's ordinary runtime bytecode.
    """
    root = Path(root)
    mac = manifest["platform"] == "macos-arm64"
    directory = root.parent if mac else root
    def reparse(path):
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    if root.is_symlink() or reparse(root) or directory.is_symlink() or reparse(directory):
        raise UpdateError("Unsafe private update inventory root")
    prefix = root.name + "/" if mac else ""
    expected_files = {prefix + entry["path"] for entry in manifest["files"]}
    expected_files.update(manifest_names(manifest["platform"]))
    expected_links = {prefix + entry["path"] for entry in manifest.get("symlinks", [])}
    expected_dirs = set()
    for name in expected_files | expected_links:
        parts = name.split("/")
        expected_dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
    stack, extras, visited = [directory], [], 0
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                visited += 1
                if visited > MAX_STAGE_ENTRIES:
                    raise UpdateError("Private update inventory exceeds its entry limit")
                path = Path(entry.path)
                name = path.relative_to(directory).as_posix()
                is_link = entry.is_symlink() or reparse(path)
                if is_link:
                    if name not in expected_links or not entry.is_symlink():
                        raise UpdateError("Unexpected link in private update inventory")
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                runtime_cache = False
                if allow_runtime_cache and "__pycache__" in path.parts:
                    parent = name.split("/__pycache__", 1)[0]
                    runtime_cache = (parent in expected_dirs and
                                     (is_dir and name == parent + "/__pycache__" or
                                      not is_dir and name.startswith(parent + "/__pycache__/") and
                                      name.count("/") == parent.count("/") + 2 and name.endswith(".pyc")))
                expected = name in (expected_dirs if is_dir else expected_files) or runtime_cache
                if not expected:
                    if not prune:
                        raise UpdateError("Unexpected file in private update inventory")
                    extras.append((path, is_dir))
                    if len(extras) > MAX_STAGE_PRUNE:
                        raise UpdateError("Private update inventory has too many unexpected entries")
                if is_dir:
                    stack.append(path)
                elif not entry.is_file(follow_symlinks=False):
                    raise UpdateError("Unexpected special file in private update inventory")
    # Walk completely before removing entries, and remove deepest paths first.
    for path, is_dir in reversed(extras):
        if is_dir:
            path.rmdir()
        else:
            path.unlink()


class UpdateStore:
    def __init__(self, base, store):
        self.base, self.root = Path(base).resolve(), Path(store).resolve()
        self.versions = self.root / "versions"
        self.state_file = self.root / "state.json"
        self.mac = self.base.suffix == ".app"

    def state(self):
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(state, dict) or any(state.get(k) is not None and (not isinstance(state[k], str) or not ID_RE.fullmatch(state[k])) for k in ("current", "previous", "pending")):
            return {}
        if (not isinstance(state.get("channel", "stable"), str) or state.get("channel", "stable") not in CHANNELS or
                type(state.get("channel_generation", 0)) is not int or state.get("channel_generation", 0) < 0 or
                (state.get("stable_anchor") is not None and
                 (not isinstance(state["stable_anchor"], str) or not ID_RE.fullmatch(state["stable_anchor"])))):
            return {}
        return state

    def policy(self):
        state = self.state()
        return state.get("channel", "stable"), state.get("channel_generation", 0)

    def set_channel(self, channel):
        """Per-install opt-in; changing policy cancels even an in-flight download.

        Stable return uses protocol-1 rollback, so old immutable launchers can
        activate a lower numeric stable version without replacing the base app.
        """
        if not isinstance(channel, str) or channel not in CHANNELS:
            raise UpdateError("Unsupported update channel")
        with lock(self.root / "state.lock"):
            state = self.state()
            if state.get("channel", "stable") == channel:
                return state
            active_channel = manifest_channel(installed_metadata(self.path(state.get("current"))))
            if channel == "experimental":
                if active_channel == "stable":
                    state["stable_anchor"] = state.get("current")
                elif "stable_anchor" not in state and manifest_channel(installed_metadata(self.base)) != "experimental":
                    raise UpdateError("A retained stable version is needed before enabling previews")
                if state.pop("return_to_stable", False):
                    state.pop("rollback_requested", None)
            elif active_channel == "experimental":
                if "stable_anchor" not in state and manifest_channel(installed_metadata(self.base)) == "experimental":
                    # Fresh separate preview install: its new bootstrap can stage
                    # a lower numeric stable app, rather than rolling to a
                    # nonexistent stable copy. No current process is replaced.
                    state.pop("return_to_stable", None)
                    state.pop("rollback_requested", None)
                elif "stable_anchor" not in state or manifest_channel(installed_metadata(self.path(state["stable_anchor"]))) != "stable":
                    raise UpdateError("The retained stable version is unavailable; the running preview is unchanged")
                else:
                    state.update(previous=state["stable_anchor"], rollback_requested=True, return_to_stable=True)
            state.update(channel=channel, channel_generation=state.get("channel_generation", 0) + 1)
            state.pop("pending", None)
            state.pop("failed", None)
            atomic_json(self.state_file, state)
            return state

    def protect_stable_anchor(self):
        """Pin the anchor BEFORE readiness lets a protocol-1 launcher clean up.

        Old activate() overwrites previous on every preview launch. Pinning it
        here keeps the stable app in the old launcher's own three-entry keep set.
        A failed preview can always roll back to that stable app.
        """
        with lock(self.root / "state.lock"):
            state = self.state()
            if manifest_channel(installed_metadata(self.path(state.get("current")))) != "experimental":
                return
            anchor = state.get("stable_anchor")
            if "stable_anchor" not in state and manifest_channel(installed_metadata(self.base)) == "experimental":
                return  # A fresh preview install has its untouched preview base.
            if "stable_anchor" not in state or manifest_channel(installed_metadata(self.path(anchor))) != "stable":
                raise UpdateError("Preview stable recovery anchor is unavailable")
            if state.get("previous") != anchor:
                state["previous"] = anchor
                atomic_json(self.state_file, state)

    def path(self, ident):
        if ident is None:
            return self.base
        if not ID_RE.fullmatch(ident):
            raise UpdateError("Unsafe version identifier")
        path = self.versions / ident
        if path.is_symlink() or path.resolve().parent != self.versions.resolve():
            raise UpdateError("Unsafe version directory")
        # Private staged folder: immutable Mac launchers require the old name.
        return path / LEGACY_MAC_BUNDLE if self.mac else path

    def active(self):
        return self.path(self.state().get("current"))

    def direct_stable_return(self, installed, target):
        # This path only exists in new preview original installers. Immutable
        # stable protocol-1 launchers use their retained stable anchor instead.
        return (self.policy()[0] == "stable" and manifest_channel(installed) == "experimental" and
                manifest_channel(target) == "stable" and manifest_channel(installed_metadata(self.base)) == "experimental")

    def verify(self, root, manifest=None):
        root = Path(root)
        manifest = manifest or read_manifest(root)
        for e in manifest["files"]:
            p = root / e["path"]
            if p.resolve().is_relative_to(root.resolve()) is False or not p.is_file() or p.stat().st_size != e["size"] or file_sha(p) != e["sha256"]:
                raise UpdateError(f"Application integrity check failed: {e['path']}")
        version_file = "Contents/Resources/VERSION" if self.mac else "_internal/VERSION"
        if (root / version_file).read_text(encoding="utf-8").strip() != manifest["version"]:
            raise UpdateError("Installed version metadata differs")
        metadata_path = root / ("Contents/Resources/UPDATE_CHANNEL.json" if self.mac else "_internal/UPDATE_CHANNEL.json")
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (metadata.get("channel") != manifest_channel(manifest) or
                    metadata.get("release_tag") != manifest.get("release_tag")):
                raise UpdateError("Installed channel metadata differs")
        elif manifest_channel(manifest) == "experimental":
            raise UpdateError("Experimental bundle channel metadata is missing")
        for link in manifest.get("symlinks", []):
            p = root / link["path"]
            if not p.is_symlink() or os.readlink(p) != link["target"] or not p.resolve().is_relative_to(root.resolve()) or not p.exists():
                raise UpdateError("Bundle symlink verification failed")
        if self.mac and sys.platform == "darwin":
            result = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(root)], capture_output=True)
            if result.returncode:
                raise UpdateError("macOS bundle signature verification failed")
        return manifest

    def prepare(self, manifest, source, progress=lambda message: None, policy_token=None):
        """Resume chunks, reuse verified local files/blocks, then publish a pending pointer.

        No live version is overwritten. Hardlinks are used only for unchanged data
        assets; executable/code/runtime files are copied into each immutable version.
        """
        validate_manifest(manifest)
        expected_platform = "macos-arm64" if self.mac else "windows-x64"
        if manifest["platform"] != expected_platform:
            raise UpdateError("Update platform differs from this installation")
        self.root.mkdir(parents=True, exist_ok=True)
        with lock(self.root / "prepare.lock"):
            token = self.policy() if policy_token is None else policy_token
            if self.policy() != token or manifest_channel(manifest) != token[0]:
                raise UpdateError("Update channel changed; this download cannot activate")
            if getattr(source, "channel", token[0]) != token[0]:
                raise UpdateError("Download source differs from selected update channel")
            state = self.state()
            current = self.active()
            installed = installed_metadata(current)
            if state.get("rollback_requested"):
                return {"status": "returning", "downloaded": 0, "reused": 0,
                        "return_to_stable": bool(state.get("return_to_stable"))}
            if (token[0] == "experimental" and "stable_anchor" not in state and
                    manifest_channel(installed_metadata(self.base)) != "experimental"):
                raise UpdateError("Experimental updates require an explicit opt-in and stable recovery anchor")
            if (version_tuple(manifest["version"]) <= version_tuple(installed["version"]) and
                    not self.direct_stable_return(installed, manifest)):
                return {"status": "current", "downloaded": 0, "reused": 0}
            identity = manifest["version"] + "-" + sha(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())[:16]
            final = self.path(identity)
            stage_folder = self.versions / (identity + ".staging")
            stage = stage_folder / LEGACY_MAC_BUNDLE if self.mac else stage_folder
            cache = self.root / "chunks"
            for directory in (self.versions, cache, stage_folder):
                if directory.is_symlink() or directory.resolve().parent != directory.parent.resolve():
                    raise UpdateError("Unsafe update storage directory")
            self.versions.mkdir(exist_ok=True)
            if self.versions.resolve().parent != self.root:
                raise UpdateError("Unsafe versions directory")
            cache.mkdir(exist_ok=True)
            total = sum(e["size"] for e in manifest["files"])
            # Conservative before even creating a stage: full copy plus all raw chunks
            # and a reserve, including on filesystems that cannot hardlink.
            if shutil.disk_usage(self.root).free < total * 2 + 256 * 1024**2:
                raise UpdateError("Not enough disk space to stage and roll back this update")
            downloaded = reused = 0
            stage.mkdir(parents=True, exist_ok=True)
            if stage.is_symlink():
                raise UpdateError("Unsafe staging directory")
            try:
                check_private_inventory(stage, manifest, prune=True)
                for index, e in enumerate(manifest["files"]):
                    progress(f"Preparing {index + 1}/{len(manifest['files'])}")
                    dest, prior = stage / e["path"], current / e["path"]
                    if not dest.resolve().is_relative_to(stage.resolve()):
                        raise UpdateError("Unsafe staging path")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.is_file() and dest.stat().st_size == e["size"] and file_sha(dest) == e["sha256"]:
                        if self.mac:
                            set_staged_mode(dest, e.get("mode", 0o644))
                        reused += e["size"]
                        continue
                    dest.unlink(missing_ok=True)
                    if prior.is_file() and prior.resolve().is_relative_to(current.resolve()) and prior.stat().st_size == e["size"] and file_sha(prior) == e["sha256"]:
                        if e["path"].startswith(("_internal/data/", "_internal/models/", "Contents/Resources/data/", "Contents/Resources/models/")) and (not self.mac or prior.stat().st_mode & 0o777 == e.get("mode", 0o644)):
                            try:
                                os.link(prior, dest)
                            except OSError:
                                shutil.copyfile(prior, dest)
                        else:
                            shutil.copyfile(prior, dest)
                        reused += e["size"]
                        if self.mac:
                            set_staged_mode(dest, e.get("mode", 0o644))
                        continue
                    # Reuse same-offset blocks in an otherwise changed large file.
                    prior_file = open(prior, "rb") if prior.is_file() and prior.resolve().is_relative_to(current.resolve()) else None
                    try:
                        with open(dest, "xb") as out:
                            for chunk_index, digest in enumerate(e["chunks"]):
                                b = manifest["blobs"][digest]
                                block = None
                                if prior_file:
                                    prior_file.seek(chunk_index * CHUNK_SIZE)
                                    candidate = prior_file.read(b["raw_size"])
                                    if sha(candidate) == digest:
                                        block = candidate
                                cp = cache / digest
                                if block is None and cp.is_file():
                                    if cp.stat().st_size == b["raw_size"]:
                                        candidate = cp.read_bytes()
                                        if sha(candidate) == digest:
                                            block = candidate
                                    if block is None:
                                        cp.unlink()
                                if block is None:
                                    packed = source.chunk(b, manifest["packs"][b["pack"]])
                                    block = unpack_chunk(packed, b["raw_size"], digest)
                                    tmp = cp.with_suffix(".part")
                                    tmp.write_bytes(block)
                                    os.replace(tmp, cp)
                                    downloaded += len(packed)
                                else:
                                    reused += len(block)
                                out.write(block)
                            out.flush()
                            os.fsync(out.fileno())
                    finally:
                        if prior_file:
                            prior_file.close()
                    if file_sha(dest) != e["sha256"]:
                        raise UpdateError("Completed file failed integrity verification")
                    if self.mac:
                        set_staged_mode(dest, e.get("mode", 0o644))
                for link in manifest.get("symlinks", []):
                    p = stage / link["path"]
                    if not p.parent.resolve().is_relative_to(stage.resolve()):
                        raise UpdateError("Unsafe bundle symlink destination")
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if p.is_symlink():
                        p.unlink()
                    if p.exists():
                        raise UpdateError("Bundle symlink conflicts with a file")
                    p.symlink_to(link["target"])
                write_manifests(stage, manifest)
                check_private_inventory(stage, manifest)
                self.verify(stage, manifest)
                if final.exists():
                    check_private_inventory(final, manifest, allow_runtime_cache=True)
                    self.verify(final, manifest)
                    shutil.rmtree(stage_folder)
                else:
                    os.replace(stage_folder, final.parent if self.mac else final)
                with lock(self.root / "state.lock"):
                    state = self.state()
                    if (state.get("channel", "stable"), state.get("channel_generation", 0)) != token:
                        return {"status": "cancelled", "downloaded": downloaded, "reused": reused}
                    state["pending"] = identity
                    state.pop("failed", None)
                    atomic_json(self.state_file, state)
                # All chunks are recoverable from the staged version once complete.
                shutil.rmtree(cache, ignore_errors=True)
                return {"status": "ready", "version": manifest["version"], "downloaded": downloaded, "reused": reused}
            except (OSError, ValueError, UpdateError):
                # Keep verified blocks and partial files for retry, never activate them.
                raise

    def activate(self):
        """Called under the session lock, before starting any study process."""
        with lock(self.root / "state.lock"):
            state = self.state()
            pending = state.get("pending")
            if pending:
                manifest = self.verify(self.path(pending))
                if manifest_channel(manifest) != state.get("channel", "stable"):
                    state.pop("pending", None)
                    atomic_json(self.state_file, state)
                    return self.active()
                installed = installed_metadata(self.active())
                if (version_tuple(manifest["version"]) <= version_tuple(installed["version"]) and
                        not self.direct_stable_return(installed, manifest)):
                    state.pop("pending", None)
                else:
                    state.update(previous=state.get("current"), current=pending, trial=True)
                    state.pop("pending", None)
                atomic_json(self.state_file, state)
            return self.active()

    def rollback(self):
        with lock(self.root / "state.lock"):
            state = self.state()
            if state.get("current") is None:
                return False
            previous = state.get("previous")
            self.verify(self.path(previous))
            state.update(current=previous, previous=None, failed=state.get("current"), trial=False)
            state.pop("pending", None)
            state.pop("rollback_requested", None)
            state.pop("return_to_stable", None)
            atomic_json(self.state_file, state)
            return True

    def adopt_newer_base(self):
        """Run a reinstalled original app instead of an older update made for the one it replaced.

        Updates are kept per install location, so dragging a newer release over the app leaves state pointing at
        the version it had updated to before, and that older copy kept launching. When the original now has the
        same channel and at least the active version, the updates are set aside and the original runs; a staged
        version newer than it stays pending."""
        with lock(self.root / "state.lock"):
            state = self.state()
            current = state.get("current")
            if current is None or state.get("trial") or state.get("rollback_requested") or state.get("return_to_stable"):
                return False
            base, active = installed_metadata(self.base), installed_metadata(self.path(current))
            if (manifest_channel(base) != manifest_channel(active) or
                    version_tuple(base["version"]) < version_tuple(active["version"])):
                return False
            state.update(current=None, previous=None)
            atomic_json(self.state_file, state)
            return True

    def replaceable_base(self):
        """The version that could replace the original Mac app, or None.

        Updates run from the update store, so Finder keeps showing the original app in /Applications with its
        old version and icon. Once an update has run healthily, it can be copied over the original instead."""
        if not self.mac or "/AppTranslocation/" in str(self.base):
            return None
        state = self.state()
        current = state.get("current")
        if (current is None or state.get("trial") or state.get("rollback_requested") or
                state.get("return_to_stable") or not os.access(self.base.parent, os.W_OK)):
            return None
        try:
            base, active = installed_metadata(self.base), installed_metadata(self.path(current))
        except (OSError, ValueError, UpdateError):
            return None
        if (manifest_channel(base) != manifest_channel(active) or
                version_tuple(active["version"]) <= version_tuple(base["version"])):
            return None
        return active["version"]

    def replace_base(self, progress=lambda message: None):
        """Copy the running update over the original Mac app, verified, then run the original again.

        The copy is checked file by file against the update's manifest (and its signature on macOS) before the
        swap. The original is set aside, not deleted: its launcher may still be running, so it is removed by the
        next cleanup. Returns the version now installed."""
        version = self.replaceable_base()
        if version is None:
            raise UpdateError("The app in Applications cannot be replaced from here")
        with lock(self.root / "prepare.lock"):
            state = self.state()
            active = self.path(state["current"])
            manifest = read_manifest(active)
            parent = self.base.parent
            staging = parent / f".{self.base.name}.{uuid.uuid4().hex[:12]}.staging"
            try:
                progress(f"Copying version {version}…")
                shutil.copytree(active, staging, symlinks=True)
                progress("Checking the copy…")
                self.verify(staging, manifest)
                retired = self.root / "retired"
                retired.mkdir(parents=True, exist_ok=True)
                old = retired / f"{uuid.uuid4().hex[:12]}.app"
                try:
                    os.rename(self.base, old)
                except OSError:            # another volume: set it aside next to the app
                    old = parent / f".{self.base.name}.{uuid.uuid4().hex[:12]}.replaced"
                    os.rename(self.base, old)
                try:
                    os.rename(staging, self.base)
                except OSError:
                    os.rename(old, self.base)
                    raise
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
            with lock(self.root / "state.lock"):
                state = self.state()
                state.update(current=None, previous=None)
                atomic_json(self.state_file, state)
            with contextlib.suppress(OSError):
                os.utime(self.base)        # Finder and Launch Services pick up the new icon and version
            if sys.platform == "darwin":
                lsregister = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework"
                                  "/Support/lsregister")
                if lsregister.exists():
                    subprocess.run([str(lsregister), "-f", str(self.base)], capture_output=True)
        return version

    def healthy(self):
        with lock(self.root / "state.lock"):
            state = self.state()
            state["trial"] = False
            atomic_json(self.state_file, state)

    def request_rollback(self):
        with lock(self.root / "state.lock"):
            state = self.state()
            if state.get("current") is None:
                raise UpdateError("The original installed version is already active")
            state["rollback_requested"] = True
            # Rollback is an update-policy decision too. Invalidate in-flight
            # preparation and already-queued ready results without changing
            # the user's selected channel or active/previous versions.
            state["channel_generation"] = state.get("channel_generation", 0) + 1
            state.pop("pending", None)
            atomic_json(self.state_file, state)

    def cleanup(self):
        """Only obsolete complete versions; never the base, active, previous or stage."""
        try:
            with lock(self.root / "prepare.lock"):
                state = self.state()
                keep = {state.get(k) for k in ("current", "previous", "pending", "stable_anchor")}
                retired = self.root / "retired"
                if retired.is_dir() and not retired.is_symlink():
                    shutil.rmtree(retired, ignore_errors=True)   # originals replaced by an update (replace_base)
                if not self.versions.exists():
                    return
                for path in self.versions.iterdir():
                    if ID_RE.fullmatch(path.name) and path.name not in keep and not path.is_symlink() and path.resolve().parent == self.versions.resolve():
                        shutil.rmtree(path, ignore_errors=True)
        except UpdateError:
            return  # a preparing version may be complete but not yet published


def store_for(base=None):
    default = Path(sys.executable).parents[2] if sys.platform == "darwin" else Path(sys.executable).parent
    base = Path(base or os.environ.get("AE_INSTALL_BASE") or default).resolve()
    # Separate update stores for separate installs; user/ and Qt settings keep their original locations.
    key = sha(str(base).casefold().encode())[:16]
    local = Path.home() / "Library/Application Support" if sys.platform == "darwin" else Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return UpdateStore(base, local / "AnatomyExplorer" / "updates" / key)


def mark_ready():
    token = os.environ.get("AE_READY_FILE")
    if token:
        store_for().protect_stable_anchor()
        Path(token).write_text("ready", encoding="ascii")


@contextlib.contextmanager
def session_lock(path, wait_seconds=0):
    """Normal launches remain nonblocking; explicit restart may wait briefly."""
    if not 0 <= wait_seconds <= 120:
        raise ValueError("Restart lock wait must be between 0 and 120 seconds")
    deadline = time.monotonic() + wait_seconds
    with contextlib.ExitStack() as stack:
        while True:
            try:
                stack.enter_context(lock(path))
                break
            except UpdateError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        yield


def launch_managed(arguments, *, base=None, wait_seconds=0):
    """Stable installer executable supervises updated children, retaining the original.

    The session lock lasts until *all* windows in that app process close. A downloaded
    version is activated only on a subsequent normal launch, never during a study.
    """
    base = Path(base) if base is not None else (
        Path(sys.executable).parents[2] if sys.platform == "darwin" else Path(sys.executable).parent)
    store = store_for(base)
    store.root.mkdir(parents=True, exist_ok=True)
    with session_lock(store.root / "session.lock", wait_seconds):
        # A prior trial that never reached the UI is also rolled back after a power loss.
        if store.state().get("trial") or store.state().get("rollback_requested"):
            store.rollback()
        try:
            store.adopt_newer_base()
        except (OSError, ValueError, KeyError, UpdateError):
            pass  # an unreadable version label must never stop the app from opening
        try:
            selected = store.activate()
        except (OSError, ValueError, UpdateError) as exc:
            with lock(store.root / "state.lock"):
                state = store.state()
                state["failed"] = state.pop("pending", None)
                state["last_error"] = str(exc)
                atomic_json(store.state_file, state)
            selected = store.active()
        for attempt in range(2):
            ready = store.root / (uuid.uuid4().hex + ".ready")
            env = dict(os.environ, AE_INSTALL_BASE=str(store.base), AE_READY_FILE=str(ready), PYINSTALLER_RESET_ENVIRONMENT="1")
            executable = application_executable(selected, store.mac)
            try:
                child = subprocess.Popen([str(executable), "--ae-managed", *arguments], env=env)
            except OSError:
                if selected == store.base or attempt == 1:
                    raise
                store.rollback()
                selected = store.active()
                continue
            try:
                confirmed = False
                while child.poll() is None:
                    if not confirmed and ready.exists():
                        confirmed = True
                        try:
                            store.healthy()
                            store.cleanup()
                        except (OSError, UpdateError):
                            pass  # bookkeeping must never spawn over a live study process
                    time.sleep(0.25)
                if ready.exists() and not confirmed:
                    confirmed = True
                    try:
                        store.healthy()
                        store.cleanup()
                    except (OSError, UpdateError):
                        pass
                if confirmed or selected == store.base or attempt == 1:
                    return child.returncode
            finally:
                try:
                    ready.unlink(missing_ok=True)
                except OSError:
                    pass
            store.rollback()
            selected = store.active()
        return 1
