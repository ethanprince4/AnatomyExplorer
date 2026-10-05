"""Copy selected refiner results into the app's independent, reversible library."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import uuid
import re


def read(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending=path.with_suffix('.pending.json')
    pending.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
    pending.replace(path)


def copy_saved(source, destination):
    before=source.stat()
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,destination)
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError(f'{source.name} changed while copying. Retry after saving finishes.')


def copy_optional(value, origin, folder, library, role):
    """Copy an optional file record; inline controls remain inline."""
    if isinstance(value,dict) and 'path' not in value:return dict(value)
    raw=value.get('path') if isinstance(value,dict) else value
    path=Path(raw);path=path if path.is_absolute() else origin/path
    if not path.is_file():return None
    safe=re.sub(r'[^A-Za-z0-9_.-]+','-',role)
    target=folder/safe/path.name;copy_saved(path,target)
    relative=target.relative_to(library).as_posix()
    return {**value,'path':relative} if isinstance(value,dict) else relative


def copy_components(records, origin, folder, library):
    result={}
    for name,value in (records or {}).items():
        value=dict(value) if isinstance(value,dict) else {'path':value}
        primary=value.get('primary',value)
        if not isinstance(primary,(str,Path)) and 'path' not in primary:continue
        copied=copy_optional(primary,origin,folder,library,name)
        if copied is None:continue
        child={**value,'path':copied['path'] if isinstance(copied,dict) else copied}
        child.pop('primary',None)
        child['companions']={}
        for role,asset in value.get('companions',{}).items():
            item=copy_optional(asset,origin,folder,library,name+'-'+role)
            if item is not None:child['companions'][role]=item
        if 'runtime_controls' in value:
            controls=copy_optional(value['runtime_controls'],origin,folder,library,name+'-controls')
            if controls is None:child.pop('runtime_controls',None)
            else:child['runtime_controls']=controls
        result[name]=child
    return result


def components_for(records,variant):
    records=records or {}
    return records.get(variant,{}) if any(key in records for key in ('pre','post')) else records


def install(refiner, library, model_ids=None, companions=None, post_only=False):
    refiner=Path(refiner);library=Path(library)
    rows=read(refiner/'library/models.json',[])
    manifest_path=library/'library.json'
    manifest=read(manifest_path,{'schema':'ae.local-library.v1','models':{}})
    selected=set(model_ids) if model_ids else None
    imported=[]
    for row in rows:
        mid=row['id']
        if row.get('reference') or row.get('status')=='unavailable':continue
        if selected is not None and mid not in selected:continue
        source=refiner/'library'/mid
        if post_only:
            result=source/'refined.npz'
            if not result.is_file():raise ValueError(mid+': no saved refinement is available.')
            previous=manifest['models'].get(mid)
            if not previous:raise ValueError(mid+': model is not in the destination library.')
            entry=dict(previous)
            revision=uuid.uuid4().hex[:12]
            folder=library/'models'/mid/revision
            target=folder/'refined.npz'
            copy_saved(result,target)
            prior=dict(entry.get('variants',{}).get('post',{}))
            prior.update(path=target.relative_to(library).as_posix(),format='npz',status='review_candidate')
            prior.pop('report',None)
            report=source/'report.json'
            if report.is_file():
                copy_saved(report,folder/'report.json')
                prior['report']=(folder/'report.json').relative_to(library).as_posix()
            entry['variants']={'post':prior}
            history=read(library/'history.json',{})
            history.setdefault(mid,[]).append(previous)
            write(library/'history.json',history)
            manifest['models'][mid]=entry
            write(manifest_path,manifest)
            imported.append(mid)
            continue
        original=source/row['input']
        if not original.is_file():continue
        previous=manifest['models'].get(mid)
        entry=dict(previous or {})
        entry.update(name=row['name'],source_label=row.get('source_label','Saved refiner input'))
        variants=dict(entry.get('variants',{}))
        revision=uuid.uuid4().hex[:12]
        folder=library/'models'/mid/revision
        shared={}
        supplied=(companions or {}).get(mid,{})
        supplied_companions=supplied.get('companions',{}) if 'companions' in supplied or 'components' in supplied else supplied
        for origin,records in ((source,row.get('companions',{})),(Path.cwd(),supplied_companions)):
            for role,value in records.items():
                copied=copy_optional(value,origin,folder/'companions',library,role)
                if copied is not None:shared[role]=copied
        component_versions={}
        for variant in ('pre','post'):
            collected={}
            for origin,records in ((source,row.get('components',{})),(Path.cwd(),supplied.get('components',{}))):
                collected.update(copy_components(components_for(records,variant),origin,folder/'components'/variant,library))
            component_versions[variant]=collected
        if 'pre' not in variants:
            target=folder/('original'+original.suffix)
            copy_saved(original,target)
            variants['pre']={'path':target.relative_to(library).as_posix(),'format':original.suffix[1:],'companions':dict(shared)}
        elif shared:
            variants['pre']={**variants['pre'],'companions':{**variants['pre'].get('companions',{}),**shared}}
        if component_versions['pre']:
            variants['pre']={**variants['pre'],'components':{**variants['pre'].get('components',{}),**component_versions['pre']}}
        result=source/('refined-view.glb' if original.suffix.lower()=='.glb' else 'refined.npz')
        if result.is_file():
            retained_components=variants.get('post',{}).get('components',{})
            target=folder/('refined'+result.suffix);copy_saved(result,target)
            variants['post']={'path':target.relative_to(library).as_posix(),'format':result.suffix[1:],
                              'companions':dict(shared or variants['pre'].get('companions',{})),
                              'status':'review_candidate'}
            if component_versions['post'] or retained_components:
                variants['post']['components']={**retained_components,**component_versions['post']}
            report=source/'report.json'
            if report.is_file():
                copy_saved(report,folder/'report.json')
                variants['post']['report']=(folder/'report.json').relative_to(library).as_posix()
        entry['variants']=variants
        if previous:
            history=read(library/'history.json',{})
            history.setdefault(mid,[]).append(previous)
            write(library/'history.json',history)
        manifest['models'][mid]=entry
        # Publish a complete model at a time. Readers never see a partial file.
        write(manifest_path,manifest)
        imported.append(mid)
    if selected and selected-set(imported):
        raise ValueError('No usable input for: '+', '.join(sorted(selected-set(imported))))
    return imported


def rollback(library,mid):
    library=Path(library);history=read(library/'history.json',{})
    if not history.get(mid):raise ValueError('No previous imported result for '+mid)
    manifest=read(library/'library.json',{})
    manifest['models'][mid]=history[mid].pop()
    write(library/'library.json',manifest);write(library/'history.json',history)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--refiner',type=Path)
    p.add_argument('--library',type=Path,required=True)
    p.add_argument('--model',action='append')
    p.add_argument('--companions',type=Path)
    p.add_argument('--rollback')
    p.add_argument('--post-only',action='store_true',help='Import only the saved result, retaining destination teaching metadata.')
    a=p.parse_args()
    if a.rollback:rollback(a.library,a.rollback);print('Previous imported result restored.');return
    if not a.refiner:p.error('--refiner is required for import')
    names=install(a.refiner,a.library,a.model,read(a.companions,{}) if a.companions else None,post_only=a.post_only)
    print(f'Copied {len(names)} models. Reopen the model library to use them.')


if __name__=='__main__':main()
