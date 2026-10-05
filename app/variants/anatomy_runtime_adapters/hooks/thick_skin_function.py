"""Geometry-immutable thick-skin function views for an already running viewer.

Install ``configure`` on each micro-model source before ProceduralModel wraps it.
Bind the independently loaded variant by its exact label and native cache SHA-256.
Use ``FunctionSession.apply`` for steps and ``restore`` before leaving/switching.
Only camera, visibility, selection and render-only state change. No native/app,
array, geometry or physiology imports occur here; mesh buffers are never accessed.
"""
from copy import deepcopy
import json
from math import isfinite
from pathlib import Path
import re

VARIANTS = ('pre_refine', 'post_refine')
VARIANT_LABELS = {'pre_refine': 'Pre refine', 'post_refine': 'Post refine'}
STATE_FIELDS = ('hidden', 'forced', 'isolated', 'system_on', 'subsystem_on',
                'region_on', 'ghost_focus', 'depth_cut', 'depth_band',
                'system_alpha', 'selected', 'hovered', '_undo')
VIEW_FIELDS = ('sections', 'cut_on', 'cut_planes', 'explode', 'labels_on',
               'reveal_state', 'reveal_amount', 'reveal_target', 'playing',
               'anim_t', 'auto_rotate', '_last_frame_time')
CAMERA_FIELDS = ('target', 'distance', 'yaw', 'pitch', 'fov', 'ortho',
                 'ortho_width', '_anim')


def load_design(path=None):
    source = Path(path) if path else Path(__file__).with_name('function_sequences.json')
    return json.loads(source.read_text(encoding='utf-8'))


def _binding(variant_id, content_identity):
    if variant_id not in VARIANTS:
        raise ValueError('Pass machine variant_id pre_refine or post_refine explicitly')
    if not isinstance(content_identity, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', content_identity):
        raise ValueError('Variant native-cache SHA-256 is required')
    return {'model_id': 'thick_skin', 'variant_id': variant_id,
            'content_identity': content_identity.lower(),
            'display_label': VARIANT_LABELS[variant_id]}


def _names(values, field):
    if not isinstance(values, (list, tuple)) or any(not isinstance(x, str) or not x for x in values):
        raise ValueError(field + ' must contain exact nonempty string selectors')
    if len(values) != len(set(values)):
        raise ValueError(field + ' contains duplicate selectors')
    return list(values)


def resolve_design(document, part_names, aliases=None, extra_visible=None, *, legacy_mode=False):
    """Resolve exact required hosts, optional authored detail and all step focus.

    Optional detail is explicitly listed, never guessed by substring. Missing
    required hosts or explicit aliases fail before any model assignment. The
    resolved document records unavailable optional detail rather than pretending
    that its existence was verified. Aliases affect focus as well as visibility.
    """
    doc = deepcopy(document)
    if doc.get('schema_version') != 1 or doc.get('model_id') != 'thick_skin':
        raise ValueError('Expected thick_skin function schema 1')
    names = _names(list(part_names), 'part_names')
    available, aliases, extras = set(names), aliases or {}, extra_visible or {}
    if set(extras) - {v['id'] for v in doc['views']}:
        raise ValueError('Extra visibility names an unknown view')

    def resolve(identity):
        replacement = aliases.get(identity, [identity])
        if isinstance(replacement, str):
            replacement = [replacement]
        replacement = _names(replacement, 'alias ' + identity)
        if not replacement or set(replacement) - available:
            raise ValueError('Unresolved required identity: ' + identity)
        return replacement

    if type(legacy_mode) is not bool:
        raise ValueError('legacy_mode must be explicit boolean')
    contract = _names(doc.get('required_selector_contract', []), 'required_selector_contract')
    if not contract:
        raise ValueError('Delivered selector contract is required')
    if not legacy_mode:
        for identity in contract:
            resolve(identity)
    doc['compatibility_mode'] = 'legacy_metadata_only' if legacy_mode else 'delivered_refined_model'
    doc['delivery_ready'] = not legacy_mode
    by_view = {}
    for view in doc['views']:
        if view['id'] in by_view:
            raise ValueError('Duplicate function view id')
        keep = {name for identity in _names(view['visible_parts'], view['id']) for name in resolve(identity)}
        optional = _names(view.get('optional_visible_parts', []), 'optional visibility')
        keep.update(set(optional) & available)
        more = _names(extras.get(view['id'], []), 'extra visibility')
        if set(more) - available:
            raise ValueError('Unresolved explicit extra: ' + view['id'])
        keep.update(more)
        view['visible_parts'] = sorted(keep)
        view['missing_optional_parts'] = sorted(set(optional) - available)
        camera = view['camera']
        for field in ('position', 'target'):
            vector = camera[field]
            if len(vector) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x) for x in vector):
                raise ValueError('Camera needs finite xyz: ' + view['id'])
        if camera['position'] == camera['target'] or camera.get('type') != 'ORTHO':
            raise ValueError('Function camera must be a nonzero orthographic pose')
        width = camera['ortho_width']
        if isinstance(width, bool) or not isinstance(width, (int, float)) or not isfinite(width) or width <= 0:
            raise ValueError('Invalid orthographic width')
        if type(view['cut_on']) is not bool:
            raise ValueError('cut_on must be boolean')
        by_view[view['id']] = view
    sequence_ids = set()
    for sequence in doc['functional_sequences']:
        if sequence['id'] in sequence_ids or not sequence['steps']:
            raise ValueError('Duplicate or empty function sequence')
        sequence_ids.add(sequence['id'])
        for step in sequence['steps']:
            if step['view'] not in by_view:
                raise ValueError('Unresolved step view')
            focus = {name for identity in _names(step.get('focus_parts', []), 'step focus') for name in resolve(identity)}
            optional = _names(step.get('optional_focus_parts', []), 'optional focus')
            focus.update(set(optional) & available)
            if not focus <= set(by_view[step['view']]['visible_parts']):
                raise ValueError('Step focus is hidden by its view')
            step['focus_parts'] = sorted(focus)
            step['missing_optional_parts'] = sorted(set(optional) - available)
            if not isinstance(step['caption'], str) or not step['caption'].strip():
                raise ValueError('Every step needs a teaching caption')
    doc['part_names'] = names
    return doc


