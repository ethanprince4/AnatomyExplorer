"""Fixed liver25/8 source views; no fictitious whole33 original-engine report."""
import hashlib
from pathlib import Path
from types import SimpleNamespace,MappingProxyType
from .security import exact,read_json,require,file_hash
from .grouped import identities
from .additional import object_hash
from .correspondence import validate_correspondence

CONTRACT_SHA='8306938f3d163dddacc51eb78a71916a85979d23502e5e98daacb7341cf4e1b4'
PRODUCER_SHA='81f6ba4d77a5981c751168f24f46b918da41b79d3c0f4145d68c9e33138ce47a'
PATH=Path(__file__).with_name('liver-source-modes-v1.json')
# Load the shipped JSON normally; checkout line endings must not block app imports.
CONTRACT=read_json(PATH)
MODES=tuple(CONTRACT['modes'])
ORDER=CONTRACT['original_selector_order']
PARENT=CONTRACT['parent_adapter_id']
AGG_ROLES={'mode_execution':frozenset({('json',CONTRACT['aggregate_execution_schema'])}),'mode_profile_bundle':frozenset({('json',CONTRACT['aggregate_profile_schema'])}),'mode_reassembly':frozenset({('json',CONTRACT['reassembly_schema'])})}
PROJECTION=frozenset({('json',CONTRACT['projection_schema'])})

def role_name(mid,variant,role):return f'mode_{mid}_{variant}_{role}'
def is_parent(mid,adapter):return mid=='liver_lobule' and adapter==PARENT
def roles(variant):
    from .execution import POST_ROLES
    d={}
    for m in MODES:
        fields={'descriptor':frozenset({('json','anatomy-variant')}),'primary':frozenset({('npz','anatomy-npz-f32-delta-v1')}),'source_receipt':frozenset({('json','anatomy-source-receipt-v1')}),'validation':frozenset({('json','anatomy-validation-v1')}),'source_mode_projection':PROJECTION}
        if variant=='pre':fields['pre_baseline_report']=frozenset({('json','ae.saved-pre-policy-validation.v1')})
        else:fields.update(POST_ROLES)
        d.update({role_name(m['mode_id'],variant,k):v for k,v in fields.items()})
    if variant=='post':
        d.update(AGG_ROLES)
        # Aggregate includes independently qualified immutable leaf Pre evidence.
        d.update(roles('pre'))
    return d

def ref(a):return {'path':a.relative_path,'sha256':a.sha256,'size':a.size}
def leaf_spec(store,spec,m):
    from .store import AdapterSpec
    return AdapterSpec(m['adapter_id'],frozenset({'liver_lobule'}),frozenset({('npz','anatomy-npz-f32-delta-v1')}),required_roles={'source_mode_projection':PROJECTION},inspector=spec.inspector,components=())

def flat(parent,leaf,m,variant):
    for a in (leaf.primary,*leaf.companions):
        declared=parent.assets.get(role_name(m['mode_id'],variant,a.role))
        require(declared is not None and (declared.path,declared.sha256,declared.size,declared.format,declared.schema)==(a.path,a.sha256,a.size,a.format,a.schema),'mode leaf evidence not declared in parent flat generation')

def projection(parent,leaf,m,full_ids,full_meta):
    a=leaf.assets['source_mode_projection'];p=read_json(a.path)
    exact(p,CONTRACT['projection_keys'],'liver source projection')
    require(p['schema']==CONTRACT['projection_schema'] and type(p['schema_version']) is int and p['schema_version']==1 and p['model_id']=='liver_lobule' and p['mode_id']==m['mode_id'] and p['producer_sha256']==PRODUCER_SHA,'unshipped projection producer/mode')
    require(p['parent_pre_primary_sha256']==parent.primary.sha256 and p['parent_source_build_sha256']==parent.provenance['source_build_sha256'] and p['parent_source_receipt_sha256']==parent.provenance['source_receipt_sha256'] and p['mode_input_sha256']==leaf.primary.sha256,'projection original parent/source/leaf identities mismatch')
    require(p['full_canonical_payload_sha256']==parent.assets['canonical_payload'].sha256 and p['full_canonical_correspondence_sha256']==parent.assets['canonical_correspondence'].sha256,'projection canonical correspondence identity mismatch')
    require(p['original_selector_order']==ORDER and p['scope_selector_order']==m['selectors'] and p['source_part_indices']==[ORDER.index(n) for n in m['selectors']] and p['coordinate_units']=='source_model_units' and p['geometry_modified'] is False and p['attributes_modified'] is False and p['metadata_preserved'] is True,'projection changed source scope/arrays/units')
    meta,ids=identities(leaf.primary.path);require([r['name'] for r in meta]==m['selectors'] and meta==[full_meta[ORDER.index(n)] for n in m['selectors']],'mode metadata is not exact source projection')
    require(len(p['parts'])==len(m['selectors']),'projection omitted source parts')
    for i,(name,row) in enumerate(zip(m['selectors'],p['parts'])):
        exact(row,CONTRACT['projection_part_keys'],'mode projection part')
        require(row['source_index']==ORDER.index(name) and row['scope_index']==i and row['arrays_exact'] is True and {k:v for k,v in row.items() if k not in {'source_index','scope_index','arrays_exact'}}==ids[name]==full_ids[name],'actual projected arrays differ from source canonical')
    return p

