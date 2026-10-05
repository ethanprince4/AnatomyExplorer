"""Apply review data through existing native APIs; no application launch on import.

Future isolated integration adds create_review_descriptor(...) to the ordinary
model selector, then existing ProceduralModel/ModelView consume these cameras.
This module never changes the original registry or global teaching defaults.
"""
import json
from copy import deepcopy
from pathlib import Path


def configure(descriptor, fragment_path=None):
    if descriptor.id != 'oesophagus_wall':
        raise ValueError('Expected oesophagus_wall review descriptor')
    path=Path(fragment_path) if fragment_path else Path(__file__).with_name('teaching.json')
    values=json.loads(path.read_text(encoding='utf-8'))['oesophagus_wall']
    for key,value in values.items():
        setattr(descriptor,key,deepcopy(value))
    return descriptor


def apply_native_view(model_view, view_name):
    cameras=model_view.vmodel.cameras
    if view_name not in cameras:
        raise ValueError('Unknown oesophageal teaching view: '+view_name)
    model_view.set_named_view(view_name)
    alpha=cameras[view_name].get('tissue_opacity_percent',28 if view_name.startswith(('3 ','4 ','5 ')) else 100)
    slider=getattr(model_view,'opacity',None)
    if slider is not None: slider.setValue(alpha)
    model_view._opacity(alpha)
    focus=cameras[view_name].get('focus_parts',[])
    if focus:
        keys={item.key:item.index for item in model_view.vmodel.items}
        model_view.state.select([keys[name] for name in focus])
        model_view.gl_widget.update()
    return cameras[view_name].get('note','')


def create_review_descriptor(native_output):
    """Requires native app modules available; instantiate only on compute/review host.

    Uses real load_parts with the saved digest and supplies all Parts to the
    ordinary ProceduralModel path. An unloaded cache never calls a builder.
    """
    folder=Path(native_output).resolve()
    receipt=json.loads((folder/'build_receipt.json').read_text(encoding='utf-8'))
    from app.micro import cache
    from app.micro.base import MicroModel
    previous=cache.CACHE_DIR
    try:
        cache.CACHE_DIR=folder
        parts=cache.load_parts('oesophagus_wall',digest=receipt['digest'])
    finally:
        cache.CACHE_DIR=previous
    if parts is None:
        raise ValueError('Native review cache unavailable or incompatible')
    def unavailable_builder():
        raise RuntimeError('Review descriptor must use its supplied native cache')
    descriptor=MicroModel('oesophagus_wall','Oesophagus wall — review','',unavailable_builder,
                          targets={'structures':['Oesophagus']},histology=('oesophagus','strat_squamous_nk'))
    configure(descriptor,folder/'teaching.json')
    descriptor.name='Oesophagus wall — review'
    descriptor._parts=parts
    return descriptor
