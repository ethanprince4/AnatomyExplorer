"""One bounded shipped component lane; never recursive external catalogs/plugins."""
from __future__ import annotations
from dataclasses import dataclass
from .security import exact,read_json,require


@dataclass(frozen=True)
class ComponentSpec:
    component_id: str = 'cell_inset'
    adapter_id: str = 'ae.axillary_skin.cell_inset.runtime.v1'
    source_role: str = 'cell_inset'
    post_role: str = 'cell_inset'
    primary_types: frozenset = frozenset({('npz','anatomy-npz-v4'),('npz','anatomy-npz-f32-delta-v1')})
    def __post_init__(self):
        # Expansion requires reviewed shipped code, not another manifest entry.
        require((self.component_id,self.adapter_id,self.source_role,self.post_role)==('cell_inset','ae.axillary_skin.cell_inset.runtime.v1','cell_inset','cell_inset'),'component is outside shipped one-level allowlist')
        require(self.primary_types==frozenset({('npz','anatomy-npz-v4'),('npz','anatomy-npz-f32-delta-v1')}),'component codec allowlist changed')


def role_name(component_id,variant,role):
    return f'component_{component_id}_{variant}_{role}'


def component_roles(components,variant):
    required={};optional={}
    for c in components:
        fields={'descriptor':('json','anatomy-variant'),'source_receipt':('json','anatomy-source-receipt-v1'),'validation':('json','anatomy-validation-v1')}
        if variant=='pre':fields['pre_baseline_report']=('json','ae.saved-pre-policy-validation.v1')
        else:
            from .execution import POST_ROLES
            fields.update({k:next(iter(v)) for k,v in POST_ROLES.items()})
            required['microrefine_components']=frozenset({('json','anatomy-microrefine-components-v1')})
        for role,type_ in fields.items():required[role_name(c.component_id,variant,role)]=frozenset({type_})
        from .correspondence import CANONICAL_ROLES
        for role,type_ in CANONICAL_ROLES.items():optional[role_name(c.component_id,variant,role)]=type_
    return required,optional


def _ref(asset):
    return {'path':asset.relative_path,'sha256':asset.sha256,'size':asset.size}


def _exact_render_asset(parent,leaf,role):
    expected=parent.assets.get(role)
    require(expected is not None and leaf.primary.path==expected.path and leaf.primary.sha256==expected.sha256 and leaf.primary.size==expected.size,'component proof differs from actual selected renderable companion')


def validate_pre_components(store,root,parent,spec,budget=None):
    result={}
    for c in spec.components:
        require(parent.model_id=='axillary_skin','component attached to unexpected model')
        asset=parent.assets[role_name(c.component_id,'pre','descriptor')]
        leafspec=store._component_adapters[c.adapter_id]
        child=store._descriptor(root,_ref(asset),parent.model_id,'pre',parent.generation_id,budget,spec_override=leafspec)
        _exact_render_asset(parent,child,c.source_role)
        require(child.provenance['source_build_sha256']==parent.provenance['source_build_sha256'],'component Pre is not from same completed source build')
        _declared_child_files(parent,child,c,'pre')
        result[c.component_id]=child
    return result


def _declared_child_files(parent,child,c,variant):
    # Every nested file must also be explicitly declared in the flat generation
    # manifest through deterministic roles. No arbitrary recursive traversal.
    for a in child.companions:
        expected=parent.assets.get(role_name(c.component_id,variant,a.role))
        require(expected is not None and (expected.path,expected.sha256,expected.size,expected.format,expected.schema)==(a.path,a.sha256,a.size,a.format,a.schema),'component evidence is undeclared or mismatched in parent variant')


