"""Shipped stdlib semantics for the narrow immutable source-interaction lane.

Mirrors the reviewed helper's envelope/transport functions. This module never
imports external manifests, source builders or numerical geometry libraries.
Actual saved numerical measurements are supplied by the pinned trusted runner.
"""
import copy
import itertools
import math
from .security import SHA as HEX, require as _require
from .additional import object_hash

# The producer pins are updated only after emitted conformance and freezing.
ADAPTER_SHA256 = 'f65c4cf605792d696f5b473e3e2c0991933fbf4bc6b31d5c374456df1267af59'
RELATIONSHIP_SCHEMA = 'ae.authored-relationship-transport.v1'

def require(condition, code, detail=''):
    _require(condition, code + (': ' + str(detail) if detail else ''))

def finite(value, *, minimum=None, maximum=None, positive=False):
    return type(value) in (int,float) and math.isfinite(value) and (not positive or value>0) and (minimum is None or value>=minimum) and (maximum is None or value<=maximum)

ADAPTER_ID = 'ae.immutable-authored-interactions.v1'

SCHEMA = 'ae.source-authored-interaction.v1'

PROOF_SCHEMA = 'ae.authored-interaction-projection.v1'

EMBEDDING = 'immutable_source_local_embedding'

AFFILIATION = 'immutable_source_exposed_child_affiliation'

SEMANTICS = {
    EMBEDDING: 'Exact immutable source-local finite embedding; opposing positive-area contact is not asserted.',
    AFFILIATION: 'Exact immutable source-exposed child and authored host affiliation; full physiological enclosure is not asserted.',
}

REFERENCE_KEYS = ('source_native_writer_capture', 'source_region', 'source_intersection_reference')

def ear_attachment_specs():
    """Exact named source roots/insertions, never label-derived contact pairs."""
    return (('Inner hair cells','Hair-cell stereocilia','_inset_cochlea'),
        ('Outer hair cells','Hair-cell stereocilia','_inset_cochlea'),
        ('Type I hair cells (crista)','Stereocilia & kinocilia (crista)','_inset_crista'),
        ('Type II hair cells (crista)','Stereocilia & kinocilia (crista)','_inset_crista'),
        ('Type I hair cells (macula)','Stereocilia & kinocilia (macula)','_inset_macula'),
        ('Type II hair cells (macula)','Stereocilia & kinocilia (macula)','_inset_macula'),
        ('Otoconia (otoliths)','Otolithic membrane (magnified)','_inset_macula'),
        ('Cupula (magnified)','Stereocilia & kinocilia (crista)','_inset_crista'),
        ('Gelatinous layer','Stereocilia & kinocilia (macula)','_inset_macula'),
        ('Malleus','Incudomallear joint','_ossicle_parts'),('Incus','Incudomallear joint','_ossicle_parts'),
        ('Incus','Incudostapedial joint','_ossicle_parts'),('Stapes','Incudostapedial joint','_ossicle_parts'),
        ('Stapes','Base (footplate) of stapes','_ossicle_parts'),
        ('Base (footplate) of stapes','Oval window & annular ligament','_ligament_parts'),
        ('Malleus','Tympanic membrane – pars tensa','_ossicle_parts'),
        ('Malleus','Tensor tympani tendon','_ligament_parts'),('Stapes','Stapedius tendon','_ligament_parts'),
        ('Tensor tympani','Tensor tympani tendon','_ligament_parts'),('Stapedius','Stapedius tendon','_ligament_parts'),
        ('Malleus','Superior ligament of malleus','_ligament_parts'),('Malleus','Lateral ligament of malleus','_ligament_parts'),
        ('Malleus','Anterior ligament of malleus','_ligament_parts'),('Incus','Posterior ligament of incus','_ligament_parts'))

def ear_embedding_pairs():
    return (('Tectorial membrane (magnified)','Spiral limbus'),
        ('Tectorial membrane (magnified)','Hair-cell stereocilia'))+tuple((a,b) for a,b,_ in ear_attachment_specs())

