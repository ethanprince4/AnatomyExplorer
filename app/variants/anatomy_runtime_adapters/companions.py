"""Streaming semantic companion validation, before store promotion or display."""
from __future__ import annotations
import hashlib,json,math,struct,zipfile
from .inspectors import header,read_json,metadata


def _array(path,key,*,dtype=None,shape=None,finite=False,unit_range=False):
    with zipfile.ZipFile(path) as z:
        with z.open(key+'.npy') as f:
            h=header(f)
            if dtype and h['descr']!=dtype:raise ValueError('Companion dtype mismatch: '+key)
            if shape and h['shape']!=tuple(shape):raise ValueError('Companion shape mismatch: '+key)
            fmt={'<f2':'<e','<f4':'<f','<f8':'<d','|u1':'<B','<i4':'<i','|i1':'<b','<u2':'<H'}[h['descr']]
            width=struct.calcsize(fmt);digest=hashlib.sha256();count=0;raw=[]
            for block in iter(lambda:f.read(1048576),b''):
                if len(block)%width:raise ValueError('Partial companion element')
                count+=len(block);digest.update(block)
                if finite or unit_range:
                    for (v,) in struct.iter_unpack(fmt,block):
                        if not math.isfinite(v) or (unit_range and not 0<=v<=1):raise ValueError('Invalid companion numeric value')
                if key=='digest':raw.append(block)
            if count!=math.prod(h['shape'])*width:raise ValueError('Companion byte count mismatch')
            return h,digest.hexdigest(),b''.join(raw)


def native_position_identity(path,index,schema):
    if schema=='anatomy-npz-f32-delta-v1':
        h,d,_=_array(path,f'p{index}',dtype='<f4',finite=True);return h['shape'][0],d
    with zipfile.ZipFile(path) as z:
        with z.open(f'b{index}.npy') as f:
            h=header(f)
            if h['descr']!='<f8' or h['shape']!=(2,3):raise ValueError('Invalid native bounds')
            values=struct.unpack('<6d',f.read(48));lo=values[:3];span=values[3:]
        with z.open(f'p{index}.npy') as f:
            h=header(f);digest=hashlib.sha256();count=0
            # 1,048,572 is divisible by the 6-byte xyz uint16 stride.
            for block in iter(lambda:f.read(1048572),b''):
                if len(block)%6:raise ValueError('Partial quantized xyz')
                for xyz in struct.iter_unpack('<3H',block):
                    digest.update(struct.pack('<3f',*(xyz[k]/65535.*span[k]+lo[k] for k in range(3))))
                count+=len(block)
            if count!=h['shape'][0]*6:raise ValueError('Quantized position byte count differs')
            return h['shape'][0],digest.hexdigest()


def validate_companions(descriptor,controls):
    assets=descriptor.assets
    # The parsed data used by hooks must exactly equal each independently
    # hash-bound JSON companion, rather than an unrelated nested document.
    for role,data in controls.get('verified_documents',{}).items():
        if role not in assets or assets[role].format!='json' or read_json(assets[role].path)!=data:raise ValueError('Controls embed stale/unlisted companion: '+role)
    if descriptor.primary.format!='npz':return
    meta=metadata(descriptor.primary.path)
    if controls.get('parts')!=meta['parts']:raise ValueError('Control metadata does not equal saved primary')
    positions={};by_name={r['name']:i for i,r in enumerate(meta['parts'])}
    def pos(name):
        if name not in positions:positions[name]=native_position_identity(descriptor.primary.path,by_name[name],descriptor.primary.schema)
        return positions[name]
    if 'colors' in assets:
        c=read_json(assets['color_contract'].path)
        if (c.get('schema'),c.get('schema_version'),c.get('model_id'),c.get('variant'),c.get('primary_sha256'),c.get('colors_sha256'),c.get('encoding'))!=('ae-position-colors-v1',1,descriptor.model_id,descriptor.variant,descriptor.primary.sha256,assets['colors'].sha256,'linear_rgb_float32'):raise ValueError('Color companion identity mismatch')
        rows=c.get('parts',[]);names=[r['name'] for r in rows];keys=[r['array_key'] for r in rows]
        if len(set(names))!=len(names) or len(set(keys))!=len(keys) or set(names)-set(by_name):raise ValueError('Ambiguous color ownership')
        from .registry import contract
        if not set(contract(descriptor.model_id)['color_hosts'])<=set(names):raise ValueError('Required inherited per-vertex color hosts missing')
        with zipfile.ZipFile(assets['colors'].path) as z:
            if set(z.namelist())!={k+'.npy' for k in keys}:raise ValueError('Color archive inventory differs')
        for r in rows:
            count,identity=pos(r['name'])
            if r.get('vertex_count')!=count or r.get('positions_sha256')!=identity:raise ValueError('Color companion bound to another position inventory')
            _,identity,_=_array(assets['colors'].path,r['array_key'],dtype='<f4',shape=(count,3),unit_range=True)
            if r.get('colors_sha256')!=identity:raise ValueError('Color bytes differ from contract')
    if 'animation' in assets:
        a=read_json(assets['animation_contract'].path)
        if (a.get('schema'),a.get('schema_version'),a.get('model_id'),a.get('variant'),a.get('primary_sha256'),a.get('animation_sha256'))!=('ae-position-animation-v1',1,descriptor.model_id,descriptor.variant,descriptor.primary.sha256,assets['animation'].sha256):raise ValueError('Animation companion identity mismatch')
        rows=a.get('parts',[]);names=[r['name'] for r in rows]
        if len(set(names))!=len(names) or set(names)-set(by_name):raise ValueError('Animation part ownership ambiguous')
        expected={'digest.npy'}
        _,_,raw=_array(assets['animation'].path,'digest',dtype='|u1')
        if raw.decode()!=meta['digest']:raise ValueError('Native animation source digest differs')
        for r in rows:
            count,identity=pos(r['name']);i=by_name[r['name']]
            if r.get('positions_sha256')!=identity or r.get('vertex_count')!=count:raise ValueError('Morph/phase companion bound to another position inventory')
            h,identity,_=_array(assets['animation'].path,f'm{i}',finite=True)
            if h['descr'] not in ('<f2','<f4') or len(h['shape'])!=3 or h['shape'][0]!=count or not 1<=h['shape'][1]<=4 or h['shape'][2]!=3 or identity!=r.get('morph_sha256'):raise ValueError('Invalid native morph channel')
            _,identity,_=_array(assets['animation'].path,f'f{i}',dtype='<f4',shape=(count,),unit_range=True)
            if identity!=r.get('phase_sha256'):raise ValueError('Native phase bytes differ')
            expected.update((f'm{i}.npy',f'f{i}.npy'))
        with zipfile.ZipFile(assets['animation'].path) as z:
            if set(z.namelist())!=expected:raise ValueError('Unsupported animation array channels')
