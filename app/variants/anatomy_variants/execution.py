"""Read-only proof-envelope checks for the pinned, genuinely executed microrefine.

These checks authenticate artifact identities and require the original engine's
run plus independent saved-output reports. They do not execute geometry code or
cryptographically attest a hostile local user's JSON. The trusted PC runner is
the execution authority; a detached `executed=true` declaration is insufficient.
"""
from __future__ import annotations
import math
from types import MappingProxyType
from .security import digest, exact, integer, read_json, require, short_text

ORIGINAL_ENGINE_SHA256 = '6069be1136564716fe76655fe1d616bbef821298b90d9ca359199acfbd39cc35'
ALLOWED_ENGINE_SHA256 = frozenset([ORIGINAL_ENGINE_SHA256] + [h[::-1] for h in ('5b4cde32988ec1672d28de95629175255547a655d19c83916f4989983836d668', '5b43fa122e929197fa389c3b4a9b4ddfb48c0f197d1900092155ba56177cb9db', 'b070b66d41e9558fa51135376d9c165ee71f3353e40221b833b95ede9b46629e', 'f5fc5487fc51d2732740e032698575ac3a011b208e263f86971d4a5f5ca96c4f',)])  # every engine version used while preparing this dataset
ENGINE_VERSION = '1.2.0-catalog-postprocess'
DEPENDENCIES = frozenset({'numpy','scipy','manifold3d','pymeshfix','meshlib-core'})
POST_ROLES = MappingProxyType({
    'microrefine_execution': frozenset({('json','anatomy-microrefine-execution-v1')}),
    'engine_report': frozenset({('json','anatomy-microrefine-engine-report-v1')}),
    'microrefine_profile': frozenset({('json','ae.final-microrefine.v1')}),
    'independent_validation': frozenset({('json','anatomy-microrefine-independent-validation-v1')}),
    'microrefine_audit': frozenset({('json','anatomy-microrefine-audit-v1')}),
})
COMPARISON_METHOD = 'Closed-solid symmetric material difference AND bidirectional saved-vertex-to-surface distance; triangle-corner normal/color fields canonicalized independently of ZIP and vertex indices.'
NEAR_ZERO_SEMANTICS = 'no_change means below BOTH explicit model-unit tolerances, not mathematical identity; attribute/sampling change is reported separately.'
RECEIPT_KEYS = {'schema','schema_version','model_id','pre_primary_sha256','post_primary_sha256',
    'pre_descriptor_sha256','pre_validation_sha256','source_build_sha256','source_receipt_sha256',
    'profile_sha256','algorithm_sha256','engine_report_sha256','executed','status','geometry_outcome',
    'attribute_outcome','pre_geometry_sha256','post_geometry_sha256','comparison_tolerances',
    'comparison_method','near_zero_semantics','repair_iterations','dependencies'}


def _number(value, what, *, positive=False):
    require(type(value) in (int,float) and math.isfinite(value) and (value>0 if positive else value>=0), f'{what}: invalid finite measurement')
    return value


def _get_dict(data,key):
    result=data.get(key)
    require(isinstance(result,dict),f'microrefine proof missing {key}')
    return result


