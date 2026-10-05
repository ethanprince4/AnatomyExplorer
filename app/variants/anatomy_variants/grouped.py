"""Fixed muscular protected-material bridge. No generic grouping or mesh repair."""
from __future__ import annotations
import copy
import hashlib
import math
import struct
import zipfile
from .additional import object_hash
from .correspondence import native_decoded_identity
from .formats import _npy_header
from .security import exact,digest,read_json,require,safe_open

ADAPTER_ID='ae.muscular_artery.closed-vasa-wall.v1'
ADAPTER_SHA256='120afe903607ea403a5b558cee84d838e21a677f372ce4f3430834c0f74f4983'
GROUP_NAME='Vasa vasorum (protected closed material group)'
MEMBERS=('Vasa vasorum','Vasa vasorum exchange network','Vasa vasorum venules')
REASON='Preserve authored material/color seams and original patch arrays; mutable repartition is unsupported.'
BOUNDARY='microrefine_with_immutable_source_patch_restoration_before_Post_freeze'
GROUP_ROLES={'grouped_material':frozenset({('json','ae.grouped-material-correspondence.v1')}),'grouped_restoration':frozenset({('json','ae.grouped-material-restoration.v1')}),
 'grouped_engine_output':frozenset({('npz','anatomy-npz-f32-delta-v1')}),'grouped_saved_material':frozenset({('npz','anatomy-npz-f32-delta-v1')})}
PROOF_KEYS={'schema','model_id','adapter_id','mode','group_name','members','source_bindings','source_graph_sha256','original_selector_order','canonical_selector_order','original_metadata_sha256','canonical_metadata_sha256','member_array_identities','closed_group_array_identity','closed_group_oriented_triangles_sha256','closure','source_classifier','protection_reason','mutable_repartition_capability','geometry_moved','faces_capped','pre_payload_sha256','canonical_payload_sha256','source_build_sha256','source_receipt_sha256','canonical_schema','coordinate_units','adapter_sha256'}
RESTORE_KEYS={'schema','model_id','adapter_id','grouping_proof_sha256','group_name','members','protection_reason','geometry_outcome','patch_arrays_byte_exact','oriented_group_triangles_sha256','mutable_repartition_capability','pre_payload_sha256','canonical_payload_sha256','engine_output_sha256','display_payload_sha256','saved_grouped_payload_sha256','adapter_sha256'}


def identities(path):
    meta,rows=native_decoded_identity(path,'anatomy-npz-f32-delta-v1')
    result={}
    for m,r in zip(meta,rows):
        result[m['name']]={k:v for k,v in r.items() if k!='arrays_exact'}
        result[m['name']]['metadata_sha256']=object_hash(m)
    return meta,result


def _geometry(path,names):
    meta,identity=identities(path);positions=[];normals=[];faces=[];offset=0
    require(set(names)<=set(identity),'fixed source wall patches missing')
    with safe_open(path) as raw,zipfile.ZipFile(raw) as z:
        for name in names:
            i=next(i for i,m in enumerate(meta) if m['name']==name)
            vectors=[]
            for k in ('p','n'):
                with z.open(f'{k}{i}.npy') as s:
                    dtype,shape,_,_=_npy_header(s);require(dtype=='<f4' and shape==(identity[name]['vertices'],3),'group source float32 layout lost')
                    require(offset+shape[0]<=5_000_000,'group exact-weld vertex bound exceeded')
                    arr=[]
                    while b:=s.read(1048572):arr.extend(struct.iter_unpack('<3f',b))
                    vectors.append(arr)
            require(all(abs(math.sqrt(sum(v*v for v in n))-1)<=1e-5 for n in vectors[1]),'source group normals not qualified unit vectors')
            positions.extend(vectors[0]);normals.extend(vectors[1]);acc=0;flat=[]
            with z.open(f'i{i}.npy') as s:
                _npy_header(s)
                while b:=s.read(1024*1024):
                    for (d,) in struct.iter_unpack('<i',b):acc+=d;flat.append(acc+offset)
            faces.extend(tuple(flat[j:j+3]) for j in range(0,len(flat),3));offset+=len(vectors[0])
    return meta,identity,positions,normals,faces


