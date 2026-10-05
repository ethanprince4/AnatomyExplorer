"""Reversible thick-skin teaching views for an already loaded native viewport.

Pure standard-library module: no application import, array/mesh load, filesystem
write, builder call, or rendering at import. The caller selects one independently
validated variant before using this adapter. Restore before replacing the model.
"""
from copy import deepcopy
from math import isfinite

VARIANTS = ('pre_refine', 'post_refine')
STATE_FIELDS = ('hidden', 'forced', 'isolated', 'ghost_focus', 'depth_cut',
                'depth_band', 'selected', 'hovered', 'system_alpha', 'system_on',
                'subsystem_on', 'region_on', '_undo')
VIEWPORT_FIELDS = ('sections', 'cut_on', 'cut_planes', 'labels_on', 'explode',
                   'reveal_state', 'reveal_amount', 'reveal_target', 'playing',
                   'auto_rotate', 'anim_t', '_last_frame_time')
CAMERA_FIELDS = ('target', 'distance', 'yaw', 'pitch', 'fov', 'ortho',
                 'ortho_width', '_anim')
MODEL_FIELDS = ('item_offsets', 'node_offsets')


def _number(value):
    return type(value) in (int, float) and isfinite(value)


def _binding(variant_id, content_identity):
    if variant_id not in VARIANTS:
        raise ValueError('Unknown selected variant')
    if (not isinstance(content_identity, str) or len(content_identity) != 64
            or any(c not in '0123456789abcdefABCDEF' for c in content_identity)):
        raise ValueError('Selected variant native-cache SHA-256 is required')
    return {'model_id': 'thick_skin', 'variant_id': variant_id,
            'content_identity': content_identity.lower()}


def configure(model, document, part_names, *, variant_id, content_identity):
    """Bind source controls to caller-verified saved metadata before wrapping.

    The caller verifies the actual selected cache SHA-256. ``part_names`` comes
    from verified metadata, never model.parts() or mesh arrays. This only adds
    view metadata to the loaded source descriptor, not to saved variant files.
    """
    if getattr(model, 'id', None) != 'thick_skin':
        raise ValueError('Teaching controls are model-specific')
    binding = _binding(variant_id, content_identity)
    names = list(part_names)
    resolved = deepcopy(document)
    for view in resolved.get('views', []):
        validate_view(resolved, view['id'], names)
    if not resolved.get('views'):
        raise ValueError('Teaching views are empty')
    resolved['variant_binding'] = deepcopy(binding)
    resolved['part_names'] = names
    model.viewer_teaching_binding = deepcopy(binding)
    model.viewer_teaching_design = deepcopy(resolved)
    return resolved


