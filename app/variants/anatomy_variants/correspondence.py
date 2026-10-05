"""Read-only, pure-stdlib canonical correspondence checks; original Pre is authority."""
from __future__ import annotations
import hashlib
import json
import math
import struct
import zipfile
from .formats import _npy_header
from .security import canonical_json,digest,exact,integer,parse_json,read_json,require,safe_open

CANONICAL_ROLES = {
  'canonical_payload':frozenset({('npz','anatomy-npz-f32-delta-v1')}),
  'canonical_correspondence':frozenset({('json','ae.canonical-correspondence.v1')}),
}
GLB_CODEC_SHA256 = '9f621283450d1b0c2001fd2fec49a6c717b1dad4d83f359d0ad7be4f22e83d0c'
PROOF_KEYS={'schema','model_id','status','read_only','pre_payload_sha256','canonical_payload_sha256',
  'source_build_sha256','selector_metadata_sha256','source_schema','canonical_schema','coordinate_units',
  'conversion','parts','source_companion_sha256','limits'}
ROW_KEYS={'name','vertices','triangles','positions_sha256','normals_sha256','indices_sha256','colors_sha256','arrays_exact'}


def _f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]


def _stream(z,key):
    stream=z.open(key+'.npy');dtype,shape,_,_=_npy_header(stream)
    return stream,dtype,shape


def _hash_numeric(z,key,*,dtype,shape,unit_range=False):
    with z.open(key+'.npy') as stream:
        actual,dimensions,_,_=_npy_header(stream)
        require(actual==dtype and dimensions==shape,'canonical numeric encoding/shape differs')
        h=hashlib.sha256()
        while block:=stream.read(1024*1024):
            if dtype=='<f4':
                for (v,) in struct.iter_unpack('<f',block):require(math.isfinite(v) and (not unit_range or 0<=v<=1),'canonical nonfinite/out-of-range array')
            h.update(block)
        return h.hexdigest()


