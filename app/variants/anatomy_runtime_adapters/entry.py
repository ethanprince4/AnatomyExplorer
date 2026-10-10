"""ModelEntry-compatible descriptor wrapper; never a ProceduralEntry."""
from __future__ import annotations
from types import SimpleNamespace
from .registry import contract
from .inspectors import read_json
from .runtime import load_variant

def _field(meta,key,default=None):
    return meta.get(key,default) if isinstance(meta,dict) else getattr(meta,key,default)

class VariantEntry:
    """One selected model/variant; switching creates a new immutable entry."""
    def __init__(self,meta,store,descriptor=None,*,component=None):
        self.meta,self.store=meta,store
        self.id=_field(meta,'id',_field(meta,'model_id'))
        c=contract(self.id)
        self.descriptor=descriptor or store.selected(self.id)
        if self.descriptor.model_id!=self.id or self.descriptor.adapter_id!=c['adapter_id']:raise ValueError('Entry/descriptor adapter identity differs')
        self.variant=self.descriptor.variant;self.label=self.descriptor.label
        self.available_components=('main','cell_inset') if self.id=='axillary_skin' else ()
        self.component=component or 'main'
        if self.component!='main' and self.component not in self.available_components:raise ValueError('Unknown shipped component')
        # The store exposes this only after complete parent/execution/audit
        # validation. Catalog metadata or detached receipt text is not authority.
        self.microrefine_outcome=getattr(self.descriptor,'outcome',None)
        if self.microrefine_outcome not in (None,'changed','no_change'):
            raise ValueError('Unrecognized verified microrefine outcome')
        self.outcome=self.microrefine_outcome
        self.validation_scope=getattr(self.descriptor,'validation_scope',None)
        self.baseline_defects=getattr(self.descriptor,'baseline_defects',None)
        self.component_baseline_defects=getattr(self.descriptor,'component_baseline_defects',None)
        self.name=_field(meta,'name',c['display_name']);self.summary=_field(meta,'summary','')
        self.targets=dict(_field(meta,'targets',{}) or {});self.histology=list(_field(meta,'histology',()) or ())
        self.related=list(_field(meta,'related',()) or ());self.clinical=[tuple(x) for x in (_field(meta,'clinical',()) or ())]
        self.scale_note=_field(meta,'scale_note','');self.credit_html=_field(meta,'credit_html','')
        self.aliases=dict(_field(meta,'aliases',{}) or {});self.order=int(_field(meta,'order',100))
        self.kind='glb' if self.descriptor.primary.format=='glb' else 'procedural'
        self.oriented=bool(_field(meta,'oriented',self.kind=='glb'))
        self.model_id=self.id
        choices=_field(meta,'variants',None)
        self.available_variants=tuple(v for v in ('pre','post') if choices is None or v in choices)
        if self.component=='cell_inset':
            from .components import selected_component,inset_controls
            from .inspectors import metadata
            child=selected_component(self.descriptor,self.component)
            controls=inset_controls(self.descriptor,metadata(child.primary.path)['parts'])
            self.baseline_defects=child.baseline_defects
        else:controls=read_json(self.descriptor.assets['runtime_controls'].path,max_bytes=16*1024*1024)
        self.micro=SimpleNamespace(labels_on_open=controls['native'].get('labels_on_open',False))
        self.scale_note=controls['native']['scale_note']
    @property
    def kind_name(self):return '3D model' if self.kind=='glb' else '3D microanatomy model'
    def available(self):return bool(self.store.revalidate(self.descriptor))
    def for_variant(self,variant):return type(self)(self.meta,self.store,self.store.resolve(self.id,variant),component=self.component)
    def for_component(self,component):return type(self)(self.meta,self.store,self.store.resolve(self.id,self.variant),component=component)
    def prepare_cpu(self,token=None):return load_variant(self.descriptor,token,store=self.store,component=None if self.component=='main' else self.component)
    def load(self):return self.prepare_cpu()
    def commit_selection(self):return self.store.select(self.id,self.variant,expected_token=self.descriptor.token)
    def _lookups(self,model):
        from app.viewer.catalog import ModelEntry
        return ModelEntry._lookups(self,model)
    def resolve(self,model,names):
        # Delegate only this stateless lookup to the existing native contract;
        # this is a live UI method, never invoked during package/source import.
        from app.viewer.catalog import ModelEntry
        return ModelEntry.resolve(self,model,names)
