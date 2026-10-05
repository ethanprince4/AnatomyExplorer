"""Updater-independent immutable geometry registry. No builder or import fallback exists."""
from __future__ import annotations
import contextlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Callable, Mapping
import uuid
from .formats import expanded_npz_size, inspect_float32, inspect_glb, inspect_npz
from .execution import POST_ROLES, validate_execution
from .correspondence import CANONICAL_ROLES
from .validation import BASELINE_ROLES, validate_scope
from .grouped import GROUP_ROLES
from . import authored as authored_lane
from . import modes as liver_modes
from .components import ComponentSpec, component_roles, validate_pre_components, validate_post_components
from .security import (MAX_FILES, MAX_FILE, MAX_JSON, MAX_TOTAL, StoreValidationError, TOKEN,
    atomic_json, canonical_json, digest, exact, file_hash, fsync_directory, ident, integer,
    no_symlinks, read_json, relative_path, require, safe_open, safe_path, short_text)

SCHEMA_VERSION = 1
EXPECTED_MODEL_IDS = frozenset('axillary_skin bladder_wall blood_cells colon_wall compact_bone cornea duodenum ear elastic_artery eyeball female_reproductive hepatobiliary ileocecal_rectum ileum jejunum_comparison_c kidney_nephron kidney_section liver_lobule lung_acinus lung_acinus_review_v2 lymph_node male_reproductive muscular_artery oesophagus_wall pancreas peripheral_nerve retina scalp skeletal_muscle spleen stomach_wall thick_skin thin_skin thyroid_follicles thyroid_parathyroid_review_v2 tongue_papillae tooth trachea_wall vein_wall'.split())
LABELS = MappingProxyType({'pre': 'Pre refine', 'post': 'Post refine'})
MANDATORY_ROLES = MappingProxyType({'source_receipt': frozenset({('json','anatomy-source-receipt-v1')}), 'validation': frozenset({('json','anatomy-validation-v1')})})


def default_store_root():
    """Always external, including development runs. Never derive from sys._MEIPASS/ROOT."""
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'AnatomyExplorer' / 'model_variants' / 'v1'


@dataclass(frozen=True)
class AdapterSpec:
    """Constructed by shipped code only, never materialized from external manifest code."""
    adapter_id: str
    model_ids: frozenset[str]
    primary_types: frozenset[tuple[str, str]]
    required_roles: Mapping[str, frozenset[tuple[str, str]]] = field(default_factory=dict)
    optional_roles: Mapping[str, frozenset[tuple[str, str]]] = field(default_factory=dict)
    inspector: Callable[[Path, str], str] | None = None
    validator: Callable[['VerifiedVariant'], None] | None = None
    pair_validator: Callable[['VerifiedVariant', 'VerifiedVariant'], bool] | None = None
    components: tuple[ComponentSpec,...] | None = None
    def __post_init__(self):
        require(isinstance(self.adapter_id,str) and TOKEN.fullmatch(self.adapter_id), 'invalid shipped adapter id')
        require(self.model_ids and all(ident(v) for v in self.model_ids), 'adapter needs allowlisted models')
        require(self.primary_types, 'adapter needs primary types')
        require(not (set(self.required_roles) & set(self.optional_roles)), 'overlapping adapter roles')
        require(not ((set(self.required_roles)|set(self.optional_roles)) & ({'primary','validation','source_receipt'}|set(POST_ROLES)|set(CANONICAL_ROLES)|set(BASELINE_ROLES))), 'adapter cannot replace mandatory receipt roles')
        components=self.components
        if components is None:
            components=(ComponentSpec(),) if self.adapter_id=='ae.axillary_skin.runtime.v1' and self.model_ids==frozenset({'axillary_skin'}) and 'cell_inset' in self.required_roles else ()
        require(isinstance(components,tuple) and len(components)<=1 and all(isinstance(c,ComponentSpec) for c in components),'unbounded/untrusted component specification')
        require(not components or (self.adapter_id=='ae.axillary_skin.runtime.v1' and self.model_ids==frozenset({'axillary_skin'}) and 'cell_inset' in self.required_roles),'component scope outside shipped axillary render-data mapping')
        object.__setattr__(self,'components',components)
        for variant in ('pre','post'):
            cr,co=component_roles(components,variant)
            require(not (set(cr)|set(co)) & (set(self.required_roles)|set(self.optional_roles)),'adapter cannot override component evidence roles')
        object.__setattr__(self,'model_ids',frozenset(self.model_ids))
        object.__setattr__(self,'primary_types',frozenset(self.primary_types))
        object.__setattr__(self,'required_roles',MappingProxyType({k:frozenset(v) for k,v in self.required_roles.items()}))
        object.__setattr__(self,'optional_roles',MappingProxyType({k:frozenset(v) for k,v in self.optional_roles.items()}))


@dataclass(frozen=True)
class VerifiedAsset:
    role: str
    path: Path
    relative_path: str
    format: str
    schema: str
    sha256: str
    size: int