def _hash(value, detail):
    require(HEX.fullmatch(str(value or '')), 'authored_interaction_hash_missing', detail)

def validate_contract(row, profile, root=None):
    """Pure-stdlib declaration checks; no numeric claims are accepted here."""
    name = str(row.get('witness_id', '?')); model = profile.get('model_id')
    require(row.get('schema') == SCHEMA and row.get('kind') in SEMANTICS and row.get('witness_id'),
            'authored_interaction_schema_invalid', name)
    require(model in {'ear', 'compact_bone', 'male_reproductive', 'female_reproductive', 'lymph_node', 'synthetic', 'fixture'} and row.get('model_id') == model,
            'authored_interaction_model_unsupported', str(model))
    require((model not in {'ear','male_reproductive','female_reproductive','lymph_node'} or row['kind'] == EMBEDDING) and
            (model != 'compact_bone' or row['kind'] == AFFILIATION), 'authored_interaction_kind_mismatch', name)
    parts = row.get('parts')
    require(isinstance(parts, list) and len(parts) == 2 and len(set(parts)) == 2 and
            all(isinstance(p, str) and p for p in parts), 'authored_interaction_parts_invalid', name)
    require(row.get('immutable_participants_required') is True and row.get('exact_saved_array_correspondence_required') is True and
            set(parts) <= set(profile.get('immutable_geometry_parts', [])) and
            not set(parts) & {x['part'] for x in profile.get('preserved_representations', [])},
            'authored_interaction_material_not_immutable', name)
    require(row.get('collision_waiver') is False and not row.get('allow_overlap') and
            row.get('coordinate_space') == 'saved_pre_model_units' and row.get('volume_units') == 'model_units_cubed',
            'authored_interaction_scope_invalid', name)
    source_hashes = profile.get('final_microrefine', {}).get('source_hashes', profile.get('source_hashes', {}))
    require(row.get('source') in source_hashes and row.get('source_sha256') == source_hashes[row['source']],
            'authored_interaction_source_unbound', name)
    _hash(row.get('source_sha256'), name)
    if model not in {'synthetic','fixture'}:
        expected_source = {'ear':'baseline/app/micro/ear.py','compact_bone':'baseline/app/micro/bone.py',
            'male_reproductive':'baseline/app/micro/male.py','female_reproductive':'recovery/female-reproductive-refinement/source/build.py',
            'lymph_node':'baseline/app/micro/lymphoid.py'}[model]
        require(row['source'] == expected_source, 'authored_interaction_source_selector_changed', name)
        _hash(row.get('source_native_metadata_sha256'), name)
    require(row.get('pair_scope', 'full_pair') in {'full_pair','source_instance_region'}, 'authored_interaction_pair_scope_invalid', name)
    ids = row.get('source_instance_ids')
    require(isinstance(ids, list) and ids and len(ids) == len(set(ids)) and all(isinstance(x, str) and x for x in ids),
            'authored_interaction_instance_ids_missing', name)
    require(row.get('source_index_encoding') in {'delta_int32','triangles_int64'}, 'authored_interaction_index_encoding_missing', name)
    refs = row.get('source_part_references'); indexes = row.get('native_part_indices'); digests = row.get('source_part_array_sha256')
    require(isinstance(refs, dict) and set(refs) == set(parts) and isinstance(indexes, dict) and set(indexes) == set(parts) and
            all(type(i) is int and i >= 0 for i in indexes.values()) and len(set(indexes.values())) == 2 and
            isinstance(digests, dict) and set(digests) == set(parts), 'authored_interaction_part_binding_missing', name)
    for digest in digests.values(): _hash(digest, name)
    require(finite(row.get('source_intersection_volume'), positive=True) and
            finite(row.get('minimum_intersection_volume'), positive=True) and
            0 < row['minimum_intersection_volume'] <= row['source_intersection_volume'] and
            finite(row.get('minimum_retained_source_fraction'), minimum=.95, maximum=1),
            'authored_interaction_bounds_invalid', name)
    require(row.get('source_capture_defect') is None, 'authored_interaction_source_defect', name)
    if row['kind'] == AFFILIATION:
        require(row.get('host') in parts and row.get('child') in parts and row['host'] != row['child'] and
                row.get('full_enclosure_asserted') is False and row.get('owners'), 'authored_affiliation_identity_missing', name)
        owners = row['owners']
        child_ids = row.get('child_instance_ids'); host_ids = row.get('host_instance_ids')
        require(isinstance(child_ids, list) and isinstance(host_ids, list) and child_ids and host_ids and
                len(child_ids) == len(set(child_ids)) and len(host_ids) == len(set(host_ids)),
                'authored_affiliation_source_registry_missing', name)
        require(len({x.get('child_id') for x in owners}) == len(owners) and
                all(isinstance(x.get('child_id'), str) and isinstance(x.get('host_id'), str) and
                    type(x.get('child_reference_index')) is int and x['child_reference_index'] >= 0 and
                    type(x.get('host_reference_index')) is int and x['host_reference_index'] >= 0 for x in owners),
                'authored_affiliation_owners_invalid', name)
        require(all(x['child_reference_index'] < len(child_ids) and x['host_reference_index'] < len(host_ids) and
                    x['child_id'] == child_ids[x['child_reference_index']] and x['host_id'] == host_ids[x['host_reference_index']] for x in owners),
                'authored_affiliation_source_registry_changed', name)
        require([x['child_id'] for x in owners] == ids, 'authored_affiliation_instance_ids_changed', name)
        for key in ('child_references', 'host_references'):
            require(isinstance(row.get(key), dict), 'authored_affiliation_reference_missing', name)
            require(root is None, 'external_source_resolution_forbidden', name)
    for spec in [*refs.values(), *[row.get(k) for k in REFERENCE_KEYS]]:
        require(isinstance(spec, dict) and HEX.fullmatch(str(spec.get('sha256', ''))), 'authored_interaction_reference_missing', name)
        require(root is None, 'external_source_resolution_forbidden', name)
    return row

