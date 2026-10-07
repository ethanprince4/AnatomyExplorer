"""Detached CPU preparation for verified immutable model variants.

Native app/NumPy imports are deferred until explicit selected-entry preparation.
No legacy registry, builder/source digest, external Python or global CACHE_DIR.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,importlib,json,math
from pathlib import Path
from types import SimpleNamespace
from .inspectors import FIELDS,metadata,read_json
from .controls import validate_controls
from .registry import HERE,contract,validate_descriptor_controls

class CancelledLoad(RuntimeError):pass

def checkpoint(token):
    if token is None:return
    for name in ('checkpoint','raise_if_cancelled','check'):
        method=getattr(token,name,None)
        if callable(method):method();return
    flag=getattr(token,'cancelled',False)
    if callable(flag):flag=flag()
    if flag:raise CancelledLoad('Selected model load cancelled')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def _hook(model_id,category):
    # Literal allowlist copied with the application, never sourced from dataset.
    manifest=json.loads((HERE/'shipped_hooks.json').read_text(encoding='utf8'))
    row=manifest.get(model_id,{}).get(category)
    if row is None:return None
    return importlib.import_module('.hooks.'+row['module'],__package__)


def decode_native(path,schema,token=None):
    """Yield exact source-precision metadata/p/n/triangle/color buffers."""
    import numpy as np
    m=metadata(path);parts=[]
    f32=schema=='anatomy-npz-f32-delta-v1'
    if schema not in ('anatomy-npz-f32-delta-v1','anatomy-npz-v4'):raise ValueError('Native codec not allowlisted')
    if f32 and (m.get('position_encoding'),m.get('normal_encoding'))!=('float32','float32'):raise ValueError('Incorrect f32 native encoding')
    with np.load(path,allow_pickle=False) as z:
        for i,row in enumerate(m['parts']):
            checkpoint(token)
            if f32:
                p=z[f'p{i}'].copy();n=z[f'n{i}'].copy()
                if p.dtype!=np.float32 or n.dtype!=np.float32:raise ValueError('Native float32 precision lost')
            else:
                lo,span=z[f'b{i}'];p=(z[f'p{i}'].astype(np.float64)/65535.0*span+lo).astype(np.float32)
                n=z[f'n{i}'].astype(np.float32)/127.0;n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-6)
            f=np.cumsum(z[f'i{i}'].astype(np.int64)).reshape(-1,3)
            if p.ndim!=2 or p.shape[1]!=3 or n.shape!=p.shape or not np.isfinite(p).all() or not np.isfinite(n).all():raise ValueError('Invalid native vertex buffers')
            if f.size and (f.min()<0 or f.max()>=len(p)):raise ValueError('Native index outside part')
            colors=z[f'c{i}'].copy() if f'c{i}' in z.files else None
            if colors is not None:_validate_colors(colors,p)
            parts.append((deepcopy(row),p,n,f,colors))
    checkpoint(token)
    return m,parts


def _validate_colors(c,p):
    import numpy as np
    if c.dtype!=np.float32 or c.shape!=p.shape or not np.isfinite(c).all() or np.any((c<0)|(c>1)):raise ValueError('Invalid finite linear RGB companion')


def load_colors(descriptor,decoded):
    import numpy as np
    colors={row['name']:c for row,p,n,f,c in decoded if c is not None}
    assets=descriptor.assets
    if 'colors' not in assets:return colors
    doc=read_json(assets['color_contract'].path)
    if (doc.get('schema')!='ae-position-colors-v1' or doc.get('model_id')!=descriptor.model_id or doc.get('variant')!=descriptor.variant or doc.get('primary_sha256')!=descriptor.primary.sha256 or doc.get('colors_sha256')!=assets['colors'].sha256 or doc.get('encoding')!='linear_rgb_float32'):raise ValueError('Color contract has wrong selected geometry/variant')
    rows=doc.get('parts',[]);by_name={r['name']:r for r in rows}
    if len(by_name)!=len(rows):raise ValueError('Duplicate color selectors')
    actual={r['name']:p for r,p,n,f,c in decoded}
    if set(by_name)-set(actual):raise ValueError('Color selector not in native metadata')
    with np.load(assets['colors'].path,allow_pickle=False) as z:
        if set(z.files)!={r['array_key'] for r in rows}:raise ValueError('Missing/extra color arrays')
        for name,row in by_name.items():
            p=actual[name]
            if hashlib.sha256(p.tobytes(order='C')).hexdigest()!=row['positions_sha256']:raise ValueError('Color companion cannot follow changed positions: '+name)
            c=z[row['array_key']].copy();_validate_colors(c,p)
            if row['vertex_count']!=len(p) or hashlib.sha256(c.tobytes(order='C')).hexdigest()!=row['colors_sha256']:raise ValueError('Color binding byte identity changed')
            colors[name]=c
    return colors


class NativeBackend:
    """Only native factory implementation. Tests inject tiny pure Python factories."""
    def part(self,row,p,n,f):
        from app.micro.base import Part
        from app.micro.geometry import Mesh
        part=Part(row['name'],row['group'],row['color'],Mesh().add(p,f,n),row['description'],
                  **{k:deepcopy(row[k]) for k in ('alpha','category','label','rank','clip','bulk','detail')})
        # Native Part historically rewrites clip when bulk=True. Exact saved
        # descriptors, including nonclipping bulk and feature metadata, win.
        for key in FIELDS:
            setattr(part,key,tuple(row[key]) if key=='detail' else deepcopy(row[key]))
        for key in ('feature','role'):
            if key in row:setattr(part,key,deepcopy(row[key]))
        return part
    def micro(self,model_id,name,summary,parts):
        from app.micro.base import MicroModel
        def prohibited():raise RuntimeError('Immutable selected variant cannot rebuild')
        model=MicroModel(model_id,name,summary,prohibited)
        model._parts=parts
        # Defend against any MicroModel implementation that revalidates legacy
        # digest before returning _parts. These methods have no build route.
        model.parts=lambda:parts
        model.build=prohibited
        return model
    def procedural(self,micro,parts):
        from app.viewer.procedural import ProceduralModel
        return ProceduralModel(micro,parts=parts)
    def glb(self,descriptor,controls):
        from app.viewer.model import Model
        side=deepcopy(controls['verified_documents'].get('viewer'))
        if not isinstance(side,dict):raise ValueError('Verified GLB teaching sidecar missing')
        # Never let Model discover a neighboring unlisted/unhashed sidecar.
        class BoundModel(Model):
            def _load_sidecar(self):return deepcopy(side)
        model=BoundModel(descriptor.primary.path)
        catalog=controls['verified_documents'].get('catalog')
        if catalog:
            from app.viewer.catalog import apply_meta
            apply_meta(model,catalog)
        return model


def _prepare_animation(descriptor,micro,parts,metadata):
    import numpy as np
    if descriptor.model_id=='pancreas':
        a=descriptor.assets['animation']
        with np.load(a.path,allow_pickle=False) as z:
            if bytes(z['digest']).decode()!=metadata['digest']:raise ValueError('Animation/source native digest mismatch')
            expected={'digest'}
            for i,part in enumerate(parts):
                if f'm{i}' not in z.files:continue
                morph=z[f'm{i}'].astype(np.float32);phase=z[f'f{i}'].copy();p=part.mesh.arrays()[0]
                if morph.ndim!=3 or morph.shape[0]!=len(p) or morph.shape[2]!=3 or not 1<=morph.shape[1]<=4 or phase.shape!=(len(p),) or not np.isfinite(morph).all() or not np.isfinite(phase).all():raise ValueError('Invalid position-bound morph/phase data')
                part.anim={'morph':morph,'phase':phase};expected.update((f'm{i}',f'f{i}'))
            if set(z.files)!=expected:raise ValueError('Animation has unsupported channels')
        from .pancreas_animation import make_animation
        micro.animation=make_animation()


def _prepare_hooks(descriptor,micro,controls,parts):
    model_id=descriptor.model_id;names=[p.name for p in parts];docs=controls['documents'];variant_id=descriptor.variant+'_refine'
    if model_id in ('thin_skin','thick_skin'):
        function=_hook(model_id,'function');teaching=_hook(model_id,'teaching')
        function.configure(micro,names,path=descriptor.assets['model_function'].path,
                           variant_id=variant_id,content_identity=descriptor.primary.sha256)
        teaching.configure(micro,controls['verified_documents']['native_controls'],names,
                           variant_id=variant_id,content_identity=descriptor.primary.sha256)
    elif model_id=='tooth':_hook(model_id,'teaching').apply_to_micro_model(micro,docs[0])
    elif model_id=='muscular_artery':_hook(model_id,'teaching').attach_metadata(micro,names,docs[0])
    elif model_id=='thyroid_follicles':
        function=_hook(model_id,'function');micro.animation=function.FunctionAnimation(docs[1],controls['parts'],model_id=model_id,variant_id=variant_id,artifact_sha256=descriptor.primary.sha256)
    # Explicit attachment after ordinary native defaults, never builder imports.
    micro.runtime_controls=deepcopy(controls)
    micro.runtime_identity=descriptor.token
    micro.runtime_descriptor=descriptor


def _retire_native_backing(model,part_metadata):
    """Release converted source meshes/colors while preserving viewer data.

    Viewer vertices/indices, packed animation channels, animation dispatch,
    camera/bounds and per-item presentation state remain unchanged. Shipped
    teaching/function hooks use source metadata/bindings and viewer buffers,
    not raw source meshes after preparation.
    """
    source=model.source
    source.part_metadata=tuple(deepcopy(row) for row in part_metadata)
    # Preserve field-level metadata used by teaching/restoration and diagnostics
    # without retaining Part.mesh or source morph/phase arrays.
    source._parts=tuple(SimpleNamespace(**deepcopy(row)) for row in part_metadata)
    def retired():
        raise RuntimeError('Raw immutable source meshes were retired after viewer conversion; no rebuild is allowed')
    source.parts=retired
    source.viewer_vertex_colors=None
    model._part_sources=[]


def _resolve_fit_cameras(model,controls):
    """Translate explicit source yaw/pitch poses to ordinary camera records.

    Source anchors are already final-coordinate teaching data. Framing uses
    saved viewer bounds only; no geometry or scale normalization occurs.
    """
    if not any('yaw_radians' in c for c in model.cameras.values()):return
    import numpy as np
    if not hasattr(model,'bounds_min') or not hasattr(model,'bounds_max'):return
    lo=np.asarray(model.bounds_min,float);hi=np.asarray(model.bounds_max,float)
    anchors=controls['verified_documents'].get('construction',{}).get('anchors',{})
    for name,old in list(model.cameras.items()):
        if 'yaw_radians' not in old:continue
        target=old.get('target')
        if old.get('target_anchor') and old['target_anchor'] in anchors:
            target=anchors[old['target_anchor']]
        target=np.asarray(target if target is not None else (lo+hi)/2,float)
        radius=float(old.get('radius_units',max(float(np.linalg.norm(hi-lo))/2,1e-3)))
        yaw=float(old['yaw_radians']);pitch=float(old['pitch_radians']);distance=radius/math.sin(math.radians(40)/2)*1.12
        direction=np.array([math.cos(pitch)*math.sin(yaw),math.sin(pitch),math.cos(pitch)*math.cos(yaw)])
        model.cameras[name]=dict(old,position=(target+distance*direction).tolist(),target=target.tolist(),type='PERSP',fov_deg=40.)


def load_variant(descriptor,token=None,*,store,backend=None,component=None):
    """Public selected-entry load. All work detached until caller installs result."""
    checkpoint(token)
    current=store.revalidate(descriptor)
    if current is not None:descriptor=current
    if component is not None:
        return _load_component(descriptor,component,token,store,backend or NativeBackend())
    validate_descriptor_controls(descriptor)
    assets=descriptor.assets;controls=read_json(assets['runtime_controls'].path,max_bytes=16*1024*1024)
    backend=backend or NativeBackend()
    if descriptor.primary.format=='glb':
        model=backend.glb(descriptor,controls)
    else:
        meta,decoded=decode_native(descriptor.primary.path,descriptor.primary.schema,token)
        if meta['parts']!=controls['parts']:raise ValueError('Saved native descriptors differ from bound controls')
        colors=load_colors(descriptor,decoded);parts=[]
        for row,p,n,f,c in decoded:
            checkpoint(token);parts.append(backend.part(row,p,n,f))
        e=contract(descriptor.model_id)
        micro=backend.micro(descriptor.model_id,e['display_name'],controls['native'].get('summary',''),parts)
        for k,v in controls['native'].items():setattr(micro,k,deepcopy(v))
        bound_positions={row['name']:p for row,p,n,f,c in decoded}
        def color_provider(name,positions):
            if name not in colors:return None
            import numpy as np
            if not np.array_equal(positions,bound_positions[name]):raise ValueError('Stale position-bound vertex colors')
            return colors[name]
        micro.viewer_vertex_colors=color_provider
        _prepare_animation(descriptor,micro,parts,meta)
        _prepare_hooks(descriptor,micro,controls,parts)
        model=backend.procedural(micro,parts)
        # Do not drop metadata/scale flags when crossing the procedural wrapper.
        model.sidecar.update(deepcopy(controls['viewer']))
        if descriptor.model_id=='tooth':_hook('tooth','teaching').apply_to_viewer_model(model,controls['documents'][0],model_id='tooth')
        if descriptor.model_id=='tongue_papillae':_hook('tongue_papillae','teaching').install_native_metadata(model,contract=controls['documents'][0],model_id='tongue_papillae')
    _resolve_fit_cameras(model,controls)
    if descriptor.primary.format=='glb':
        names=[item.key for item in model.items]
        if len(names)!=len(set(names)):raise ValueError('Ambiguous GLB item identity')
        for camera in model.cameras.values():
            if set(camera.get('hidden',[]))-set(names):raise ValueError('GLB teaching references unknown saved item')
    model.runtime_controls=deepcopy(controls);model.runtime_descriptor=descriptor;model.runtime_identity=descriptor.token
    model.sidecar.update(deepcopy(controls['viewer']))
    model.sidecar.update({'variant':descriptor.variant,'variant_label':descriptor.label,'model_id':descriptor.model_id,'generation_id':descriptor.generation_id,'descriptor_sha256':descriptor.descriptor_sha256})
    # Ruler reads this before ModelView construction. Never infer a biological
    # scale from an old registry or from rendered bounding-box dimensions.
    if descriptor.primary.format!='glb':model.metres_per_unit=controls['native']['metres_per_unit']
    checkpoint(token);store.revalidate(descriptor);checkpoint(token)
    if descriptor.primary.format!='glb':
        _retire_native_backing(model,meta['parts'])
    return model


def _load_component(descriptor,component,token,store,backend):
    from .components import selected_component,inset_controls
    child=selected_component(descriptor,component)
    meta,decoded=decode_native(child.primary.path,child.primary.schema,token)
    controls=inset_controls(descriptor,meta['parts'])
    parts=[]
    for row,p,n,f,c in decoded:
        checkpoint(token);parts.append(backend.part(row,p,n,f))
    micro=backend.micro(descriptor.model_id,'Axillary gland cells — enlarged schematic inset',controls['native']['summary'],parts)
    for key,value in controls['native'].items():setattr(micro,key,deepcopy(value))
    # Native inline RGB is position-bound to this child, never the main model.
    colors={row['name']:c for row,p,n,f,c in decoded if c is not None}
    micro.viewer_vertex_colors=lambda name,positions:colors.get(name)
    micro.runtime_descriptor=descriptor;micro.runtime_identity=descriptor.token
    micro.runtime_controls=deepcopy(controls)
    model=backend.procedural(micro,parts)
    model.runtime_controls=deepcopy(controls);model.runtime_descriptor=descriptor;model.runtime_identity=descriptor.token
    model.runtime_component_id=component;model.runtime_component_descriptor=child
    model.sidecar.update(deepcopy(controls['viewer']))
    model.sidecar.update({'variant':descriptor.variant,'variant_label':descriptor.label,'model_id':descriptor.model_id,
                         'component_id':component,'generation_id':descriptor.generation_id,'descriptor_sha256':descriptor.descriptor_sha256})
    model.metres_per_unit=0.0
    checkpoint(token);store.revalidate(descriptor);checkpoint(token)
    _retire_native_backing(model,meta['parts'])
    return model
