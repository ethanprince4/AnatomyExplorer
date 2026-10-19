"""Optional portable LOD arrays; exact full geometry remains the source of truth."""
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from . import lod


SCHEMA = 'anatomy.native-lod.v1'


def constants():
    return {name: getattr(lod, name) for name in ('LEVELS', 'MIN_TRIANGLES', 'MIN_KEEP', 'MIN_GAIN', '_BITS', 'REFERENCE_PIXELS')}


def digest(path, check=None):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            if check:
                check()
            result.update(block)
    return result.hexdigest()


def part_layout(model):
    return [[int(part.id), str(part.name), int(part.first), int(part.count), int(part.vertex_base), int(part.vertex_count)]
            for part in model.parts]


def load(model, bundle, source, companions, check=None):
    """Raise on stale/unsafe arrays; the local loader then uses its ordinary path."""
    maximum = max(int(model.indices.size) * lod.LEVELS * 4 + 4 * 1024 * 1024, 4 * 1024 * 1024)
    with zipfile.ZipFile(bundle) as archive:
        if sum(item.file_size for item in archive.infolist()) > maximum:
            raise ValueError('Precomputed LOD exceeds the original geometry allocation bound')
        if len({item.filename for item in archive.infolist()}) != len(archive.infolist()):
            raise ValueError('Repeated precomputed LOD archive entries')
    with np.load(bundle, allow_pickle=False) as archive:
        raw = archive['meta']
        if raw.dtype != np.uint8 or raw.ndim != 1 or raw.size > 4 * 1024 * 1024:
            raise ValueError('Precomputed LOD metadata encoding differs')
        metadata = json.loads(raw.tobytes().decode('utf-8'))
        if not isinstance(metadata, dict):
            raise ValueError('Precomputed LOD metadata must be an object')
        if metadata.get('schema') != SCHEMA or metadata.get('algorithm_constants') != constants():
            raise ValueError('Precomputed LOD algorithm identity differs')
        if metadata.get('source_sha256') != digest(source, check):
            raise ValueError('Precomputed LOD geometry checksum differs')
        expected = metadata.get('companion_sha256', {})
        if 'viewer' not in expected or set(expected) != set(companions):
            raise ValueError('Precomputed LOD companion binding differs')
        if any(expected[role] != digest(path, check) for role, path in companions.items()):
            raise ValueError('Precomputed LOD companion checksum differs')
        if metadata.get('part_layout') != part_layout(model) or metadata.get('vertex_count') != len(model.vertices) or metadata.get('index_count') != int(model.indices.size):
            raise ValueError('Precomputed LOD native primitive layout differs')
        parts = {part.id: part for part in model.parts}
        result, names = {}, {'meta'}
        for row in metadata.get('parts', []):
            if check:
                check()
            part_id = row['part_id']
            if type(part_id) is not int or part_id not in parts or part_id in result:
                raise ValueError('Precomputed LOD part identity differs')
            part = parts[part_id]
            cells = np.asarray(row['cells'], dtype=np.float64)
            keys = row['arrays']
            if cells.shape != (lod.LEVELS,) or len(keys) != lod.LEVELS or not np.isfinite(cells).all() or np.any(cells <= 0) or np.any(np.diff(cells) < 0):
                raise ValueError('Precomputed LOD levels are invalid')
            indices = []
            for key in keys:
                if not isinstance(key, str) or key == 'meta' or key in names:
                    raise ValueError('Precomputed LOD array identity differs')
                names.add(key)
                values = archive[key]
                if values.dtype != np.uint32 or values.ndim != 1 or values.size < 3 * lod.MIN_KEEP or values.size > part.count or values.size % 3:
                    raise ValueError('Precomputed LOD triangle array shape differs')
                if int(values.min()) < part.vertex_base or int(values.max()) >= part.vertex_base + part.vertex_count:
                    raise ValueError('Precomputed LOD crosses its original primitive vertex range')
                triangles = values.reshape(-1, 3)
                if np.any((triangles[:, 0] == triangles[:, 1]) | (triangles[:, 1] == triangles[:, 2]) | (triangles[:, 0] == triangles[:, 2])):
                    raise ValueError('Precomputed LOD contains collapsed triangles')
                indices.append(np.ascontiguousarray(values))
            result[part_id] = lod.PartLod(cells, indices)
        if set(archive.files) != names:
            raise ValueError('Precomputed LOD contains unowned arrays')
    return result