def validate_inventory(rows, profile, root=None):
    require(isinstance(rows, list) and rows, 'authored_interaction_inventory_missing', str(profile.get('model_id')))
    for row in rows: validate_contract(row, profile, root)
    require(len({x['witness_id'] for x in rows}) == len(rows) and
            len({identity for row in rows for identity in row['source_instance_ids']}) == sum(len(row['source_instance_ids']) for row in rows),
            'authored_interaction_duplicate_identity', 'Every declared source instance has one witness')
    pairs = {}
    for row in rows: pairs.setdefault(tuple(row['parts']), []).append(row)
    require(all(len(group) == 1 or all(x.get('pair_scope') == 'source_instance_region' for x in group) for group in pairs.values()),
            'authored_interaction_duplicate_pair', 'Repeated pairs require distinct source-instance regions')
    if profile['model_id'] == 'ear':
        require(len(rows)==26 and {tuple(x['parts']) for x in rows} == set(ear_embedding_pairs()), 'authored_ear_pair_inventory_changed', 'All 26 source-declared pairs required')
    if profile['model_id'] == 'compact_bone':
        require(len(rows) == 1 and rows[0]['parts'] == ['Osteoclasts (Howship lacunae)', 'Osteoclast nuclei'] and
                len(rows[0]['owners']) == 15 and len(rows[0]['host_instance_ids']) == 3,
                'authored_bone_inventory_changed', 'Exactly three source osteoclasts and fifteen nuclei')
    if profile['model_id'] == 'male_reproductive':
        expected = {'Spermatogonia':12, 'Primary spermatocytes':12, 'Secondary spermatocytes':3, 'Spermatids':16}
        require(len(rows) == 43 and all(row['parts'][1] == 'Sertoli (sustentacular) cells' and
                row.get('pair_scope') == 'source_instance_region' for row in rows) and
                {name:sum(row['parts'][0] == name for row in rows) for name in expected} == expected,
                'authored_male_inventory_changed', 'Exact 43 source-declared germ-cell instances')
    if profile['model_id'] == 'female_reproductive':
        require(all(row['parts'] == ['Ampullary ciliated cells (sampled patch)', 'Ampullary cilia (enlarged samples)'] and
                row.get('pair_scope') == 'source_instance_region' for row in rows),
                'authored_female_inventory_changed', 'Source-local apical cilium roots only')
    if profile['model_id']=='lymph_node':
        require(len(rows)==7 and all(row['parts']==(['Efferent lymphatic vessel' if i==0 else 'Afferent lymphatic vessels','Lymphatic valves']) and
            row['source_instance_ids']==['ln:valves:'+str(i)] and row.get('pair_scope')=='source_instance_region' and
            row.get('source_rule',{}).get('source_unit')=='ln:valves:'+str(i) for i,row in enumerate(rows)),
            'authored_lymph_node_inventory_changed','Exact first efferent and six authored afferent cusp clusters')
    # Every occurrence of a Part must bind the same full source arrays.
    known = {}
    for row in rows:
        for name in row['parts']:
            record = (row['source_part_references'][name], row['source_part_array_sha256'][name],
                      row['native_part_indices'][name], row['source_native_writer_capture'], row['source_index_encoding'])
            require(name not in known or known[name] == record, 'authored_interaction_source_identity_conflict', name)
            known[name] = record
    return known

