"""Static scalp stages for an already-loaded native ModelView, import-safe.

No native, Qt, NumPy, cache or builder imports. ModelViewport keeps authored
common-settle coordinates; the atlas clip_* API is not this model-view route.
"""
from copy import deepcopy
import json
import math
import operator
from pathlib import Path

AXES = {'sagittal': 0, 'coronal': 1, 'transverse': 2}
COORDINATE_AXIS = (0, 2, 1)


def load_sequences(path=None):
    path = Path(path) if path else Path(__file__).with_name('sequences.json')
    return json.loads(path.read_text(encoding='utf-8'))


def resolve_stage(data, sequence_id, stage_id):
    sequence = next((s for s in data['functional_sequences'] if s['id'] == sequence_id), None)
    if sequence is None:
        raise ValueError(f'Unknown scalp sequence: {sequence_id}')
    stage = next((s for s in sequence['steps'] if s['id'] == stage_id), None)
    if stage is None:
        raise ValueError(f'Unknown scalp stage: {sequence_id}/{stage_id}')
    return sequence, stage


def exact_name_map(dataset):
    """Actual ModelDataset item indices, without aliases/fuzzy matches."""
    result = {}
    for sid, item in enumerate(dataset.structures):
        name = item['name']
        if name in result:
            raise ValueError(f'Duplicate exact loaded name: {name}')
        result[name] = sid
    if len(result) != dataset.n:
        raise ValueError('Loaded native item metadata/count mismatch')
    return result


def _checked_stage(state, viewport, data, sequence_id, stage_id, name_to_sid,
                   anchors, available_geometry, require_verified_geometry):
    sequence, stage = resolve_stage(data, sequence_id, stage_id)
    catalog = data['catalog']
    names = {p['id']: p['name'] for p in catalog}
    if len(names) != len(catalog) or len(set(names.values())) != len(names):
        raise ValueError('Duplicate scalp catalog selector or exact name')
    for key in ('visible_parts', 'hidden_parts', 'solid_parts', 'ghost_parts', 'selected_parts'):
        if len(stage[key]) != len(set(stage[key])) or set(stage[key]) - names.keys():
            raise ValueError(f'Invalid/duplicate scalp selector in {key}')
    vis, hidden = set(stage['visible_parts']), set(stage['hidden_parts'])
    solid, ghost = set(stage['solid_parts']), set(stage['ghost_parts'])
    if vis & hidden or vis | hidden != set(names):
        raise ValueError('Visibility must partition every known selector')
    if solid & ghost or solid | ghost != vis:
        raise ValueError('Solid and ghost must partition the visible stage')
    if set(stage['selected_parts']) - solid:
        raise ValueError('Selected ghost targets would become solid in native rendering')
    actual = exact_name_map(state.ds)
    resolved = {}
    for pid in vis:
        name = names[pid]
        if name not in name_to_sid or name not in actual:
            raise ValueError(f'Missing exact loaded scalp name: {name}')
        value = name_to_sid[name]
        if isinstance(value, bool):
            raise ValueError('Boolean is not a native item index')
        try:
            sid = operator.index(value)
        except TypeError as exc:
            raise ValueError(f'Noninteger native item index for {name}') from exc
        if sid != actual[name]:
            raise ValueError(f'Exact selector map differs from loaded dataset: {name}')
        resolved[pid] = sid
    if len(set(resolved.values())) != len(resolved):
        raise ValueError('Duplicate native item indices')
    if getattr(state.ds, 'model', None) is not getattr(viewport, 'model', None):
        raise ValueError('Viewport and ModelDataset do not share the loaded model')
    if getattr(viewport.model, 'kind', None) != 'procedural':
        raise ValueError('Scalp requires the native ProceduralModel route')
    for obj, methods in ((state, ('_snapshot', 'restore', 'set_depth', 'isolate', 'clear_forced',
                                  'set_ghost_focus', 'clear_ghost', 'select', 'set_hovered')),
                         (viewport, ('set_explode', 'set_playing', 'invalidate_labels', 'update'))):
        if any(not callable(getattr(obj, method, None)) for method in methods):
            raise ValueError('Loaded native stage API is incomplete')
    if len(viewport.sections) != 3:
        raise ValueError('ModelViewport.sections must have three axes')
    controls = stage['native_controls']
    if (controls['depth_cut'] != 0 or controls['depth_band'] != 0
            or controls['layer_separation'] != 0 or not controls['isolate']):
        raise ValueError('Mechanism stages require assembled static geometry')
    missing = sorted(set(stage['geometry_requirements']) - set(available_geometry))
    if missing and require_verified_geometry:
        raise ValueError(f'Stage anatomical detail not verified: {missing}')
    section = controls['section']
    axis = position = None
    if section['mode'] != 'none':
        if section['mode'] != 'section' or section['axis'] not in AXES:
            raise ValueError('Unsupported section mode/axis')
        key = section['position_anchor']
        if key not in anchors:
            raise ValueError(f'Missing authored-coordinate section anchor: {key}')
        position = float(anchors[key])
        if not math.isfinite(position):
            raise ValueError(f'Nonfinite section anchor: {key}')
        axis = AXES[section['axis']]
        coordinate = COORDINATE_AXIS[axis]
        lo = float(viewport.model.bounds_min[coordinate])
        hi = float(viewport.model.bounds_max[coordinate])
        if not math.isfinite(lo + hi) or hi <= lo or not lo <= position <= hi:
            raise ValueError(f'Section anchor outside authored model bounds: {key}')
    return sequence, stage, resolved, missing, axis, position