def configure(model, part_names, aliases=None, extra_visible=None, path=None,
              *, variant_id, content_identity, legacy_mode=False):
    """Append cameras on one verified variant source; no opening-view override.

    ``part_names`` is metadata supplied by the caller; never force model.parts().
    The caller verifies the cache hash. Reconfigure separately for every variant.
    """
    binding = _binding(variant_id, content_identity)
    if getattr(model, 'id', 'thick_skin') != 'thick_skin':
        raise ValueError('Function controls are model-specific')
    doc = resolve_design(load_design(path), part_names, aliases, extra_visible, legacy_mode=legacy_mode)
    doc['variant_binding'] = binding
    cameras = deepcopy(getattr(model, 'viewer_cameras', {}))
    available = set(doc['part_names'])
    for view in doc['views']:
        record = deepcopy(view['camera'])
        record.update(hidden=sorted(available - set(view['visible_parts'])),
                      cut_on=view['cut_on'], state='assembled',
                      note=view['purpose'] + ' ' + doc['scale_note'])
        cameras[view['id']] = record
    # All resolution/validation finishes before publishing the controls.
    model.viewer_cameras = cameras
    model.viewer_function_design = deepcopy(doc)
    model.viewer_function_binding = deepcopy(binding)
    return doc


def _snapshot(viewport):
    state, model = viewport.state, viewport.model
    return {
        'state': {name: deepcopy(getattr(state, name)) for name in STATE_FIELDS},
        'view': {name: deepcopy(getattr(viewport, name)) for name in VIEW_FIELDS},
        'camera': {name: deepcopy(getattr(viewport.camera, name)) for name in CAMERA_FIELDS},
        'had_part_alpha': hasattr(state, 'part_alpha'),
        'part_alpha': deepcopy(getattr(state, 'part_alpha', None)),
        # Offsets are tiny per-host render translations, never vertices/normals.
        'item_offsets': deepcopy(model.item_offsets),
    }


def _restore(viewport, snapshot):
    for name, value in snapshot['state'].items():
        setattr(viewport.state, name, deepcopy(value))
    if snapshot['had_part_alpha']:
        viewport.state.part_alpha = deepcopy(snapshot['part_alpha'])
    elif hasattr(viewport.state, 'part_alpha'):
        del viewport.state.part_alpha
    for name, value in snapshot['view'].items():
        setattr(viewport, name, deepcopy(value))
    for name, value in snapshot['camera'].items():
        setattr(viewport.camera, name, deepcopy(value))
    viewport.model.item_offsets = deepcopy(snapshot['item_offsets'])
    viewport.state._vis_dirty()
    viewport.state.select(snapshot['state']['selected'])
    viewport.invalidate_labels()
    viewport.update()