def _groups(rows):
    remaining = set(n for row in rows for n in row['parts']); result = []
    while remaining:
        group = {min(remaining)}; changed = True
        while changed:
            old = set(group)
            for row in rows:
                if group & set(row['parts']): group.update(row['parts'])
            changed = old != group
        remaining -= group; result.append(sorted(group))
    return result

def validate_projection_envelope(proof, profile, rows):
    """Check exact material inventory and proof semantics with stdlib only."""
    validate_inventory(rows, profile)
    require(proof.get('schema') == PROOF_SCHEMA and proof.get('adapter_id') == ADAPTER_ID and
            proof.get('adapter_sha256') == ADAPTER_SHA256 and proof.get('model_id') == profile['model_id'] and
            proof.get('declarations') == rows and proof.get('declarations_sha256') == object_hash(rows) and
            proof.get('original_profile_sha256') == object_hash(profile) and
            proof.get('original_selector_order') == profile['expected_parts'] and
            proof.get('source_material_excluded') is False and proof.get('anatomical_qualification') is False and
            proof.get('obstacle_semantics') == 'exact occupied union of source-declared immutable members',
            'authored_projection_proof_changed', profile['model_id'])
    for key in ('pre_payload_sha256','source_build_sha256','source_receipt_sha256'):
        _hash(proof.get('source_bindings',{}).get(key), key)
    groups = _groups(rows); records = proof.get('groups', [])
    require(len(records) == len(groups), 'authored_projection_groups_missing', profile['model_id'])
    replacement = {}
    for i, (group, record) in enumerate(zip(groups, records)):
        name = '__authored_occupied_union_' + str(i)
        require(record.get('name') == name and record.get('members') == group and
                record.get('occupied_union_identity',{}).get('name') == name,
                'authored_projection_group_members_changed', name)
        for key in ('metadata_sha256','arrays_sha256'): _hash(record['occupied_union_identity'].get(key), name)
        for member in group: replacement[member] = name
    expected = []; seen = set()
    for name in profile['expected_parts']:
        projected = replacement.get(name, name)
        if projected not in seen: expected.append(projected); seen.add(projected)
    require(proof.get('projected_selector_order') == expected and
            [row.get('name') for row in proof.get('participant_arrays',[])] ==
            [name for name in profile['expected_parts'] if name in replacement],
            'authored_projection_inventory_changed', profile['model_id'])
    for row in proof['participant_arrays']:
        for key in ('metadata_sha256','arrays_sha256'): _hash(row.get(key), row['name'])
    _hash(proof.get('original_metadata_sha256'), 'original metadata')
    return proof

ANCESTRY_SCHEMA='ae.source-nested-owner-link.v1'

ANCESTRY_METHOD='exact_source_child_i_intersection_authored_germ_i_sertoli_intersection'

