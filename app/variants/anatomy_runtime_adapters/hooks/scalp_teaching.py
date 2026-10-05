"""Scalp teaching controls for an already loaded native ModelView.

Only standard-library imports; no application, numerical, mesh or builder import.
Use after the first-frame home reset. Geometry, colors and physical scale are
never edited. Recipes are teaching state, not anatomical certification.
"""
from __future__ import annotations

import json
import math
from pathlib import Path


AXES = {0: 'X', 1: 'Z', 2: 'Y'}


def load_views(path=None):
    source = Path(path) if path else Path(__file__).with_name('views.json')
    document = json.loads(source.read_text(encoding='utf-8'))
    validate_document(document)
    return document


def _finite(value, context):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Nonfinite scalp ' + context)
    return value


def validate_document(document):
    """Reject malformed exact selector partitions before native state changes."""
    if document.get('schema_version') != 1 or document.get('model_id') != 'scalp':
        raise ValueError('Unsupported scalp recipe document')
    baseline = document['baseline_selectors']
    base = set(baseline)
    if not baseline or len(base) != len(baseline):
        raise ValueError('Duplicate/empty baseline selector catalog')
    companions = document.get('companion_selectors', {})
    if set(companions) & base:
        raise ValueError('Added companion duplicates a baseline selector')
    for name, hosts in companions.items():
        if not hosts or len(set(hosts)) != len(hosts) or not set(hosts) <= base:
            raise ValueError('Invalid exact companion hosts: ' + name)
    seen = set()
    for recipe in document['views']:
        if recipe['id'] in seen:
            raise ValueError('Duplicate scalp view id')
        seen.add(recipe['id'])
        visible, hidden = recipe['visible_parts'], recipe['hidden_parts']
        if (len(set(visible)) != len(visible) or len(set(hidden)) != len(hidden)
                or set(visible) & set(hidden) or set(visible + hidden) != base):
            raise ValueError('Invalid scalp baseline partition: ' + recipe['id'])
        focus = recipe['focus_parts']
        if len(set(focus)) != len(focus) or not set(focus) <= set(visible):
            raise ValueError('Hidden or duplicate scalp focus selector')
        for key in ('tissue_opacity_percent', 'layer_separation_percent'):
            value = _finite(recipe[key], key)
            if value != int(value) or not 0 <= value <= 100:
                raise ValueError('Invalid scalp percentage: ' + key)
        camera = recipe['camera']
        _finite(camera['yaw_radians'], 'camera yaw')
        pitch = _finite(camera['pitch_radians'], 'camera pitch')
        if abs(pitch) > math.radians(89.5):
            raise ValueError('Scalp pitch outside native camera limit')
        if 'target' in camera:
            if len(camera['target']) != 3:
                raise ValueError('Scalp target needs three authored coordinates')
            for value in camera['target']:
                _finite(value, 'camera target')
            if _finite(camera['radius_units'], 'camera radius') <= 0:
                raise ValueError('Scalp camera radius must be positive')
        section = recipe.get('section')
        if section:
            axis = section['ui_axis_index']
            if axis not in AXES or section['world_axis'] != AXES[axis]:
                raise ValueError('Scalp section axis disagrees with native X/Z/Y mapping')
            _finite(section['authored_position'], 'section seed')
            if recipe['layer_separation_percent']:
                raise ValueError('Authored-coordinate sections require zero separation')
    if document['default_view'] not in seen:
        raise ValueError('Unknown scalp opening recipe')
    return document


def resolve_view(items, document, recipe):
    """Exact names only; additive unknowns stay visible with explicit diagnostics.

    New component markers follow their exact baseline host. Shared connective
    unit support follows any named retained unit/target host. Split sheath and
    eccrine nuclei must never use combined predecessor selectors.
    """
    validate_document(document)
    if recipe not in document['views']:
        raise ValueError('Recipe does not belong to this scalp document')
    items = list(items)
    by_key = {item.key: item.index for item in items}
    if len(by_key) != len(items):
        raise ValueError('Duplicate selectable scalp keys')
    if len(set(by_key.values())) != len(items):
        raise ValueError('Duplicate native scalp item indices')
    if any(not isinstance(index, int) or isinstance(index, bool) or index < 0
           for index in by_key.values()):
        raise ValueError('Invalid native scalp item index')
    missing = set(document['baseline_selectors']) - by_key.keys()
    if missing:
        raise ValueError('Scalp baseline selectors missing: ' + ', '.join(sorted(missing)))
    base = set(document['baseline_selectors'])
    visible = set(recipe['visible_parts'])
    companions = document.get('companion_selectors', {})
    unmapped = []
    # Anchor membership is evaluated against baseline state, never against
    # previously resolved extras; iteration order cannot change the result.
    for key in sorted(by_key.keys() - base):
        anchors = companions.get(key)
        if anchors is None:
            visible.add(key)
            unmapped.append(key)
        elif set(anchors) & set(recipe['visible_parts']):
            visible.add(key)
    selected = [by_key[key] for key in recipe['focus_parts']]
    return sorted(by_key[key] for key in visible), selected, unmapped


