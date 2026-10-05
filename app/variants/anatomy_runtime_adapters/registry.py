"""Explicit shipped39 catalog. Dataset manifests cannot supply import paths."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
import json
from .inspectors import inspect_native,read_json

HERE=Path(__file__).resolve().parent
_raw=json.loads((HERE/'contracts.json').read_text(encoding='utf8'))
CONTRACTS=MappingProxyType({e['model_id']:e for e in _raw['entries']})
EXPECTED_MODEL_IDS=tuple(CONTRACTS)
if len(EXPECTED_MODEL_IDS)!=39:raise RuntimeError('Shipped39 registry incomplete')
ADAPTER_IDS=tuple(e['adapter_id'] for e in CONTRACTS.values())

@dataclass(frozen=True)
class RuntimeAdapter:
    adapter_id:str
    model_ids:tuple[str,...]
    primary_types:frozenset
    required_roles:dict
    optional_roles:dict
    inspector:object=None
    validator:object=None
    pair_validator:object=None


def contract(model_id):
    try:return CONTRACTS[model_id]
    except KeyError:raise ValueError('Model is outside the shipped new39 catalog') from None


def validate_descriptor_controls(descriptor):
    from .controls import validate_controls
    roles={a.role:a for a in descriptor.companions}
    if len(roles)!=len(descriptor.companions):raise ValueError('Duplicate companion roles')
    entry=contract(descriptor.model_id)
    if descriptor.adapter_id!=entry['adapter_id']:raise ValueError('Wrong model-specific adapter')
    absent=set(entry['required_roles'])-set(roles)
    if absent:raise ValueError('Missing runtime sidecars: '+', '.join(sorted(absent)))
    d=read_json(roles['runtime_controls'].path,max_bytes=16*1024*1024)
    validate_controls(d,model_id=descriptor.model_id,variant=descriptor.variant,primary_sha256=descriptor.primary.sha256)
    from .companions import validate_companions
    validate_companions(descriptor,d)


def store_adapter_specs(spec_type=None,*,glb_inspector=None):
    """Create VariantStore AdapterSpec objects without importing the native app.

    Pass the store's AdapterSpec type; None returns local structural dataclasses.
    GLB parsing/fingerprint authority belongs to the store's shipped inspector.
    """
    cls=spec_type or RuntimeAdapter
    result={}
    def inspect_glb_primary(path, schema):
        if schema != 'gltf2-glb':
            raise ValueError('Unexpected GLB primary schema')
        return glb_inspector(path)
    for model,e in CONTRACTS.items():
        inspector=inspect_native if e['primary_format']=='npz' else (inspect_glb_primary if glb_inspector is not None else None)
        types={}
        for role,path in e['required_roles'].items():
            if role=='runtime_controls':types[role]=frozenset({('json','ae-runtime-controls-v1')})
            elif role=='color_contract':types[role]=frozenset({('json','ae-position-colors-v1')})
            elif role=='colors':types[role]=frozenset({('npz','ae-linear-rgb-v1')})
            elif role=='animation_contract':types[role]=frozenset({('json','ae-position-animation-v1')})
            elif role=='animation':types[role]=frozenset({('npz','ae-four-morph-phase-v1')})
            elif model=='axillary_skin' and role=='cell_inset':
                types[role]=frozenset({('npz','anatomy-npz-v4'),('npz','anatomy-npz-f32-delta-v1')})
            elif path.endswith('.npz'):types[role]=frozenset({('npz','ae-model-data-v1')})
            else:types[role]=frozenset({('json','ae-model-data-v1')})
        kwargs=dict(adapter_id=e['adapter_id'],model_ids=frozenset({model}),primary_types=frozenset((e['primary_format'],s) for s in e['primary_schemas']),
                    required_roles=types,optional_roles={},
                    inspector=inspector,validator=validate_descriptor_controls,pair_validator=None)
        result[e['adapter_id']]=cls(**kwargs)
    return result


def metadata_catalog():
    return tuple({'id':m,'model_id':m,'name':e['display_name'],'summary':e['catalog_metadata'].get('summary') or '',
                  'scale_note':e['catalog_metadata'].get('scale_note') or '',
                  'histology':e['catalog_metadata'].get('histology') or [],'targets':{},'related':[],
                  'clinical':[],'order':i,'kind':'procedural' if e['primary_format']=='npz' else 'glb'}
                 for i,(m,e) in enumerate(CONTRACTS.items()))

# Public name used by the current-main integration.
adapter_specs = store_adapter_specs