def pre_modes(store,root,parent,spec,budget=None):
    require(is_parent(parent.model_id,parent.adapter_id),'unshipped source mode parent')
    ca=parent.assets['canonical_payload'];co=parent.assets['canonical_correspondence'];proof=read_json(co.path)
    profile={'expected_parts':ORDER,'final_microrefine':{'canonical_payload':{'sha256':ca.sha256},'canonical_correspondence':{'sha256':co.sha256}}}
    dummy=SimpleNamespace(primary=SimpleNamespace(schema='anatomy-npz-f32-delta-v1'),assets=parent.assets)
    validate_correspondence(parent,dummy,profile,{'canonical_correspondence':proof,'canonical_correspondence_sha256':co.sha256})
    meta,ids=identities(ca.path);require([m['name'] for m in meta]==ORDER,'full source33 native order changed')
    children={}
    for m in MODES:
        asset=parent.assets[role_name(m['mode_id'],'pre','descriptor')]
        child=store._descriptor(root,ref(asset),'liver_lobule','pre',parent.generation_id,budget,spec_override=leaf_spec(store,spec,m))
        require(child.provenance['source_build_sha256']==parent.provenance['source_build_sha256'],'qualified mode not from same source build')
        flat(parent,child,m,'pre');projection(parent,child,m,ids,meta);children[m['mode_id']]=child
    # The human Pre report is an aggregate of real independent qualifications,
    # never numerical acceptance of one fabricated all33 collision domain.
    raw=read_json(parent.assets['pre_baseline_report'].path)
    expected={mid:c.assets['pre_baseline_report'].sha256 for mid,c in children.items()}
    require(raw.get('mode_pre_qualification_sha256')==expected,'full human Pre baseline not bound to both independently qualified source modes')
    findings=[dict(f) for mid in ('overview','exchange') for f in read_json(children[mid].assets['pre_baseline_report'].path)['baseline_findings']]
    require(raw['baseline_findings']==findings,'full human Pre baseline did not preserve actual mode findings')
    return children