def validate_ancestry_links(profile,root=None):
    links=profile['final_microrefine'].get('source_nested_owner_links',[])
    if not links:return []
    model=profile['model_id'];require(model in {'male_reproductive','synthetic','fixture'},'authored_ancestry_model_unsupported',model)
    interactions={row['witness_id']:row for row in profile['final_microrefine']['authored_interactions']}
    owners={row['witness_id']:row for row in profile['final_microrefine']['additional_checks']['cell_ownership']}
    identities=set()
    for link in links:
        detail=str(link.get('child_id'))
        require(link.get('schema')==ANCESTRY_SCHEMA and link.get('model_id')==model and link.get('expected_intersection_method')==ANCESTRY_METHOD and
            link.get('full_ancestor_enclosure_asserted') is False and link.get('collision_waiver') is False and
            {link.get('child'),link.get('host'),link.get('ancestor_part')}<=set(profile['immutable_geometry_parts']),
            'authored_ancestry_scope_invalid',detail)
        source=link.get('source');require(source in profile['final_microrefine']['source_hashes'] and
            link.get('source_sha256')==profile['final_microrefine']['source_hashes'][source],'authored_ancestry_source_unbound',detail)
        interaction=interactions.get(link.get('interaction_witness_id'));owner_row=owners.get(link.get('cell_ownership_witness_id'))
        require(interaction and owner_row and interaction['parts']==[link['host'],link['ancestor_part']] and
            link.get('interaction_instance_id') in interaction['source_instance_ids'] and
            link.get('source_intersection_reference')==interaction['source_intersection_reference'] and
            owner_row['child']==link['child'] and link['child_references']==owner_row['child_references'] and link['host_references']==owner_row['host_references'],
            'authored_ancestry_reference_join_changed',detail)
        matching=[row for row in owner_row['owners'] if row['child_id']==link['child_id']]
        require(len(matching)==1 and all(matching[0].get(key)==link.get(key) for key in ('child_id','host_id','child_reference_index','host_reference_index')) and
            matching[0].get('host_part',owner_row['host'])==link['host'],'authored_ancestry_owner_join_changed',detail)
        identity=(link['child'],link['child_id']);require(identity not in identities,'authored_ancestry_duplicate_child',detail);identities.add(identity)
        for key in ('source_child_part_reference','source_live_final_buffer_capture','source_native_metadata_capture'):
            require(isinstance(link.get(key),dict),'authored_ancestry_source_capture_missing',key)
            require(root is None,'external_source_resolution_forbidden',key)
        if model=='male_reproductive':
            require(link['child']=='Germ cell nuclei' and link['ancestor_part']=='Sertoli (sustentacular) cells' and source=='baseline/app/micro/male.py' and
                link['child_id']==link['host_id']+':nucleus' and link['interaction_instance_id']==link['host_id'] and
                link['interaction_witness_id']=='male_reproductive:authored:'+link['host_id'] and
                link['cell_ownership_witness_id']=='male_reproductive:owner:Germ cell nuclei' and
                {(row.get('line_start'),row.get('line_end'),row.get('source')) for row in link.get('source_citations',[])}==
                {(1198,1214,source),(1238,1260,source)},'authored_male_ancestry_identity_changed',detail)
    if model=='male_reproductive':
        require(len(links)==43 and {x['interaction_witness_id'] for x in links}==set(interactions) and
            {x['child_id'] for x in links}=={x['child_id'] for x in owners['male_reproductive:owner:Germ cell nuclei']['owners']},
            'authored_male_ancestry_inventory_changed','Exact 43 source nuclear owners')
    return links

def ancestry_pairs(profile):
    return {frozenset((x['child'],x['ancestor_part'])) for x in validate_ancestry_links(profile)}

