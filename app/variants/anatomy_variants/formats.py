"""Pure-stdlib structural inspectors. Never unpickle NPZs or execute dataset code."""
from __future__ import annotations
import ast
import hashlib
import math
import re
import struct
import zipfile
from pathlib import Path
from .security import MAX_JSON, MAX_TOTAL, StoreValidationError, canonical_json, integer, parse_json, require, safe_open

NPY_TYPES = {'|u1': ('B',1), '|i1': ('b',1), '<u2': ('H',2), '<i2': ('h',2), '<u4': ('I',4), '<i4': ('i',4), '<u8': ('Q',8), '<i8': ('q',8), '<f2': ('e',2), '<f4': ('f',4), '<f8': ('d',8), '|b1': ('?',1)}
MAX_ARRAYS = 8192
MAX_ELEMENTS = 150_000_000
MAX_EXPANDED = 8 * 1024 * 1024 * 1024


def _npy_header(stream, *, allow_scalar=False, max_elements=MAX_ELEMENTS):
    require(stream.read(6) == b'\x93NUMPY', 'invalid NPY magic')
    version = stream.read(2)
    require(version in {b'\x01\x00', b'\x02\x00', b'\x03\x00'}, 'unsupported NPY version')
    n = 2 if version == b'\x01\x00' else 4
    raw = stream.read(n)
    require(len(raw) == n, 'truncated NPY header')
    length = int.from_bytes(raw, 'little')
    require(0 < length <= 65536, 'oversized NPY header')
    header = stream.read(length)
    require(len(header) == length, 'truncated NPY header')
    try:
        data = ast.literal_eval(header.decode('utf-8' if version == b'\x03\x00' else 'latin1'))
    except (ValueError, SyntaxError, UnicodeDecodeError, RecursionError) as e:
        raise StoreValidationError('malformed NPY header') from e
    require(isinstance(data, dict) and set(data) == {'descr', 'fortran_order', 'shape'}, 'unsupported NPY header schema')
    dtype, shape = data['descr'], data['shape']
    require(dtype in NPY_TYPES and data['fortran_order'] is False, 'object/structured/big-endian/Fortran NPY forbidden')
    require(isinstance(shape, tuple) and (0 <= len(shape) <= 4 if allow_scalar else 0 < len(shape) <= 4), 'invalid NPY shape')
    count = 1
    for d in shape:
        integer(d, 0, max_elements, 'NPY dimension')
        count *= d
    require(count <= max_elements, 'NPY element limit exceeded')
    return dtype, shape, count * NPY_TYPES[dtype][1], 8 + n + length


def _zip_members(z):
    infos = z.infolist()
    require(0 < len(infos) <= MAX_ARRAYS, 'NPZ member limit exceeded')
    names = [i.filename for i in infos]
    require(len(names) == len(set(names)), 'duplicate NPZ member')
    require(sum(i.file_size for i in infos) <= MAX_EXPANDED, 'NPZ decompressed limit exceeded')
    for i in infos:
        require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,95}\.npy', i.filename) is not None, 'NPZ member path forbidden')
        require(i.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} and not i.flag_bits & 1, 'unsupported NPZ compression/encryption')
        require(i.file_size <= MAX_EXPANDED and i.file_size <= max(i.compress_size, 1) * 10000, 'NPZ decompression ratio exceeded')
    return {i.filename[:-4]: i for i in infos}



def expanded_npz_size(path):
    """Central-directory bounded size accounting; inspect_npz still validates all bytes."""
    with safe_open(path) as f:
        try:
            with zipfile.ZipFile(f) as z:
                return sum(info.file_size for info in _zip_members(z).values())
        except zipfile.BadZipFile as e:
            raise StoreValidationError('invalid NPZ archive') from e