class FunctionSession:
    """A reversible teaching session belonging to exactly one live variant.

    No physiological motion, flow arrows, concentration field or spike train is
    implemented. Applying a step is a view/visibility/selection/caption change.
    Restore before replacing viewport.model. A stale session never writes into
    a newly loaded model, even when its part keys happen to be identical.
    """
    def __init__(self, viewport, document=None):
        self.viewport, self.model, self.state = viewport, viewport.model, viewport.state
        self.source = getattr(self.model, 'source', None)
        self.camera = viewport.camera
        binding = getattr(self.source, 'viewer_function_binding', None)
        document = document if document is not None else getattr(self.source, 'viewer_function_design', None)
        if not binding or not document or document.get('variant_binding') != binding:
            raise ValueError('Configure the verified selected variant before starting function controls')
        self.binding = _binding(binding['variant_id'], binding['content_identity'])
        self.document = deepcopy(document)
        self.keys = tuple(it.key for it in self.model.items)
        if len(set(self.keys)) != len(self.keys) or sorted(it.index for it in self.model.items) != list(range(len(self.keys))):
            raise ValueError('Expected exact unique Item keys and contiguous indices')
        if set(self.keys) != set(document['part_names']):
            raise ValueError('Configured metadata differs from the loaded variant inventory')
        if any(v['id'] not in self.model.cameras for v in document['views']):
            raise ValueError('Configured cameras are absent from the loaded variant')
        self._check_live()
        self._entry = _snapshot(viewport)
        self.closed = False

    def _check_live(self):
        vp = self.viewport
        if vp.model is not self.model or vp.state is not self.state or vp.camera is not self.camera:
            raise ValueError('Stale session: loaded model/state changed; discard this session')
        if tuple(it.key for it in self.model.items) != self.keys:
            raise ValueError('Stale session: Item identity/order changed')
        if getattr(self.source, 'viewer_function_binding', None) != self.binding:
            raise ValueError('Stale session: selected variant provenance changed')

    def apply(self, sequence_id, step_index):
        self._check_live()
        if self.closed:
            raise ValueError('Function session is closed')
        sequences = [s for s in self.document['functional_sequences'] if s['id'] == sequence_id]
        if len(sequences) != 1:
            raise ValueError('Unknown function sequence')
        if type(step_index) is not int or not 0 <= step_index < len(sequences[0]['steps']):
            raise ValueError('Step index must be an in-range nonnegative integer')
        step = sequences[0]['steps'][step_index]
        view = next(v for v in self.document['views'] if v['id'] == step['view'])
        by_key = {it.key: it.index for it in self.model.items}
        visible, focus = set(view['visible_parts']), step['focus_parts']
        if step['view'] not in self.model.cameras or set(focus) - by_key.keys() or not set(focus) <= visible:
            raise ValueError('Function view/focus no longer resolves')
        before = _snapshot(self.viewport)
        try:
            vp, state = self.viewport, self.state
            # Neutralize prior display-only transforms; never call a builder,
            # morph provider, set_anim_fraction, set_explode or mesh mutation.
            vp.playing = vp.auto_rotate = False
            vp.explode = 0.0
            self.model.item_offsets = None
            vp.reveal_state = None
            vp.reveal_amount = vp.reveal_target = 0.0
            state.isolated = state.ghost_focus = None
            state.depth_cut = state.depth_band = 0.0
            state.hovered = -1
            for field in ('system_on', 'subsystem_on', 'region_on'):
                mask = getattr(state, field)
                for i in range(len(mask)):
                    mask[i] = True
            for i in range(len(state.system_alpha)):
                state.system_alpha[i] = 1.0
            state.part_alpha = [1.0] * len(self.keys)
            vp.set_named_view(step['view'], animate=False, visibility=True)
            # Explicit forced visibility beats any existing regional/peel state.
            for key, index in by_key.items():
                state.hidden[index] = key not in visible
                state.forced[index] = key in visible
            vp.sections = [None, None, None]
            vp.cut_on = view['cut_on']
            vp.reveal_state = None
            vp.reveal_amount = vp.reveal_target = 0.0
            state.select([by_key[key] for key in focus])
            # Function navigation has its own restore; do not grow stock undo.
            state._undo = deepcopy(self._entry['state']['_undo'])
            state._vis_dirty()
            vp.invalidate_labels()
            vp.update()
        except Exception:
            _restore(self.viewport, before)
            raise
        return step['caption']

    def restore(self):
        self._check_live()
        if self.closed:
            return False
        _restore(self.viewport, self._entry)
        self.closed = True
        return True


def apply_step(viewport, sequence_id, step_index, path=None):
    """Convenience driver retaining one session; returns the exact step caption.

    Pair with restore_steps(viewport) before changing variant/model. Configure
    must already have installed variant-bound source metadata. ``path`` may be
    omitted; changing sequences during a session uses its frozen document.
    """
    session = getattr(viewport, '_thick_skin_function_session', None)
    if session is None or session.closed:
        source = getattr(viewport.model, 'source', None)
        doc = getattr(source, 'viewer_function_design', None)
        if path is not None:
            raise ValueError('Configure a custom path before wrapping the selected model')
        session = FunctionSession(viewport, doc)
        viewport._thick_skin_function_session = session
    return session.apply(sequence_id, step_index)


def restore_steps(viewport):
    session = getattr(viewport, '_thick_skin_function_session', None)
    if session is None:
        return False
    result = session.restore()
    del viewport._thick_skin_function_session
    return result
