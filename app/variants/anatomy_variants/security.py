"""Bounded, fail-closed I/O shared by the external datastore and shipped adapters."""
from __future__ import annotations
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

class StoreValidationError(ValueError):
    """No payload or state with this error may be treated as ready."""

ID = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_JSON = 16 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024 * 1024
MAX_TOTAL = 24 * 1024 * 1024 * 1024
MAX_FILES = 4096

def require(condition, message):
    if not condition:
        raise StoreValidationError(message)

def exact(value, keys, what):
    require(isinstance(value, dict) and set(value) == set(keys), f"{what}: unexpected/missing fields")
    return value

def integer(value, low, high, what):
    require(type(value) is int and low <= value <= high, f"{what}: invalid integer")
    return value

def ident(value, what="identity"):
    require(isinstance(value, str) and ID.fullmatch(value), f"{what}: invalid identity")
    return value

def digest(value, what="sha256"):
    require(isinstance(value, str) and SHA.fullmatch(value), f"{what}: invalid sha256")
    return value

def short_text(value, what, limit=4096):
    require(isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 and c not in '\n\t\r' for c in value), f"{what}: invalid text")
    return value

def relative_path(value):
    require(isinstance(value, str) and 0 < len(value) <= 240 and '\\' not in value and ':' not in value, "invalid relative asset path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and p.as_posix() == value and all(TOKEN.fullmatch(s) and s not in {'.','..'} for s in p.parts), "asset path traversal/unsupported filename")
    # Portable paths must also be legal on Windows.
    reserved = {'CON','PRN','AUX','NUL'} | {f'{s}{n}' for s in ('COM','LPT') for n in range(1,10)}
    require(all(s.split('.')[0].upper() not in reserved and not s.endswith(('.', ' ')) for s in p.parts), "reserved Windows asset path")
    return p

def no_symlinks(path: Path, *, must_exist=True):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            st = part.lstat()
        except FileNotFoundError:
            if part == path and must_exist:
                raise StoreValidationError(f"missing path: {path}")
            continue
        require(not stat.S_ISLNK(st.st_mode), f"symlink path forbidden: {part}")
        require(not (getattr(st, 'st_file_attributes', 0) & 0x400), f"reparse point forbidden: {part}")
    return path

def safe_path(root, rel, *, must_exist=True):
    root = no_symlinks(Path(root))
    p = root.joinpath(*relative_path(rel).parts)
    no_symlinks(p, must_exist=must_exist)
    require(p.is_relative_to(root), "asset escapes root")
    return p

def safe_open(path):
    path = no_symlinks(Path(path))
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "asset must be an ordinary unlinked regular file")
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags)
    current = os.fstat(fd)
    if not stat.S_ISREG(current.st_mode) or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
        os.close(fd)
        raise StoreValidationError("asset changed during open")
    return os.fdopen(fd, 'rb')

def file_hash(path, *, maximum=MAX_FILE):
    h = hashlib.sha256()
    total = 0
    with safe_open(path) as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            require(total <= maximum, "asset exceeds size limit")
            h.update(chunk)
    return h.hexdigest(), total

def _pairs(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, "duplicate JSON key")
        result[k] = v
    return result

def _bound_json(value, depth=0):
    require(depth <= 32, "JSON nesting exceeds bound")
    if isinstance(value, dict):
        require(len(value) <= MAX_FILES, "JSON map exceeds bound")
        for k, v in value.items():
            short_text(k, 'JSON key', 256)
            _bound_json(v, depth + 1)
    elif isinstance(value, list):
        require(len(value) <= 100000, "JSON list exceeds bound")
        for v in value:
            _bound_json(v, depth + 1)
    elif isinstance(value, str):
        require(len(value) <= MAX_JSON, "JSON string exceeds bound")
    elif isinstance(value, float):
        import math
        require(math.isfinite(value), "nonfinite JSON number")

def parse_json(data):
    require(len(data) <= MAX_JSON, "JSON exceeds size bound")
    try:
        result = json.loads(data, object_pairs_hook=_pairs, parse_constant=lambda s: (_ for _ in ()).throw(StoreValidationError("nonfinite JSON")))
        _bound_json(result)
        return result
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        raise StoreValidationError("malformed JSON") from e

def read_json(path):
    with safe_open(path) as f:
        return parse_json(f.read(MAX_JSON + 1))

def canonical_json(value):
    _bound_json(value)
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')

def atomic_json(path, value):
    import uuid
    path = no_symlinks(Path(path), must_exist=False)
    no_symlinks(path.parent)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    payload = canonical_json(value)
    require(len(payload) <= MAX_JSON, "state exceeds size bound")
    try:
        with open(temp, 'xb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fsync_directory(path.parent)
    finally:
        if temp.exists():
            temp.unlink()

def fsync_directory(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