def inspect_npz(path, *, native_v4=False):
    """Return format-bound geometry digest; generic sidecars get structural checks only."""
    with safe_open(path) as f:
        try:
            with zipfile.ZipFile(f) as z:
                members = _zip_members(z)
                headers = {}
                for name, info in members.items():
                    with z.open(info) as s:
                        dtype, shape, size, header_size = _npy_header(s)
                        require(size + header_size == info.file_size, 'NPY declared byte size mismatch')
                        headers[name] = (dtype, shape)
                        # Consume all entries to check CRC and prohibit truncated arrays.
                        total = 0
                        while chunk := s.read(1024 * 1024):
                            total += len(chunk)
                        require(total == size, 'truncated NPY array')
                if not native_v4:
                    return None
                require('meta' in members and headers['meta'][0] == '|u1' and len(headers['meta'][1]) == 1 and headers['meta'][1][0] <= MAX_JSON, 'native v4 meta missing/invalid')
                with z.open(members['meta']) as s:
                    _npy_header(s)
                    metadata = parse_json(s.read(MAX_JSON + 1))
                require(isinstance(metadata, dict) and set(metadata) == {'digest', 'parts'}, 'native v4 metadata schema mismatch')
                require(isinstance(metadata['digest'], str) and len(metadata['digest']) <= 128, 'invalid native source digest')
                parts = metadata['parts']
                require(isinstance(parts, list) and 0 < len(parts) <= 1024, 'native v4 parts missing/excessive')
                require(set(members) == {'meta'} | {f'{k}{i}' for i in range(len(parts)) for k in 'bpni'}, 'native v4 arrays incomplete/unrecognized')
                h = hashlib.sha256(b'anatomy-npz-v4-geometry\0')
                for i, part in enumerate(parts):
                    require(isinstance(part, dict) and isinstance(part.get('name'), str), 'invalid native part metadata')
                    vertices = headers[f'p{i}'][1][0]
                    require(vertices > 0 and headers[f'p{i}'] == ('<u2', (vertices, 3)), 'native positions must be Nx3 uint16')
                    require(headers[f'n{i}'] == ('|i1', (vertices, 3)), 'native normals must be Nx3 int8')
                    require(headers[f'b{i}'] == ('<f8', (2,3)), 'native bounds must be 2x3 float64')
                    dtype, shape = headers[f'i{i}']
                    require(dtype == '<i4' and len(shape) == 1 and shape[0] > 0 and shape[0] % 3 == 0, 'native index deltas must be triangle int32')
                    with z.open(members[f'b{i}']) as s:
                        _npy_header(s)
                        bounds = struct.unpack('<6d', s.read(48))
                    require(all(math.isfinite(v) for v in bounds) and all(v > 0 for v in bounds[3:]), 'invalid native quantization bounds')
                    acc = 0
                    with z.open(members[f'i{i}']) as s:
                        _npy_header(s)
                        while chunk := s.read(1024 * 1024):
                            for (delta,) in struct.iter_unpack('<i', chunk):
                                acc += delta
                                require(0 <= acc < vertices, 'native triangle index out of bounds')
                    for key in (f'b{i}', f'p{i}', f'i{i}'):
                        h.update(canonical_json([key, headers[key]]))
                        with z.open(members[key]) as s:
                            _npy_header(s)
                            while chunk := s.read(1024 * 1024):
                                h.update(chunk)
                return h.hexdigest()
        except (zipfile.BadZipFile, EOFError, struct.error) as e:
            raise StoreValidationError('invalid NPZ archive') from e