def validate_view(document, view_id, item_keys):
    """Resolve the complete delivered Part-name/Item-key inventory before edits.

    New cell/receptor details are required, even when a particular view hides
    them. An incomplete build cannot silently masquerade as a complete lesson.
    Extra items are hidden explicitly; exact duplicates are always rejected.
    """
    if document.get('schema_version') != 1 or document.get('model_id') != 'thick_skin':
        raise ValueError('Expected thick_skin teaching schema version 1')
    policy = document.get('variant_policy', {})
    if policy.get('allowed_variants') != list(VARIANTS) or policy.get('layout') != 'single_selected_variant':
        raise ValueError('Teaching requires independently selectable Pre/Post variants')
    keys = list(item_keys)
    if any(not isinstance(key, str) or not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError('Item keys must be nonempty and unique')
    required = document.get('required_parts', [])
    if not required or len(required) != len(set(required)):
        raise ValueError('Required part inventory is empty or duplicated')
    missing = set(required) - set(keys)
    if missing:
        raise ValueError('Missing required teaching parts: ' + ', '.join(sorted(missing)))
    views = document.get('views', [])
    ids = [v.get('id') for v in views]
    if len(ids) != len(set(ids)):
        raise ValueError('Teaching view ids are not unique')
    matches = [v for v in views if v.get('id') == view_id]
    if len(matches) != 1:
        raise ValueError('Teaching view must resolve exactly once: ' + str(view_id))
    view = matches[0]
    hosts = view.get('hosts', {})
    if set(hosts) != set(required):
        raise ValueError('Every view must explicitly address every delivered part')
    for name, rec in hosts.items():
        if any(type(rec.get(field)) is not bool for field in ('visible', 'clip_enabled', 'label')):
            raise ValueError('Visibility, clipping and labels must be booleans: ' + name)
        alpha = rec.get('alpha_multiplier')
        if not _number(alpha) or not 0 <= alpha <= 1:
            raise ValueError('Invalid opacity multiplier: ' + name)
    axes = set()
    for section in view.get('sections', []):
        axis = section.get('axis')
        if axis not in ('x', 'y', 'z') or axis in axes:
            raise ValueError('Sections must use distinct Cartesian axes')
        axes.add(axis)
        if section.get('keep') not in ('ge', 'le') or not _number(section.get('position')):
            raise ValueError('Invalid section plane')
    if type(view.get('labels_on')) is not bool or type(view.get('cut_on')) is not bool:
        raise ValueError('Labels/cut_on must be booleans')
    camera = view.get('camera', {})
    for field in ('position', 'target'):
        vector = camera.get(field)
        if not isinstance(vector, (list, tuple)) or len(vector) != 3 or not all(_number(v) for v in vector):
            raise ValueError('Camera requires finite xyz vectors')
    if list(camera['position']) == list(camera['target']):
        raise ValueError('Camera position equals target')
    if camera.get('type') != 'ORTHO' or not _number(camera.get('ortho_width')) or camera['ortho_width'] <= 0:
        raise ValueError('Teaching camera requires positive orthographic width')
    aliases = document.get('display_aliases', {})
    if set(aliases) - set(required) or any(not isinstance(v, str) or not v for v in aliases.values()):
        raise ValueError('Invalid display alias')
    return view


def _check_binding(model, document, variant):
    source = model.source
    binding = getattr(source, 'viewer_teaching_binding', None)
    design = getattr(source, 'viewer_teaching_design', None)
    if not binding or not design:
        raise ValueError('Configure the verified selected variant before teaching')
    expected = _binding(binding.get('variant_id'), binding.get('content_identity'))
    if expected != binding or binding['variant_id'] != variant:
        raise ValueError('Teaching variant binding differs from the selected variant')
    if document.get('variant_binding', binding) != binding or design.get('variant_binding') != binding:
        raise ValueError('Teaching document belongs to another variant')
    if tuple(design.get('part_names', [])) != tuple(it.key for it in model.items):
        raise ValueError('Configured metadata differs from the loaded variant inventory')
    return binding


def _check_runtime(viewport):
    model, state, camera = viewport.model, viewport.state, viewport.camera
    source = getattr(model, 'source', None)
    if source is None or getattr(source, 'id', None) != 'thick_skin':
        raise ValueError('Viewport must contain the selected native thick_skin model')
    items = model.items
    if sorted(it.index for it in items) != list(range(len(items))):
        raise ValueError('Viewer Item indices must be contiguous')
    if len(state.hidden) != len(items) or len(state.forced) != len(items):
        raise ValueError('Scene visibility lengths do not match model')
    for owner, fields in ((state, STATE_FIELDS), (viewport, VIEWPORT_FIELDS),
                          (camera, CAMERA_FIELDS), (model, MODEL_FIELDS)):
        for field in fields:
            if not hasattr(owner, field):
                raise ValueError('Unsupported native viewer, missing field: ' + field)
    for owner, method in ((state, '_vis_dirty'), (state, 'select'), (camera, 'set_record'),
                          (viewport, 'invalidate_labels'), (viewport, 'update')):
        if not callable(getattr(owner, method, None)):
            raise ValueError('Unsupported native viewer, missing method: ' + method)


def _refresh(viewport):
    viewport.state._vis_dirty()
    viewport.state.select(viewport.state.selected)
    viewport.invalidate_labels()
    viewport.update()


def apply_view(viewport, document, view_id, animate=False, *, variant=None):
    """Apply one lesson to exactly one already-selected built variant.

    Visibility, labels, alpha, display aliases, and clipping are transient viewer
    controls. Materials, vertex colors/normals, mesh arrays, source Part metadata,
    and saved variants are untouched. The returned token is viewport/model-bound.
    Call after ordinary set_named_view, which otherwise resets section planes.
    """
    if variant not in VARIANTS:
        raise ValueError('Pass the selected pre_refine or post_refine variant explicitly')
    if type(animate) is not bool:
        raise ValueError('animate must be a boolean')
    _check_runtime(viewport)
    model, state, camera = viewport.model, viewport.state, viewport.camera
    items = model.items
    view = validate_view(document, view_id, [it.key for it in items])
    binding = _check_binding(model, document, variant)
    if animate and not callable(getattr(viewport, 'duration', None)):
        raise ValueError('Animated camera requires native viewport.duration')
    token = {
        'viewport_ref': viewport, 'model_ref': model, 'state_ref': state,
        'camera_ref': camera, 'item_refs': tuple(items), 'variant': variant,
        'binding': deepcopy(binding),
        'restored': False,
        'state': {k: deepcopy(getattr(state, k)) for k in STATE_FIELDS},
        'viewport': {k: deepcopy(getattr(viewport, k)) for k in VIEWPORT_FIELDS},
        'camera': {k: deepcopy(getattr(camera, k)) for k in CAMERA_FIELDS},
        'model': {k: deepcopy(getattr(model, k)) for k in MODEL_FIELDS},
        'items': [(it, it.clip, it.label, it.name) for it in items],
        'had_part_alpha': hasattr(state, 'part_alpha'),
        'part_alpha': deepcopy(getattr(state, 'part_alpha', None)),
    }
    try:
        state.isolated = state.ghost_focus = None
        state.depth_cut = state.depth_band = 0.0
        state.selected, state.hovered = [], -1
        for field in ('system_on', 'subsystem_on', 'region_on'):
            values = getattr(state, field)
            for i in range(len(values)):
                values[i] = True
        for i in range(len(state.system_alpha)):
            state.system_alpha[i] = 1.0
        state.part_alpha = [1.0] * len(items)
        aliases = document.get('display_aliases', {})
        for item in items:
            record = view['hosts'].get(item.key)
            visible = bool(record and record['visible'])
            state.hidden[item.index], state.forced[item.index] = not visible, visible
            item.label = bool(record and record['label'])
            if record:
                state.part_alpha[item.index] = record['alpha_multiplier']
                item.clip = record['clip_enabled']
            if item.key in aliases:
                item.name = aliases[item.key]
        viewport.sections = [None, None, None]
        for section in view['sections']:
            slot = {'x': 0, 'z': 1, 'y': 2}[section['axis']]
            # Native shader removes the negative halfspace; flip retains <=.
            viewport.sections[slot] = (section['position'], section['keep'] == 'le')
        viewport.cut_on, viewport.labels_on = view['cut_on'], view['labels_on']
        # Reset display-space offsets only; never stretch passage geometry.
        viewport.explode = 0.0
        model.item_offsets, model.node_offsets = None, {}
        viewport.reveal_state = None
        viewport.reveal_amount = viewport.reveal_target = 0.0
        viewport.playing = viewport.auto_rotate = False
        camera.set_record(view['camera'], duration=viewport.duration() if animate else 0.0,
                          zoom_path=bool(animate), fit=None)
        _refresh(viewport)
    except Exception:
        _restore(viewport, token, notify=False)
        # Retain the original apply failure even if the native repaint also fails.
        try:
            _refresh(viewport)
        except Exception:
            pass
        raise
    return token


def _restore(viewport, token, *, notify):
    if token.get('restored'):
        raise ValueError('Teaching token has already been restored')
    if (viewport is not token['viewport_ref'] or viewport.model is not token['model_ref']
            or viewport.state is not token['state_ref'] or viewport.camera is not token['camera_ref']
            or len(viewport.model.items) != len(token['item_refs'])
            or any(a is not b for a, b in zip(viewport.model.items, token['item_refs']))):
        raise ValueError('Restore teaching before replacing the selected viewport/model')
    if getattr(viewport.model.source, 'viewer_teaching_binding', None) != token['binding']:
        raise ValueError('Restore teaching before rebinding the selected variant')
    for name, value in token['state'].items():
        setattr(viewport.state, name, deepcopy(value))
    if token['had_part_alpha']:
        viewport.state.part_alpha = deepcopy(token['part_alpha'])
    elif hasattr(viewport.state, 'part_alpha'):
        del viewport.state.part_alpha
    for item, clip, label, name in token['items']:
        item.clip, item.label, item.name = clip, label, name
    for owner, key in ((viewport, 'viewport'), (viewport.camera, 'camera'),
                       (viewport.model, 'model')):
        for name, value in token[key].items():
            setattr(owner, name, deepcopy(value))
    token['restored'] = True
    if notify:
        _refresh(viewport)


def restore_view(viewport, token):
    """Restore all changed display controls, including alias/clip/alpha/offsets.

    Stock visibility undo omits several of these fields. Tokens cannot cross
    variant/model replacement and are deliberately single-use.
    """
    _restore(viewport, token, notify=True)


class TeachingSession:
    """Small controller hook: replace lessons; clear before a variant/model swap."""
    def __init__(self, viewport, document, *, variant):
        if variant not in VARIANTS:
            raise ValueError('Unknown selected variant')
        self.viewport, self.document, self.variant = viewport, document, variant
        self.token = None

    def apply(self, view_id, *, animate=False):
        # Validate first so a bad menu choice preserves the current lesson.
        validate_view(self.document, view_id, [it.key for it in self.viewport.model.items])
        self.clear()
        self.token = apply_view(self.viewport, self.document, view_id,
                                animate=animate, variant=self.variant)
        return self.token

    def clear(self):
        if self.token is not None:
            restore_view(self.viewport, self.token)
            self.token = None
