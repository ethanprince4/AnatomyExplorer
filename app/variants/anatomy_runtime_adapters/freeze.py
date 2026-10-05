"""Deferred pre-freeze canonical transport and data-only sidecar emitters.

Never called in source-only integration tests with anatomy. These functions
write new paths only, preserve geometry, and do not import external Python.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json,os
from pathlib import Path
from .runtime import decode_native,sha,checkpoint
from .registry import contract
from .inspectors import metadata,read_json,inspect_native
from .companions import _array,native_position_identity
from .controls import compile_controls


def write_json_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as f:json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    return path


def canonicalize_native(primary,target,*,model_id,input_sha256,source_hashes,schema,color_companions=None,animation=None,token=None):
    """Decode authoritative native geometry to f32 before immutable Pre freeze.

    No refinement, smoothing, welding, normal recomputation or color invention.
    If already f32, p/n bytes remain exactly f32. Source hashes are supplied by
    the source receipt compiler, never silently replaced with old builder IDs.
    """
    import numpy as np
    e=contract(model_id)
    if e['primary_format']!='npz' or schema not in e['primary_schemas']:raise ValueError('Canonicalization only supports allowlisted native outputs')
    if sha(primary)!=input_sha256:raise ValueError('Canonical transport source identity changed')
    if Path(primary).resolve()==Path(target).resolve():raise ValueError('Canonical target must be a new file')
    meta,buffers=decode_native(primary,schema,token);arrays={};bindings={}
    supplied=color_companions or {}
    for i,(row,p,n,f,c) in enumerate(buffers):
        checkpoint(token);arrays[f'p{i}']=p;arrays[f'n{i}']=n
        delta=np.diff(f.astype(np.int64).ravel(),prepend=0)
        if len(delta) and (delta.min()<-2147483648 or delta.max()>2147483647):raise ValueError('Canonical delta indexes overflow')
        arrays[f'i{i}']=delta.astype(np.int32)
        color=supplied.get(row['name'],c)
        if color is not None:
            from .runtime import _validate_colors
            color=np.asarray(color,dtype=np.float32);_validate_colors(color,p);arrays[f'c{i}']=color
            bindings[row['name']]={'position_bound':True,'canonical_embedded':True}
    canonical=deepcopy(meta);canonical['position_encoding']='float32';canonical['normal_encoding']='float32'
    arrays['meta']=np.frombuffer(json.dumps(canonical,ensure_ascii=False,allow_nan=False).encode('utf8'),np.uint8)
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:np.savez_compressed(f,**arrays)
    if sha(primary)!=input_sha256:raise ValueError('Canonical source changed while reading')
    animate=deepcopy(animation or {'kind':'none'})
    result={'schema':'ae.microrefine-canonical-metadata.v1','model_id':model_id,'input_sha256':input_sha256,'parts':canonical['parts'],'source_hashes':dict(source_hashes),'native_metadata_preserved':True,'unknown_vertex_arrays':[],
            'canonical_payload':{'path':str(target),'sha256':sha(target),'format':'anatomy-npz-f32-delta-v1'},
            'decode_positions_exact':True,'decode_indices_exact':True,'adapter_id':e['adapter_id'],'color_bindings':bindings,'animation':animate}
    return result


def emit_color_contract(model_id,variant,primary,schema,colors,*,target):
    """Bind actual RGB arrays to the exact selected primary, including new Post."""
    import numpy as np
    with np.load(colors,allow_pickle=False) as _z:_arrs={k:_z[k] for k in _z.files}
    if any(a.dtype==np.float64 for a in _arrs.values()):  # source RGB stored as float64: normalise to the contract's float32
        with open(colors,'wb') as _f:np.savez_compressed(_f,**{k:(a.astype(np.float32) if a.dtype==np.float64 else a) for k,a in _arrs.items()})
    e=contract(model_id);meta=metadata(primary);names=[r['name'] for r in meta['parts']];rows=[]
    with np.load(colors,allow_pickle=False) as z:
        for key in z.files:
            if key in names:name=key
            elif key.startswith('c') and key[1:].isdigit() and int(key[1:])<len(names):name=names[int(key[1:])]
            elif model_id=='jejunum_comparison_c' and key=='capillary':name='Villus capillary network'
            else:raise ValueError('Unresolved color-array ownership: '+key)
            i=names.index(name);count,pdigest=native_position_identity(primary,i,schema)
            color=z[key]
            if color.dtype!=np.float32 or color.shape!=(count,3) or not np.isfinite(color).all() or np.any((color<-1e-3)|(color>1+1e-3)):raise ValueError('Invalid source-preserved linear RGB')  # tolerate float overshoot
            rows.append({'name':name,'array_key':key,'vertex_count':count,'positions_sha256':pdigest,'colors_sha256':hashlib.sha256(color.tobytes(order='C')).hexdigest()})
    d={'schema':'ae-position-colors-v1','schema_version':1,'model_id':model_id,'variant':variant,'primary_sha256':sha(primary),'colors_sha256':sha(colors),'encoding':'linear_rgb_float32','parts':rows}
    write_json_new(target,d);return d


def materialize_colors(primary,schema,target,*,provider=None,token=None):
    """Capture the live source-built model's reviewed provider before Pre freeze.

    The caller passes its already loaded shipped builder callback, never an
    external artifact module. Missing native embedded colors are not invented.
    After microrefine, pass independently remapped embedded canonical RGB.
    """
    import numpy as np
    _,parts=decode_native(primary,schema,token);arrays={}
    for i,(r,p,n,f,c) in enumerate(parts):
        checkpoint(token)
        if provider is not None:c=provider(r['name'],p)
        if c is not None:
            from .runtime import _validate_colors
            c=np.asarray(c,dtype=np.float32);_validate_colors(c,p);arrays[f'c{i}']=c
    if not arrays:raise ValueError('Required inherited RGB provider/embedded bindings unavailable')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:np.savez_compressed(f,**arrays)
    return target


def emit_animation_contract(model_id,variant,primary,schema,animation,*,target):
    meta=metadata(primary);names=[r['name'] for r in meta['parts']];rows=[]
    import zipfile
    with zipfile.ZipFile(animation) as z:
        keys={x[:-4] for x in z.namelist()}
    _,_,digest=_array(animation,'digest',dtype='|u1')
    if digest.decode()!=meta['digest']:raise ValueError('Animation source digest changed')
    for i,name in enumerate(names):
        if f'm{i}' not in keys:continue
        count,pdigest=native_position_identity(primary,i,schema)
        h,mhash,_=_array(animation,f'm{i}',finite=True)
        if h['shape'][0]!=count or h['shape'][2]!=3 or not 1<=h['shape'][1]<=4:raise ValueError('Morph targets do not match selected positions')
        _,fhash,_=_array(animation,f'f{i}',dtype='<f4',shape=(count,),unit_range=True)
        rows.append({'name':name,'vertex_count':count,'positions_sha256':pdigest,'morph_sha256':mhash,'phase_sha256':fhash})
    d={'schema':'ae-position-animation-v1','schema_version':1,'model_id':model_id,'variant':variant,'primary_sha256':sha(primary),'animation_sha256':sha(animation),'parts':rows}
    write_json_new(target,d);return d


def emit_runtime_controls(model_id,variant,primary,schema,*,companions,target):
    """Generate separate Pre/Post contracts against actual saved primary data."""
    verified={role:read_json(path) for role,path in companions.items() if str(path).endswith('.json') and role not in ('runtime_controls','source_receipt','validation','color_contract','animation_contract')}
    parts=metadata(primary)['parts'] if schema!='gltf2-glb' else []
    data=compile_controls(model_id,variant,sha(primary),parts,verified_documents=verified)
    write_json_new(target,data);return data