@dataclass(frozen=True)
class VerifiedVariant:
    model_id: str
    variant: str
    adapter_id: str
    generation_id: str
    descriptor_path: Path
    descriptor_sha256: str
    primary: VerifiedAsset
    companions: tuple[VerifiedAsset, ...]
    geometry_sha256: str
    provenance: Mapping
    schema_version: int = 1
    validation_scope: str = ''
    baseline_defects: Mapping | None = None
    verified_components: Mapping | None = None
    component_outcomes: Mapping | None = None
    verified_modes: Mapping | None = None
    mode_outcomes: Mapping | None = None
    @property
    def label(self):
        return LABELS[self.variant]
    @property
    def assets(self):
        return MappingProxyType({a.role: a for a in (self.primary,*self.companions)})
    @property
    def geometry_outcome(self):
        return self.provenance.get('geometry_outcome')
    @property
    def outcome(self):
        if self.variant=='post' and self.component_outcomes:
            return 'changed' if self.geometry_outcome=='changed' or 'changed' in self.component_outcomes.values() else 'no_change'
        return self.geometry_outcome
    @property
    def microrefine_outcome(self):
        return self.outcome
    @property
    def composite_geometry_outcome(self):
        return self.outcome if self.component_outcomes else None
    @property
    def component_baseline_defects(self):
        return MappingProxyType({k:v.baseline_defects for k,v in (self.verified_components or {}).items()})
    @property
    def validation_receipt(self):
        return self.assets['validation'].path
    @property
    def token(self):
        return (self.generation_id,self.model_id,self.variant,self.descriptor_sha256)


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    summary: str
    targets: Mapping
    histology: tuple
    related: tuple
    clinical: tuple
    scale_note: str
    aliases: tuple
    variants: Mapping[str, VerifiedVariant]
    @property
    def model_id(self):
        return self.id


@dataclass(frozen=True)
class PendingVariantIndex:
    """Descriptor/index integrity only; cannot be loaded as a VerifiedVariant."""
    model_id: str
    variant: str
    adapter_id: str
    generation_id: str
    descriptor_path: Path
    descriptor_sha256: str
    verification_state: str = 'pending'
    @property
    def label(self): return LABELS[self.variant]
    @property
    def token(self): return (self.generation_id,self.model_id,self.variant,self.descriptor_sha256)
    @property
    def outcome(self): return None


@dataclass(frozen=True)
class CatalogIndexEntry:
    id: str
    name: str
    summary: str
    targets: Mapping
    histology: tuple
    related: tuple
    clinical: tuple
    scale_note: str
    aliases: tuple
    variants: Mapping[str,PendingVariantIndex]
    verification_state: str = 'pending'
    @property
    def model_id(self): return self.id


@contextlib.contextmanager
def _lock(root):
    """OS-held lock automatically releases on crashes; no stale PID deletion/retries."""
    path = no_symlinks(root / '.write.lock', must_exist=False)
    flags = os.O_RDWR | os.O_CREAT | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_BINARY',0)
    fd = os.open(path,flags,0o600)
    f = os.fdopen(fd,'r+b')
    try:
        require(f.fileno() >= 0 and path.stat().st_nlink == 1, 'unsafe lock file')
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                f.write(b'0'); f.flush()
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as e:
                raise StoreValidationError('another datastore write is in progress') from e
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as e:
                raise StoreValidationError('another datastore write is in progress') from e
        yield
    finally:
        f.close()


def _schema(data, name, keys):
    exact(data, {'schema','schema_version'} | set(keys), name)
    require(data['schema'] == name and type(data['schema_version']) is int and data['schema_version'] == SCHEMA_VERSION, f'{name}: incompatible schema/version')
    return data


def _metadata(data):
    exact(data, {'name','summary','targets','histology','related','clinical','scale_note','aliases'}, 'model metadata')
    short_text(data['name'],'model name',256); short_text(data['summary'],'model summary')
    short_text(data['scale_note'],'model scale note')
    targets = data['targets']
    require(isinstance(targets,dict) and set(targets) <= {'categories','groups','structures'}, 'metadata targets invalid')
    def texts(value,what,limit=512):
        require(isinstance(value,list) and len(value)<=limit, f'{what}: list invalid')
        return tuple(short_text(v,what,4096) for v in value)
    targets = MappingProxyType({k:texts(v,'target') for k,v in targets.items()})
    clinical = data['clinical']
    require(isinstance(clinical,list) and len(clinical)<=128, 'clinical metadata invalid')
    for c in clinical:
        require(isinstance(c,list) and len(c)==2,'clinical entry invalid')
        for v in c: short_text(v,'clinical text')
    return dict(name=data['name'],summary=data['summary'],targets=targets,histology=texts(data['histology'],'histology'),related=texts(data['related'],'related'),clinical=tuple(tuple(c) for c in clinical),scale_note=data['scale_note'],aliases=texts(data['aliases'],'aliases'))


