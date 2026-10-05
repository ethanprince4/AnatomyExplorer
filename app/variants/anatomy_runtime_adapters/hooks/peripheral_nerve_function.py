"""Resolve explicit teaching frames; never import the app or load geometry.

CLI emits JSON for a lesson consumer. Captions are manual teaching states,
not a voltage, ion, perfusion, or regeneration simulation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path


def validate(document):
    assert document['schema_version'] == 1
    assert document['model_id'] == 'peripheral_nerve'
    names = document['part_names']
    assert len(names) == len(set(names)) == 16
    sequence_ids = set()
    for sequence in document['sequences']:
        assert sequence['id'] not in sequence_ids
        sequence_ids.add(sequence['id'])
        step_ids = set()
        for step in sequence['steps']:
            assert step['id'] not in step_ids
            step_ids.add(step['id'])
            state = step['state']
            visible, hidden = set(state['visible_parts']), set(state['hidden_parts'])
            assert not (visible & hidden)
            assert visible | hidden == set(names)
            assert set(state['focus_parts']) <= visible
            assert state['layer_separation'] == 0
            assert state['opacity'] == 1.0
            assert len(state['labels']) <= 3
            assert set(state['labels']) <= visible
            if 'Schwann cell nuclei' in visible:
                assert {'Schwann cell outer cytoplasm', 'Remak Schwann cells'} <= visible
            assert step['caption'] and step['schematic_limitations']
    return document


def resolve(document, sequence_id, step_id, variant, model_sha256, certificate=None):
    validate(document)
    sequence = next(s for s in document['sequences'] if s['id'] == sequence_id)
    step = next(s for s in sequence['steps'] if s['id'] == step_id)
    gate = sequence.get('gate')
    if gate:
        certificate = certificate or {}
        if variant != gate['source_variant']:
            raise ValueError('Connected-route lesson requires the R1 refinement source variant')
        if certificate.get('source_variant') != variant:
            raise ValueError('Certificate source variant mismatch')
        if len(model_sha256) != 64 or certificate.get('model_sha256') != model_sha256:
            raise ValueError('Connected-route lesson requires a certificate for this saved model digest')
        if certificate.get('model_id') != document['model_id']:
            raise ValueError('Certificate model identity mismatch')
        if not all(certificate.get('checks', {}).get(key) is True for key in gate['required_checks']):
            raise ValueError('Connected-route lesson remains disabled until every required check passes')
    return {'model_id': document['model_id'], 'sequence_id': sequence_id,
            'step_id': step_id, 'state': step['state'], 'caption': step['caption'],
            'conceptual_inset': step.get('conceptual_inset'),
            'schematic_limitations': step['schematic_limitations'],
            'source_variant': variant, 'model_sha256': model_sha256,
            'simulation': False}


def install_function_presets(model, document, variant, model_sha256, certificate=None):
    """Add ordered manual function presets to an additive review MicroModel.

    Call after the teaching adapter and before native ProceduralModel creation.
    Native camera selection applies hidden/cut_on. It does not automatically
    render captions, conceptual insets, focus, per-step labels or opacity.
    Those remain explicit accompanying review instructions in returned frames.
    """
    if getattr(model, 'id', None) not in ('peripheral_nerve_design', 'peripheral_nerve_design_review', 'peripheral_nerve_refinement'):
        raise ValueError('Apply only to an additive peripheral nerve review model')
    validate(document)
    cameras = deepcopy(model.viewer_cameras)
    frames, gated = [], []
    for sequence in document['sequences']:
        for step in sequence['steps']:
            try:
                frame = resolve(document, sequence['id'], step['id'], variant, model_sha256, certificate)
            except ValueError as exc:
                if sequence.get('gate'):
                    gated.append({'sequence': sequence['id'], 'reason': str(exc)})
                    break
                raise
            record = deepcopy(cameras[frame['state']['camera_preset']])
            record['hidden'] = frame['state']['hidden_parts']
            record['cut_on'] = frame['state']['cut_on']
            record['note'] = frame['caption'] + ' ' + ' '.join(frame['schematic_limitations'])
            key = 'FUNCTION ' + sequence['id'] + ' ' + step['id']
            cameras[key] = record
            frames.append(dict(frame, installed_camera_preset=key))
    model.viewer_cameras = cameras
    return {'frames': frames, 'disabled_sequences': gated, 'caption_display': 'manual accompanying sidecar; native camera notes are not automatically displayed'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sidecar', type=Path, default=Path(__file__).with_name('function_sequences.json'))
    parser.add_argument('--sequence')
    parser.add_argument('--step')
    parser.add_argument('--source-variant', default='baseline', choices=('baseline', 'r1_refinement'))
    parser.add_argument('--model-sha256', default='')
    parser.add_argument('--certificate', type=Path)
    args = parser.parse_args(argv)
    doc = validate(json.loads(args.sidecar.read_text(encoding='utf-8')))
    if args.sequence is None:
        result = {'validated': True, 'sequences': [s['id'] for s in doc['sequences']],
                  'steps': sum(len(s['steps']) for s in doc['sequences'])}
    else:
        if not args.step:
            parser.error('--sequence requires --step')
        cert = json.loads(args.certificate.read_text(encoding='utf-8')) if args.certificate else None
        result = resolve(doc, args.sequence, args.step, args.source_variant, args.model_sha256, cert)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
