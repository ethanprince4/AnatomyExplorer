"""Explicit native duodenum loader and actionable teaching-state adapter.

Load into the existing app runtime only on the separate machine. This module
does not import the app, NumPy or geometry dependencies until load_native().
No cache writes, registry edits, rendering or application launch occur here.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

def load_native(artifact_dir, baseline):
    import sys
    import numpy as np
    artifact_dir, baseline = Path(artifact_dir), Path(baseline).resolve()
    lesson = json.loads((artifact_dir / 'duodenum_teaching.json').read_text(encoding='utf-8'))
    source = artifact_dir / 'duodenum_refined.npz'
    h = hashlib.sha256()
    with source.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    if h.hexdigest() != lesson['archive_sha256']:
        raise ValueError('Artifact hash mismatch')
    for req in lesson['native_source_requirements']:
        source_hash = hashlib.sha256()
        with (baseline / req['path']).open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                source_hash.update(chunk)
        if source_hash.hexdigest() != req['sha256']:
            raise ValueError('Native source hash mismatch: ' + req['path'])
    sys.path.insert(0, str(baseline))
    from app.micro.base import MicroModel, Part
    from app.micro.geometry import Mesh
    from app.micro.duodenum_refinement import vertex_color_recipe
    import app.micro.base as native_base
    import app.micro.geometry as native_geometry
    import app.micro.duodenum_refinement as native_refinement
    for module in (native_base, native_geometry, native_refinement):
        if not Path(module.__file__).resolve().is_relative_to(baseline):
            raise ValueError('Wrong app runtime already imported')
    parts = []
    with np.load(source, allow_pickle=False) as archive:
        meta = json.loads(bytes(archive['meta']).decode('utf-8'))
        if [p['name'] for p in meta['parts']] != lesson['part_names']:
            raise ValueError('Selector identity changed')
        for i, m in enumerate(meta['parts']):
            mesh = Mesh().add(archive[f'p{i}'], np.cumsum(archive[f'i{i}'].astype(np.int64)).reshape(-1, 3), archive[f'n{i}'])
            parts.append(Part(m['name'], m['group'], m['color'], mesh, m['description'],
                **{key: m[key] for key in ('alpha', 'category', 'label', 'rank', 'clip', 'bulk', 'detail')}))
    model = MicroModel('duodenum_design_review', 'Duodenum wall — source refinement', lesson['summary'], lambda: parts,
                       scale_note=lesson['scale_note'], cutaway=((1., 0., 0.), (0., 0., 1.)), cut_at=(0., 0.))
    model._parts = parts  # bypass automatic cache/generation and preserve originals
    model.viewer_vertex_colors = vertex_color_recipe
    model.cut_on = True
    model.labels_on_open = True
    model.viewer_cameras = {v['id']: dict(v['camera'], hidden=v['hidden_parts'], note=v['purpose']) for v in lesson['views']}
    model.start_view = lesson['opening_view']
    model.duodenum_teaching = lesson
    return model

def apply_state(viewer, state):
    """Set live Part.visible and Item.label using exact native item keys."""
    by_name = {item.key: item for item in viewer.items}
    visible = set(state['visible_parts'])
    labels = set(state.get('label_parts', []))
    if not visible.issubset(by_name) or not labels.issubset(by_name):
        raise ValueError('Teaching state has unresolved selectors')
    for name, item in by_name.items():
        item.label = name in labels
        for part in item.parts:
            part.visible = name in visible
    viewer.cutaway['on'] = bool(state.get('cut_on', True))
    viewer.duodenum_caption = state.get('caption', state.get('purpose', ''))
    viewer.duodenum_highlight = list(state.get('highlight_parts', []))
    return {'caption': viewer.duodenum_caption, 'highlight_parts': viewer.duodenum_highlight,
            'scale_note': getattr(viewer.source, 'scale_note', '')}

def apply_view(viewer, view_id):
    lesson = viewer.source.duodenum_teaching
    state = next(v for v in lesson['views'] if v['id'] == view_id)
    return apply_state(viewer, state)

def apply_sequence(viewer, sequence_id, step):
    lesson = viewer.source.duodenum_teaching
    sequence = next(s for s in lesson['sequences'] if s['id'] == sequence_id)
    state = sequence['steps'][step]
    result = apply_state(viewer, state)
    result['limitations'] = sequence['schematic_limitations']
    return result

def apply_to_viewport(viewport, view_id=None, sequence_id=None, step=0):
    """Apply states to the existing viewport's actual native visibility state.

    Caller displays the returned caption/route in its teaching panel. Native
    selection highlights identify structures without changing their materials.
    """
    viewer = viewport.model
    lesson = viewer.source.duodenum_teaching
    if view_id is not None:
        state = next(v for v in lesson['views'] if v['id'] == view_id)
        viewport.set_named_view(view_id, animate=False, visibility=True)
        result = apply_view(viewer, view_id)
    else:
        sequence = next(s for s in lesson['sequences'] if s['id'] == sequence_id)
        state = sequence['steps'][step]
        result = apply_sequence(viewer, sequence_id, step)
    by_name = {item.key: item.index for item in viewer.items}
    st = viewport.state
    st.push_undo()
    st.hidden[:] = False
    st.forced[:] = False
    st.isolated = None
    st.ghost_focus = None
    visible_indices = [index for name, index in by_name.items() if name in state['visible_parts']]
    st.forced[visible_indices] = True
    hidden = [index for name, index in by_name.items() if name not in state['visible_parts']]
    if hidden:
        st.hidden[hidden] = True
    st._vis_dirty()
    st.select([by_name[name] for name in state.get('highlight_parts', [])])
    viewport.cut_on = bool(state.get('cut_on', True))
    viewport.sections = [None, None, None]
    viewport.labels_on = True
    viewport.invalidate_labels()
    viewport.update()
    result['route_annotation'] = state.get('route_annotation', '')
    result['label_overrides'] = dict(state.get('label_overrides', {}))
    return result

def register_review(register, artifact_dir, baseline):
    """Add the review model through the native registry's register(model) API.

    Later integration calls this with its own register callable. This function
    never edits registry files, replaces original duodenum or launches the app.
    """
    model = load_native(artifact_dir, baseline)
    register(model)
    return model
