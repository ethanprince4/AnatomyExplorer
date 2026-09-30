"""Windows updater protocol 1. Standard library only; also used by the stable launcher.

Trust root: HTTPS GitHub API for this *fixed* repository, its asset digest, then the
manifest's SHA-256 file/chunk hashes. No credentials, shell commands or remote code
are accepted by the protocol. Installation files and study data are never changed.
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

REPO = "ethanprince4/AnatomyExplorer"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
MANIFEST = "AnatomyExplorer-Windows-update.json"
MAC_MANIFEST = "AnatomyExplorer-macOS-update.json"
CHUNK_SIZE = 4 * 1024 * 1024
PACK_SIZE = 64 * 1024 * 1024
MAX_MANIFEST = 16 * 1024 * 1024
MAX_TOTAL = 20 * 1024**3
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ID_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{16}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
PACK_RE = re.compile(r"AnatomyExplorer-(Windows|macOS)-pack-[0-9]{4}\.bin")


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
    elif parts[0] not in {"_internal", "AnatomyExplorer.exe", "LICENSE.txt", "THIRD_PARTY_LICENSES.md"}:
        raise UpdateError("Update attempted to write outside the application")
    if platform != "macos-arm64" and parts[0] != "_internal" and len(parts) != 1:
        raise UpdateError("Invalid application file")
    if any(p.casefold() in {"user", "logs", "updates", "__pycache__"} for p in parts):
        raise UpdateError("Personal or mutable files must not be shipped")
    return value


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("platform") not in {"windows-x64", "macos-arm64"} or data.get("launcher") != 1:
        raise UpdateError("This update needs a newer installer")
    version_tuple(data.get("version"))
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


def read_manifest(root):
    root = Path(root)
    path = manifest_path(root)
    if root.suffix == ".app" and (not ID_RE.fullmatch(root.parent.name) and not root.parent.name.endswith(".staging") or not path.exists()):
        # Initial DMG install: inventory signed bytes locally, with no extra file
        # inserted into the signed bundle (that would break its resource seal).
        return local_inventory(root)
    if path.stat().st_size > MAX_MANIFEST:
        raise UpdateError("Manifest too large")
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


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
    return {"schema": 1, "platform": "macos-arm64", "version": (root / "Contents/Resources/VERSION").read_text().strip(), "files": files}


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
        raise UpdateError("Another Anatomy Explorer operation is still running") from exc
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
    def __init__(self, platform=None):
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.urls = {}
        self.platform = platform or ("macos-arm64" if sys.platform == "darwin" else "windows-x64")

    def read(self, url, limit, headers=None, expected_range=None):
        req = urllib.request.Request(trusted_url(url), headers={"User-Agent": "AnatomyExplorer-Updater/1", **(headers or {})})
        with self.opener.open(req, timeout=30) as response:
            trusted_url(response.url)
            if expected_range is not None and (response.status != 206 or response.headers.get("Content-Range") != expected_range):
                raise UpdateError("Server does not support incremental downloads; the installed app is unchanged")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise UpdateError("Update response exceeds its expected size")
            return data

    def latest(self):
        release = json.loads(self.read(API, 2 * 1024 * 1024))
        if release.get("draft") or release.get("prerelease"):
            raise UpdateError("Only stable releases are supported")
        assets = {a["name"]: a for a in release.get("assets", [])}
        name = MAC_MANIFEST if self.platform == "macos-arm64" else MANIFEST
        if name not in assets:
            return None  # Older release or Mac-only release. No installer fallback download.
        asset = assets[name]
        tag = release.get("tag_name", "")
        version = tag[1:] if tag.startswith("v") else tag
        version_tuple(version)
        prefix = f"https://github.com/{REPO}/releases/download/{tag}/"
        if asset.get("browser_download_url") != prefix + name:
            raise UpdateError("Manifest is not from the trusted repository release")
        digest = asset.get("digest", "")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise UpdateError("GitHub did not provide a manifest integrity digest")
        raw = self.read(asset["browser_download_url"], MAX_MANIFEST)
        if sha(raw) != digest[7:] or len(raw) != asset.get("size"):
            raise UpdateError("Release manifest integrity check failed")
        manifest = validate_manifest(json.loads(raw))
        if manifest["version"] != version or manifest["platform"] != self.platform:
            raise UpdateError("Release and manifest versions differ")
        for name, size in manifest["packs"].items():
            a = assets.get(name, {})
            if a.get("size") != size or a.get("browser_download_url") != prefix + name:
                raise UpdateError("Missing or untrusted release pack")
            self.urls[name] = prefix + name
        return manifest

    def chunk(self, blob, total):
        start, length = blob["offset"], blob["size"]
        end = start + length - 1
        raw = self.read(self.urls[blob["pack"]], length, {"Range": f"bytes={start}-{end}"}, f"bytes {start}-{end}/{total}")
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
        return state

    def path(self, ident):
        if ident is None:
            return self.base
        if not ID_RE.fullmatch(ident):
            raise UpdateError("Unsafe version identifier")
        path = self.versions / ident
        if path.is_symlink() or path.resolve().parent != self.versions.resolve():
            raise UpdateError("Unsafe version directory")
        return path / "Anatomy Explorer.app" if self.mac else path

    def active(self):
        return self.path(self.state().get("current"))

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
        for link in manifest.get("symlinks", []):
            p = root / link["path"]
            if not p.is_symlink() or os.readlink(p) != link["target"] or not p.resolve().is_relative_to(root.resolve()) or not p.exists():
                raise UpdateError("Bundle symlink verification failed")
        if self.mac and sys.platform == "darwin":
            result = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(root)], capture_output=True)
            if result.returncode:
                raise UpdateError("macOS bundle signature verification failed")
        return manifest

    def prepare(self, manifest, source, progress=lambda message: None):
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
            current = self.active()
            installed = read_manifest(current)
            if version_tuple(manifest["version"]) <= version_tuple(installed["version"]):
                return {"status": "current", "downloaded": 0, "reused": 0}
            identity = manifest["version"] + "-" + sha(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())[:16]
            final = self.path(identity)
            stage_folder = self.versions / (identity + ".staging")
            stage = stage_folder / "Anatomy Explorer.app" if self.mac else stage_folder
            cache = self.root / "chunks"
            self.versions.mkdir(exist_ok=True)
            cache.mkdir(exist_ok=True)
            old = {e["path"]: e for e in installed["files"]}
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
                for index, e in enumerate(manifest["files"]):
                    progress(f"Preparing {index + 1}/{len(manifest['files'])}")
                    dest, prior = stage / e["path"], current / e["path"]
                    if not dest.resolve().is_relative_to(stage.resolve()):
                        raise UpdateError("Unsafe staging path")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.is_file() and dest.stat().st_size == e["size"] and file_sha(dest) == e["sha256"]:
                        if self.mac:
                            os.chmod(dest, e.get("mode", 0o644))
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
                            os.chmod(dest, e.get("mode", 0o644))
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
                        os.chmod(dest, e.get("mode", 0o644))
                for link in manifest.get("symlinks", []):
                    p = stage / link["path"]
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if p.is_symlink():
                        p.unlink()
                    if p.exists():
                        raise UpdateError("Bundle symlink conflicts with a file")
                    p.symlink_to(link["target"])
                atomic_json(manifest_path(stage), manifest)
                self.verify(stage, manifest)
                if final.exists():
                    self.verify(final, manifest)
                    shutil.rmtree(stage_folder)
                else:
                    os.replace(stage_folder, final.parent if self.mac else final)
                with lock(self.root / "state.lock"):
                    state = self.state()
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
                self.verify(self.path(pending))
                if version_tuple(read_manifest(self.path(pending))["version"]) <= version_tuple(read_manifest(self.active())["version"]):
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
            atomic_json(self.state_file, state)
            return True

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
            atomic_json(self.state_file, state)

    def cleanup(self):
        """Only obsolete complete versions; never the base, active, previous or stage."""
        state = self.state()
        keep = {state.get(k) for k in ("current", "previous", "pending")}
        if not self.versions.exists():
            return
        for path in self.versions.iterdir():
            if ID_RE.fullmatch(path.name) and path.name not in keep and not path.is_symlink() and path.resolve().parent == self.versions.resolve():
                shutil.rmtree(path, ignore_errors=True)


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
        Path(token).write_text("ready", encoding="ascii")


def launch_managed(arguments):
    """Stable installer executable supervises updated children, retaining the original.

    The session lock lasts until *all* windows in that app process close. A downloaded
    version is activated only on a subsequent normal launch, never during a study.
    """
    base = Path(sys.executable).parents[2] if sys.platform == "darwin" else Path(sys.executable).parent
    store = store_for(base)
    store.root.mkdir(parents=True, exist_ok=True)
    with lock(store.root / "session.lock"):
        # A prior trial that never reached the UI is also rolled back after a power loss.
        if store.state().get("trial") or store.state().get("rollback_requested"):
            store.rollback()
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
            try:
                executable = selected / ("Contents/MacOS/AnatomyExplorer" if store.mac else "AnatomyExplorer.exe")
                child = subprocess.Popen([str(executable), "--ae-managed", *arguments], env=env)
                confirmed = False
                while child.poll() is None:
                    if not confirmed and ready.exists():
                        store.healthy()
                        store.cleanup()
                        confirmed = True
                    time.sleep(0.25)
                if ready.exists() and not confirmed:
                    store.healthy()
                    store.cleanup()
                    confirmed = True
                if confirmed or selected == store.base or attempt == 1:
                    return child.returncode
            except OSError:
                if selected == store.base or attempt == 1:
                    raise
            finally:
                ready.unlink(missing_ok=True)
            store.rollback()
            selected = store.active()
        return 1
