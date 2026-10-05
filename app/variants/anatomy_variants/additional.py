"""Strict source-witness acceptance beyond edge/lumen numerical diagnostics."""
import hashlib
import math
from .security import canonical_json, require, digest

SCOPES={'cell_ownership','lumens','passages','radii','contacts'}
INSTANCE_SEMANTICS='source-authored immutable instance near-point adjacency; positive-area material contact is not asserted'
INTERFACE_SEMANTICS='opposing outward-facing normals and reciprocal nonnegative signed plane gaps; float64 arithmetic roundoff only'

def object_hash(value):return hashlib.sha256(canonical_json(value)[:-1]).hexdigest()
def finite(value):return type(value) in (int,float) and math.isfinite(value)

def validate_additional_envelope(profile,audit,*,model_id,saved_sha256):
    binding=profile['final_microrefine'];expected=binding.get('additional_checks')
    require(isinstance(expected,dict) and set(expected)==SCOPES,'source check scopes missing')
    require(all(isinstance(v,list) and len(v)<=4096 for v in expected.values()),'invalid source check declarations')
    witnesses=binding.get('witnesses');require(isinstance(witnesses,dict),'source witnesses missing')
    checked=audit.get('additional_validation',audit.get('additional'))
    require(isinstance(checked,dict) and checked.get('schema')=='ae.final-microrefine-extra-validation.v1' and checked.get('model_id')==model_id and checked.get('status')=='passed' and checked.get('read_only') is True and checked.get('input_sha256')==saved_sha256 and checked.get('source_witnesses_sha256')==object_hash(witnesses),'independent source check binding missing/mismatched')
    rows=checked.get('checks');require(isinstance(rows,dict) and set(rows)==SCOPES-{'lumens'},'independent source check scopes incomplete')
    for scope in rows:
        require(isinstance(rows[scope],list) and all(isinstance(r,dict) for r in rows[scope]) and all(isinstance(r,dict) for r in expected[scope]),'malformed source check rows')
        actual=[r.get('witness_id') for r in rows[scope]];declared=[r.get('witness_id') for r in expected[scope]]
        require(actual==declared and all(isinstance(w,str) and w and w in witnesses for w in declared) and all(r.get('status')=='passed' for r in rows[scope]),'source checks omitted/reordered/failed/unbound')
    for row,decl in zip(rows['contacts'],expected['contacts']):
        require(row.get('contact_kind','meaningful_area')==decl.get('contact_kind','meaningful_area'),'contact kind changed')
        if decl.get('contact_kind')=='immutable_source_instance_adjacency':
            require(model_id in {'blood_cells','synthetic','fixture'} and row.get('semantics')==INSTANCE_SEMANTICS and row.get('immutable_source_arrays_exact') is True,'immutable instance adjacency unqualified')
            gap=row.get('minimum_signed_axis_gap');lo=row.get('minimum_gap');hi=row.get('maximum_gap')
            require(all(finite(v) for v in (gap,lo,hi)) and lo-1e-9<=gap<=hi+1e-9,'instance adjacency gap outside exact source bounds')
            require(row.get('instance_ids')==decl.get('instance_ids') and row.get('part')==decl.get('part') and row.get('instance_spans_sha256')==object_hash(decl.get('instance_spans')) and row.get('instance_reference_sha256')==decl.get('instance_references',{}).get('sha256') and row.get('source_part_reference_sha256')==decl.get('source_part_reference',{}).get('sha256') and all(row.get(k)==decl.get(k) for k in ('minimum_gap','maximum_gap','source_clearance')),'instance adjacency source identity changed')
            if model_id=='blood_cells':require(decl.get('part')=='Rouleau' and decl.get('source_clearance')==3e-6 and 0<hi<=7e-6,'blood source adjacency semantics changed')
            continue
        require(row.get('interface_semantics')==INTERFACE_SEMANTICS,'contact interface is not qualified outward-facing reciprocal gap measurement')
        area=row.get('area');minimum=decl.get('minimum_area')
        require(finite(area) and finite(minimum) and area>=minimum>=0 and row.get('max_gap')==decl.get('max_gap') and row.get('maximum_normal_angle')==decl.get('maximum_normal_angle',10) and row.get('source_region_restricted')==bool(decl.get('contact_window') or decl.get('contact_bounds')),'meaningful source interface measurement failed/waived')
    return checked