def inspect_glb(path):
    """Validate embedded triangle geometry and hash only POSITION/index accessor content."""
    with safe_open(path) as f:
        total = Path(path).stat().st_size
        header = f.read(12)
        require(len(header) == 12, 'truncated GLB')
        magic, version, length = struct.unpack('<III', header)
        require(magic == 0x46546C67 and version == 2 and length == total, 'GLB header/schema mismatch')
        chunks = []
        while f.tell() < total:
            raw = f.read(8)
            require(len(raw) == 8, 'truncated GLB chunk')
            size, kind = struct.unpack('<II', raw)
            offset = f.tell()
            require(size % 4 == 0 and offset + size <= total, 'GLB chunk bounds invalid')
            chunks.append((kind, offset, size))
            require(len(chunks) <= 2, 'unsupported GLB chunks')
            f.seek(size, 1)
        require(len(chunks) == 2 and chunks[0][0] == 0x4E4F534A and chunks[1][0] == 0x004E4942, 'GLB requires one JSON and embedded BIN chunk')
        f.seek(chunks[0][1])
        require(chunks[0][2] <= MAX_JSON, 'GLB JSON too large')
        doc = parse_json(f.read(chunks[0][2]))
        require(isinstance(doc, dict) and isinstance(doc.get('asset'), dict) and doc['asset'].get('version') == '2.0', 'invalid glTF asset version')
        require(not doc.get('extensionsRequired'), 'unsupported required glTF extension')
        buffers = doc.get('buffers')
        require(isinstance(buffers, list) and len(buffers) == 1 and isinstance(buffers[0], dict) and 'uri' not in buffers[0], 'external GLB buffers forbidden')
        bin_size = integer(buffers[0].get('byteLength'), 1, chunks[1][2], 'GLB buffer size')
        require(chunks[1][2] - bin_size <= 3, 'GLB buffer padding mismatch')
        for image in doc.get('images', []):
            require(isinstance(image, dict) and 'uri' not in image, 'external GLB images forbidden')
        views, accessors, meshes = doc.get('bufferViews', []), doc.get('accessors', []), doc.get('meshes', [])
        require(isinstance(views, list) and isinstance(accessors, list) and isinstance(meshes, list) and 0 < len(meshes) <= 1024, 'GLB geometry missing/excessive')
        require(len(views) <= MAX_ARRAYS and len(accessors) <= MAX_ARRAYS, 'GLB table limit exceeded')
        for v in views:
            require(isinstance(v, dict) and v.get('buffer') == 0, 'invalid GLB bufferView')
            offset = integer(v.get('byteOffset', 0), 0, bin_size, 'GLB view offset')
            size = integer(v.get('byteLength'), 1, bin_size, 'GLB view size')
            require(offset + size <= bin_size, 'GLB view escapes buffer')
        def accessor(index, *, position=False, indices=False):
            integer(index, 0, len(accessors)-1, 'GLB accessor index')
            a = accessors[index]
            require(isinstance(a, dict) and 'sparse' not in a, 'sparse/invalid GLB accessor unsupported')
            vi = integer(a.get('bufferView'), 0, len(views)-1, 'GLB accessor view')
            v = views[vi]
            ct = a.get('componentType')
            type_ = a.get('type')
            dims = {'SCALAR':1, 'VEC2':2, 'VEC3':3, 'VEC4':4, 'MAT4':16}.get(type_)
            sizes = {5120:1,5121:1,5122:2,5123:2,5125:4,5126:4}
            require(dims is not None and ct in sizes, 'unsupported GLB accessor representation')
            if position:
                require(ct == 5126 and type_ == 'VEC3' and not a.get('normalized', False), 'GLB POSITION must be float32 VEC3')
            if indices:
                require(ct in {5121,5123,5125} and type_ == 'SCALAR' and not a.get('normalized', False), 'GLB indices must be unsigned scalar')
            count = integer(a.get('count'), 1, MAX_ELEMENTS, 'GLB accessor count')
            size = dims * sizes[ct]
            stride = integer(v.get('byteStride', size), size, 252, 'GLB stride')
            off = integer(a.get('byteOffset', 0), 0, v['byteLength'], 'GLB accessor offset')
            require(off + (count-1)*stride + size <= v['byteLength'], 'GLB accessor escapes bufferView')
            return a, chunks[1][1] + v.get('byteOffset',0) + off, size, stride, count, ct
        h = hashlib.sha256(b'gltf2-glb-geometry\0')
        primitive_count = 0
        for mesh in meshes:
            require(isinstance(mesh,dict) and isinstance(mesh.get('primitives'),list) and mesh['primitives'], 'GLB primitives missing')
            for primitive in mesh['primitives']:
                primitive_count += 1
                require(primitive_count <= 4096 and isinstance(primitive,dict) and primitive.get('mode',4) == 4, 'GLB must contain bounded triangles')
                attrs = primitive.get('attributes')
                require(isinstance(attrs,dict) and 'POSITION' in attrs and not primitive.get('targets'), 'GLB POSITION required; morph targets require shipped custom schema')
                pos = accessor(attrs['POSITION'], position=True)
                for attr, idx in attrs.items():
                    a = accessor(idx)
                    require(a[4] == pos[4], 'GLB vertex attributes count mismatch')
                items = [('POSITION',pos)]
                if 'indices' in primitive:
                    ix = accessor(primitive['indices'], indices=True)
                    require(ix[4] % 3 == 0, 'GLB index count must be triangles')
                    items.append(('indices',ix))
                else:
                    require(pos[4] % 3 == 0, 'GLB non-indexed vertex count must be triangles')
                for role, (_, off, size, stride, count, ct) in items:
                    h.update(canonical_json([role, count, ct, size]))
                    # Bound read buffers and avoid a seek per vertex on large PC outputs.
                    batch=max(1,(1024*1024)//stride)
                    for start in range(0,count,batch):
                        n=min(batch,count-start)
                        f.seek(off+start*stride)
                        raw=f.read((n-1)*stride+size)
                        require(len(raw)==(n-1)*stride+size,'truncated GLB accessor')
                        values=raw if stride==size else b''.join(raw[i*stride:i*stride+size] for i in range(n))
                        if role=='POSITION':
                            for xyz in struct.iter_unpack('<3f',values):
                                require(all(math.isfinite(x) for x in xyz),'nonfinite GLB position')
                        else:
                            fmt={5121:'<B',5123:'<H',5125:'<I'}[ct]
                            for (index,) in struct.iter_unpack(fmt,values):
                                require(index<pos[4],'GLB triangle index out of bounds')
                        h.update(values)
        return h.hexdigest()


def inspect_float32(path):
    """Shipped native float32/delta inspector, same geometry identity as runtime."""
    from .correspondence import native_decoded_identity
    metadata,rows=native_decoded_identity(path,'anatomy-npz-f32-delta-v1')
    h=hashlib.sha256()
    import json
    with safe_open(path) as raw,zipfile.ZipFile(raw) as z:
        expected={'meta.npy'}
        for i,row in enumerate(rows):
            names=[f'{k}{i}.npy' for k in 'pni'];expected.update(names)
            if f'c{i}.npy' in z.namelist():expected.add(f'c{i}.npy')
            hashes={}
            for key in ('p','i'):
                current=hashlib.sha256()
                with z.open(f'{key}{i}.npy') as stream:
                    _npy_header(stream)
                    while block:=stream.read(1024*1024):current.update(block)
                hashes[key]=current.hexdigest()
            h.update(json.dumps({'shape':(row['vertices'],3),'p':hashes['p'],'i':hashes['i']},sort_keys=True).encode())
        require(set(z.namelist())==expected,'unrecognized float32 native arrays')
    return h.hexdigest()
