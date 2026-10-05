"""Collect an explicitly selected portable model library for a release seed.

No geometry rebuilding or model lineage certification happens here. The runtime
uses this read-only seed only when an external library is unavailable.
"""
import json
from pathlib import Path


def seed_files(directory):
    root = Path(directory).resolve()
    manifest = root / "library.json"
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    rows = data.get("models", [])
    rows = rows.values() if isinstance(rows, dict) else rows
    for row in rows:
        for value in row.get("variants", {}).values():
            path = value if isinstance(value, str) else value["path"]
            asset = Path(path)
            if asset.is_absolute() or not (root / asset).resolve().is_relative_to(root):
                raise ValueError(f"Release model paths must be relative to the library: {path}")
            if not (root / asset).is_file():
                raise FileNotFoundError(root / asset)
    result = []
    for source in sorted(root.rglob("*")):
        relative = source.relative_to(root)
        if any(p.startswith(".") or p == "__pycache__" for p in relative.parts):
            continue
        if source.name in {"preferences.json", "preferences.pending.json"}:
            continue
        if source.is_file():
            if not source.resolve().is_relative_to(root):
                raise ValueError(f"Release seed link escapes its folder: {relative}")
            result.append((str(source), str(Path("data/local_model_library") / relative.parent)))
    return result
