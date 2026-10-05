"""Truthful technical Pre scope and bounded baseline findings, separate from Post."""
from __future__ import annotations
import math
from types import MappingProxyType
from .security import digest,exact,read_json,require,short_text

BASELINE_ROLES={'pre_baseline_report':frozenset({('json','ae.saved-pre-policy-validation.v1')})}
PRE_SCOPE='source_technical_correspondence'
POST_SCOPE='strict_post_acceptance'
OPERATIONS={
  'self_intersection':frozenset({'repair_self_intersections'}),
  'containment':frozenset({'repair_containment'}),
  'contact':frozenset({'repair_collisions','repair_precision_contacts'}),
}


def immutable(value):
    if isinstance(value,dict):return MappingProxyType({k:immutable(v) for k,v in value.items()})
    if isinstance(value,list):return tuple(immutable(v) for v in value)
    return value


def validate_scope(receipt,variant,assets,*,model_id,primary_sha256,source_build_sha256):
    require(receipt['scope']==(PRE_SCOPE if variant=='pre' else POST_SCOPE),'validation scope must distinguish technical Pre from strict Post acceptance')
    summary=receipt['baseline_defects']
    if variant=='post':
        require(summary is None,'Post acceptance cannot substitute a Pre baseline report')
        return None
    exact(summary,{'schema','source_correspondence_passed','indispensable_construction_gates_passed','repair_candidate_bound','findings','report_sha256'},'Pre baseline defects summary')
    require(summary['schema']=='ae.pre-baseline-defects.v1','unsupported Pre baseline summary schema')
    require(summary['source_correspondence_passed'] is True and summary['indispensable_construction_gates_passed'] is True and summary['repair_candidate_bound'] is True,'critical source/construction/correspondence failure or unbounded Pre repair')
    digest(summary['report_sha256'],'Pre baseline report identity')
    findings=summary['findings'];require(isinstance(findings,list) and len(findings)<=4096,'baseline finding count invalid')
    for f in findings:
        exact(f,{'kind','selectors','status','measured','repair_bound'},'bounded Pre finding')
        require(isinstance(f['kind'],str) and f['kind'] in OPERATIONS and f['status']=='bounded_repair_candidate','unsupported/unbounded baseline finding')
        names=f['selectors'];require(isinstance(names,list) and 0<len(names)<=4096 and all(isinstance(n,str) and 0<len(n)<=256 for n in names) and len(names)==len(set(names)),'baseline exact selector inventory missing/ambiguous')
        measured=f['measured'];require(isinstance(measured,dict) and 0<len(measured)<=64,'baseline source measurements missing')
        for k,v in measured.items():
            short_text(k,'baseline metric',128);require(type(v) in (int,float) and math.isfinite(v),'invalid baseline measurement')
        bound=exact(f['repair_bound'],{'operation','source_profile_bounds'},'source-bound repair policy')
        require(isinstance(bound['operation'],str) and bound['operation'] in OPERATIONS[f['kind']],'repair operation is outside supplied original algorithm')
        limits=bound['source_profile_bounds'];require(isinstance(limits,dict) and 0<len(limits)<=64,'explicit source repair bounds missing')
        for k,v in limits.items():
            short_text(k,'source repair bound',128);require(type(v) in (int,float) and math.isfinite(v) and v>=0,'invalid explicit source repair bound')
    # Nonzero bounded targets are deliberately NOT geometry acceptance failures.
    # The raw report preserves actual technical gates and baseline measurements.
    report_asset=assets.get('pre_baseline_report')
    require(report_asset is not None and report_asset.sha256==summary['report_sha256'],'hashbound raw Pre technical/baseline report missing')
    report=read_json(report_asset.path)
    require(isinstance(report,dict) and report.get('schema')=='ae.saved-pre-policy-validation.v1' and report.get('model_id')==model_id and report.get('status')=='passed' and report.get('read_only') is True,'Pre technical report failed/wrong schema or model')
    require(report.get('input_sha256')==primary_sha256 and report.get('source_build_sha256')==source_build_sha256,'Pre baseline report is not for exact new source-improved payload')
    require(report.get('scope')==PRE_SCOPE or report.get('qualification_scope')=='source_identity_correspondence_and_bounded_repair_candidate','Pre baseline report must explicitly state technical qualification scope')
    require(report.get('baseline_findings')==findings,'summary does not preserve raw measured baseline findings')
    return immutable(summary)