def validate_ancestry_envelope(profile,report):
    links=validate_ancestry_links(profile);checks=report.get('source_nested_owner_checks',[]);pair_checks=report.get('source_nested_owner_pair_checks',[])
    require(len(checks)==len(links),'authored_ancestry_check_coverage_changed',profile['model_id'])
    for result,link in zip(checks,links):
        require(all(result.get(key)==link[key] for key in ('child_id','host_id','interaction_instance_id','interaction_witness_id','cell_ownership_witness_id')) and
            result.get('link_sha256')==object_hash(link) and result.get('expected_intersection_method')==ANCESTRY_METHOD and result.get('status')=='passed' and
            result.get('immutable_source_child_arrays_exact') is True and result.get('full_ancestor_enclosure_asserted') is False and result.get('collision_waiver') is False and
            finite(result.get('expected_intersection_volume'),minimum=0) and finite(result.get('roundoff_volume_allowance'),positive=True) and
            finite(result.get('source_child_outside_parent_volume'),minimum=0,maximum=result['roundoff_volume_allowance']),
            'authored_ancestry_source_result_changed',link['child_id'])
    groups={}
    for link in links:groups.setdefault((link['child'],link['ancestor_part']),[]).append(link)
    require(len(pair_checks)==len(groups),'authored_ancestry_pair_coverage_changed',profile['model_id'])
    for result,(pair,group) in zip(pair_checks,groups.items()):
        require(result.get('parts')==list(pair) and result.get('link_sha256')==[object_hash(x) for x in group] and result.get('status')=='passed' and
            finite(result.get('roundoff_volume_allowance'),positive=True) and all(finite(result.get(key),minimum=0,maximum=result['roundoff_volume_allowance']) for key in
            ('missing_source_intersection_volume','added_source_intersection_volume')) and all(finite(result.get(key),minimum=0) for key in
            ('actual_intersection_volume','expected_intersection_volume')),'authored_ancestry_pair_measurement_changed',str(pair))
    return report

def participants(rows):return {n for row in rows for n in row['parts']}

def selectors(row,kind):
    if kind=='containment':return list(dict.fromkeys([row['host'],row['child']]+row.get('host_candidates',[])))
    return row.get('parts',[row.get('part')])

def prepare(profile):
    """Move touching semantics into a strict saved lane; no repair is waived."""
    rows=profile['final_microrefine']['authored_interactions'];members=participants(rows)
    immutable=set(profile['immutable_geometry_parts']);base=copy.deepcopy(profile)
    moved={'containment':[],'continuity':[],'lumen_checks':[],'layer_measurements':[],'lumen_exclusions':[]}
    for kind in ('containment','continuity'):
        kept=[]
        for row in profile.get(kind,[]):
            names=set(selectors(row,kind))
            if names & members:
                require(names<=immutable,'authored_mutable_relationship_transport_unsupported',kind+':'+str(sorted(names-immutable)))
                if kind=='containment':
                    refs=[x for x in profile['final_microrefine']['additional_checks']['cell_ownership'] if x['child']==row['child'] and
                        row['host'] in x.get('hosts',[x['host']])]
                    require(refs,'authored_containment_source_owner_witness_missing',row['child'])
                else:
                    refs=[x for x in profile['final_microrefine']['additional_checks']['contacts'] if x['witness_id']==row['name']]
                    require(refs,'authored_continuity_source_interface_missing',row['name'])
                moved[kind].append(copy.deepcopy(row))
            else:kept.append(copy.deepcopy(row))
        base[kind]=kept
    spec=base.get('independent_validation',{})
    for kind in ('lumen_checks','layer_measurements','lumen_exclusions'):
        kept=[]
        for row in profile.get('independent_validation',{}).get(kind,[]):
            names=set(selectors(row,kind))-{None}
            if names & members:
                require(names<=immutable,'authored_mutable_lumen_or_layer_transport_unsupported',kind)
                moved[kind].append(copy.deepcopy(row))
            else:kept.append(copy.deepcopy(row))
        if kind in spec:spec[kind]=kept
    if moved['lumen_checks'] and not spec.get('lumen_checks'):
        spec['lumen_status']='not_applicable'
        spec['lumen_reason']='Projected-engine wall selectors are absent; all original required lumen checks execute in the independent saved-original-selector lane'
    return base,dict(schema=RELATIONSHIP_SCHEMA,model_id=profile['model_id'],original_profile_sha256=object_hash(profile),
        projection_base_profile_sha256=object_hash(base),transported=moved,
        semantics='Saved original selectors certify original relationships; projected union constraints certify conservative occupancy only',
        immutable_source_relationships_required=True)