def native_decoded_identity(path,schema,external_colors=None):
    """Hash the exact native viewer-decoded p/n/int64 triangle/color arrays."""
    require(schema in {'anatomy-npz-v4','anatomy-npz-f32-delta-v1'},'unsupported native correspondence codec')
    f32=schema=='anatomy-npz-f32-delta-v1';external_colors=external_colors or {}
    with safe_open(path) as raw,zipfile.ZipFile(raw) as z:
        with z.open('meta.npy') as stream:_npy_header(stream);meta=parse_json(stream.read(4*1024*1024+1))
        require(isinstance(meta,dict) and isinstance(meta.get('parts'),list) and 0<len(meta['parts'])<=4096,'canonical part metadata missing/excessive')
        names=[]
        for part in meta['parts']:
            require(isinstance(part,dict) and isinstance(part.get('name'),str) and 0<len(part['name'])<=256,'canonical part identity invalid')
            names.append(part['name'])
        require(len(names)==len(set(names)),'canonical repeated part selectors')
        if f32:require(meta.get('position_encoding')=='float32' and meta.get('normal_encoding')=='float32','canonical float32 encoding declarations missing')
        rows=[]
        for i,part in enumerate(meta['parts']):
            p,dtype,shape=_stream(z,f'p{i}');vertices=shape[0];p.close()
            require(shape==(vertices,3) and vertices>0,'canonical vertex layout invalid')
            if f32:
                ph=_hash_numeric(z,f'p{i}',dtype='<f4',shape=(vertices,3));nh=_hash_numeric(z,f'n{i}',dtype='<f4',shape=(vertices,3))
            else:
                with z.open(f'b{i}.npy') as stream:
                    dt,sh,_,_=_npy_header(stream);require((dt,sh)==('<f8',(2,3)),'source quantization bounds invalid');bounds=struct.unpack('<6d',stream.read(48))
                lo,span=bounds[:3],bounds[3:];require(all(math.isfinite(v) for v in bounds) and all(s>0 for s in span),'source quantization bounds nonfinite/nonpositive')
                hp=hashlib.sha256();hn=hashlib.sha256()
                with z.open(f'p{i}.npy') as stream:
                    dt,sh,_,_=_npy_header(stream);require((dt,sh)==('<u2',(vertices,3)),'source positions encoding invalid')
                    while block:=stream.read(1048572):
                        for xyz in struct.iter_unpack('<3H',block):hp.update(struct.pack('<3f',*(xyz[k]/65535.*span[k]+lo[k] for k in range(3))))
                with z.open(f'n{i}.npy') as stream:
                    dt,sh,_,_=_npy_header(stream);require((dt,sh)==('|i1',(vertices,3)),'source normal encoding invalid')
                    while block:=stream.read(1048575):
                        for xyz in struct.iter_unpack('<3b',block):
                            v=[_f32(x/127.) for x in xyz]
                            squared=_f32(_f32(_f32(v[0]*v[0])+_f32(v[1]*v[1]))+_f32(v[2]*v[2]))
                            norm=max(_f32(math.sqrt(squared)),_f32(1e-6));hn.update(struct.pack('<3f',*(_f32(x/norm) for x in v)))
                ph,nh=hp.hexdigest(),hn.hexdigest()
            faces=hashlib.sha256();acc=0
            with z.open(f'i{i}.npy') as stream:
                dt,sh,_,_=_npy_header(stream);require(dt=='<i4' and len(sh)==1 and sh[0]%3==0,'canonical delta triangle layout invalid')
                count=sh[0]
                while block:=stream.read(1024*1024):
                    converted=bytearray()
                    for (delta,) in struct.iter_unpack('<i',block):
                        acc+=delta;require(0<=acc<vertices,'canonical/source triangle index out of bounds');converted.extend(struct.pack('<q',acc))
                    faces.update(converted)
            ch=None
            if f'c{i}.npy' in z.namelist():ch=_hash_numeric(z,f'c{i}',dtype='<f4',shape=(vertices,3),unit_range=True)
            if part['name'] in external_colors:
                require(ch is None or ch==external_colors[part['name']],'source embedded/external colors disagree');ch=external_colors[part['name']]
            rows.append({'name':part['name'],'vertices':vertices,'triangles':count//3,'positions_sha256':ph,'normals_sha256':nh,
              'indices_sha256':faces.hexdigest(),'colors_sha256':ch,'arrays_exact':True})
        return meta['parts'],rows


