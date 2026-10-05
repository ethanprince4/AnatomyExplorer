"""Stage only explicitly referenced post-refine assets for a release seed.

The editable library is read-only input. No builders, hashes, active-run imports,
pre-refine variants, history folders or review reports enter the release seed.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import sys

# Support direct invocation from outside the application directory.
_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))
from app.variants.display_names import display_name

# Keep temporary directories alive until PyInstaller has consumed its file list.
_STAGES = []
_REVIEW_KEYS = {'report', 'reports', 'history', 'pre', 'previous', 'original',
                'source_label', 'refinement_report', 'validation_report', 'witnesses'}

def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _REVIEW_KEYS}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def stage_post_library(directory, staging_parent=None):
    """Return a new isolated folder containing a complete post-only library.

    All selected manifest rows must have a post variant. Callers wanting a subset
    must explicitly prepare a subset manifest; absence never silently drops rows.
    Only primary paths and declared supporting assets are copied. Companion JSON
    contents are not treated as instructions to recursively collect other files.
    """
    root = Path(directory).resolve()
    data = json.loads((root / 'library.json').read_text(encoding='utf-8-sig'))
    raw = data.get('models', [])
    keyed = isinstance(raw, dict)
    rows = [(key, value) for key, value in raw.items()] if keyed else [(r.get('id') or r.get('model_id'), r) for r in raw]
    missing = [str(mid or '<unnamed model>') for mid, row in rows if not row.get('variants', {}).get('post')]
    if missing:
        raise ValueError('Release requires a post-refine variant for every selected model. Missing post: '
                         + ', '.join(sorted(missing)) + '. Finish these models, or explicitly select a smaller release library; pre-refine files will not be substituted.')
    if not rows:
        raise ValueError('Release library has no models. Select a completed post-refine library.')
    assets = {}
    def file_ref(value, context):
        path = Path(value)
        if path.is_absolute() or not (root / path).resolve().is_relative_to(root):
            raise ValueError(f'{context}: release paths must stay relative to the library: {value}')
        source = (root / path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f'{context}: declared release asset is missing: {value}')
        # Keep teaching sidecars, without obsolete pre-refinement filenames.
        public = path.with_name(path.name.replace('_pre_refine', '').replace('-pre-refine', ''))
        assets[public.as_posix()] = source
        return public.as_posix()
    def asset(value, context):
        if isinstance(value, str):
            return file_ref(value, context)
        if not isinstance(value, dict):
            raise ValueError(f'{context}: expected an asset path or descriptor')
        result = _clean(value)
        for key in ('path', 'runtime_controls'):
            if isinstance(result.get(key), str):
                result[key] = file_ref(result[key], context + '.' + key)
        for key in ('primary',):
            if key in result:
                result[key] = asset(result[key], context + '.' + key)
        for key in ('companions', 'components'):
            entries = result.get(key)
            if isinstance(entries, dict):
                result[key] = {role: asset(v, context + '.' + role) for role, v in entries.items()}
            elif isinstance(entries, list):
                result[key] = [asset(v, context + '.' + key) for v in entries
                               if not isinstance(v, dict) or v.get('role') not in _REVIEW_KEYS]
        return result
    selected=[]
    for mid,row in rows:
        post = asset(row['variants']['post'], str(mid))
        if isinstance(post, dict) and not post.get('path'):
            raise ValueError(f'{mid}: post variant needs its primary path')
        new_row = _clean({k:v for k,v in row.items() if k != 'variants'})
        new_row['name'] = display_name(mid, new_row.get('name', str(mid)))
        new_row['variants'] = {'post': post}
        selected.append((mid,new_row))
    release = _clean({k:v for k,v in data.items() if k != 'models'})
    release['models'] = dict(selected) if keyed else [r for _,r in selected]
    if staging_parent is not None:
        parent = Path(staging_parent).resolve()
        # Reject inside-source output even if it would be ignored by collection.
        if parent.is_relative_to(root):
            raise ValueError('Release staging must be outside the editable source library')
        parent.mkdir(parents=True, exist_ok=True)
    else:
        parent = None
    temporary = tempfile.TemporaryDirectory(prefix='ae-post-release-', dir=parent)
    _STAGES.append(temporary)
    stage = Path(temporary.name)
    for relative,source in sorted(assets.items()):
        destination=stage / relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,destination)
    (stage / 'library.json').write_text(json.dumps(release,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return stage


def seed_files(directory, staging_parent=None):
    stage = stage_post_library(directory, staging_parent)
    return [(str(source), str(Path('data/local_model_library') / source.relative_to(stage).parent))
            for source in sorted(stage.rglob('*')) if source.is_file()]


def export_post_library(directory, output):
    """Export a portable release library to an explicitly chosen empty folder."""
    source = Path(directory).resolve()
    target = Path(output).resolve()
    if target.is_relative_to(source):
        raise ValueError('Release output must be outside the editable source library')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f'Release output must be an empty directory: {target}')
    stage = stage_post_library(source)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(stage, target, dirs_exist_ok=True)
    return target


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Export only completed post-refine model variants; leave source untouched.')
    parser.add_argument('library', help='Editable library folder containing library.json')
    parser.add_argument('--output', required=True, help='New or empty portable release folder')
    args = parser.parse_args(argv)
    try:
        target = export_post_library(args.library, args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(f'Post-refine release library exported to {target}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
