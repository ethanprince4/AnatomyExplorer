"""Serialization helpers for a trusted PC runner. Promotion remains the authority.

The runner must freeze model-changing computation before using these helpers.
No helper renders, exports, mutates geometry, loads an external Python adapter,
or upgrades incomplete/failed receipts to success.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from .security import atomic_json, file_hash, no_symlinks, relative_path, safe_path


def write_json(root,rel,data):
    root=no_symlinks(Path(root))
    path=root.joinpath(*relative_path(rel).parts)
    no_symlinks(path,must_exist=False)
    path.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(path,data)
    sha,size=file_hash(path)
    return {'path':rel,'sha256':sha,'size':size}


def asset(root,role,rel,format,schema):
    sha,size=file_hash(safe_path(root,rel))
    return {'role':role,'path':rel,'format':format,'schema':schema,'sha256':sha,'size':size}


def source_receipt(model_id,source_build_sha256,pre_primary_sha256):
    return {'schema':'anatomy-source-receipt-v1','schema_version':1,'model_id':model_id,'source_build_sha256':source_build_sha256,'primary_sha256':pre_primary_sha256,'stage':'source_improved_complete','completed':True}


def validation_receipt(model_id,variant,primary_sha256,geometry_sha256,source_pre_sha256,checks,*,baseline_defects=None):
    return {'schema':'anatomy-validation-v1','schema_version':1,'model_id':model_id,'variant':variant,'primary_sha256':primary_sha256,'geometry_sha256':geometry_sha256,'source_pre_sha256':source_pre_sha256,'status':'passed','checks':list(checks),'scope':'source_technical_correspondence' if variant=='pre' else 'strict_post_acceptance','baseline_defects':baseline_defects}


def descriptor(model_id,variant,adapter_id,primary,companions,geometry_sha256,provenance):
    return {'schema':'anatomy-variant','schema_version':1,'model_id':model_id,'variant':variant,'adapter_id':adapter_id,'primary':primary,'companions':list(companions),'geometry_sha256':geometry_sha256,'provenance':dict(provenance),'validation':{'status':'passed','receipt_role':'validation'}}


def metadata(name,summary='',targets=None,histology=(),related=(),clinical=(),scale_note='',aliases=()):
    return {'name':name,'summary':summary,'targets':targets or {},'histology':list(histology),'related':list(related),'clinical':[list(c) for c in clinical],'scale_note':scale_note,'aliases':list(aliases)}


def catalog(generation_id,models,required_models):
    return {'schema':'anatomy-variant-catalog','schema_version':1,'generation_id':generation_id,'created_utc':datetime.now(timezone.utc).isoformat(),'required_models':sorted(required_models),'models':list(models)}