def validate_post_components(store,root,pre,post,spec,budget=None):
    if not spec.components:return {},{}
    data=read_json(post.assets['microrefine_components'].path)
    exact(data,{'schema','schema_version','model_id','generation_id','parent_pre_descriptor_sha256','source_build_sha256','source_receipt_sha256','primary_geometry_outcome','composite_geometry_outcome','components'},'microrefine components container')
    require(data['schema']=='anatomy-microrefine-components-v1' and type(data['schema_version']) is int and data['schema_version']==1,'unsupported bounded component proof schema')
    require(data['model_id']==pre.model_id=='axillary_skin' and data['generation_id']==pre.generation_id==post.generation_id and data['parent_pre_descriptor_sha256']==pre.descriptor_sha256,'components do not bind same model/immutable Pre generation')
    require(data['source_build_sha256']==pre.provenance['source_build_sha256'] and data['source_receipt_sha256']==pre.provenance['source_receipt_sha256'],'components source build/receipt mismatch')
    require(data['primary_geometry_outcome']==post.geometry_outcome,'component aggregate cannot rewrite main primary engine outcome')
    entries=data['components'];require(isinstance(entries,list) and len(entries)==len(spec.components)<=1,'missing/additional/nested component proofs')
    outcome={};children={};seen=set()
    by_id={c.component_id:c for c in spec.components}
    for entry in entries:
        exact(entry,{'component_id','adapter_id','source_role','post_role','source_component_sha256','post_component_sha256','pre_descriptor_role','post_descriptor_role','geometry_outcome'},'component proof entry')
        require(isinstance(entry['component_id'],str) and entry['component_id'] in by_id and entry['component_id'] not in seen,'unallowlisted/repeated component')
        c=by_id[entry['component_id']];seen.add(c.component_id)
        expected={'adapter_id':c.adapter_id,'source_role':c.source_role,'post_role':c.post_role,'source_component_sha256':pre.assets[c.source_role].sha256,
          'post_component_sha256':post.assets[c.post_role].sha256,'pre_descriptor_role':role_name(c.component_id,'pre','descriptor'),'post_descriptor_role':role_name(c.component_id,'post','descriptor')}
        require(all(entry.get(k)==v for k,v in expected.items()),'component roles/identities differ from shipped render-data mapping')
        childpre=pre.verified_components[c.component_id]
        require(pre.assets[entry['pre_descriptor_role']].sha256==childpre.descriptor_sha256,'component Pre proof changed')
        childpost=store._descriptor(root,_ref(post.assets[entry['post_descriptor_role']]),pre.model_id,'post',pre.generation_id,budget,spec_override=store._component_adapters[c.adapter_id])
        _exact_render_asset(post,childpost,c.post_role);_declared_child_files(post,childpost,c,'post')
        childpost=store._pair(childpre,childpost,root=root)
        profile=read_json(childpost.assets['microrefine_profile'].path)
        binding=profile.get('final_microrefine',{}).get('component_binding')
        exact(binding,{'model_id','component_id','source_role','post_role','parent_pre_descriptor_sha256','parent_pre_generation_id','source_component_sha256','parent_source_build_sha256','parent_source_receipt_sha256'},'component profile parent binding')
        expected={'model_id':pre.model_id,'component_id':c.component_id,'source_role':c.source_role,'post_role':c.post_role,'parent_pre_descriptor_sha256':pre.descriptor_sha256,'parent_pre_generation_id':pre.generation_id,
          'source_component_sha256':pre.assets[c.source_role].sha256,'parent_source_build_sha256':pre.provenance['source_build_sha256'],'parent_source_receipt_sha256':pre.provenance['source_receipt_sha256']}
        require(binding==expected,'component profile is not bound to exact same parent Pre source/generation')
        require(entry['geometry_outcome']==childpost.geometry_outcome,'component result does not match independently validated original engine execution')
        outcome[c.component_id]=childpost.geometry_outcome
        children[c.component_id]=childpost
    aggregate='changed' if post.geometry_outcome=='changed' or 'changed' in outcome.values() else 'no_change'
    require(data['composite_geometry_outcome']==aggregate,'aggregate no_change requires genuine no_change from main AND all shipped components')
    return children,outcome
