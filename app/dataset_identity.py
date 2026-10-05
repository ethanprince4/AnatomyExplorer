"""Versioned atlas cache identity, authored at packaging time.

Installed startup validates the small manifest, metadata hashes and file sizes.
Full binary hashes are checked when packaging, not on every installed launch.
This is a coherence contract for an immutable install, not a signature or a
runtime detector for malicious/same-size replacement of its binary files.
"""
import hashlib
import json
import re
import struct
from pathlib import Path
from zipfile import BadZipFile

MANIFEST_NAME = "dataset-manifest.json"
SCHEMA = 1
STAMP_SCHEMA = 2
FILES = ("anatomy/anatomy.json", "anatomy/vertices.bin", "anatomy/indices.bin",
         "findings/findings.json", "findings/findings.npz")
OPTIONAL = frozenset(FILES[-2:])


class DatasetIdentityError(ValueError):
    """The installed atlas or packaging stage is incomplete/incompatible."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_id(files):
    return hashlib.sha256(_canonical({"schema": SCHEMA, "files": files})).hexdigest()


def build_manifest(data_dir):
    """Hash source bytes once per package build; never change the source files."""
    root = Path(data_dir).parent
    files = {}
    for key in FILES:
        path = root / key
        if key in OPTIONAL and not path.exists():
            files[key] = None
            continue
        if not path.is_file():
            raise DatasetIdentityError(f"Required atlas input is missing: {key}")
        before = path.stat()
        digest = file_hash(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise DatasetIdentityError(f"Atlas input changed during hashing: {key}")
        files[key] = {"size": after.st_size, "sha256": digest}
    if (files[FILES[-2]] is None) != (files[FILES[-1]] is None):
        raise DatasetIdentityError("Findings metadata and geometry must be packaged together")
    return {"schema": SCHEMA, "files": files, "content_id": _content_id(files)}


def read_manifest(data_dir, path=None, *, verify_content=False):
    """Validate metadata cheaply at runtime; full content validation is opt-in."""
    data_dir = Path(data_dir)
    path = Path(path) if path is not None else data_dir / MANIFEST_NAME
    try:
        if path.stat().st_size > 64 * 1024:
            raise DatasetIdentityError("Atlas identity manifest is unexpectedly large")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(doc, dict) or set(doc) != {"schema", "files", "content_id"}
                or type(doc["schema"]) is not int or doc["schema"] != SCHEMA):
            raise DatasetIdentityError("Unsupported atlas identity manifest schema")
        files = doc["files"]
        if not isinstance(files, dict) or set(files) != set(FILES):
            raise DatasetIdentityError("Atlas identity manifest has an incompatible file inventory")
        for key, record in files.items():
            if key in OPTIONAL and record is None:
                continue
            if (not isinstance(record, dict) or set(record) != {"size", "sha256"}
                    or type(record["size"]) is not int or record["size"] < 0
                    or not isinstance(record["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None):
                raise DatasetIdentityError(f"Invalid atlas identity record: {key}")
        if (files[FILES[-2]] is None) != (files[FILES[-1]] is None):
            raise DatasetIdentityError("Findings metadata and geometry must be packaged together")
        if doc["content_id"] != _content_id(files):
            raise DatasetIdentityError("Atlas identity manifest content ID does not match its inventory")
        for key, record in files.items():
            source = data_dir.parent / key
            if record is None:
                if source.exists():
                    raise DatasetIdentityError(f"Unrecorded atlas input is present: {key}")
                continue
            if not source.is_file() or source.stat().st_size != record["size"]:
                raise DatasetIdentityError(f"Atlas input is missing or has the wrong size: {key}")
            if (verify_content or source.suffix == ".json") and file_hash(source) != record["sha256"]:
                raise DatasetIdentityError(f"Atlas input does not match its manifest: {key}")
        return doc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetIdentityError(f"Cannot read atlas identity manifest {path.name}: {exc}") from exc


def _words(digest):
    return list(struct.unpack("<4q", bytes.fromhex(digest)))


def installed_stamp(ds, content_id):
    """Include the loaded mapping, so geometry slices cannot borrow other IDs' caches."""
    mapping = [(s["id"], s["i_start"], s["i_count"], s["system"]) for s in ds.structures]
    semantic = hashlib.sha256(_canonical(mapping)).hexdigest()
    return [STAMP_SCHEMA, *_words(content_id), *_words(semantic)]


def source_stamp(ds):
    paths = [ds.dir / "vertices.bin", ds.dir / "indices.bin", ds.dir / "anatomy.json"]
    if getattr(ds, "findings", None) is not None:
        paths.extend([ds.findings.path / "findings.npz", ds.findings.path / "findings.json"])
    stamp = [STAMP_SCHEMA, -1]
    for path in paths:
        if path.name.endswith(".json") and not path.exists():
            # Small programmatic/test datasets do not necessarily use sidecars.
            stamp.extend((0, 0))
        else:
            info = path.stat()
            stamp.extend((info.st_size, info.st_mtime_ns))
    mapping = [(s["id"], s["i_start"], s["i_count"], s["system"]) for s in ds.structures]
    stamp.extend(_words(hashlib.sha256(_canonical(mapping)).hexdigest()))
    return stamp


def validate_staged(data_dir, stage_dir):
    """Fail closed before bundling a stale, mixed or incomplete atlas stage."""
    import numpy as np
    from .cache_io import format_matches
    from .data import Dataset
    from .depth import FORMAT as depth_format
    from .relations import SAMPLE_FORMAT

    stage_dir = Path(stage_dir)
    doc = read_manifest(data_dir, stage_dir / MANIFEST_NAME, verify_content=True)
    ds = Dataset(Path(data_dir))
    stamp = np.array(installed_stamp(ds, doc["content_id"]), dtype=np.int64)
    for name, version in (("samples.npz", SAMPLE_FORMAT), ("depth.npz", depth_format)):
        try:
            with (stage_dir / name).open("rb") as stream, np.load(stream, allow_pickle=False) as archive:
                if not np.array_equal(archive["stamp"], stamp) or not format_matches(archive["format"], version):
                    raise DatasetIdentityError(f"Staged {name} belongs to a different dataset/cache schema")
                if name == "samples.npz":
                    points, offsets = archive["points"], archive["offsets"]
                    valid = (points.ndim == 2 and points.shape[1] == 3 and points.dtype.kind == "f"
                             and np.isfinite(points).all() and offsets.shape == (ds.n + 1,)
                             and offsets.dtype.kind in "iu" and offsets[0] == 0
                             and offsets[-1] == len(points) and np.all(offsets[1:] >= offsets[:-1]))
                else:
                    relative, absolute = archive["depth"], archive["absolute"]
                    valid = (relative.shape == absolute.shape == (ds.n,)
                             and relative.dtype.kind == absolute.dtype.kind == "f"
                             and np.isfinite(relative).all() and np.isfinite(absolute).all()
                             and np.all((relative >= -1) & (relative <= 1.2)) and np.all(absolute >= -1))
                if not valid:
                    raise DatasetIdentityError(f"Staged {name} contains invalid cache arrays")
        except (OSError, ValueError, KeyError, EOFError, BadZipFile) as exc:
            raise DatasetIdentityError(f"Invalid atlas package stage ({name}): {exc}") from exc
    return doc