def map_engine(projected,proof,transport):
    mapping={member:group['name'] for group in proof['groups'] for member in group['members']}
    engine=copy.deepcopy(projected);shadow=[]
    for row in transport['transported']['containment']:
        mapped=copy.deepcopy(row);mapped['host']=mapping.get(row['host'],row['host']);mapped['child']=mapping.get(row['child'],row['child'])
        if 'host_candidates' in mapped:mapped['host_candidates']=list(dict.fromkeys(mapping.get(n,n) for n in row['host_candidates']))
        if mapped['host']==mapped['child']:
            shadow.append(dict(original=row,engine_relation=None,reason='Both unchanged members occupy the same exact immutable union; original identity remains independently checked'))
        else:
            mapped['reason']='Conservative immutable occupied-union constraint; exact original source parent identity is checked in saved-original-selector lane'
            engine['containment'].append(mapped);shadow.append(dict(original=row,engine_relation=mapped,reason=mapped['reason']))
    transport=copy.deepcopy(transport);transport['engine_containment_transport']=shadow
    transport['projected_profile_sha256']=object_hash(engine)
    return engine,transport

def reconstructed_engine_profile(original,proof,input_sha256):
    """Pure-stdlib exact reconstruction of frozen helper's profile projection."""
    base,transport=prepare(original);members=participants(original['final_microrefine']['authored_interactions'])
    projected=copy.deepcopy(base);projected['expected_parts']=proof['projected_selector_order']
    grouped={group['name']:group['members'] for group in proof['groups']}
    projected['ownership_priority']={name:min(original['ownership_priority'][member] for member in grouped[name]) if name in grouped else original['ownership_priority'][name]
        for name in projected['expected_parts']}
    for key in ('continuous_matrix_parts','preserve_unit_parts','debris_cleanup_parts','convex_repair_parts','cell_partition_parts','immutable_geometry_parts'):
        projected[key]=[name for name in base.get(key,[]) if name not in members]
    projected['immutable_geometry_parts']+=list(grouped)
    for key in ('smoothing','vertex_color_transfer','boundary_fit_max_loss'):
        if key in projected:projected[key]={name:value for name,value in base[key].items() if name not in members}
    projected,transport=map_engine(projected,proof,transport)
    projected['readiness']['source_sha256']=input_sha256
    transport['projected_profile_sha256']=object_hash(projected)
    return base,projected,transport