def _assemble_identity(path):
    metadata,identity,p,n,faces=_geometry(path,MEMBERS)
    first={}
    for i,v in enumerate(p):first.setdefault(v,i)
    vertices=sorted(first);mapping={v:i for i,v in enumerate(vertices)}
    welded=[tuple(mapping[p[i]] for i in f) for f in faces]
    require(all(len(set(f))==3 for f in welded),'source weld contains degenerate triangles; caps/tolerance weld forbidden')
    edges={};parent=list(range(len(welded)));volumes=[];oriented=[]
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,f in enumerate(welded):
        a,b,c=[vertices[j] for j in f]
        cross=((b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]),(b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
        require(sum(x*x for x in cross)>0,'source group zero-area face')
        points=[a,b,c];oriented.append(min(tuple(points[k:]+points[:k]) for k in range(3)))
        volumes.append((a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6)
        for j in range(3):
            u,v=f[j],f[(j+1)%3];key=(min(u,v),max(u,v));edges.setdefault(key,[]).append((i,u,v))
    require(len(set(oriented))==len(oriented),'duplicate source-owned faces')
    for values in edges.values():
        require(len(values)==2 and values[0][1:]==tuple(reversed(values[1][1:])),'exact source group is open/nonmanifold/inconsistently oriented')
        a,b=find(values[0][0]),find(values[1][0]);parent[b]=a
    shells={}
    for i,v in enumerate(volumes):shells[find(i)]=shells.get(find(i),0)+v
    require(sum(v>0 for v in shells.values())==1 and all(v!=0 for v in shells.values()) and sum(shells.values())>0,'source group does not have one positive material domain')
    h=hashlib.sha256()
    for f in sorted(oriented):
        for v in f:h.update(struct.pack('<3f',*v))
    meta=copy.deepcopy(next(m for m in metadata if m['name']==MEMBERS[0]));meta.update(name=GROUP_NAME,color='#808080',description=REASON)
    def raw_hash(fmt,rows):
        d=hashlib.sha256()
        for row in rows:d.update(struct.pack(fmt,*row))
        return d.hexdigest()
    grouped={'name':GROUP_NAME,'metadata_sha256':object_hash(meta),'positions_sha256':raw_hash('<3f',vertices),
      'normals_sha256':raw_hash('<3f',[n[first[v]] for v in vertices]),'indices_sha256':raw_hash('<3q',welded),
      'colors_sha256':None,'vertices':len(vertices),'triangles':len(welded)}
    metrics={'source_vertices':len(p),'welded_vertices':len(vertices),'triangles':len(welded),'boundary_edges':0,'zero_area_triangles':0,'nonmanifold_edges':0,'material_domains':1,'cavity_shells':sum(v<0 for v in shells.values()),'volume':sum(shells.values())}
    return metadata,identity,meta,grouped,h.hexdigest(),metrics


def validate_grouped(pre,post,profile,audit,report,independent):
    require(pre.model_id==post.model_id=='muscular_artery' and pre.adapter_id==post.adapter_id=='ae.muscular_artery.runtime.v1','grouped exception is muscular-only shipped adapter')
    require(pre.primary.schema==post.primary.schema=='anatomy-npz-f32-delta-v1','group source must be exact float32; no quantized seam tolerance bridge is authorized')
    assets=post.assets;require(set(GROUP_ROLES)|{'canonical_payload'}<=set(assets),'re-openable protected-group payload/proofs missing')
    proof=read_json(assets['grouped_material'].path);restore=read_json(assets['grouped_restoration'].path)
    exact(proof,PROOF_KEYS,'grouped proof');exact(restore,RESTORE_KEYS,'grouped restoration')
    for d,schema in ((proof,'ae.grouped-material-correspondence.v1'),(restore,'ae.grouped-material-restoration.v1')):
        require(d['schema']==schema and d['model_id']=='muscular_artery' and d['adapter_id']==ADAPTER_ID and d['adapter_sha256']==ADAPTER_SHA256 and d['group_name']==GROUP_NAME and d['members']==list(MEMBERS) and d['protection_reason']==REASON and d['mutable_repartition_capability']=='unsupported','unapproved grouping/repartition adapter or protection policy')
    require(proof['mode']=='protected_immutable_source_material' and proof['geometry_moved'] is False and proof['faces_capped'] is False,'mutable/capped/moved grouping forbidden')
    require(proof['coordinate_units']=='source_model_units' and proof['canonical_schema']=='anatomy-npz-f32-delta-v1','group units/schema changed')
    binding=profile['final_microrefine'];require(binding.get('material_grouping',{}).get('sha256')==assets['grouped_material'].sha256==audit.get('material_grouping_sha256') and audit.get('material_grouping')==proof,'group proof/profile/audit mismatch')
    src={'pre_payload_sha256':pre.primary.sha256,'source_build_sha256':pre.provenance['source_build_sha256'],'source_receipt_sha256':pre.provenance['source_receipt_sha256']}
    require(all(proof.get(k)==v for k,v in src.items()) and proof['canonical_payload_sha256']==assets['canonical_payload'].sha256==report['input_sha256'],'group original/canonical source identity mismatch')
    sb=exact(proof['source_bindings'],set(src)|{'classifier_source_sha256','source_graph_file_sha256'},'group source bindings')
    require(all(sb[k]==v for k,v in src.items()) and sb['classifier_source_sha256'] in binding.get('source_hashes',{}).values(),'group classifier is not exact original source pinned code')
    digest(sb['source_graph_file_sha256']);digest(proof['source_graph_sha256'])
    require(proof['source_classifier']=='ordered source graph edge/path samples; scipy cKDTree; float32 face means; all original saved owner labels reproduced','source ownership classifier semantics changed')
    require(GROUP_NAME in profile.get('immutable_geometry_parts',[]) and GROUP_NAME not in {r['part'] for r in profile.get('preserved_representations',[])},'closed group must remain real immutable audited material/obstacle')
    require(restore['grouping_proof_sha256']==object_hash(proof) and restore['geometry_outcome']=='no_change' and restore['patch_arrays_byte_exact'] is True and audit.get('grouped_restoration')==restore and audit.get('grouped_restoration_sha256')==assets['grouped_restoration'].sha256,'restoration proof cannot claim changed group unchanged')
    require(restore['pre_payload_sha256']==pre.primary.sha256 and restore['canonical_payload_sha256']==assets['canonical_payload'].sha256 and restore['display_payload_sha256']==post.primary.sha256,'display/source restoration identity mismatch')
    require(restore['engine_output_sha256']==assets['grouped_engine_output'].sha256==report['output_sha256']==audit.get('canonical_engine_output_sha256') and restore['saved_grouped_payload_sha256']==assets['grouped_saved_material'].sha256==independent.get('input_sha256')==audit.get('saved_material_canonical_sha256'),'actual grouped engine/saved material payload binding mismatch')
    require(audit.get('canonical_engine_input_sha256')==report['input_sha256'] and audit.get('group_adapter_sha256')==ADAPTER_SHA256 and audit.get('final_geometry_boundary')==BOUNDARY,'protected restoration must finish before immutable Post freeze')
    original,orig_ids,gm,assembled,oriented,metrics=_assemble_identity(pre.primary.path)
    display,display_ids=identities(post.primary.path);canonical,canon_ids=identities(assets['canonical_payload'].path)
    engine,engine_ids=identities(assets['grouped_engine_output'].path);saved,saved_ids=identities(assets['grouped_saved_material'].path)
    original_names=[m['name'] for m in original];expected=[];inserted=False
    for m in original:
        if m['name'] in MEMBERS:
            if not inserted:expected.append(gm);inserted=True
        else:expected.append(m)
    require(proof['original_selector_order']==original_names==[m['name'] for m in display] and proof['canonical_selector_order']==[m['name'] for m in expected]==profile['expected_parts'],'original/display/canonical selector topology changed')
    require(canonical==expected and [m['name'] for m in engine]==[m['name'] for m in saved]==profile['expected_parts'],'canonical grouping metadata/inventory changed')
    require(proof['original_metadata_sha256']==object_hash(original) and proof['canonical_metadata_sha256']==object_hash(canonical),'group full metadata hash mismatch')
    require(proof['member_array_identities']==[orig_ids[n] for n in MEMBERS] and proof['closed_group_array_identity']==assembled==canon_ids[GROUP_NAME]==engine_ids[GROUP_NAME]==saved_ids[GROUP_NAME],'protected source/canonical/engine/saved group arrays not byte-exact')
    require(proof['closed_group_oriented_triangles_sha256']==restore['oriented_group_triangles_sha256']==oriented,'source oriented triangles erased/reversed/invented')
    require(all(display_ids[n]==orig_ids[n] for n in MEMBERS),'actual displayed original3 patches changed')
    require(all(canon_ids[n]==orig_ids[n] for n in orig_ids if n not in MEMBERS),'unprotected source geometry altered before original engine')
    require(all(display_ids[n]==engine_ids[n]==saved_ids[n] for n in orig_ids if n not in MEMBERS),'other processed display arrays differ from actual original-engine output')
    closure=exact(proof['closure'],{'method',*metrics},'group closure')
    require(closure['method']=='exact float32 positional welding ONLY across explicit source-owned member faces','tolerance welding forbidden')
    require(all(closure[k]==v for k,v in metrics.items() if k!='volume') and type(closure['volume']) in (int,float) and math.isclose(closure['volume'],metrics['volume'],rel_tol=1e-6,abs_tol=1e-12),'actual source closure/domain measurements disagree')
    accepted=audit.get('protected_material_validation',{})
    require(accepted.get('status')=='passed' and all(accepted.get(k) is True for k in ('closed_group_unchanged','source_owned_patches_exact','other_processed_parts_exact')) and all(accepted.get('closure',{}).get(k)==v for k,v in metrics.items() if k!='volume'),'saved reassembled material strict acceptance missing')
    return assets['grouped_saved_material'].sha256
