"""Bounded metadata/header checks and streamed fingerprints. No NumPy/app import."""
from __future__ import annotations
import ast,hashlib,json,math,struct,zipfile
from pathlib import Path

MAX_META=2*1024*1024
FIELDS=('name','group','color','description','alpha','category','label','rank','clip','bulk','detail')


def header(stream):
    if stream.read(6)!=b'\x93NUMPY':raise ValueError('Invalid NPY signature')
    v=stream.read(2)
    if v==b'\x01\x00': n=struct.unpack('<H',stream.read(2))[0]
    elif v in (b'\x02\x00',b'\x03\x00'):n=struct.unpack('<I',stream.read(4))[0]
    else:raise ValueError('Unsupported NPY version')
    if n>65536:raise ValueError('NPY header too large')
    raw=stream.read(n)
    if len(raw)!=n:raise ValueError('Truncated NPY header')
    h=ast.literal_eval(raw.decode('utf8' if v==b'\x03\x00' else 'latin1'))
    if type(h) is not dict or set(h)!={'descr','fortran_order','shape'}:raise ValueError('Invalid NPY header fields')
    if type(h['shape']) is not tuple or any(type(x) is not int or x<0 for x in h['shape']):raise ValueError('Invalid NPY dimensions')
    if h['fortran_order'] is not False:raise ValueError('Fortran arrays not supported')
    if h['descr'] not in ('|u1','<u2','<f2','<f4','<f8','<i4','|i1'):raise ValueError('Unsafe/unsupported array dtype')
    return h


def unique_json(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ValueError('Duplicate JSON key: '+k)
        out[k]=v
    return out


def read_json(path,max_bytes=MAX_META):
    with Path(path).open('rb') as f:raw=f.read(max_bytes+1)
    if len(raw)>max_bytes:raise ValueError('JSON exceeds budget')
    return json.loads(raw.decode('utf8'),object_pairs_hook=unique_json,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def metadata(path):
    with zipfile.ZipFile(path) as z:
        if len(z.namelist())>20000 or len(z.namelist())!=len(set(z.namelist())):raise ValueError('Duplicate/excess NPZ members')
        info=z.getinfo('meta.npy')
        if info.file_size>MAX_META+65546:raise ValueError('Oversize metadata')
        with z.open(info) as f:
            h=header(f)
            if h['descr']!='|u1' or len(h['shape'])!=1:raise ValueError('Metadata must be byte vector')
            raw=f.read(MAX_META+1)
            if len(raw)!=h['shape'][0] or len(raw)>MAX_META:raise ValueError('Metadata size mismatch')
    m=json.loads(raw.decode('utf8'),object_pairs_hook=unique_json,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    rows=m.get('parts')
    if not isinstance(rows,list) or not rows or len(rows)>4096:raise ValueError('Invalid part inventory')
    names=[]
    for r in rows:
        if not isinstance(r,dict) or not set(FIELDS)<=set(r):raise ValueError('Incomplete native metadata')
        for b in ('label','clip','bulk'):
            if type(r[b]) is not bool:raise ValueError('Native booleans must be exact')
        for n in ('alpha','rank'):
            if type(r[n]) not in (int,float) or not math.isfinite(r[n]):raise ValueError('Invalid native number')
        if not isinstance(r['name'],str) or not r['name']:raise ValueError('Invalid selector')
        names.append(r['name'])
    if len(names)!=len(set(names)):raise ValueError('Duplicate native selectors')
    return m


def inspect_native(path,schema):
    """Returns geometry-only fingerprint of exact stored coordinate/index bytes.

    Same-encoding comparison only. This does not certify winding, anatomy,
    remapped colors or animation. The separate geometry receipt covers those.
    """
    if schema not in ('anatomy-npz-f32-delta-v1','anatomy-npz-v4'):raise ValueError('Unsupported native schema')
    m=metadata(path); f32=schema=='anatomy-npz-f32-delta-v1'
    if f32 and (m.get('position_encoding'),m.get('normal_encoding'))!=('float32','float32'):raise ValueError('Missing f32 encoding declaration')
    geometry=hashlib.sha256();expected={'meta.npy'}
    with zipfile.ZipFile(path) as z:
        for i,row in enumerate(m['parts']):
            hashes={}; shapes={}
            for key in (('p','n','i') if f32 else ('b','p','n','i')):
                name=f'{key}{i}.npy';expected.add(name)
                with z.open(name) as f:
                    h=header(f);shapes[key]=h['shape'];dtype=h['descr']
                    required={'p':'<f4' if f32 else '<u2','n':'<f4' if f32 else '|i1','i':'<i4','b':'<f8'}[key]
                    if dtype!=required:raise ValueError('Native encoding mismatch: '+name)
                    if key in ('p','n') and (len(h['shape'])!=2 or h['shape'][1]!=3):raise ValueError('Invalid vertex shape')
                    if key=='i' and (len(h['shape'])!=1 or h['shape'][0]%3):raise ValueError('Invalid index shape')
                    if key=='b' and h['shape']!=(2,3):raise ValueError('Invalid quantization bounds')
                    elements=math.prod(h['shape'])
                    if elements>3_000_000_000:raise ValueError('Array exceeds supported native budget')
                    digest=hashlib.sha256();count=0;index_sum=0;bounds=[]
                    for block in iter(lambda:f.read(1048576),b''):
                        digest.update(block);count+=len(block)
                        if dtype in ('<f4','<f8'):
                            width=4 if dtype=='<f4' else 8
                            if len(block)%width:raise ValueError('Partial float element')
                            for (value,) in struct.iter_unpack('<f' if width==4 else '<d',block):
                                if not math.isfinite(value):raise ValueError('Nonfinite native arrays')
                                if key=='b':bounds.append(value)
                        elif key=='i':
                            if len(block)%4:raise ValueError('Partial index element')
                            vertices=shapes['p'][0]
                            for (delta,) in struct.iter_unpack('<i',block):
                                index_sum+=delta
                                if not 0<=index_sum<vertices:raise ValueError('Native delta index out of bounds')
                    if key=='b' and (len(bounds)!=6 or any(x<=0 for x in bounds[3:])):raise ValueError('Invalid native quantization span')
                    widths={'|u1':1,'|i1':1,'<u2':2,'<i4':4,'<f4':4,'<f8':8}
                    if count!=math.prod(h['shape'])*widths[dtype]:raise ValueError('Truncated or trailing array data')
                    hashes[key]=digest.hexdigest()
            if shapes['p']!=shapes['n']:raise ValueError('Position/normal counts differ')
            geometry.update(json.dumps({'ordinal':i,'shape':shapes['p'],'p':hashes['p'],'i':hashes['i'],**({'b':hashes['b']} if not f32 else {})},sort_keys=True).encode())
            color=f'c{i}.npy'
            if color in z.namelist():
                expected.add(color)
                with z.open(color) as f:
                    h=header(f)
                    if h['descr']!='<f4' or h['shape']!=shapes['p']:raise ValueError('Embedded RGB count mismatch')
        if set(z.namelist())!=expected:raise ValueError('Unexpected native members')
    return geometry.hexdigest()