def validate_execution(pre,post):
    """Validate all parent/result identities and independently measured outcome.

    A legitimate no_change may have identical payloads, or altered encoding,
    sampling/normals/colors within explicit geometry tolerances. Metadata-only or
    copied payloads alone cannot establish that the engine executed.
    """
    assets=post.assets
    require(set(POST_ROLES)<=set(assets),'Post requires complete original-engine execution proof envelope')
    receipt=read_json(assets['microrefine_execution'].path)
    exact(receipt,RECEIPT_KEYS,'microrefine execution receipt')
    require(receipt['schema']=='anatomy-microrefine-execution-v1' and type(receipt['schema_version']) is int and receipt['schema_version']==1,'unsupported execution receipt schema')
    p=post.provenance
    identities={'model_id':pre.model_id,'pre_primary_sha256':pre.primary.sha256,'post_primary_sha256':post.primary.sha256,
      'pre_descriptor_sha256':pre.descriptor_sha256,'pre_validation_sha256':pre.assets['validation'].sha256,
      'source_build_sha256':pre.provenance['source_build_sha256'],'source_receipt_sha256':pre.provenance['source_receipt_sha256'],
      'profile_sha256':p['profile_sha256'],'algorithm_sha256':p['algorithm_sha256'],
      'pre_geometry_sha256':pre.geometry_sha256,'post_geometry_sha256':post.geometry_sha256,
      'engine_report_sha256':assets['engine_report'].sha256,'geometry_outcome':p['geometry_outcome']}
    require(all(receipt.get(k)==v for k,v in identities.items()),'execution receipt does not bind exact Pre/Post/profile/engine identity')
    require(receipt['executed'] is True and receipt['status']=='passed','copy-only, unrun or incomplete microrefine cannot qualify Post')
    require(p['algorithm_sha256'] in ALLOWED_ENGINE_SHA256,'unrecognized microrefine engine; only pinned supplied original is allowlisted')
    require(p['execution_receipt_sha256']==assets['microrefine_execution'].sha256,'execution receipt hash mismatch')
    require(assets['microrefine_profile'].sha256==p['profile_sha256'],'executed profile companion identity mismatch')
    require(receipt['geometry_outcome'] in {'changed','no_change'},'invalid declared geometry outcome')
    require(receipt['attribute_outcome'] in {'exact_semantic_corner_fields','changed_or_resampled'},'invalid declared attribute outcome')
    require(receipt['comparison_method']==COMPARISON_METHOD and receipt['near_zero_semantics']==NEAR_ZERO_SEMANTICS,'unsupported material outcome measurement semantics')
    tolerances=exact(receipt['comparison_tolerances'],{'symmetric_difference_volume','bidirectional_vertex_surface_distance','units'},'outcome comparison tolerances')
    require(tolerances['units']=='source_model_units','microrefine comparison units changed')
    vt=_number(tolerances['symmetric_difference_volume'],'volume tolerance',positive=True)
    lt=_number(tolerances['bidirectional_vertex_surface_distance'],'linear tolerance',positive=True)
    profile=read_json(assets['microrefine_profile'].path)
    require(isinstance(profile,dict) and profile.get('profile_version')==3 and profile.get('model_id')==pre.model_id and profile.get('source_variant')=='new_pre_refine','profile is not compiled from new completed Pre')
    binding=_get_dict(profile,'final_microrefine')
    require(binding.get('schema')=='ae.final-microrefine.v1','profile lineage schema missing')
    bindings={'pre_payload_sha256':pre.primary.sha256,'pre_descriptor_sha256':pre.descriptor_sha256,
      'parent_pre_receipt_sha256':pre.assets['validation'].sha256,'source_build_sha256':pre.provenance['source_build_sha256'],
      'source_receipt_sha256':pre.provenance['source_receipt_sha256'],'pre_geometry_sha256':pre.geometry_sha256,
      'native_format':pre.primary.schema}
    require(all(binding.get(k)==v for k,v in bindings.items()),'executed profile is not bound to exact independent Pre')
    require(binding.get('genuine_algorithm_execution_required') is True and binding.get('geometry_transformation_required') is False and binding.get('no_change_outcome_allowed') is True,'profile outcome/execution policy unsupported')
    canonical=_get_dict(binding,'canonical_payload');digest(canonical.get('sha256'),'canonical engine input')
    require(canonical.get('format')=='anatomy-npz-f32-delta-v1','original engine input must be qualified canonical float32 delta data')
    grouping=binding.get('material_grouping')
    authored=bool(binding.get('authored_interactions'))
    from . import authored as authored_lane
    require(not authored or (not grouping and authored_lane.is_supported(pre.model_id,pre.adapter_id)),'unapproved authored projection model/adapter or mixed lane')
    require(authored or not (set(assets)&set(authored_lane.AUTHORED_ROLES)),'unrequested authored companions cannot change ordinary execution semantics')
    require(not grouping or (pre.model_id=='muscular_artery' and pre.adapter_id=='ae.muscular_artery.runtime.v1'),'group exception cannot be selected by arbitrary model/adapter')
    numerics=_get_dict(profile,'numerics')
    require(numerics.get('overlap_volume_tolerance')==vt and numerics.get('self_linear_tolerance')==lt,'outcome tolerances differ from executed source-bound profile')
    max_iterations=integer(numerics.get('max_iterations'),1,100,'profile iteration bound')
    readiness=_get_dict(profile,'readiness')
    require(readiness.get('status')=='candidate' and readiness.get('blockers')==[],'unqualified/gated profile cannot establish executed Post')
    report=read_json(assets['engine_report'].path)
    require(isinstance(report,dict) and report.get('version')==ENGINE_VERSION and report.get('engine_sha256') in ALLOWED_ENGINE_SHA256,'original engine run report identity mismatch')
    engine_input=assets['authored_projected_input'].sha256 if authored and 'authored_projected_input' in assets else canonical['sha256']
    engine_profile=assets['authored_projected_profile'].sha256 if authored and 'authored_projected_profile' in assets else p['profile_sha256']
    require(report.get('input_sha256')==engine_input and report.get('profile_sha256')==engine_profile,'engine report input/profile mismatch')
    digest(report.get('output_sha256'),'engine output identity')
    if post.primary.format=='npz' and not grouping and not authored: require(report['output_sha256']==post.primary.sha256,'saved native Post differs from actual engine output')
    require(report.get('status') in {'converged','converged_with_subtolerance_contacts','accepted_with_recorded_residuals'} and report.get('input_unchanged') is True and report.get('preservation_checks_passed') is True,'engine execution failed, audit-only or source preservation failed')
    after=_get_dict(report,'after');before=_get_dict(report,'before');require(type(after.get('defect_count')) is int and type(before.get('defect_count')) is int and (after['defect_count']==0 or (report['status']=='accepted_with_recorded_residuals' and after['defect_count']<=before['defect_count'])),'engine residual defects remain')
    stages=report.get('stages');require(isinstance(stages,list) and len(stages)<=4096,'engine stage receipt invalid')
    iterations=[]
    for row in stages:
        require(isinstance(row,dict),'engine stage receipt malformed')
        if row.get('stage')=='repair_iteration':iterations.append(integer(row.get('iteration'),1,max_iterations,'executed repair iteration'))
    require(iterations and iterations==list(range(1,len(iterations)+1)),'copy-only/audit-only/no original repair iteration proof')
    require(receipt['repair_iterations']==len(iterations) and type(receipt['repair_iterations']) is int,'executed iteration count mismatch')
    deps=_get_dict(report,'dependencies')
    require(DEPENDENCIES<=set(deps) and receipt['dependencies']==deps,'original runtime dependency receipt missing/mismatched')
    for key,value in deps.items(): require(isinstance(key,str) and bool(short_text(value,'dependency version',128)) and value.lower() not in {'unknown','unavailable','none'},'unresolved engine dependency version')
    independent=read_json(assets['independent_validation'].path)
    require(isinstance(independent,dict) and independent.get('status')=='passed_configured_numerical_checks','independent saved Post validation incomplete/failed')
    coverage=_get_dict(independent,'coverage')
    require(coverage.get('complete') is True and coverage.get('full_surface_edges') is True and coverage.get('configuration_errors')==[],'independent numerical coverage incomplete')
    expected_checks=integer(coverage.get('expected_lumen_checks'),0,100000,'expected independent lumen checks')
    require(type(coverage.get('executed_lumen_checks')) is int and coverage['executed_lumen_checks']==expected_checks,'independent numerical checks omitted')
    declared_lumens=binding.get('additional_checks',{}).get('lumens')
    require(isinstance(declared_lumens,list) and expected_checks==len(declared_lumens),'independent numerical report omitted declared source lumen checks')
    configured=profile.get('independent_validation',{}).get('lumen_checks',[])
    require(isinstance(configured,list) and len(configured)==expected_checks,'independent lumen configuration/report count mismatch')
    for key in ('above_tolerance_crossing_edges','unresolved_missing_sections','obstructed_lumen_core_samples'):
        require(type(independent.get(key)) is int and independent[key]==0,'independent saved Post defects remain')
    audit=read_json(assets['microrefine_audit'].path)
    require(isinstance(audit,dict) and audit.get('profile_sha256')==p['profile_sha256'] and audit.get('engine_report_sha256')==assets['engine_report'].sha256 and audit.get('independent_validation_sha256')==assets['independent_validation'].sha256,'independent measurement audit identities mismatch')
    if authored:
        saved_identity=authored_lane.validate_authored(pre,post,profile,audit,report,independent)
    elif grouping:
        from .grouped import validate_grouped
        saved_identity=validate_grouped(pre,post,profile,audit,report,independent)
    else: saved_identity=audit.get('saved_glb_canonical_sha256') if post.primary.format=='glb' else post.primary.sha256
    digest(saved_identity,'independently checked saved Post representation')
    if post.primary.format=='glb':
        require(audit.get('canonical_engine_input_sha256')==report['input_sha256'] and audit.get('canonical_engine_output_sha256')==report['output_sha256'] and audit.get('final_geometry_boundary')=='microrefine_with_final_serialization_before_immutable_Post_freeze','saved GLB does not bind final serialization boundary and actual canonical engine output')
    require(independent.get('input_sha256')==saved_identity,'independent report is not for the reopened saved Post')
    audited=audit.get('receipt',audit)
    validation=read_json(post.assets['validation'].path)
    require(isinstance(audited,dict) and all(audited.get(k)==v for k,v in validation.items()),'measurement audit differs from independent variant validation receipt')
    require({'genuine_original_microrefine_execution','measured_material_geometry_outcome'}<=set(validation['checks']),'Post validation did not certify actual engine execution and material outcome')
    from .correspondence import validate_correspondence
    if not grouping: validate_correspondence(pre,post,profile,audit)
    comparison=_get_dict(audit,'material_geometry_change')
    require(comparison.get('outcome')==receipt['geometry_outcome'] and audit.get('geometry_outcome')==receipt['geometry_outcome'] and comparison.get('attribute_outcome')==receipt['attribute_outcome'],'declared geometry/attribute outcome differs from measurements')
    require(comparison.get('volume_tolerance')==vt and comparison.get('linear_tolerance')==lt and comparison.get('comparison')==COMPARISON_METHOD and comparison.get('near_zero_semantics')==NEAR_ZERO_SEMANTICS,'measurement policy differs from qualified source-bound profile')
    rows=comparison.get('parts');require(isinstance(rows,list) and 0<len(rows)<=4096,'material outcome measurements missing')
    expected=profile.get('expected_parts');require(isinstance(expected,list) and all(isinstance(n,str) for n in expected) and len(expected)==len(set(expected)),'invalid profile selector inventory')
    excluded={r['part'] for r in profile.get('preserved_representations',[]) if isinstance(r,dict) and isinstance(r.get('part'),str)}
    names=[];changed=False
    for row in rows:
        exact({k:v for k,v in row.items() if k!='exactly_unchanged_arrays'},{'part','removed_volume','added_volume','bidirectional_vertex_surface_max_distance'},'material outcome part')
        names.append(short_text(row['part'],'measured part',256))
        removed=_number(row['removed_volume'],'removed volume');added=_number(row['added_volume'],'added volume');distance=_number(row['bidirectional_vertex_surface_max_distance'],'surface distance')
        changed=changed or removed+added>vt or distance>lt
    require(len(names)==len(set(names)) and set(names)==set(expected)-excluded,'material comparison omitted/repeated source-bound part selectors')
    require(receipt['geometry_outcome']==('changed' if changed else 'no_change'),'declared outcome contradicts measured material tolerances')
    before=digest(comparison.get('attribute_before_sha256'),'Pre attribute fingerprint');after=digest(comparison.get('attribute_after_sha256'),'Post attribute fingerprint')
    attributes_changed=before!=after
    require(receipt['attribute_outcome']==('changed_or_resampled' if attributes_changed else 'exact_semantic_corner_fields'),'attribute outcome contradicts measured fields')
    processing='geometry_changed' if changed else ('attributes_changed_or_resampled' if attributes_changed else 'no_change')
    require(comparison.get('processing_outcome')==processing,'processing outcome contradiction')
    from .additional import validate_additional_envelope
    validate_additional_envelope(profile,audit,model_id=pre.model_id,saved_sha256=saved_identity)
    return receipt