def validate_post(store,root,pre,post,spec):
    from .execution import ORIGINAL_ENGINE_SHA256
    ex=read_json(post.assets['mode_execution'].path);pb=read_json(post.assets['mode_profile_bundle'].path);ra=read_json(post.assets['mode_reassembly'].path)
    exact(ex,CONTRACT['aggregate_execution_keys'],'liver aggregate execution');exact(pb,CONTRACT['aggregate_profile_keys'],'liver profile bundle');exact(ra,CONTRACT['reassembly_keys'],'liver reassembly')
    for data,schema in ((ex,CONTRACT['aggregate_execution_schema']),(pb,CONTRACT['aggregate_profile_schema']),(ra,CONTRACT['reassembly_schema'])):
        require(data['schema']==schema and type(data['schema_version']) is int and data['schema_version']==1 and data['model_id']=='liver_lobule' and data['original_selector_order']==ORDER,'liver aggregate schema/source order changed')
        require(data['parent_pre_primary_sha256']==pre.primary.sha256 and data['parent_pre_descriptor_sha256']==pre.descriptor_sha256,'mode aggregate wrong immutable humanPre')
    for data in (ex,pb):
        require(data['source_build_sha256']==pre.provenance['source_build_sha256'] and data['source_receipt_sha256']==pre.provenance['source_receipt_sha256'] and data['algorithm_sha256']==ORIGINAL_ENGINE_SHA256,'aggregate source/engine identity changed')
    require(ex['parent_pre_validation_sha256']==pre.assets['validation'].sha256 and ex['profile_bundle_sha256']==post.assets['mode_profile_bundle'].sha256==post.provenance['profile_sha256'] and post.provenance['execution_receipt_sha256']==post.assets['mode_execution'].sha256,'aggregate parent validation/profile/execution hash mismatch')
    require(ex['saved_post_sha256']==ra['saved_post_sha256']==post.primary.sha256 and ex['saved_post_geometry_sha256']==post.geometry_sha256 and ex['status']=='passed' and ex['reassembly_validation_role']=='mode_reassembly','actual saved Post identity/status mismatch')
    require(ra['metadata_preserved'] is True and ra['arrays_exact_to_saved_leaves'] is True and ra['geometry_modified_after_engine'] is False and ra['status']=='passed' and ra['read_only'] is True,'reassembly cannot modify saved engine outputs')
    require(ex['modes']==pb['modes'] and isinstance(ex['modes'],list) and len(ex['modes'])==2,'aggregate mode inventory missing/reordered')
    children={};outcomes={};all_ids={}
    for m,row in zip(MODES,ex['modes']):
        exact(row,CONTRACT['aggregate_mode_keys'],'aggregate mode')
        expected={'mode_id':m['mode_id'],'adapter_id':m['adapter_id'],'projection_role':role_name(m['mode_id'],'post','source_mode_projection'),'pre_descriptor_role':role_name(m['mode_id'],'pre','descriptor'),'post_descriptor_role':role_name(m['mode_id'],'post','descriptor'),
          **{k+'_role':role_name(m['mode_id'],'post',v) for k,v in [('execution','microrefine_execution'),('engine_report','engine_report'),('profile','microrefine_profile'),('independent_validation','independent_validation'),('audit','microrefine_audit')]}}
        require(all(row[k]==v for k,v in expected.items()),'aggregate uses unshipped modes/role namespaces')
        cp=pre.verified_modes[m['mode_id']];a=post.assets[row['post_descriptor_role']]
        child=store._descriptor(root,ref(a),'liver_lobule','post',pre.generation_id,spec_override=leaf_spec(store,spec,m));flat(post,cp,m,'pre');flat(post,child,m,'post')
        require(post.assets[row['pre_descriptor_role']].sha256==cp.descriptor_sha256 and child.assets['source_mode_projection'].sha256==cp.assets['source_mode_projection'].sha256,'leaf independent source projection changed')
        child=store._pair(cp,child,root=root)
        profile=read_json(child.assets['microrefine_profile'].path);binding=profile['final_microrefine'].get('mode_binding');exact(binding,CONTRACT['mode_binding_keys'],'executed mode binding')
        expected={'model_id':'liver_lobule','mode_id':m['mode_id'],'parent_pre_descriptor_sha256':pre.descriptor_sha256,'parent_pre_primary_sha256':pre.primary.sha256,'parent_pre_validation_sha256':pre.assets['validation'].sha256,'parent_source_build_sha256':pre.provenance['source_build_sha256'],'parent_source_receipt_sha256':pre.provenance['source_receipt_sha256'],'projection_sha256':cp.assets['source_mode_projection'].sha256,'scope_selector_order':m['selectors']}
        require(binding==expected and profile['expected_parts']==m['selectors'] and not profile['final_microrefine'].get('component_binding'),'executed mode is not bound to exact final humanPre/source scope')
        require(row['geometry_outcome']==child.geometry_outcome,'mode measured outcome changed')
        _,ids=identities(child.primary.path);require(list(ids)==m['selectors'],'actual saved mode25/8 source order changed');all_ids.update(ids);children[m['mode_id']]=child;outcomes[m['mode_id']]=child.geometry_outcome
    require(len({c.assets['microrefine_execution'].sha256 for c in children.values()})==2 and len({pre.verified_modes[mid].primary.sha256 for mid in children})==2,'copied/nonindependent mode executions')
    meta,display=identities(post.primary.path);parent_meta,_=identities(pre.assets['canonical_payload'].path)
    require(meta==parent_meta and list(display)==ORDER and display=={n:all_ids[n] for n in ORDER},'full saved Post arrays/metadata differ from verified saved modes')
    require(ra['mode_saved_output_sha256']=={mid:c.primary.sha256 for mid,c in children.items()} and len(ra['parts'])==33,'reassembly missing actual leaf payload identities')
    for i,(n,row) in enumerate(zip(ORDER,ra['parts'])):
        mode=next(m for m in MODES if n in m['selectors']);mid=mode['mode_id']
        require(row==dict(display[n],source_index=i,mode_id=mid,mode_part_index=mode['selectors'].index(n),arrays_exact=True),'reassembly actual part witness changed')
    outcome='changed' if 'changed' in outcomes.values() else 'no_change'
    require(ex['composite_geometry_outcome']==post.geometry_outcome==outcome,'aggregate no_change requires genuine no_change from both modes')
    return children,outcomes
