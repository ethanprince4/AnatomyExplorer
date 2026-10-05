"""Read-only package inventory checks shared by prebuild and spec collection.

This verifies required identity, portable included paths, the GLB envelope and
JSON sidecar presence. Prebuild still decodes geometry through the viewer's CPU
reader. No Qt widgets, OpenGL objects, builders or source writes belong here.
"""
import json
from pathlib import Path, PureWindowsPath
import struct

REQUIRED_MODEL_IDS = frozenset({'whole_heart', 'cardiac_muscle', 'kidney_nephron'})


def required_model_metadata(folder, *, required_ids=()):
    folder = Path(folder)
    paths = sorted(folder.glob('*.json')) if folder.is_dir() else []
    if not paths:
        raise RuntimeError(f'No required in-house model metadata found in {folder}')
    records, seen = [], set()
    for path in paths:
        try:
            meta = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError(f'Required model metadata is unreadable: {path.name}') from exc
        if (not isinstance(meta, dict) or not isinstance(meta.get('id'), str) or not meta['id'].strip()
                or not isinstance(meta.get('file'), str) or not meta['file'].strip()):
            raise RuntimeError(f'Required model metadata needs a nonempty id and file: {path.name}')
        if meta['id'] in seen:
            raise RuntimeError(f'Duplicate in-house model identity: {meta["id"]}')
        seen.add(meta['id'])
        records.append(meta)
    missing = set(required_ids) - seen
    if missing:
        raise RuntimeError('Missing required in-house model metadata: ' + ', '.join(sorted(missing)))
    return records


def validate_required_models(root, *, metadata_dir=None, required_ids=REQUIRED_MODEL_IDS):
    """Validate every declared pair before any geometry decode or collection.

    Explicit required IDs cannot disappear just because a metadata file was
    omitted. Additional well-formed models remain supported. Tests can provide
    a bounded synthetic inventory without changing production requirements.
    """
    root = Path(root).resolve()
    folder = Path(metadata_dir) if metadata_dir is not None else root / 'data/content/models'
    records = required_model_metadata(folder, required_ids=required_ids)
    seen = set()
    for meta in records:
        relative = Path(meta['file'])
        if (relative.is_absolute() or PureWindowsPath(meta['file']).drive or '\\' in meta['file']
                or '..' in relative.parts or relative.suffix.lower() != '.glb'
                or relative.parts[:1] != ('models',) and relative.parts[:2] != ('data', 'models')):
            raise RuntimeError(f'Required model path is outside packaged model folders: {meta["file"]}')
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError(f'Required model path leaves the package: {meta["file"]}')
        if path in seen:
            raise RuntimeError(f'Duplicate required model asset path: {meta["file"]}')
        seen.add(path)
        try:
            size = path.stat().st_size
            with path.open('rb') as stream:
                header = stream.read(12)
            if size <= 1024 or len(header) != 12:
                raise ValueError('missing geometry or Git LFS pointer')
            magic, version, length = struct.unpack('<4sII', header)
            if magic != b'glTF' or version != 2 or length != size:
                raise ValueError('invalid or truncated GLB envelope')
        except (OSError, ValueError) as exc:
            raise RuntimeError(f'Required model geometry is missing or invalid: {path}: {exc}') from exc
        sidecar = path.with_suffix('.viewer.json')
        try:
            doc = json.loads(sidecar.read_text(encoding='utf-8'))
            if not isinstance(doc, dict):
                raise ValueError('expected a JSON object')
        except (OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError(f'Required model sidecar is missing or unreadable: {sidecar}') from exc
    return records