def validate_saved_envelope(profile,report,rows,*,saved_sha256,proof,base,transport):
    """Pure-stdlib exact pair/relationship coverage; actual arrays checked by store."""
    validate_projection_envelope(proof,base,rows)
    require(report.get('schema')=='ae.authored-interaction-saved-lane.v1' and report.get('model_id')==profile['model_id'] and
        report.get('status')=='passed' and report.get('read_only') is True and report.get('input_sha256')==saved_sha256 and
        report.get('declarations_sha256')==object_hash(rows) and report.get('relationship_transport_sha256')==object_hash(transport) and
        report.get('projection_proof_sha256')==object_hash(proof) and report.get('pre_scope') is False and
        report.get('all_material_pairs_classified') is True and report.get('source_material_excluded') is False and report.get('anatomical_qualification') is False,
        'authored_saved_lane_envelope_unbound',profile['model_id'])
    # All actual material pairs are separately classified, including declared
    # source containment. Never manufacture zero-volume rows to appease a
    # validator whose scope did not originally include occupied containment.
    material=[name for name in profile['expected_parts'] if name not in {r['part'] for r in profile['preserved_representations']}]
    validate_ancestry_envelope(profile,report)
    authored={frozenset(row['parts']) for row in rows};owned=containment_pairs(profile);nested=ancestry_pairs(profile)
    expected=[]
    for a,b in itertools.combinations(material,2):
        kind='source_authored_interaction' if frozenset((a,b)) in authored else ('source_owned_containment' if frozenset((a,b)) in owned else
            ('source_nested_owner_ancestry' if frozenset((a,b)) in nested else 'undeclared_disjoint_material'))
        expected.append((a,b,kind))
    actual=report.get('pair_checks',[])
    require(len(actual)==len(expected) and all(row.get('parts')==[a,b] and row.get('kind')==kind and row.get('status')=='passed' and
        finite(row.get('intersection_volume'),minimum=0) and (kind!='undeclared_disjoint_material' or row['intersection_volume']==0)
        for row,(a,b,kind) in zip(actual,expected)),'authored_saved_pair_coverage_changed',profile['model_id'])
    require(report.get('original_selector_order')==profile['expected_parts'] and report.get('material_selector_order')==material and
        report.get('self_checks')==[dict(part=name,status='passed') for name in material],
        'authored_saved_surface_coverage_changed',profile['model_id'])
    checks=report.get('checks',[])
    require(len(checks)==len(rows),'authored_saved_declarations_omitted',profile['model_id'])
    for result,row in zip(checks,rows):
        allowance=row['source_intersection_volume']*1e-6
        require(result.get('witness_id')==row['witness_id'] and result.get('kind')==row['kind'] and result.get('status')=='passed' and
            result.get('semantics')==SEMANTICS[row['kind']] and result.get('declaration_sha256')==object_hash(row) and
            result.get('source_instance_ids')==row['source_instance_ids'] and result.get('immutable_source_arrays_exact') is True and
            result.get('source_intersection_volume')==row['source_intersection_volume'] and result.get('roundoff_volume_allowance')==allowance and
            finite(result.get('measured_intersection_volume'),positive=True) and abs(result['measured_intersection_volume']-row['source_intersection_volume'])<=allowance and
            result['measured_intersection_volume']+allowance>=row['minimum_intersection_volume'] and
            all(finite(result.get(key),minimum=0,maximum=allowance) for key in ('missing_reference_volume','added_reference_volume','out_of_region_volume')),
            'authored_saved_source_measurements_changed',row['witness_id'])
        if row['kind']==AFFILIATION:
            owners=result.get('owners',[])
            require(len(owners)==len(row['owners']) and all(all(owner.get(key)==value for key,value in declared.items()) and
                finite(owner.get('attachment_volume'),positive=True) and finite(owner.get('exposed_volume'),positive=True) and owner.get('full_enclosure_asserted') is False
                for owner,declared in zip(owners,row['owners'])),'authored_saved_exposed_identity_changed',row['witness_id'])
    declared_pairs={}
    for row in rows:declared_pairs.setdefault(tuple(row['parts']),[]).append(row)
    measured=report.get('declared_pair_checks',[])
    require(len(measured)==len(declared_pairs),'authored_saved_pair_scope_omitted',profile['model_id'])
    for result,(pair,group) in zip(measured,declared_pairs.items()):
        allowance=sum(row['source_intersection_volume'] for row in group)*1e-6
        require(result.get('parts')==list(pair) and result.get('status')=='passed' and result.get('witness_ids')==[row['witness_id'] for row in group] and
            result.get('roundoff_volume_allowance')==allowance and all(finite(result.get(key),minimum=0,maximum=allowance) for key in
            ('outside_authored_intersections_volume','missing_authored_intersections_volume')),'authored_saved_pair_scope_changed',str(pair))
    owned=report.get('source_owned_containment_checks',[])
    require([row.get('witness_id') for row in owned]==[row['witness_id'] for row in profile['final_microrefine']['additional_checks']['cell_ownership']] and
        all(row.get('status')=='passed' for row in owned),
        'authored_source_containment_saved_checks_failed',profile['model_id'])
    return report

def containment_pairs(profile):
    return {frozenset((host,row['child'])) for row in profile.get('containment',[]) for host in row.get('host_candidates',[row['host']])}
