"""Small local model library: independent files, no build or generation gates."""
import json
from pathlib import Path
from types import SimpleNamespace
from threading import RLock

class LocalLibrary:
    is_local = True
    def __init__(self, root, preferences_path=None):
        value=Path(root).expanduser().resolve()
        self.manifest=value if value.suffix.lower()=='.json' else value/'library.json'
        self.root=self.manifest.parent
        self.preferences_path=Path(preferences_path) if preferences_path else self.root/'preferences.json'
        self._lock=RLock()
        self.warnings=[]
        self.expected_model_ids=()
        self._metadata=None
        self._manifest_signature=None

    def _path(self,value):
        p=Path(value)
        return p.resolve() if p.is_absolute() else (self.root/p).resolve()

    def _descriptor(self,mid,variant,value):
        value={'path':value} if isinstance(value,str) else dict(value)
        path=self._path(value['path'])
        if path.suffix.lower() not in ('.npz','.glb') or not path.is_file():
            raise ValueError(f'{mid}: {variant} file is missing or is not NPZ/GLB: {path}')
        primary=SimpleNamespace(path=path,format=path.suffix.lower()[1:])
        # Tokens identify selections only; they are not hashes or certification.
        return SimpleNamespace(model_id=mid,variant=variant,label={'pre':'Before','post':'After'}[variant],
            path=path,primary=primary,primary_format=primary.format,root=self.root,
            token=(mid,variant,str(path)),generation_id='local',
            companions=value.get('companions',{}),runtime_controls=value.get('runtime_controls'),
            components=value.get('components',{}),outcome=value.get('outcome'),record=value,
            validation_scope=None,baseline_defects=None,component_baseline_defects=None)

    def catalog_index(self):
        data=json.loads(self.manifest.read_text(encoding='utf-8-sig'))
        rows=data.get('models',[])
        if isinstance(rows,dict):rows=[dict(value,id=key) for key,value in rows.items()]
        result=[];seen=set();self.warnings=[]
        for row in rows:
            mid=row.get('id') or row.get('model_id')
            if not mid or mid in seen:
                self.warnings.append('Skipped model without a unique identifier.');continue
            variants={}
            for variant,value in row.get('variants',{}).items():
                if variant not in ('pre','post'):continue
                try:variants[variant]=self._descriptor(mid,variant,value)
                except (OSError,ValueError,KeyError,TypeError) as exc:self.warnings.append(str(exc))
            if not variants:continue
            seen.add(mid)
            fields=dict(name=row.get('name',mid.replace('_',' ').title()),summary='',targets={},histology=[],
                        related=[],clinical=[],scale_note='',aliases={},credit_html='',order=100)
            fields.update({key:row[key] for key in fields if key in row})
            result.append(SimpleNamespace(id=mid,variants=variants,**fields))
        self.expected_model_ids=tuple(meta.id for meta in result)
        self._metadata={meta.id:meta for meta in result}
        self._manifest_signature=self._signature()
        return result

    def resolve(self,mid,variant):
        for meta in self.catalog_index():
            if meta.id==mid and variant in meta.variants:return meta.variants[variant]
        raise ValueError(f'{mid}: the selected version is no longer available.')

    def _signature(self):
        try:
            stat=self.manifest.stat();return (stat.st_mtime_ns,stat.st_size)
        except OSError:return None

    def metadata(self,mid):
        if self._metadata is None or self._manifest_signature!=self._signature():self.catalog_index()
        meta=self._metadata.get(mid)
        if meta is None:raise ValueError(f"Model is not available: {mid}")
        return meta

    def preferred(self,mid):
        try:preferences=json.loads(self.preferences_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):preferences={}
        meta=self.metadata(mid)
        choice=preferences.get(mid) if isinstance(preferences,dict) else None
        return choice if choice in meta.variants else ('post' if 'post' in meta.variants else 'pre')

    def select(self,mid,variant,expected_token=None,before_persist=None):
        descriptor=self.resolve(mid,variant)
        if before_persist:before_persist()
        with self._lock:
            try:preferences=json.loads(self.preferences_path.read_text(encoding='utf-8'))
            except (OSError,ValueError):preferences={}
            if not isinstance(preferences,dict):preferences={}
            preferences[mid]=variant
            self.preferences_path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.preferences_path.with_suffix('.pending.json')
            temporary.write_text(json.dumps(preferences,indent=2),encoding='utf-8')
            temporary.replace(self.preferences_path)
        return descriptor

    def selected(self,mid):return self.resolve(mid,self.preferred(mid))
    def revalidate(self,descriptor):return descriptor.path.is_file()
    def active_identity(self):
        return {'generation_id':'local','model_count':len(self.catalog_index()),'library':str(self.root)}


class MergedLocalLibrary(LocalLibrary):
    """Read-only bundled defaults with independent per-model user replacements."""
    def __init__(self, seed, overrides, preferences_path=None):
        super().__init__(overrides,preferences_path=preferences_path)
        self.seed=LocalLibrary(seed)
        self.overrides=LocalLibrary(overrides,preferences_path=self.preferences_path)

    def _signature(self):
        return (self.seed._signature(),self.overrides._signature())

    def catalog_index(self):
        combined={};warnings=[]
        for library in (self.seed,self.overrides):
            if not library.manifest.exists():continue
            try:
                for meta in library.catalog_index():combined[meta.id]=meta
                warnings.extend(library.warnings)
            except (OSError,ValueError,TypeError) as exc:
                warnings.append(f'{library.manifest}: {exc}')
        self.warnings=warnings
        self._metadata=combined
        self.expected_model_ids=tuple(combined)
        self._manifest_signature=self._signature()
        return list(combined.values())