class VariantStore:
    def __init__(self,root=None,*,adapters: Mapping[str,AdapterSpec],expected_model_ids=EXPECTED_MODEL_IDS,forbidden_roots=()):
        self.root = no_symlinks(Path(root or default_store_root()),must_exist=False)
        self.adapters = MappingProxyType(dict(adapters))
        require(all(k == v.adapter_id and isinstance(v,AdapterSpec) for k,v in self.adapters.items()), 'adapter registry is not a trusted AdapterSpec mapping')
        self.expected_model_ids = frozenset(ident(m) for m in expected_model_ids)
        require(0 < len(self.expected_model_ids) <= 128, 'invalid required model set')
        # Callers must include app install/bundle and updater cleanup roots; default location is independent.
        for banned in forbidden_roots:
            banned = no_symlinks(Path(banned),must_exist=False)
            require(not self.root.is_relative_to(banned) and not banned.is_relative_to(self.root), 'variant store overlaps replaceable application/updater directory')
        self._component_adapters={}
        for parent in self.adapters.values():
            for c in parent.components:
                self._component_adapters[c.adapter_id]=AdapterSpec(c.adapter_id,parent.model_ids,c.primary_types,inspector=parent.inspector,components=())
        self._cache = None
        self._index_cache = None
        self.last_error = None

    def _init(self):
        no_symlinks(self.root,must_exist=False)
        self.root.mkdir(parents=True,exist_ok=True)
        no_symlinks(self.root)
        generations = self.root / 'generations'
        no_symlinks(generations,must_exist=False)
        generations.mkdir(exist_ok=True)

    def _asset(self,root,data,types,budget=None):
        exact(data,{'role','path','format','schema','sha256','size'},'asset')
        ident(data['role'],'asset role')
        require(isinstance(data['format'],str) and isinstance(data['schema'],str) and (data['format'],data['schema']) in types, 'asset representation is not allowlisted by shipped adapter')
        digest(data['sha256']); integer(data['size'],1,MAX_FILE,'asset size')
        path = safe_path(root,data['path'])
        require(path.suffix.lower()=='.'+data['format'],'asset extension/format mismatch')
        actual,size = file_hash(path)
        require(actual == data['sha256'] and size == data['size'], 'asset hash/size mismatch')
        if budget is not None and data['path'] not in budget['seen']:
            budget['seen'].add(data['path']); budget['compressed']+=size
            budget['expanded']+=expanded_npz_size(path) if data['format']=='npz' else size
            require(budget['compressed']<=MAX_TOTAL and budget['expanded']<=64*1024*1024*1024,'generation byte/decompression budget exceeded')
        if data['format'] == 'json': read_json(path)
        elif data['format'] == 'npz':
            if data['schema']=='ae.authored-source-bundle.v1':authored_lane.inspect_source_bundle(path)
            else:inspect_npz(path)
        elif data['format'] == 'glb': inspect_glb(path)
        elif data['format'] == 'png':
            with safe_open(path) as f: require(f.read(8)==b'\x89PNG\r\n\x1a\n','invalid PNG signature')
        elif data['format'] != 'bin':
            raise StoreValidationError('unsupported data asset format')
        return VerifiedAsset(data['role'],path,data['path'],data['format'],data['schema'],data['sha256'],data['size'])

    def _descriptor(self,root,ref,model_id,variant,generation_id,budget=None,*,spec_override=None):
        exact(ref,{'path','sha256','size'},'descriptor reference')
        digest(ref['sha256']); integer(ref['size'],1,MAX_JSON,'descriptor size')
        path = safe_path(root,ref['path'])
        sha,size = file_hash(path,maximum=MAX_JSON)
        require((sha,size)==(ref['sha256'],ref['size']), 'descriptor hash/size mismatch')
        data = _schema(read_json(path),'anatomy-variant',{'model_id','variant','adapter_id','primary','companions','geometry_sha256','provenance','validation'})
        require(data['model_id']==model_id and data['variant']==variant, 'descriptor model/variant identity mismatch')
        require(isinstance(data['adapter_id'],str),'invalid adapter identity type')
        spec = spec_override if spec_override is not None else self.adapters.get(data['adapter_id'])
        require(spec is None or data['adapter_id']==spec.adapter_id,'component adapter identity mismatch')
        require(spec is not None and model_id in spec.model_ids, 'unknown/nonmatching shipped adapter id')
        primary = self._asset(root,data['primary'],spec.primary_types,budget)
        require(primary.role == 'primary','primary role mismatch')
        roles = dict(MANDATORY_ROLES); roles.update(CANONICAL_ROLES); roles.update(BASELINE_ROLES)
        if model_id=='muscular_artery' and spec.adapter_id=='ae.muscular_artery.runtime.v1':
            roles.update(GROUP_ROLES if variant=='post' else {'grouped_material':GROUP_ROLES['grouped_material']})
        if variant=='post' and authored_lane.is_supported(model_id,spec.adapter_id):roles.update(authored_lane.AUTHORED_ROLES)
        mode_parent=liver_modes.is_parent(model_id,spec.adapter_id)
        mode_leaf=model_id=='liver_lobule' and spec.adapter_id in {m['adapter_id'] for m in liver_modes.MODES}
        if mode_parent: roles.update(liver_modes.roles(variant))
        if variant=='post' and not mode_parent: roles.update(POST_ROLES)
        component_required,component_optional=component_roles(spec.components,variant)
        roles.update(component_required);roles.update(component_optional)
        roles.update(spec.required_roles); roles.update(spec.optional_roles)
        companions = data['companions']
        require(isinstance(companions,list) and len(companions) <= 128, 'invalid companion count')
        seen = set(); checked = []
        for c in companions:
            require(isinstance(c,dict) and isinstance(c.get('role'),str) and c['role'] in roles and c['role'] not in seen, 'unrecognized/duplicate companion role')
            seen.add(c['role']); checked.append(self._asset(root,c,roles[c['role']],budget))
        require(set(MANDATORY_ROLES)|set(spec.required_roles)|set(component_required)|(set(liver_modes.roles(variant)) if mode_parent else (set(POST_ROLES) if variant=='post' else set())) <= seen,'required companions missing')
        assets = {a.role:a for a in checked}
        if set(assets)&set(authored_lane.AUTHORED_ROLES):
            require(set(authored_lane.AUTHORED_ROLES)|{'canonical_payload'}<=set(assets),'authored partial envelope cannot qualify a variant')
        provenance = exact(data['provenance'],{'source_build_sha256','source_receipt_sha256','source_pre_sha256','pre_descriptor_sha256','parent_pre_receipt_sha256','profile_sha256','algorithm_sha256','final_geometry_step','transformation_required','geometry_outcome','execution_receipt_sha256'},'variant provenance')
        for k in ('source_build_sha256','source_receipt_sha256','source_pre_sha256'): digest(provenance[k],k)
        require(provenance['source_receipt_sha256']==assets['source_receipt'].sha256,'source receipt identity mismatch')
        require(provenance['transformation_required'] is True,'required microrefine execution cannot be disabled')
        if variant == 'pre':
            require(provenance['source_pre_sha256']==primary.sha256 and provenance['final_geometry_step']=='source_improvement','Pre must be completed newly source-improved payload')
            require(all(provenance[k] is None for k in ('pre_descriptor_sha256','parent_pre_receipt_sha256','profile_sha256','algorithm_sha256','geometry_outcome','execution_receipt_sha256')), 'Pre provenance cannot depend on Post')
        else:
            require(provenance['final_geometry_step']=='microrefine','microrefine must be final model-changing step')
            for k in ('pre_descriptor_sha256','parent_pre_receipt_sha256','profile_sha256','algorithm_sha256','execution_receipt_sha256'): digest(provenance[k],k)
            require(isinstance(provenance['geometry_outcome'],str) and provenance['geometry_outcome'] in {'changed','no_change'},'Post requires explicit measured geometry outcome')
        source = _schema(read_json(assets['source_receipt'].path),'anatomy-source-receipt-v1',{'model_id','source_build_sha256','primary_sha256','stage','completed'})
        require(source['model_id']==model_id and source['source_build_sha256']==provenance['source_build_sha256'] and source['primary_sha256']==provenance['source_pre_sha256'] and source['stage']=='source_improved_complete' and source['completed'] is True,'source-improved receipt invalid')
        exact(data['validation'],{'status','receipt_role'},'validation declaration')
        require(data['validation']=={'status':'passed','receipt_role':'validation'},'variant validation incomplete/failed')
        validation = _schema(read_json(assets['validation'].path),'anatomy-validation-v1',{'model_id','variant','primary_sha256','geometry_sha256','source_pre_sha256','status','checks','scope','baseline_defects'})
        require(validation['model_id']==model_id and validation['variant']==variant and validation['primary_sha256']==primary.sha256 and validation['geometry_sha256']==data['geometry_sha256'] and validation['source_pre_sha256']==provenance['source_pre_sha256'] and validation['status']=='passed','validation receipt identity/status mismatch')
        require(isinstance(validation['checks'],list) and 0<len(validation['checks'])<=256,'validation checks missing')
        for c in validation['checks']: require(bool(short_text(c,'validation check',256)), 'empty validation check')
        baseline=validate_scope(validation,variant,assets,model_id=model_id,primary_sha256=primary.sha256,source_build_sha256=provenance['source_build_sha256'])
        digest(data['geometry_sha256'],'geometry digest')
        if spec.inspector is not None:
            try: measured = spec.inspector(primary.path,primary.schema)
            except Exception as e: raise StoreValidationError(f'shipped primary inspector rejected payload: {e}') from e
        elif primary.schema == 'anatomy-npz-v4':
            measured = inspect_npz(primary.path,native_v4=True)
        elif primary.schema == 'anatomy-npz-f32-delta-v1':
            measured = inspect_float32(primary.path)
        elif primary.schema == 'gltf2-glb':
            measured = inspect_glb(primary.path)
        else:
            raise StoreValidationError('primary schema requires shipped structural inspector')
        require(measured == data['geometry_sha256'],'geometry digest disagrees with inspected payload')
        result = VerifiedVariant(model_id,variant,spec.adapter_id,generation_id,path,sha,primary,tuple(checked),measured,MappingProxyType(dict(provenance)),validation_scope=validation['scope'],baseline_defects=baseline)
        if spec.validator is not None:
            try: spec.validator(result)
            except Exception as e: raise StoreValidationError(f'shipped companion validator rejected payload: {e}') from e
        if variant=='pre' and mode_parent:
            require({'canonical_payload','canonical_correspondence','pre_baseline_report'}<=set(result.assets),'full source-mode correspondence/baseline evidence missing')
            children=liver_modes.pre_modes(self,root,result,spec,budget)
            result=replace(result,verified_modes=MappingProxyType(children))
        if variant=='pre' and spec.components:
            children=validate_pre_components(self,root,result,spec,budget)
            result=replace(result,verified_components=MappingProxyType(children))
        return result

    def _pair(self,pre,post,*,root=None):
        p = post.provenance
        require(pre.adapter_id==post.adapter_id,'variant adapter mismatch')
        require(p['pre_descriptor_sha256']==pre.descriptor_sha256 and p['source_pre_sha256']==pre.primary.sha256 and p['parent_pre_receipt_sha256']==pre.assets['validation'].sha256,'Post does not bind exact independent Pre descriptor/receipt')
        require(p['source_build_sha256']==pre.provenance['source_build_sha256'] and p['source_receipt_sha256']==pre.provenance['source_receipt_sha256'],'Post source lineage mismatch')
        spec = self.adapters.get(pre.adapter_id) or self._component_adapters.get(pre.adapter_id)
        mode_leaf=pre.model_id=='liver_lobule' and pre.adapter_id in {m['adapter_id'] for m in liver_modes.MODES}
        if spec is None and mode_leaf:
            m=next(m for m in liver_modes.MODES if m['adapter_id']==pre.adapter_id)
            spec=liver_modes.leaf_spec(self,self.adapters[liver_modes.PARENT],m)
        require(spec is not None,'unknown trusted pair adapter')
        if liver_modes.is_parent(pre.model_id,pre.adapter_id):
            require(root is not None,'fixed liver mode proof requires exact generation root')
            try: children,outcomes=liver_modes.validate_post(self,root,pre,post,spec)
            except StoreValidationError: raise
            except Exception as e: raise StoreValidationError(f'fixed liver mode proof rejected: {e}') from e
            return replace(post,verified_modes=MappingProxyType(children),mode_outcomes=MappingProxyType(outcomes))
        try: validate_execution(pre,post)
        except StoreValidationError: raise
        except Exception as e: raise StoreValidationError(f'original-engine execution proof rejected: {e}') from e
        profile=read_json(post.assets['microrefine_profile'].path)
        names=set(profile['expected_parts'])
        if profile['final_microrefine'].get('material_grouping'):
            names.update(read_json(post.assets['grouped_material'].path)['original_selector_order'])
        for finding in pre.baseline_defects['findings']:
            require(set(finding['selectors'])<=names,'Pre baseline report references unknown model selectors')
        if p['geometry_outcome']=='changed':
            require(post.primary.sha256 != pre.primary.sha256 and post.geometry_sha256 != pre.geometry_sha256,'changed outcome contradicts unchanged payload/geometry')
        # The authenticated original-engine envelope includes canonical saved-surface
        # measurements and allows honest cross-encoding/no-change outcomes.
        # Model-specific pair validators can impose additional restrictions.
        if spec.pair_validator is not None:
            try: transformed=spec.pair_validator(pre,post)
            except Exception as e: raise StoreValidationError(f'shipped pair validator rejected payload: {e}') from e
            require(transformed is True,'shipped pair validator did not prove required transformation')
        if spec.components:
            require(root is not None,'component proof requires exact containing generation root')
            children,outcomes=validate_post_components(self,root,pre,post,spec)
            post=replace(post,verified_components=MappingProxyType(children),component_outcomes=MappingProxyType(outcomes))
        return post

    def _catalog_at(self,root,expected_ref=None):
        root = no_symlinks(root)
        path = safe_path(root,'catalog.json')
        sha,size = file_hash(path,maximum=MAX_JSON)
        if expected_ref is not None: require(sha==expected_ref['catalog_sha256'],'active catalog hash mismatch')
        data = _schema(read_json(path),'anatomy-variant-catalog',{'generation_id','created_utc','required_models','models'})
        gen = data['generation_id']
        require(isinstance(gen,str) and TOKEN.fullmatch(gen) and gen not in {'.','..'},'invalid generation identity')
        relative_path(gen)
        if expected_ref is not None: require(gen==expected_ref['generation_id'],'active generation identity mismatch')
        try: created = datetime.fromisoformat(data['created_utc'])
        except (ValueError,TypeError) as e: raise StoreValidationError('catalog timestamp invalid') from e
        require(created.tzinfo is not None and created.utcoffset().total_seconds()==0,'catalog timestamp must be UTC')
        ids = data['required_models']
        require(isinstance(ids,list) and len(ids)<=128 and all(isinstance(i,str) for i in ids) and len(ids)==len(set(ids)) and set(ids)==self.expected_model_ids,'catalog required model set differs from shipped all-model contract')
        models = data['models']
        require(isinstance(models,list) and len(models)==len(self.expected_model_ids),'catalog incomplete model count')
        entries = []; seen = set(); files = {'catalog.json': (sha,size)}
        budget={'seen':set(),'compressed':size,'expanded':size}
        for m in models:
            exact(m,{'model_id','metadata','variants'},'catalog model')
            model_id=ident(m['model_id']); require(model_id in self.expected_model_ids and model_id not in seen,'duplicate/unexpected catalog model'); seen.add(model_id)
            metadata=_metadata(m['metadata']); refs=exact(m['variants'],{'pre','post'},'variant refs')
            variants={v:self._descriptor(root,refs[v],model_id,v,gen,budget) for v in ('pre','post')}
            variants['post']=self._pair(variants['pre'],variants['post'],root=root)
            entries.append(CatalogEntry(model_id,**metadata,variants=MappingProxyType(variants)))
            for v in variants.values():
                drel=v.descriptor_path.relative_to(root).as_posix()
                for rel,identity in [(drel,(v.descriptor_sha256,refs[v.variant]['size'])),*((a.relative_path,(a.sha256,a.size)) for a in (v.primary,*v.companions))]:
                    require(rel not in files or files[rel]==identity,'same path has conflicting declarations')
                    files[rel]=identity
        require(len(files)<=MAX_FILES and sum(v[1] for v in files.values())<=MAX_TOTAL,'generation file/size limits exceeded')
        expanded=sum(expanded_npz_size(safe_path(root,rel)) if rel.lower().endswith('.npz') else size for rel,(_,size) in files.items())
        require(expanded<=64*1024*1024*1024,'generation decompressed size limit exceeded')
        # An immutable generation is data-only and exactly manifest-declared. No stray Python/plugins.
        actual = set()
        for base,dirs,names in os.walk(root,followlinks=False):
            for name in dirs: no_symlinks(Path(base)/name)
            for name in names:
                p=no_symlinks(Path(base)/name)
                require(p.is_file(),'nonregular generation file')
                actual.add(p.relative_to(root).as_posix())
                require(len(actual)<=MAX_FILES,'generation has excessive files')
        require(actual==set(files),'generation contains undeclared/missing files')
        return {'generation_id':gen,'catalog_sha256':sha},tuple(entries),files

    def _ref(self,value):
        if value is None: return None
        exact(value,{'generation_id','catalog_sha256'},'catalog pointer')
        require(isinstance(value['generation_id'],str) and TOKEN.fullmatch(value['generation_id']),'invalid pointer generation')
        relative_path(value['generation_id'])
        digest(value['catalog_sha256']); return value

    def _state(self,path=None):
        data=_schema(read_json(path or self.root/'state.json'),'anatomy-variant-state',{'sequence','active','previous'})
        integer(data['sequence'],1,2**53-1,'state sequence')
        require(self._ref(data['active']) is not None,'active pointer missing'); self._ref(data['previous'])
        return data

    def _load_ref(self,ref):
        return self._catalog_at(safe_path(self.root,'generations/'+ref['generation_id']),ref)

    def _active(self):
        if not self.root.exists() or not (self.root/'state.json').exists(): return None,()
        state=self._state()
        cache_key=canonical_json(state)
        if self._cache is not None and self._cache[0]==cache_key: return state,self._cache[1]
        _,entries,_=self._load_ref(state['active'])
        self._cache=(cache_key,entries)
        return state,entries

    def catalog(self):
        """Validated new catalog only. Empty uninitialized store never exposes legacy models."""
        try:
            _,entries=self._active(); self.last_error=None; return entries
        except (OSError,StoreValidationError) as e:
            self.last_error=str(e)
            raise StoreValidationError(f'active new-model catalog unavailable: {e}') from e

    def _catalog_index_at(self,root,ref):
        """Hash only bounded catalog/descriptor JSON, never payload/report arrays."""
        root=no_symlinks(root);path=safe_path(root,'catalog.json')
        sha,size=file_hash(path,maximum=MAX_JSON)
        require(sha==ref['catalog_sha256'],'active catalog index hash mismatch')
        data=_schema(read_json(path),'anatomy-variant-catalog',{'generation_id','created_utc','required_models','models'})
        require(data['generation_id']==ref['generation_id'],'catalog index generation mismatch')
        ids=data['required_models']
        require(isinstance(ids,list) and all(isinstance(i,str) for i in ids) and len(ids)==len(set(ids)) and set(ids)==self.expected_model_ids,'catalog index model contract mismatch')
        require(isinstance(data['models'],list) and len(data['models'])==len(ids),'catalog index incomplete')
        try: created=datetime.fromisoformat(data['created_utc'])
        except (ValueError,TypeError) as e: raise StoreValidationError('catalog index timestamp invalid') from e
        require(created.tzinfo is not None and created.utcoffset().total_seconds()==0,'catalog index timestamp must be UTC')
        entries=[];seen=set();total=size
        for m in data['models']:
            exact(m,{'model_id','metadata','variants'},'index model')
            mid=ident(m['model_id']);require(mid in self.expected_model_ids and mid not in seen,'index model duplicate/unexpected');seen.add(mid)
            fields=_metadata(m['metadata']);refs=exact(m['variants'],{'pre','post'},'index variants');variants={}
            for v in ('pre','post'):
                dr=exact(refs[v],{'path','sha256','size'},'index descriptor reference');digest(dr['sha256']);integer(dr['size'],1,MAX_JSON,'index descriptor size')
                dp=safe_path(root,dr['path']);actual,n=file_hash(dp,maximum=MAX_JSON);total+=n
                require(total<=16*1024*1024,'catalog/descriptor startup index exceeds16MiB budget')
                require((actual,n)==(dr['sha256'],dr['size']),'index descriptor hash/size mismatch')
                d=_schema(read_json(dp),'anatomy-variant',{'model_id','variant','adapter_id','primary','companions','geometry_sha256','provenance','validation'})
                require(d['model_id']==mid and d['variant']==v and isinstance(d['adapter_id'],str),'index descriptor identity mismatch')
                spec=self.adapters.get(d['adapter_id']);require(spec is not None and mid in spec.model_ids,'index adapter not allowlisted')
                allowed=dict(MANDATORY_ROLES);allowed.update(CANONICAL_ROLES);allowed.update(BASELINE_ROLES)
                if mid=='muscular_artery' and spec.adapter_id=='ae.muscular_artery.runtime.v1':
                    allowed.update(GROUP_ROLES if v=='post' else {'grouped_material':GROUP_ROLES['grouped_material']})
                if v=='post' and authored_lane.is_supported(mid,spec.adapter_id):allowed.update(authored_lane.AUTHORED_ROLES)
                mode_parent=liver_modes.is_parent(mid,spec.adapter_id)
                if mode_parent:allowed.update(liver_modes.roles(v))
                if v=='post' and not mode_parent:allowed.update(POST_ROLES)
                component_required,component_optional=component_roles(spec.components,v)
                allowed.update(component_required);allowed.update(component_optional)
                allowed.update(spec.required_roles);allowed.update(spec.optional_roles)
                companions=d['companions'];require(isinstance(companions,list) and len(companions)<=128,'index companion count invalid')
                roles=set()
                for a in [d['primary'],*companions]:
                    exact(a,{'role','path','format','schema','sha256','size'},'index asset declaration');role=ident(a['role'],'index role')
                    require(role not in roles,'index duplicate asset role');roles.add(role)
                    types=spec.primary_types if role=='primary' else allowed.get(role)
                    require(types is not None and isinstance(a['format'],str) and isinstance(a['schema'],str) and (a['format'],a['schema']) in types,'index asset type not allowlisted')
                    digest(a['sha256']);integer(a['size'],1,MAX_FILE,'index declared asset size')
                    # Do not touch any payload path at startup. Lexical containment only;
                    # symlink/existence/hash/schema checks happen in selected resolve().
                    rel=relative_path(a['path']);require(rel.suffix.lower()=='.'+a['format'],'index asset extension mismatch')
                mandatory=set(MANDATORY_ROLES)|set(spec.required_roles)|set(component_required)|(set(liver_modes.roles(v))|({'canonical_payload','canonical_correspondence','pre_baseline_report'} if v=='pre' else set()) if mode_parent else (set(POST_ROLES) if v=='post' else {'pre_baseline_report'}))
                if roles&set(authored_lane.AUTHORED_ROLES):mandatory.update(set(authored_lane.AUTHORED_ROLES)|{'canonical_payload'})
                require(mandatory<=roles and d['primary']['role']=='primary','index required data roles missing')
                digest(d['geometry_sha256'],'index declared geometry digest')
                provenance=exact(d['provenance'],{'source_build_sha256','source_receipt_sha256','source_pre_sha256','pre_descriptor_sha256','parent_pre_receipt_sha256','profile_sha256','algorithm_sha256','final_geometry_step','transformation_required','geometry_outcome','execution_receipt_sha256'},'index provenance')
                for k in ('source_build_sha256','source_receipt_sha256','source_pre_sha256'):digest(provenance[k],k)
                require(provenance['transformation_required'] is True,'index required engine execution missing')
                if v=='pre':
                    require(provenance['final_geometry_step']=='source_improvement' and provenance['source_pre_sha256']==d['primary']['sha256'],'index Pre origin invalid')
                    require(all(provenance[k] is None for k in ('pre_descriptor_sha256','parent_pre_receipt_sha256','profile_sha256','algorithm_sha256','geometry_outcome','execution_receipt_sha256')),'index Pre depends on Post')
                else:
                    require(provenance['final_geometry_step']=='microrefine' and isinstance(provenance['geometry_outcome'],str) and provenance['geometry_outcome'] in {'changed','no_change'},'index Post declaration invalid')
                    for k in ('pre_descriptor_sha256','parent_pre_receipt_sha256','profile_sha256','algorithm_sha256','execution_receipt_sha256'):digest(provenance[k],k)
                require(d['validation']=={'status':'passed','receipt_role':'validation'},'index incomplete validation declaration')
                variants[v]=PendingVariantIndex(mid,v,spec.adapter_id,ref['generation_id'],dp,actual)
            entries.append(CatalogIndexEntry(mid,**fields,variants=MappingProxyType(variants)))
        return tuple(entries)

    def _active_index(self):
        if not self.root.exists() or not (self.root/'state.json').exists():return None,()
        state=self._state();key=canonical_json(state)
        if self._index_cache is not None and self._index_cache[0]==key:return state,self._index_cache[1]
        root=safe_path(self.root,'generations/'+state['active']['generation_id'])
        entries=self._catalog_index_at(root,state['active'])
        require(self._state()==state,'active state changed while reading startup index; retry')
        self._index_cache=(key,entries)
        return state,entries

    def catalog_index(self):
        """Bounded startup listing with explicit pending verification, no payload I/O."""
        try:
            _,entries=self._active_index();self.last_error=None;return entries
        except (OSError,StoreValidationError) as e:
            self.last_error=str(e)
            raise StoreValidationError(f'new-model index unavailable: {e}') from e

    def preferred(self,model_id):
        """Read choices without touching payloads or persisting the initial Pre default."""
        require(isinstance(model_id,str) and model_id in self.expected_model_ids,'model not in shipped new catalog')
        return self._preferences()['choices'].get(model_id,'pre')

    def active_identity(self):
        """Fresh full-catalog verification for deployment's dataset-ready receipt."""
        state=self._state()
        ref,entries,_=self._load_ref(state['active'])
        self._preferences()
        require(self._state()==state,'active state changed during dataset verification; retry')
        return MappingProxyType(dict(ref,schema_version=1,model_count=len(entries),sequence=state['sequence']))

    def resolve(self,model_id,variant):
        require(isinstance(variant,str) and variant in LABELS,'variant must be pre or post')
        state,entries=self._active_index()
        require(state is not None,'new-model catalog has not been promoted')
        entry=next((e for e in entries if e.id==model_id),None)
        require(entry is not None,'model not in active new catalog')
        root=safe_path(self.root,'generations/'+state['active']['generation_id'])
        # Rehash independent Pre only for Pre display; Post additionally requires
        # its exact parent and complete execution lineage. Never scan other models.
        catalog=read_json(root/'catalog.json')
        require(file_hash(root/'catalog.json',maximum=MAX_JSON)[0]==state['active']['catalog_sha256'],'active catalog changed')
        refs=next(m['variants'] for m in catalog['models'] if m['model_id']==model_id)
        pre=self._descriptor(root,refs['pre'],model_id,'pre',state['active']['generation_id'])
        if variant=='post':
            post=self._descriptor(root,refs['post'],model_id,'post',state['active']['generation_id'])
            post=self._pair(pre,post,root=root)
            chosen=post
        else: chosen=pre
        require(self._state()==state,'active state changed while resolving selected pair; retry')
        return chosen

    def revalidate(self,variant):
        require(isinstance(variant,VerifiedVariant),'runtime requires a verified store descriptor')
        current=self.resolve(variant.model_id,variant.variant)
        require(current.token==variant.token,'stale descriptor: active generation changed')
        return current

    def _preferences(self):
        path=self.root/'preferences.json'
        if not path.exists(): return {'schema':'anatomy-variant-preferences','schema_version':1,'choices':{}}
        data=_schema(read_json(path),'anatomy-variant-preferences',{'choices'})
        choices=data['choices']; require(isinstance(choices,dict) and set(choices)<=self.expected_model_ids,'preference model invalid')
        require(all(isinstance(v,str) and v in LABELS for v in choices.values()),'preference variant invalid')
        return data

    def selected(self,model_id):
        return self.resolve(model_id,self.preferred(model_id))

    def select(self,model_id,variant,*,expected_token=None,before_persist=None):
        """Call after detached runtime load succeeds; optional token guards concurrent promotion."""
        self._init()
        with _lock(self.root):
            chosen=self.resolve(model_id,variant)
            if expected_token is not None: require(chosen.token==tuple(expected_token),'catalog changed while loading; selection not persisted')
            old=self._preferences(); new=dict(old); new['choices']=dict(old['choices']); new['choices'][model_id]=variant
            if before_persist is not None: require(callable(before_persist),'selection cancellation checkpoint must be trusted callable')
            if (self.root/'preferences.json').exists(): atomic_json(self.root/'preferences.lastgood.json',old)
            if before_persist is not None: require(before_persist() is not False,'selection was cancelled before persistence')
            atomic_json(self.root/'preferences.json',new)
            return chosen

    def promote(self,staged_generation):
        """Copy all validated data, then publish one atomic pointer. Never remove a generation."""
        self._init()
        source=no_symlinks(Path(staged_generation))
        require(not source.is_relative_to(self.root) and not self.root.is_relative_to(source),'stage/store roots must be separate')
        with _lock(self.root):
            ref,_,files=self._catalog_at(source)
            dest=self.root/'generations'/ref['generation_id']
            no_symlinks(dest,must_exist=False)
            if dest.exists():
                existing,_,_=self._catalog_at(dest,ref)
                require(existing==ref,'generation id collision')
            else:
                incoming=self.root/'generations'/('.incoming-'+uuid.uuid4().hex)
                incoming.mkdir()
                # Interrupted incoming directories are retained for diagnosis, never activated.
                for rel,(sha,size) in sorted(files.items()):
                    src=safe_path(source,rel); out=incoming.joinpath(*relative_path(rel).parts)
                    out.parent.mkdir(parents=True,exist_ok=True)
                    h=hashlib.sha256(); n=0
                    with safe_open(src) as fi,open(out,'xb') as fo:
                        while chunk:=fi.read(1024*1024):
                            n+=len(chunk); require(n<=size,'stage changed while copying'); h.update(chunk); fo.write(chunk)
                        fo.flush(); os.fsync(fo.fileno())
                    require((h.hexdigest(),n)==(sha,size),'stage changed during copy')
                self._catalog_at(incoming,ref)
                for base,_,_ in os.walk(incoming,topdown=False): fsync_directory(base)
                os.rename(incoming,dest); fsync_directory(dest.parent)
            old=self._state() if (self.root/'state.json').exists() else None
            if old is not None:
                self._load_ref(old['active']) # Do not overwrite recovery anchor with corrupt state.
                if old['active']==ref: return ref
                atomic_json(self.root/'state.lastgood.json',old)
            new={'schema':'anatomy-variant-state','schema_version':1,'sequence':1 if old is None else old['sequence']+1,'active':ref,'previous':None if old is None else old['active']}
            if old is None: atomic_json(self.root/'state.lastgood.json',new)
            atomic_json(self.root/'state.json',new)
            self._cache=None; self._index_cache=None
            self._active()
            return MappingProxyType(ref)

    def rollback(self):
        self._init()
        with _lock(self.root):
            old=self._state(); ref=old['previous']; require(ref is not None,'no previous verified catalog available')
            self._load_ref(ref)
            new=dict(old,sequence=old['sequence']+1,active=ref,previous=old['active'])
            atomic_json(self.root/'state.lastgood.json',old); atomic_json(self.root/'state.json',new)
            self._cache=None; self._index_cache=None
            return MappingProxyType(ref)

    def recover(self):
        """Explicit recovery; try current, previous, then lastgood. Preserve all files/settings."""
        self._init()
        with _lock(self.root):
            state=None; candidates=[]
            for path in (self.root/'state.json',self.root/'state.lastgood.json'):
                try:
                    s=self._state(path)
                    if state is None: state=s
                    candidates.extend([s['active'],s['previous']])
                except (OSError,StoreValidationError): pass
            seen=set()
            for ref in candidates:
                if ref is None or ref['generation_id'] in seen: continue
                seen.add(ref['generation_id'])
                try: self._load_ref(ref)
                except (OSError,StoreValidationError): continue
                recovered={'schema':'anatomy-variant-state','schema_version':1,'sequence':1 if state is None else state['sequence']+1,'active':ref,'previous':None}
                atomic_json(self.root/'state.json',recovered); self._cache=None; self._index_cache=None
                return MappingProxyType(ref)
            raise StoreValidationError('no intact compatible new-model catalog; recompute or restore data explicitly')

    def recover_preferences(self):
        """Fail closed on corrupt choices until this explicit lastgood restore is requested."""
        self._init()
        with _lock(self.root):
            backup=self.root/'preferences.lastgood.json'
            data=_schema(read_json(backup),'anatomy-variant-preferences',{'choices'})
            require(isinstance(data['choices'],dict) and set(data['choices'])<=self.expected_model_ids and all(isinstance(v,str) and v in LABELS for v in data['choices'].values()),'invalid lastgood preference choices')
            atomic_json(self.root/'preferences.json',data)
            return MappingProxyType(dict(data['choices']))
