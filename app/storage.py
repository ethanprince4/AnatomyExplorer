"""Study-file reads and atomic saves, preserving damaged originals on recovery."""
import datetime
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path


def load_json(path, normalize):
    """Return usable data and whether the original needs backing up before saving."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return normalize(None), path.exists()
    data = normalize(raw)
    return data, data != raw


def write_json(path, data, *, indent=1, backup=False):
    """Replace a JSON file only after serialization and its temporary write succeed."""
    text = json.dumps(data, indent=indent, ensure_ascii=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if backup and path.exists():
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            original = path.with_name(f"{path.name}.recovery-{stamp}-{uuid.uuid4().hex[:8]}.bak")
            with path.open("rb") as source, original.open("xb") as destination:
                shutil.copyfileobj(source, destination)
        temporary.replace(path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
