"""Shipped axillary inset presentation in its own schematic scene space."""
from copy import deepcopy

INSET_ID = 'cell_inset'
INSET_SCALE_NOTE = ('Separate schematic space. Cell counts and dimensions are illustrative; '
                    'the physical ruler is suppressed.')


def selected_component(descriptor, component):
    if descriptor.model_id != 'axillary_skin' or component != INSET_ID:
        raise ValueError('Component is outside the shipped axillary inset contract')
    child = (getattr(descriptor, 'verified_components', None) or {}).get(component)
    asset = descriptor.assets.get(component)
    if (child is None or asset is None or child.variant != descriptor.variant
            or child.generation_id != descriptor.generation_id
            or child.primary.path != asset.path or child.primary.sha256 != asset.sha256):
        raise ValueError('Matching verified selected-version cell inset is missing')
    return child


def inset_controls(descriptor, parts):
    """Exact original inset cameras/disclosure, independent of the main model."""
    from .controls import validate_controls
    child = selected_component(descriptor, INSET_ID)
    rows = deepcopy(list(parts))
    names = [row['name'] for row in rows]
    hidden = [name for name in names if name.endswith('/ nucleus') or name.endswith('/ basement membrane')]
    pose = {'type': 'ORTHO', 'position': [2.4, 2.8, 3.2], 'target': [0, .1, 0],
            'ortho_width': 2.7, 'cut_on': False}
    cameras = {'V1': dict(pose, title='Cell walls and open lumens', hidden=hidden),
               'V2': dict(pose, title='Basal lamina and nuclei', hidden=[])}
    native = {'summary': 'Separate secretory and duct fragments with selectable epithelial cells and hosted nuclei.',
              'scale_note': INSET_SCALE_NOTE, 'metres_per_unit': 0.0, 'viewer_cameras': cameras,
              'start_view': 'V1', 'cut_on': False, 'labels_on_open': False, 'home_view': [-.62, .42]}
    return validate_controls({'schema': 'ae-runtime-controls-v1', 'schema_version': 1,
        'adapter_id': descriptor.adapter_id, 'model_id': descriptor.model_id, 'variant': descriptor.variant,
        'primary_sha256': child.primary.sha256, 'parts': rows, 'part_names': names, 'native': native,
        'viewer': {'mixed_schematic_scale': True, 'scale_note': INSET_SCALE_NOTE},
        'documents': [], 'verified_documents': {}, 'teaching_views': [], 'functional_sequences': [],
        'autoplay': False, 'geometry_modified': False})
