"""Compile model-specific teaching data into a selected, hash-bound contract.

This compiler reads only reviewed shipped JSON and caller-supplied verified data.
It does not evaluate builders or import any artifact's Python source.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json,math
from pathlib import Path
from .inspectors import read_json
from .registry import HERE,contract

NATIVE_FIELDS={'summary','scale_note','metres_per_unit','home_view','cutaway','cut_at','cut_on','labels_on_open','viewer_cameras','start_view','viewer_look','aliases'}
CONTAINERS=('native_model_settings','native_model_attributes','native_attributes','native_properties','native_defaults','metadata','native_sidecar_patch','viewer_settings','opening','scale')
EXPLICIT_DEFAULTS={
 'axillary_skin':{'metres_per_unit':.0015,'start_view':'V1','cut_on':True,'home_view':[-.62,.42]},
 'male_reproductive':{'metres_per_unit':.1},
 'jejunum_comparison_c':{'metres_per_unit':.0015},
 'lung_acinus_review_v2':{'metres_per_unit':.0012,'cut_on':True,'cut_at':[0,0],'cutaway':[[1,0,0],[0,0,1]]},
 'thyroid_parathyroid_review_v2':{'metres_per_unit':.0005,'labels_on_open':True},
 'scalp':{'metres_per_unit':.002,'cut_on':False},
 'tongue_papillae':{'metres_per_unit':.005},
 'thyroid_follicles':{'metres_per_unit':.0005,'home_view':[-.62,.46]},
 'muscular_artery':{'cutaway':[[1,0,0],[0,1,0]],'cut_at':[0,0]},
 'tooth':{'metres_per_unit':.01,'cut_on':False,'labels_on_open':True},
}
# Explicit flags come from source/native adapter instructions, including models
# whose bare ProceduralModel wrapper would otherwise drop the ruler disclosure.
MIXED_MODELS=frozenset({'ear','eyeball','female_reproductive','kidney_nephron','liver_lobule','muscular_artery','skeletal_muscle','stomach_wall','thyroid_parathyroid_review_v2','tongue_papillae','vein_wall'})


def shipped_documents(model_id):
    result=[]
    for row in contract(model_id)['source_documents']:
        path=HERE/row['shipped_path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Shipped teaching document modified')
        result.append(read_json(path,max_bytes=8*1024*1024))
    return result


def _native(document,model_id):
    if not isinstance(document,dict):return {}
    if model_id in document and isinstance(document[model_id],dict):document=document[model_id]
    result={k:deepcopy(v) for k,v in document.items() if k in NATIVE_FIELDS}
    for container in CONTAINERS:
        row=document.get(container)
        if not isinstance(row,dict):continue
        result.update({k:deepcopy(v) for k,v in row.items() if k in NATIVE_FIELDS})
        if 'cameras' in row:result['viewer_cameras']=deepcopy(row['cameras'])
        if 'um_per_bu' in row:result['metres_per_unit']=float(row['um_per_bu'])*1e-6
    if 'um_per_bu' in document:result['metres_per_unit']=float(document['um_per_bu'])*1e-6
    if 'micrometres_per_model_unit' in document.get('scale',{}):result['metres_per_unit']=document['scale']['micrometres_per_model_unit']*1e-6
    for camera_field in ('native_cameras','cameras'):
        if isinstance(document.get(camera_field),dict):result['viewer_cameras']=deepcopy(document[camera_field])
    cut=document.get('cutaway')
    if isinstance(cut,dict) and 'axes' in cut:result['cutaway']=deepcopy(cut['axes']);result['cut_at']=deepcopy(cut['at'])
    elif isinstance(cut,dict):result.pop('cutaway',None)
    return result


def _views(document):
    if not isinstance(document,dict):return []
    for key in ('teaching_views','views','states'):
        value=document.get(key)
        if isinstance(value,list) and value and any(isinstance(v,dict) and any(k in v for k in ('camera','native_camera','visible_parts','hosts')) for v in value):return deepcopy(value)
    return []


def _view_name(view,model_id):
    for k in ('camera_name','native_view_name','native_name','name'):
        if k in view:return view[k]
    if model_id in ('male_reproductive','muscular_artery','retina','thick_skin','thin_skin'):return view['id']
    if model_id=='tongue_papillae':return view['title']
    return view.get('title',view.get('id'))


def _sequences(document):
    if isinstance(document,list):result=deepcopy(document)
    elif not isinstance(document,dict):return []
    elif len(document)==1 and isinstance(next(iter(document.values())),dict):return _sequences(next(iter(document.values())))
    else:
        value=next((document[k] for k in ('functional_sequences','sequences') if k in document),None)
        if isinstance(value,list):result=deepcopy(value)
        elif isinstance(value,dict):result=[dict(deepcopy(row),id=id) for id,row in value.items()]
        elif isinstance(document.get('function_hooks'),dict):return _sequences(document['function_hooks'])
        else:return []
    for seq in result:
        if not isinstance(seq,dict):raise ValueError('Function sequence must be a record')
        raw=seq.get('steps',seq.get('stages',seq.get('states',[])))
        seq['steps']=[dict(step) if isinstance(step,dict) else {'id':str(i),'caption':str(step),'presentation':'text_only'} for i,step in enumerate(raw)]
    return result


def compile_controls(model_id,variant,primary_sha256,part_metadata,*,verified_documents=None):
    """Prepare JSON only after decoding metadata from the NEW frozen candidate.

    verified_documents maps declared companion roles to parsed JSON; ordinary
    source data are defaults, while actual per-variant sidecars take precedence.
    This never marks a candidate ready, writes geometry or invents a Post lane.
    """
    e=contract(model_id)
    if variant not in ('pre','post'):raise ValueError('One selected variant required')
    if not isinstance(primary_sha256,str) or len(primary_sha256)!=64:raise ValueError('Exact saved primary SHA required')
    rows=deepcopy(list(part_metadata));names=[r['name'] for r in rows]
    if len(names)!=len(set(names)) or (not names and e['primary_format']!='glb'):raise ValueError('Exact saved metadata required')
    docs=shipped_documents(model_id)
    native=deepcopy(read_json(HERE/'inherited_defaults.json').get(model_id,{}))
    native={k:v for k,v in native.items() if k in NATIVE_FIELDS}
    native.update(EXPLICIT_DEFAULTS.get(model_id,{}))
    views=[];sequences=[]
    for d in docs:
        native.update(_native(d,model_id))
        if not views:views=_views(d)
        seq=_sequences(d)
        if seq:
            seen={x.get('id') for x in sequences}
            sequences.extend(x for x in seq if x.get('id') not in seen)
    supplied=deepcopy(verified_documents or {})
    for role in ('comparison','native_defaults','teaching_recipe','teaching_views','native_controls','viewer'):
        d=supplied.get(role)
        if d is not None:
            native.update(_native(d,model_id))
            v=_views(d)
            if v:views=v
    cameras=deepcopy(native.get('viewer_cameras',{}))
    for v in views:
        camera=deepcopy(v.get('native_camera',v.get('camera',{})))
        if not camera:continue
        name=_view_name(v,model_id)
        if not name:raise ValueError('Teaching view has no explicit identity')
        visible=v.get('visible_parts')
        if visible is not None:
            absent=set(visible)-set(names)
            if absent:raise ValueError(f'{model_id}/{name} unimplemented selectors: {sorted(absent)}')
            camera['hidden']=[n for n in names if n not in visible]
        if 'hosts' in v:camera['hidden']=[n for n in names if not v['hosts'].get(n,{}).get('visible',False)]
        for field in ('cut_on','labels_on','sections','tissue_opacity_percent'):
            if field in v:camera[field]=deepcopy(v[field])
        camera.setdefault('note',v.get('caption',v.get('purpose',v.get('teaching_note',''))))
        cameras[name]=camera
    # Skin function.configure installs its complete function view namespace.
    if model_id in ('thin_skin','thick_skin'):
        for d in docs:
            for v in d.get('views',[]) if isinstance(d,dict) else []:
                if 'visible_parts' in v and 'camera' in v:
                    camera=deepcopy(v['camera']);camera['hidden']=[n for n in names if n not in v['visible_parts']];cameras[v['id']]=camera
    native['viewer_cameras']=cameras
    if model_id=='stomach_wall':
        from .runtime import _hook
        for seq in docs[1]['sequences']:
            episode=_hook(model_id,'function').compile_episode(docs[1],docs[0],seq['id'])
            for key,value in episode['viewer_cameras'].items():
                if key!='Function overview':cameras[key]=value
        native['viewer_cameras']=cameras
    if model_id=='tongue_papillae':native['start_view']=views[0]['title'];native['scale_note']=docs[0]['scale_disclosure']
    if native.get('start_view') not in cameras:
        first=docs[0] if isinstance(docs[0],dict) else {}
        opening=first.get('opening_view',first.get('default_view'))
        native['start_view']=opening if opening in cameras else next(iter(cameras),None)
    if 'metres_per_unit' not in native:native['metres_per_unit']=0.0
    if 'scale_note' not in native:
        native['scale_note']=next((v['scale_note'] for v in views if 'scale_note' in v),e['catalog_metadata'].get('scale_note') or 'Schematic teaching representation; no specimen morphometry claimed.')
    native.setdefault('home_view',[-.62,.42]);native.setdefault('cutaway',[[1,0,0],[0,0,1]]);native.setdefault('cut_at',[0,0]);native.setdefault('cut_on',False)
    return validate_controls({'schema':'ae-runtime-controls-v1','schema_version':1,'adapter_id':e['adapter_id'],'model_id':model_id,'variant':variant,'primary_sha256':primary_sha256,'part_names':names,'parts':rows,'native':native,'viewer':{'mixed_schematic_scale':model_id in MIXED_MODELS or any(isinstance(x,dict) and (x.get('mixed_schematic_scale') is True or x.get('opening',{}).get('mixed_schematic_scale') is True) for x in [*docs,*supplied.values()]),'view_transition':'zoom','review_status':'unaccepted','scale_note':native['scale_note']},'teaching_views':views,'functional_sequences':sequences,'documents':docs,'verified_documents':supplied,'autoplay':False,'geometry_modified':False})


def validate_controls(d,*,model_id=None,variant=None,primary_sha256=None):
    if not isinstance(d,dict) or d.get('schema')!='ae-runtime-controls-v1' or d.get('schema_version')!=1:raise ValueError('Unsupported runtime controls')
    e=contract(d['model_id'])
    if d.get('adapter_id')!=e['adapter_id'] or d.get('variant') not in ('pre','post'):raise ValueError('Controls adapter/variant mismatch')
    for key,value in (('model_id',model_id),('variant',variant),('primary_sha256',primary_sha256)):
        if value is not None and d.get(key)!=value:raise ValueError('Controls '+key+' differs from selected immutable variant')
    if d.get('autoplay') is not False or d.get('geometry_modified') is not False:raise ValueError('Unexpected runtime processing/autoplay')
    names=d.get('part_names',[])
    if len(names)!=len(set(names)) or [r['name'] for r in d.get('parts',[])]!=names:raise ValueError('Control part order mismatch')
    native=d['native']
    if set(native)-NATIVE_FIELDS:raise ValueError('Unsupported native model property')
    cameras=native['viewer_cameras']
    if not isinstance(cameras,dict) or not cameras:raise ValueError('Model-specific cameras absent')
    if native.get('start_view') not in cameras:raise ValueError('Model-specific opening view absent')
    mpu=native.get('metres_per_unit')
    if type(mpu) not in (int,float) or not math.isfinite(mpu) or mpu<0:raise ValueError('Invalid native scale')
    for name,cam in cameras.items():
        if not isinstance(cam,dict):raise ValueError('Camera must be data')
        if 'yaw_radians' in cam:continue # exact source pose resolved against saved bounds on explicit native load
        for key in ('position','target'):
            v=cam.get(key)
            if not isinstance(v,(list,tuple)) or len(v)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in v):raise ValueError('Invalid native camera '+name)
        if list(cam['position'])==list(cam['target']):raise ValueError('Degenerate native camera')
        hidden=cam.get('hidden',[])
        if len(hidden)!=len(set(hidden)) or (names and set(hidden)-set(names)):raise ValueError('Unknown/repeated hidden selector '+name)
        if cam.get('type')=='ORTHO' and (type(cam.get('ortho_width')) not in (int,float) or cam['ortho_width']<=0):raise ValueError('Missing native orthographic width '+name)
    if type(d['viewer'].get('mixed_schematic_scale')) is not bool:raise ValueError('Ruler disclosure missing')
    return d