def capture_stage_session(state, viewport):
    """Capture controller-mutated state, including undo. Camera is untouched."""
    keys = ('sections', 'cut_on', 'explode', 'playing', 'anim_t',
            'reveal_state', 'reveal_amount', 'reveal_target')
    return dict(scene=deepcopy(state._snapshot()), selected=list(state.selected),
                hovered=state.hovered, custom_colors=deepcopy(state.custom_colors),
                part_alpha_present=hasattr(state, 'part_alpha'),
                part_alpha=deepcopy(getattr(state, 'part_alpha', None)),
                undo=list(state._undo),
                viewport={key: deepcopy(getattr(viewport, key)) for key in keys})


def restore_stage_session(state, viewport, snapshot):
    """Restore runtime state; no model construction or anatomy acceptance."""
    state.restore(deepcopy(snapshot['scene']))
    state.custom_colors = deepcopy(snapshot['custom_colors'])
    if snapshot['part_alpha_present']:
        state.part_alpha = deepcopy(snapshot['part_alpha'])
    elif hasattr(state, 'part_alpha'):
        delattr(state, 'part_alpha')
    state.select(snapshot['selected'])
    state.set_hovered(snapshot['hovered'])
    state._undo[:] = snapshot['undo']
    fields = snapshot['viewport']
    viewport.set_explode(fields['explode'])
    for key, value in fields.items():
        setattr(viewport, key, deepcopy(value))
    viewport.invalidate_labels()
    viewport.update()


def apply_stage(state, viewport, sequence_id, stage_id, name_to_sid, anchors,
                available_geometry=(), data=None, require_verified_geometry=True):
    """Apply a static stage to ModelView.state/ModelView.gl_widget.

    Item IDs are ModelDataset indices, never cache pN or renderer part IDs.
    Explicit inspection always returns anatomy_verified=False. Overlays stay off.
    """
    data = load_sequences() if data is None else data
    sequence, stage, resolved, missing, axis, position = _checked_stage(
        state, viewport, data, sequence_id, stage_id, name_to_sid, anchors,
        available_geometry, require_verified_geometry)
    before = capture_stage_session(state, viewport)
    try:
        state.set_depth(0.0, 0.0)
        state.clear_forced()
        state.isolate([resolved[p] for p in stage['visible_parts']])
        if stage['ghost_parts']:
            state.set_ghost_focus([resolved[p] for p in stage['solid_parts']])
        else:
            state.clear_ghost()
        state.part_alpha = None
        state.system_alpha[:] = 1.0
        state.custom_colors = {}
        state.select([resolved[p] for p in stage['selected_parts']])
        state.set_hovered(-1)
        viewport.set_explode(0.0)
        viewport.set_playing(False)
        viewport.anim_t = 0.0
        viewport.reveal_state = None
        viewport.reveal_amount = viewport.reveal_target = 0.0
        viewport.cut_on = False
        viewport.sections[:] = [None, None, None]
        if axis is not None:
            viewport.sections[axis] = [position, bool(stage['native_controls']['section'].get('flip', False))]
        viewport.invalidate_labels()
        viewport.update()
    except Exception:
        restore_stage_session(state, viewport, before)
        raise
    overlay = stage['mechanism_overlay']
    need = overlay.get('required_geometry')
    return dict(sequence_id=sequence_id, stage_id=stage_id, caption=stage['caption'],
                missing_geometry=missing, anatomy_verified=False,
                geometry_requirements_satisfied=not missing,
                inspection_only=not require_verified_geometry,
                overlay_enabled=False, overlay_design=deepcopy(overlay),
                missing_overlay_geometry=[need] if need and need not in available_geometry else [],
                visible_native_items=[resolved[p] for p in stage['visible_parts']],
                limitations=sequence['schematic_limitations'])


def _widget_value(widget, setter, value):
    blocked = widget.blockSignals(True)
    try:
        getattr(widget, setter)(value)
    finally:
        widget.blockSignals(blocked)


def sync_view_controls(view):
    """Synchronize ModelView controls without snapping exact section anchors.

    The slider stores 1001 positions; viewport keeps the exact scalar until the
    user intentionally moves it. Camera is untouched.
    """
    viewport = view.gl_widget
    for axis, section in enumerate(viewport.sections):
        box, slider, flip = view.section_rows[axis]
        on = section is not None
        _widget_value(view.section_actions[axis], 'setChecked', on)
        box.setVisible(on)
        if on:
            lo, hi = view._axis_range(axis)
            value = round(1000 * (section[0] - lo) / (hi - lo))
            _widget_value(slider, 'setValue', max(0, min(1000, value)))
            _widget_value(flip, 'setChecked', section[1])
    view.section_bar.setVisible(any(section is not None for section in viewport.sections))
    view._mark_section()
    if hasattr(view, 'explode'):
        _widget_value(view.explode, 'setValue', round(viewport.explode * 100))
    if hasattr(view, 'cut'):
        _widget_value(view.cut, 'setChecked', viewport.cut_on)


def apply_stage_to_view(view, sequence_id, stage_id, anchors, available_geometry=(),
                        data=None, require_verified_geometry=True):
    """Concrete entry point for a lead-supplied cache-backed review loader/menu."""
    result = apply_stage(view.state, view.gl_widget, sequence_id, stage_id,
                         exact_name_map(view.state.ds), anchors, available_geometry,
                         data, require_verified_geometry)
    sync_view_controls(view)
    return result


def restore_stage_session_to_view(view, snapshot):
    restore_stage_session(view.state, view.gl_widget, snapshot)
    sync_view_controls(view)