def validate_correspondence(pre,post,profile,audit):
    binding=profile['final_microrefine'];canonical=binding['canonical_payload']
    need=pre.primary.schema!='anatomy-npz-f32-delta-v1' or canonical['sha256']!=pre.primary.sha256 or post.primary.schema!=pre.primary.schema
    if not need:return
    assets=post.assets
    require(set(CANONICAL_ROLES)<=set(assets),'canonical conversion payload/proof companion missing')
    proof_asset=assets['canonical_correspondence'];payload=assets['canonical_payload'];proof=read_json(proof_asset.path)
    exact(proof,PROOF_KEYS,'canonical correspondence proof')
    ref=binding.get('canonical_correspondence');require(isinstance(ref,dict) and ref.get('sha256')==proof_asset.sha256==audit.get('canonical_correspondence_sha256') and audit.get('canonical_correspondence')==proof,'canonical proof/profile/audit identity mismatch')
    require(payload.sha256==canonical['sha256'] and proof['schema']=='ae.canonical-correspondence.v1' and proof['model_id']==pre.model_id and proof['status']=='passed' and proof['read_only'] is True,'canonical conversion was not independently qualified')
    require(proof['pre_payload_sha256']==pre.primary.sha256 and proof['canonical_payload_sha256']==payload.sha256 and proof['source_build_sha256']==pre.provenance['source_build_sha256'],'canonical/source build payload identity mismatch')
    require(proof['source_schema']==pre.primary.schema and proof['canonical_schema']=='anatomy-npz-f32-delta-v1' and proof['coordinate_units']=='source_model_units','canonical source representation/units changed')
    relevant={k:a.sha256 for k,a in pre.assets.items() if k in {'colors','color_contract','animation','animation_contract'}}
    require(proof['source_companion_sha256']==relevant,'canonical source colors/animation companion identity mismatch')
    metadata,rows=native_decoded_identity(payload.path,'anatomy-npz-f32-delta-v1')
    require(proof['parts']==rows and [r['name'] for r in rows]==profile['expected_parts'],'canonical proof differs from actual saved canonical p/n/i/colors/ordered selectors')
    require(proof['selector_metadata_sha256']==hashlib.sha256(canonical_json(metadata)[:-1]).hexdigest(),'canonical full Part metadata hash mismatch')
    conversion=proof['conversion'];require(isinstance(conversion,dict),'canonical conversion policy missing')
    if pre.primary.format=='npz':
        exact(conversion,{'adapter','source_schema','canonical_schema','coordinate_space','units','positions','normals','indices'},'native canonical conversion policy')
        require(conversion['adapter']==pre.adapter_id and conversion['source_schema']==pre.primary.schema and conversion['canonical_schema']=='anatomy-npz-f32-delta-v1' and conversion['coordinate_space']=='identity' and conversion['units']=='source_model_units','native canonical coordinate mapping changed')
        expected_positions='uint16/65535 * float64 span + float64 origin -> authoritative float32' if pre.primary.schema=='anatomy-npz-v4' else 'float32 exact'
        expected_normals='int8/127 -> float32 unit normalization' if pre.primary.schema=='anatomy-npz-v4' else 'float32 exact'
        require(conversion['positions']==expected_positions and conversion['normals']==expected_normals and conversion['indices']=='int32 delta cumulative decode -> int64 triangles; no reindexing','unsupported native canonical decoder')
        colors={}
        if 'colors' in pre.assets:
            contract=read_json(pre.assets['color_contract'].path)
            with safe_open(pre.assets['colors'].path) as raw,zipfile.ZipFile(raw) as z:
                for row in contract['parts']:colors[row['name']]=_hash_numeric(z,row['array_key'],dtype='<f4',shape=(row['vertex_count'],3),unit_range=True)
        source_metadata,source_rows=native_decoded_identity(pre.primary.path,pre.primary.schema,colors)
        require(source_metadata==metadata and [(r['name'],r['vertices'],r['triangles'],r['indices_sha256']) for r in source_rows]==[(r['name'],r['vertices'],r['triangles'],r['indices_sha256']) for r in rows],'actual immutable native Pre does not decode exactly to claimed canonical derivative')
    else:
        exact(conversion,{'adapter','source_coordinate_space','canonical_coordinate_space','units','transform_policy','max_roundtrip_error','scene_material_mapping_sha256','source_node_primitive_mapping'},'GLB canonical conversion policy')
        require(conversion['adapter']=='ae.static-glb-f32-delta.v1' and conversion['source_coordinate_space']=='node_local' and conversion['canonical_coordinate_space']=='world' and conversion['units']=='source_model_units','unsupported static GLB world/node conversion')
        digest(conversion['scene_material_mapping_sha256'],'GLB scene/material mapping')
        tolerance=conversion['max_roundtrip_error'];require(type(tolerance) in (int,float) and math.isfinite(tolerance) and tolerance>=0,'GLB canonical explicit representability bound missing')
        mapping=conversion['source_node_primitive_mapping'];require(isinstance(mapping,list) and [r.get('name') for r in mapping if isinstance(r,dict)]==[r['name'] for r in rows],'GLB source node/primitive mapping omitted/reordered')
        require(audit.get('codec_sha256')==GLB_CODEC_SHA256,'untrusted static GLB canonical/final codec identity')
        # The runner's pinned reviewed GLB codec independently decodes exact retained
        # node/TRS/material/world mapping before emitting this qualified proof.
        # This stdlib store rechecks saved canonical arrays + all proof identities;
        # it does not pretend that a local-node fingerprint is a world-space proof.
