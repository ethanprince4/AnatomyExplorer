"""Source-only teaching metadata adapter; no native-app or numerical imports.

Run only to produce a NEW sidecar in the future output directory:
  python teaching_sidecar.py --source-sidecar INPUT.viewer.json \
    --construction NEW.construction.json --output OUTPUT.viewer.json

The lead may call install_native_metadata(viewer_model, entry) AFTER constructing
its viewer model and BEFORE creating ModelView. This function imports no app.
Camera positions are provisional saved-candidate poses; new framing is a visual gate.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent


def load_contract(path=None):
    return json.loads(Path(path or BUNDLE / 'teaching_contract.json').read_text(encoding='utf-8'))


def validate_names(part_names, contract=None):
    contract = contract or load_contract()
    names = list(part_names)
    if len(names) != len(set(names)):
        raise ValueError('Duplicate selectors would make native key lookup ambiguous')
    required = {p['key'] for p in contract['selectors']}
    missing = sorted(required - set(names))
    if missing:
        raise ValueError('Required tongue selectors missing: ' + ', '.join(missing))
    return names


def make_overlay(part_names, contract=None):
    contract = contract or load_contract()
    names = validate_names(part_names, contract)
    cameras = {}
    for v in contract['views']:
        rec = deepcopy(v['camera'])
        visible = set(names) if v['id'] == 'T01' else set(v['visible_parts'])
        rec['hidden'] = [name for name in names if name not in visible]
        cameras[v['title']] = rec
    return dict(cameras=cameras, camera_order=list(cameras),
                start_view=next(iter(cameras)), view_transition='zoom',
                mixed_schematic_scale=True, teaching_scope=contract['scale_disclosure'],
                review_status='Source-defined revision; new native and GLB visual acceptance pending.')


def merge_sidecar(source_sidecar, part_names, contract=None):
    result = deepcopy(source_sidecar)
    # Existing source hashes, materials, roles, states and structures are preserved.
    result.update(make_overlay(part_names, contract))
    return result


def install_native_metadata(viewer_model, entry=None, contract=None, model_id=None):
    """Apply metadata to an already-loaded tongue-only viewer, without mesh work.

    Call before ModelView creates its sidebar/button list. The caller must supply
    a verified tongue entry; this intentionally does not choose or register one.
    mixed_schematic_scale goes on ViewerModel.sidecar, not just the micro source.
    """
    source = getattr(viewer_model, 'source', None)
    source_id = getattr(source, 'id', None)
    entry_id = getattr(entry, 'id', None)
    if model_id != 'tongue_papillae' and source_id not in {'tongue_papillae', 'tongue_papillae_refined_review'} and entry_id not in {
            'tongue_papillae', 'tongue_papillae_refined_review'}:
        raise ValueError('Metadata adapter requires a verified tongue-only model identity')
    contract = contract or load_contract()
    overlay = make_overlay([item.key for item in viewer_model.items], contract)
    viewer_model.sidecar.update(deepcopy(overlay))
    viewer_model.cameras = deepcopy(overlay['cameras'])
    viewer_model.camera_order = list(overlay['camera_order'])
    if source is not None:
        source.scale_note = contract['scale_disclosure']
    if entry is not None:
        entry.scale_note = contract['scale_disclosure']
    return overlay


def set_named_view_with_context_reset(model_view, name, model_id=None, contract=None):
    """On-machine tongue-only UI adapter; not executed by source checks.

    Wire tongue preset buttons/stepping/home through this adapter after ModelView
    exists. Native set_named_view alone does not clear group/depth/opacity filters
    or separate-layer offsets. Do not use for ordinary generic isolate actions.
    """
    model = model_view.vmodel
    source_id = getattr(getattr(model, 'source', None), 'id', None)
    entry_id = getattr(getattr(model_view, 'entry', None), 'id', None)
    if model_id != 'tongue_papillae' and source_id not in {'tongue_papillae', 'tongue_papillae_refined_review'} and entry_id not in {
            'tongue_papillae', 'tongue_papillae_refined_review'}:
        raise ValueError('Context reset requires a verified tongue-only model identity')
    validate_names([item.key for item in model.items], contract)
    if name not in model.cameras:
        raise ValueError('Unknown tongue preset: ' + name)
    state = model_view.state
    state.reset_visibility()
    for attr in ('system_on', 'subsystem_on', 'region_on'):
        getattr(state, attr).fill(True)
    state.system_alpha.fill(1.0)
    if getattr(state, 'part_alpha', None) is not None:
        state.part_alpha.fill(1.0)
    state.depth_cut = 0.0
    state.depth_band = 0.0
    state.ghost_focus = None
    state._vis_dirty()
    model_view.gl_widget.set_explode(0.0)
    # Keep the native controls consistent without invoking replacement methods.
    for control, value in (('explode', 0), ('opacity', 100)):
        slider = getattr(model_view, control, None)
        if slider is not None:
            old = slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(old)
    model_view.gl_widget.set_named_view(name, visibility=True)


def visibility_warnings(visible_names, contract=None):
    """Pure diagnostic for integration; never moves a correctly seated part.

    Generic app isolation remains available. Host absence means a display state,
    not anatomical displacement. The native app has no automatic warning hook;
    the integrating UI may show these strings as context notices.
    """
    contract = contract or load_contract()
    shown = set(visible_names)
    warnings = []
    if shown & {'Taste buds', 'Gustatory receptor cells', 'Basal taste cells'} and not shown & {
            'Circumvallate papilla', 'Fungiform papillae', 'Foliate papillae'}:
        warnings.append('Papillary host is hidden; exposed taste structures are an isolation view.')
    if shown & {'Von Ebner glands', 'Von Ebner ducts'} and not shown & {
            'Stratified squamous epithelium', 'Circumvallate papilla', 'Foliate papillae'}:
        warnings.append('Outlet host is hidden; return to the floor-context view before judging drainage.')
    for pair in contract['guardrails']['paired_cover_removals']:
        states = [name in shown for name in pair]
        if any(states) and not all(states):
            warnings.append('Matched tissue and nuclear covers are partly hidden: ' + ', '.join(pair))
    return warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sidecar', type=Path, required=True)
    parser.add_argument('--construction', type=Path, required=True)
    parser.add_argument('--contract', type=Path, default=None)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    source = json.loads(args.source_sidecar.read_text(encoding='utf-8'))
    construction = json.loads(args.construction.read_text(encoding='utf-8'))
    contract = load_contract(args.contract)
    result = merge_sidecar(source, [part['name'] for part in construction['parts']], contract)
    # Exclusive creation preserves every input and prevents accidental replacement.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print('New teaching sidecar written:', args.output)


if __name__ == '__main__':
    main()