def _native_plan(model_view, document, recipe, anchors, require_refined_additions):
    """Bounded preflight of item metadata and section limits; no geometry reads."""
    source = getattr(model_view.vmodel, 'source', None)
    if getattr(source, 'id', None) != 'scalp':
        raise ValueError('Recipe applies only to the scalp model')
    visible, selected, unmapped = resolve_view(model_view.vmodel.items, document, recipe)
    keys = {item.key for item in model_view.vmodel.items}
    absent = sorted(set(document['companion_selectors']) - keys)
    if absent and require_refined_additions:
        raise ValueError('Scalp refined teaching additions missing: ' + ', '.join(absent))
    anchors = {} if anchors is None else anchors
    warnings = []
    camera = recipe['camera']
    target = camera.get('target')
    anchor = camera.get('target_anchor')
    if anchor and anchor in anchors:
        target = anchors[anchor]
    elif anchor:
        warnings.append('Camera anchor ' + anchor + ' unavailable; unverified source seed used')
    if target is not None:
        if len(target) != 3:
            raise ValueError('Scalp native camera anchor needs three coordinates')
        target = [_finite(value, 'native camera anchor') for value in target]
    section_plan = None
    section = recipe.get('section')
    if section:
        axis = section['ui_axis_index']
        lo, hi = model_view._axis_range(axis)
        lo, hi = _finite(lo, 'lower section bound'), _finite(hi, 'upper section bound')
        if hi <= lo:
            raise ValueError('Degenerate native section extent')
        anchor = section.get('position_anchor')
        if anchor and anchor in anchors:
            position = _finite(anchors[anchor], 'native section anchor')
        else:
            position = _finite(section['authored_position'], 'native section seed')
            if anchor:
                warnings.append('Section anchor ' + anchor + ' unavailable; unverified source seed used')
        if not lo <= position <= hi:
            raise ValueError('Scalp section target lies outside loaded bounds')
        slider_value = round(1000 * (position - lo) / (hi - lo))
        actual = lo + (hi - lo) * slider_value / 1000
        section_plan = dict(axis=axis, requested_position=position,
                            native_position=actual, quantization_error=actual-position,
                            slider_value=slider_value, flip=bool(section['flip']))
    return visible, selected, unmapped, absent, target, section_plan, warnings


def apply_view(model_view, view_id, path=None, *, anchors=None,
               require_refined_additions=True):
    """Apply via actual native controls; validate all recipe data before mutation.

    ``anchors`` is the saved construction-manifest anchors mapping, already in
    common-settle-warped authored coordinates. No normalization is applied.
    Baseline-only state inspection may explicitly set require_refined_additions
    False; returned missing additions do not count as anatomy implementation.
    Selection/section/hover names may remain even when Labels is off. A caller
    running recognition assessment must enter native Practice first, then apply
    the recipe; names_hidden is owned by Practice and is never overridden here.
    """
    document = load_views(path)
    recipes = {recipe['id']: recipe for recipe in document['views']}
    if view_id not in recipes:
        raise ValueError('Unknown scalp view: ' + view_id)
    recipe = recipes[view_id]
    visible, selected, unmapped, absent, target, section, warnings = _native_plan(
        model_view, document, recipe, anchors, require_refined_additions)
    g = model_view.gl_widget
    # Exact native method path, including repeat applications whose Qt signal
    # does not fire because the widget already has the requested value.
    model_view.clear_sections()
    if model_view.cut is not None:
        model_view.cut.setChecked(False)
    g.cut_on = False
    play = getattr(model_view, 'play', None)
    if play is not None:
        play.setChecked(False)
    g.set_playing(False)
    g.auto_rotate = False
    teased = getattr(model_view, 'teased', None)
    if teased is not None:
        teased.setChecked(False)
    g.reveal_state = None
    g.reveal_amount = g.reveal_target = 0.0
    model_view.vmodel.node_offsets = {}
    model_view.explode.setValue(int(recipe['layer_separation_percent']))
    g.set_explode(recipe['layer_separation_percent'] / 100.0)
    if model_view.opacity is not None:
        model_view.opacity.setValue(int(recipe['tissue_opacity_percent']))
        model_view._opacity(int(recipe['tissue_opacity_percent']))
    model_view.state.set_depth(0.0, 0.0)
    model_view.state.isolate(visible)
    model_view.state.select(selected)
    model_view.labels.setChecked(bool(recipe['labels']))
    g.labels_on = bool(recipe['labels'])
    camera = recipe['camera']
    g.camera._anim = None
    g.camera.yaw = float(camera['yaw_radians'])
    g.camera.pitch = float(camera['pitch_radians'])
    g.camera.ortho = False
    if target is not None:
        g.frame_point(target, camera['radius_units'])
        g.camera.snap()
    else:
        g.frame_structures(selected if selected else visible, duration=0.0)
    if section:
        axis = section['axis']
        _, slider, flip = model_view.section_rows[axis]
        slider.setValue(section['slider_value'])
        model_view.set_section(axis, True)
        flip.setChecked(section['flip'])
        model_view._section_moved(axis)
    g.invalidate_labels()
    g.update()
    return {
        'view_id': view_id,
        'teaching_note': recipe['teaching_note'],
        'missing_context': recipe['missing_context'],
        'scale_note': document['scale_note'],
        'unmapped_extra_selectors': unmapped,
        'missing_expected_extra_selectors': absent,
        'coordinate_warnings': warnings,
        'section': section,
        'label_policy': document['label_policy'],
        'acceptance': 'native_interaction_and_anatomical_visual_acceptance_deferred',
    }
