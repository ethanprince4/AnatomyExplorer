"""Narrow authored occupied-union proof lane; no generic collision waiver.

The trusted pinned numeric runner measures true material unions and saved source
relations. This shipped stdlib verifier independently checks every actual native
array identity, immutable participant restoration, genuine engine lineage and
exhaustive saved pair/relationship coverage. External code is never imported.
"""
from __future__ import annotations
import contextlib
import hashlib
import io
import struct
import zipfile
from . import authored_contract as ac
from .additional import object_hash
from .correspondence import native_decoded_identity
from .formats import _npy_header, _zip_members
from .security import digest,exact,file_hash,integer,parse_json,read_json,relative_path,require,safe_open

MODELS=frozenset({'ear','compact_bone','male_reproductive','female_reproductive','lymph_node'})
ADAPTER_ID=ac.ADAPTER_ID
ADAPTER_SHA256=ac.ADAPTER_SHA256
RELATIONSHIPS_SHA256='27043c70b0bef156b161371692776658fcfe413ba3ae83a430dbf52325311a0e'
WRAPPER_SHA256='5ca2867b1a7a5e7b77e1e835c93396aa1bf015976e52c3574e0fa50af2f5d830'
ANCESTRY_SHA256='b4d7c15b0aa8e3454b8cb1193b3aa099228e615e40008396fcdaddff93bb440f'
BUNDLE_WRITER_SHA256='f703c1fd7be447debd235c3d3171062ca2640e96c7beb5daea24a0e7ce4b8b84'
BOUNDARY='microrefine_with_exact_authored_member_restoration_before_Post_freeze'
AUTHORED_ROLES={
 'authored_projected_profile':frozenset({('json','ae.authored-projected-profile.v1')}),
 'authored_base_profile':frozenset({('json','ae.authored-projection-base-profile.v1')}),
 'authored_projection':frozenset({('json',ac.PROOF_SCHEMA)}),
 'authored_relationship_transport':frozenset({('json',ac.RELATIONSHIP_SCHEMA)}),
 'authored_projected_input':frozenset({('npz','anatomy-npz-f32-delta-v1')}),
 'authored_engine_output':frozenset({('npz','anatomy-npz-f32-delta-v1')}),
 'authored_saved_validation':frozenset({('json','ae.authored-interaction-saved-lane.v1')}),
 'authored_source_bundle':frozenset({('npz','ae.authored-source-bundle.v1')}),
}
PROOF_KEYS={'schema','adapter_id','adapter_sha256','model_id','source_bindings','declarations_sha256','declarations','original_profile_sha256','original_metadata_sha256','original_selector_order','projected_selector_order','groups','participant_arrays','source_material_excluded','obstacle_semantics','anatomical_qualification'}
IDENTITY_KEYS={'name','metadata_sha256','arrays_sha256'}


def is_supported(model_id,adapter_id):
    return model_id in MODELS and adapter_id=='ae.'+model_id+'.runtime.v1'


def _array_stream(z,key):
    stream=z.open(key+'.npy');dtype,shape,size,header=_npy_header(stream)
    require(size+header==z.getinfo(key+'.npy').file_size,'authored array byte count mismatch')
    return stream,dtype,shape


def _raw_array_hash(z,key,*,decoded_delta=False):
    stream,dtype,shape=_array_stream(z,key);h=hashlib.sha256();acc=0
    with stream:
        while b:=stream.read(1048576):
            if decoded_delta:
                require(dtype=='<i4' and len(shape)==1 and shape[0]%3==0,'source delta layout invalid')
                for (d,) in struct.iter_unpack('<i',b):acc+=d;h.update(struct.pack('<q',acc))
            else:h.update(b)
    return h.hexdigest(),dtype,shape


def _native(path):
    meta,rows=native_decoded_identity(path,'anatomy-npz-f32-delta-v1');ids={}
    with safe_open(path) as raw,zipfile.ZipFile(raw) as z:
        for i,(m,r) in enumerate(zip(meta,rows)):
            h=hashlib.sha256()
            for k in sorted(['p','n','i']+(['c'] if r['colors_sha256'] is not None else [])):
                stream,dtype,shape=_array_stream(z,k+str(i))
                if k=='i':dtype='<i8';shape=(r['triangles'],3)
                h.update(k.encode());h.update(dtype.encode());h.update(str(shape).encode());acc=0
                with stream:
                    while b:=stream.read(1048576):
                        if k=='i':
                            for (d,) in struct.iter_unpack('<i',b):acc+=d;h.update(struct.pack('<q',acc))
                        else:h.update(b)
            ids[m['name']]={'name':m['name'],'metadata_sha256':object_hash(m),'arrays_sha256':h.hexdigest()}
    return meta,rows,ids


class _Slice(io.RawIOBase):
    """Seekable uint8 NPY body view for nested ZIP, without whole-blob loading."""
    def __init__(self,stream,start,size):self.stream,self.start,self.size=stream,start,size;self.pos=0
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.pos
    def seek(self,offset,whence=0):
        target=offset if whence==0 else (self.pos+offset if whence==1 else self.size+offset)
        require(0<=target<=self.size,'authored bundle nested seek outside member')
        self.stream.seek(self.start+target);self.pos=target;return target
    def read(self,size=-1):
        size=self.size-self.pos if size<0 else min(size,self.size-self.pos)
        data=self.stream.read(size);self.pos+=len(data);return data


class SourceBundle:
    def __init__(self,asset,model_id):
        self.asset=asset;self.model_id=model_id;self.entries={}
        with safe_open(asset.path) as raw,zipfile.ZipFile(raw) as z:
            members=_zip_members(z)
            with z.open('meta.npy') as s:
                dt,sh,_,_=_npy_header(s);require(dt=='|u1' and len(sh)==1 and sh[0]<=4*1024*1024,'authored evidence metadata layout invalid');data=parse_json(s.read(4*1024*1024+1))
            exact(data,{'schema','schema_version','model_id','entries'},'authored evidence index')
            require(data['schema']=='ae.authored-source-bundle.v1' and type(data['schema_version']) is int and data['schema_version']==1 and isinstance(data['model_id'],str) and (model_id is None or data['model_id']==model_id),'authored evidence index identity mismatch')
            rows=data['entries'];require(isinstance(rows,list) and 0<len(rows)<=1024,'authored evidence entry bound invalid')
            keys=set();paths=[]
            for row in rows:
                exact(row,{'path','sha256','size','array_key'},'authored evidence entry');relative_path(row['path']);digest(row['sha256']);integer(row['size'],1,2*1024*1024*1024,'authored source blob size')
                key=row['array_key'];require(isinstance(key,str) and key=='blob_'+str(len(paths)) and key not in keys and row['path'] not in self.entries,'authored evidence duplicate/noncanonical index')
                keys.add(key);paths.append(row['path']);self.entries[row['path']]=row
                with z.open(key+'.npy') as s:
                    dt,shape,size,header=_npy_header(s,max_elements=2*1024*1024*1024);require(dt=='|u1' and shape==(row['size'],) and header+size==z.getinfo(key+'.npy').file_size,'authored blob dtype/size mismatch');h=hashlib.sha256()
                    while block:=s.read(1048576):h.update(block)
                    require(h.hexdigest()==row['sha256'],'authored raw source blob identity changed')
            require(paths==sorted(paths) and set(members)=={'meta'}|keys,'authored evidence unsorted/undeclared arrays')
        self.used=set()

    def entry(self,spec):
        require(isinstance(spec,dict) and isinstance(spec.get('path'),str),'authored source reference declaration missing');relative_path(spec['path']);digest(spec.get('sha256'))
        entry=self.entries.get(spec['path']);require(entry is not None and entry['sha256']==spec['sha256'] and ('size' not in spec or entry['size']==spec['size']),'authored source reference missing/rebound in immutable bundle')
        self.used.add(spec['path']);return entry

    @contextlib.contextmanager
    def open(self,spec):
        e=self.entry(spec)
        with safe_open(self.asset.path) as raw,zipfile.ZipFile(raw) as z,z.open(e['array_key']+'.npy') as s:
            _,_,size,_=_npy_header(s,max_elements=2*1024*1024*1024);yield _Slice(s,s.tell(),size)

    @contextlib.contextmanager
    def npz(self,spec):
        require(spec['path'].endswith('.npz'),'authored numeric witness must retain original NPZ type')
        with self.open(spec) as s,zipfile.ZipFile(s) as z:
            members=_zip_members(z)
            for name,info in members.items():
                with z.open(info) as stream:
                    dt,shape,size,header=_npy_header(stream,allow_scalar=name=='count');require(shape!=() or (name=='count' and dt=='<i8'),'authored witness scalar type invalid');require(size+header==info.file_size,'authored nested witness NPY size invalid');total=0
                    while b:=stream.read(1048576):
                        total+=len(b)
                        if dt in {'<f4','<f8'}:
                            fmt='<f' if dt=='<f4' else '<d'
                            require(all(ac.finite(v) for (v,) in struct.iter_unpack(fmt,b)),'authored source witness has nonfinite numeric values')
                    require(total==size,'authored nested witness truncated')
            yield z


def inspect_source_bundle(path):
    from types import SimpleNamespace
    return SourceBundle(SimpleNamespace(path=path),None)


def _references(rows,bundle):
    for row in rows:
        specs=[*row['source_part_references'].values(),*[row[k] for k in ac.REFERENCE_KEYS]]
        specs += [row[k] for k in ('child_references','host_references','artifact') if k in row]
        for spec in specs:
            bundle.entry(spec)
            if spec['path'].endswith('.npz'):
                with bundle.npz(spec):pass
            else:
                require(spec['path'].endswith('.json'),'authored source evidence format invalid')
                with bundle.open(spec) as stream:parse_json(stream.read(4*1024*1024+1))
    return bundle


def source_specs(profile):
    """Exact unchanged reference inventory from the reviewed source scopes."""
    found={}
    def visit(value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
                relative_path(value['path']);digest(value['sha256']);old=found.get(value['path'])
                require(old is None or old['sha256']==value['sha256'],'authored source path has conflicting witness identities');found[value['path']]=value
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    binding=profile['final_microrefine']
    for scope in ('witnesses','additional_checks','authored_interactions','source_nested_owner_links'):visit(binding.get(scope,{}))
    return found


def _complete_bundle(bundle,profile):
    specs=source_specs(profile);require(set(bundle.entries)==set(specs),'authored source bundle missing/extra source reference inventory')
    for spec in specs.values():
        bundle.entry(spec)
        if spec['path'].endswith('.npz'):
            with bundle.npz(spec):pass
        else:
            require(spec['path'].endswith('.json'),'authored source evidence type unsupported')
            with bundle.open(spec) as s:parse_json(s.read(4*1024*1024+1))



def _source_arrays(rows,bundle,metadata,native_rows):
    _references(rows,bundle);by={m['name']:(m,r) for m,r in zip(metadata,native_rows)};seen=set()
    for row in rows:
        capture=bundle.entry(row['source_native_writer_capture'])
        with bundle.npz(row['source_native_writer_capture']) as z:
            if row.get('source_native_metadata_sha256'):
                with z.open('meta.npy') as s:_npy_header(s);b=s.read(4*1024*1024+1)
                require(hashlib.sha256(b).hexdigest()==row['source_native_metadata_sha256'],'authored native capture metadata hash mismatch')
                source_meta=parse_json(b);require(isinstance(source_meta,dict) and isinstance(source_meta.get('parts'),list),'authored capture metadata invalid')
            for name in row['parts']:
                index=row['native_part_indices'][name];m,r=by[name];record=(name,capture['sha256'],index,row['source_index_encoding'])
                require(index<len(metadata) and metadata[index]['name']==name,'authored native source Part index changed')
                if row.get('source_native_metadata_sha256'):require(source_meta['parts'][index]==m,'authored participant metadata changed')
                if record in seen:continue
                seen.add(record);h=hashlib.sha256()
                for k in sorted(('p','n','i')):
                    s,dt,shape=_array_stream(z,k+str(index));h.update(k.encode());h.update(dt.encode());h.update(str(shape).encode())
                    with s:
                        while b:=s.read(1048576):h.update(b)
                require(h.hexdigest()==row['source_part_array_sha256'][name],'authored source capture raw p/n/i fingerprint changed')
                for k,field in (('p','positions_sha256'),('n','normals_sha256'),('i','indices_sha256')):
                    result,dt,shape=_raw_array_hash(z,k+str(index),decoded_delta=k=='i' and row['source_index_encoding']=='delta_int32')
                    expected=('<i4',(r['triangles']*3,)) if k=='i' and row['source_index_encoding']=='delta_int32' else (('<i8',(r['triangles'],3)) if k=='i' else ('<f4',(r['vertices'],3)))
                    require((dt,shape)==expected and result==r[field],'authored canonical participant differs from exact native capture')
                ref=row['source_part_references'][name]
                with bundle.npz(ref) as rz:
                    _count(rz,1)
                    require(_raw_array_hash(rz,'p0')== (r['positions_sha256'],'<f4',(r['vertices'],3)) and _raw_array_hash(rz,'f0')==(r['indices_sha256'],'<i8',(r['triangles'],3)),'authored full source Part reference changed')
    return bundle


def _count(z,expected):
    with z.open('count.npy') as stream:
        dt,shape,_,_=_npy_header(stream,allow_scalar=True);value=stream.read(8)
    require(dt=='<i8' and shape==() and len(value)==8 and struct.unpack('<q',value)[0]==expected,'authored source reference count mismatch')


def _selected_geometry(path,part_index,vids,fids):
    """Exact source-index projection, never proximity matching or reclassification."""
    positions=hashlib.sha256();faces={};wanted=set(fids)
    with safe_open(path) as raw,zipfile.ZipFile(raw) as z:
        with z.open('p'+str(part_index)+'.npy') as stream:
            dt,shape,_,_=_npy_header(stream);start=stream.tell();require(dt=='<f4' and len(shape)==2 and shape[1]==3,'authored subset source positions invalid')
            for i in vids:
                stream.seek(start+12*i);b=stream.read(12);require(len(b)==12,'authored subset vertex missing');positions.update(b)
        with z.open('i'+str(part_index)+'.npy') as stream:
            dt,shape,_,_=_npy_header(stream);require(dt=='<i4' and len(shape)==1 and shape[0]%3==0,'authored subset source indices invalid');acc=0;triangle=[];fi=0
            while block:=stream.read(1048576):
                for (delta,) in struct.iter_unpack('<i',block):
                    acc+=delta;triangle.append(acc)
                    if len(triangle)==3:
                        if fi in wanted:faces[fi]=tuple(triangle)
                        fi+=1;triangle=[]
    require(set(faces)==wanted,'authored subset source face missing');remap={v:i for i,v in enumerate(vids)};h=hashlib.sha256()
    for fi in fids:
        require(all(v in remap for v in faces[fi]),'authored subset face vertex omitted');h.update(struct.pack('<3q',*(remap[v] for v in faces[fi])))
    return positions.hexdigest(),h.hexdigest()


def _indexed_affiliation(rows,bundle,path,metadata,native_rows):
    by={m['name']:(i,r) for i,(m,r) in enumerate(zip(metadata,native_rows))}
    for row in rows:
        if row['kind']!=ac.AFFILIATION:continue
        coverage={'host':{},'child':{}}
        for owner in row['owners']:
            for label in ('host','child'):
                span=owner.get(label+'_span');subset=owner.get(label+'_subset');name=row[label];part_index,r=by[name]
                require(isinstance(span,dict)!=isinstance(subset,dict),'authored affiliation requires exact span OR indexed subset')
                if subset is not None:
                    exact(subset,{'vertex_indices','face_indices','mapping_method'},'authored exact source subset');require(subset['mapping_method']=='exact_oriented_source_triangle_coordinates','authored subset mapping changed')
                    vids,fids=subset['vertex_indices'],subset['face_indices']
                    for ids,length in ((vids,r['vertices']),(fids,r['triangles'])):
                        require(isinstance(ids,list) and 0<len(ids)<=100000 and len(ids)==len(set(ids)) and all(type(i) is int and 0<=i<length for i in ids),'authored source subset index bound/identity invalid')
                else:
                    exact(span,{'vertex_start','vertex_count','face_start','face_count'},'authored exact source span')
                    vs=integer(span['vertex_start'],0,r['vertices']-1,'authored source vertex start');vc=integer(span['vertex_count'],1,r['vertices']-vs,'authored source vertex count')
                    fs=integer(span['face_start'],0,r['triangles']-1,'authored source face start');fc=integer(span['face_count'],1,r['triangles']-fs,'authored source face count');require(vc<=100000 and fc<=100000,'authored source span exceeds indexed bound');vids=list(range(vs,vs+vc));fids=list(range(fs,fs+fc))
                identity=owner[label+'_id'];record=(vids,fids);require(identity not in coverage[label] or coverage[label][identity]==record,'authored source subset identity conflict');coverage[label][identity]=record
                ph,fh=_selected_geometry(path,part_index,vids,fids);spec=row[label+'_references'];index=owner[label+'_reference_index'];count=len(row[label+'_instance_ids'])
                with bundle.npz(spec) as z:
                    _count(z,count);require(_raw_array_hash(z,'p'+str(index))==(ph,'<f4',(len(vids),3)) and _raw_array_hash(z,'f'+str(index))==(fh,'<i8',(len(fids),3)),'authored affiliation exact source projection changed')
        for label in ('host','child'):
            require(set(coverage[label])==set(row[label+'_instance_ids']),'authored source subset registry incomplete');_,r=by[row[label]]
            for component,length in ((0,r['vertices']),(1,r['triangles'])):
                ids=[i for record in coverage[label].values() for i in record[component]]
                require(len(ids)==len(set(ids))==length and set(ids)==set(range(length)),'authored source subset partition omitted/duplicated source arrays')


def _reference_inventory(rows,bundle,model_id):
    for row in rows:
        spec=row['source_intersection_reference']
        with bundle.npz(spec) as z:
            with z.open('count.npy') as stream:
                dt,shape,_,_=_npy_header(stream,allow_scalar=True);data=stream.read(8)
            require(dt=='<i8' and shape==() and len(data)==8,'authored intersection reference count invalid');count=integer(struct.unpack('<q',data)[0],1,100000,'authored intersection reference count')
            require(set(z.namelist())=={'count.npy'}|{f'{k}{i}.npy' for i in range(count) for k in ('p','f')},'authored intersection reference arrays incomplete/extra')
        if row['kind']!=ac.AFFILIATION and count!=len(row['source_instance_ids']):
            require(model_id=='lymph_node' and len(row['source_instance_ids'])==1 and row.get('source_region_component_ids')==[row['source_instance_ids'][0]+':intersection:'+str(i) for i in range(count)],'authored source intersection region IDs/count changed')
        if model_id=='lymph_node' and 'source_region_component_ids' in row:
            require(row['source_region_component_ids']==[row['source_instance_ids'][0]+':intersection:'+str(i) for i in range(count)],'authored LN decomposed intersection identity changed')


def _ancestry_arrays(profile,bundle,metadata,source_rows,source,delivered):
    links=ac.validate_ancestry_links(profile);b=profile['final_microrefine']
    if not links:return
    require(b.get('source_nested_owner_links_sha256')==object_hash(links),'authored nested owner declarations hash mismatch')
    by={m['name']:(m,r) for m,r in zip(metadata,source_rows)};verified=set()
    for link in links:
        name=link['child'];capture=link['source_live_final_buffer_capture'];identity=(name,capture['sha256'])
        require(source[name]==delivered[name],'authored nested original child arrays changed')
        if identity in verified:continue
        verified.add(identity);m,r=by[name]
        with bundle.npz(capture) as z:
            with z.open('meta.npy') as stream:
                dt,shape,_,_=_npy_header(stream);require(dt=='|u1' and len(shape)==1,'authored nested source metadata encoding invalid');live_meta=parse_json(stream.read(4*1024*1024+1))
            require(isinstance(live_meta,list) and len(live_meta)==len(metadata) and live_meta==metadata,'authored nested source metadata changed');_count(z,len(live_meta));index=next(i for i,p in enumerate(live_meta) if p['name']==name)
            for key,field,dt,shape in [('p','positions_sha256','<f4',(r['vertices'],3)),('n','normals_sha256','<f4',(r['vertices'],3)),('f','indices_sha256','<i8',(r['triangles'],3))]:
                require(_raw_array_hash(z,key+str(index))==(r[field],dt,shape),'authored nested native child p/n/f changed')
        with bundle.open(link['source_native_metadata_capture']) as stream:native=parse_json(stream.read(4*1024*1024+1))
        require(isinstance(native,dict) and native.get('parts')==live_meta,'authored nested native writer metadata changed')
        with bundle.npz(link['source_child_part_reference']) as z:
            _count(z,1);require(_raw_array_hash(z,'p0')==(r['positions_sha256'],'<f4',(r['vertices'],3)) and _raw_array_hash(z,'f0')==(r['indices_sha256'],'<i8',(r['triangles'],3)),'authored nested full source child reference changed')


def _relationships(profile,audit,saved):
    relation=exact(audit.get('original_saved_relationships'),{'containment','continuity'},'authored saved original relationships')
    expected=profile.get('containment',[]);actual=relation['containment'];require(isinstance(actual,list),'authored saved containment report malformed')
    owner_rows=profile['final_microrefine']['additional_checks']['cell_ownership'];children=[];count=0
    for declared in expected:
        child=declared['child'];require(child not in children,'authored duplicate containment child scope unsupported');children.append(child)
        hosts=set(declared.get('host_candidates',[declared['host']]));owners=[o for row in owner_rows if row['child']==child for o in row['owners']]
        require(owners and len({o['child_id'] for o in owners})==len(owners),'authored source ownership inventory missing/duplicated')
        rows=[r for r in actual if r.get('child')==child];count+=len(owners)
        require(len(rows)==len(owners) and [r.get('component') for r in rows]==list(range(len(owners))),'authored containment component coverage incomplete/repeated')
        if declared.get('reference_parents'):hosts.add('source parent envelope')
        for r in rows:
            require(r.get('host') in hosts and type(r.get('parent_component')) is int and r['parent_component']>=0 and r.get('valid') is True and ac.finite(r.get('outside_volume'),minimum=0,maximum=profile['numerics']['overlap_volume_tolerance']),'authored individual source parent containment failed/unbound')
    require(len(actual)==count,'authored containment report adds unknown child selectors')
    expected=profile.get('continuity',[]);actual=relation['continuity'];require(isinstance(actual,list) and len(actual)==len(expected),'authored original continuity coverage incomplete')
    for r,d in zip(actual,expected):
        require(r.get('name')==d['name'] and r.get('allowed_regions')==d['allowed_regions'] and r.get('contact_tolerance')==d['contact_tolerance'] and r.get('valid') is True and type(r.get('connected_regions')) is int and 0<r['connected_regions']<=d['allowed_regions'] and type(r.get('material_domains')) is int and r['material_domains']>=r['connected_regions'],'authored original source continuity changed/failed')
    owned=saved.get('source_owned_containment_checks')
    require(isinstance(owned,list) and [r.get('witness_id') for r in owned]==[r['witness_id'] for r in owner_rows] and all(r.get('status')=='passed' for r in owned),'authored saved source ownership scope omitted/failed')


def validate_authored(pre,post,profile,audit,report,independent):
    require(pre.model_id==post.model_id and pre.adapter_id==post.adapter_id and is_supported(pre.model_id,pre.adapter_id),'authored projection unavailable for this shipped model/adapter')
    require(post.primary.schema=='anatomy-npz-f32-delta-v1' and pre.primary.format=='npz','authored projection supports native saved source only')
    assets=post.assets;require(set(AUTHORED_ROLES)|{'canonical_payload'}<=set(assets),'complete authored actual payload/envelope missing')
    for role,types in AUTHORED_ROLES.items():require((assets[role].format,assets[role].schema) in types and file_hash(assets[role].path)==(assets[role].sha256,assets[role].size),'authored asset type/hash changed')
    b=profile['final_microrefine'];rows=b.get('authored_interactions');ac.validate_inventory(rows,profile)
    if pre.model_id=='male_reproductive':require(isinstance(b.get('source_nested_owner_links'),list) and len(b['source_nested_owner_links'])==43,'male authored lane requires all43 exact source nuclear ancestry joins')
    require(b.get('authored_interactions_sha256')==object_hash(rows) and b.get('authored_adapter_sha256')==ADAPTER_SHA256,'authored declaration/helper identity mismatch')
    require(not b.get('material_grouping') and b.get('animation',{}).get('kind')=='none','authored projection cannot combine unknown grouping/animation lanes')
    proof=exact(read_json(assets['authored_projection'].path),PROOF_KEYS,'authored projection proof')
    base=read_json(assets['authored_base_profile'].path);projected=read_json(assets['authored_projected_profile'].path);transport=read_json(assets['authored_relationship_transport'].path);saved=read_json(assets['authored_saved_validation'].path)
    expected_base,expected_projected,expected_transport=ac.reconstructed_engine_profile(profile,proof,assets['authored_projected_input'].sha256)
    require((base,projected,transport)==(expected_base,expected_projected,expected_transport),'authored projected profile/relationship semantics changed')
    ac.validate_projection_envelope(proof,base,rows)
    require(proof['source_bindings']=={k:b[k] for k in ('pre_payload_sha256','source_build_sha256','source_receipt_sha256')},'authored projection source lineage mismatch')
    hashes={'projected_profile_sha256':'authored_projected_profile','projection_base_profile_sha256':'authored_base_profile','projected_input_sha256':'authored_projected_input','projected_output_sha256':'authored_engine_output','projection_sha256':'authored_projection','relationship_transport_sha256':'authored_relationship_transport','authored_saved_validation_sha256':'authored_saved_validation','authored_source_bundle_sha256':'authored_source_bundle'}
    require(all(audit.get(k)==assets[v].sha256 for k,v in hashes.items()) and audit.get('original_profile_sha256')==assets['microrefine_profile'].sha256 and assets['canonical_payload'].sha256==b['canonical_payload']['sha256'],'authored source/projected/saved audit identities mismatch')
    require(report.get('input_sha256')==assets['authored_projected_input'].sha256 and report.get('output_sha256')==assets['authored_engine_output'].sha256 and report.get('profile_sha256')==assets['authored_projected_profile'].sha256,'authored report is not actual projected engine execution')
    require(audit.get('authored_adapter_sha256')==ADAPTER_SHA256 and audit.get('authored_relationships_sha256')==RELATIONSHIPS_SHA256 and audit.get('authored_wrapper_sha256')==WRAPPER_SHA256 and audit.get('authored_ancestry_sha256')==ANCESTRY_SHA256 and audit.get('authored_source_bundle_writer_sha256')==BUNDLE_WRITER_SHA256 and audit.get('final_geometry_boundary')==BOUNDARY,'unshipped authored adapter/transport/restoration boundary')
    original,source_rows,source=_native(assets['canonical_payload'].path);display,_,delivered=_native(post.primary.path)
    input_meta,_,input_ids=_native(assets['authored_projected_input'].path);output_meta,_,output_ids=_native(assets['authored_engine_output'].path)
    names=[m['name'] for m in original];require(names==profile['expected_parts']==proof['original_selector_order']==[m['name'] for m in display] and original==display,'authored original/display metadata or selectors changed')
    require(proof['original_metadata_sha256']==object_hash(original),'authored original full Part metadata hash mismatch')
    participants=ac.participants(rows);require(proof['participant_arrays']==[source[n] for n in names if n in participants],'authored actual original participant identities mismatch')
    groups={g['name']:g for g in proof['groups']};mapping={n:g['name'] for g in groups.values() for n in g['members']};expected=[];emitted=set()
    for m in original:
        if m['name'] in mapping:
            group=mapping[m['name']]
            if group not in emitted:
                owner=next(x for x in original if x['name']==groups[group]['members'][0]);gm=dict(owner,name=group,color='#808080',description='Immutable occupied source-interaction union; original display members retained exactly')
                expected.append(gm);emitted.add(group)
        else:expected.append(m)
    require(input_meta==expected and [m['name'] for m in input_meta]==proof['projected_selector_order']==projected['expected_parts'] and output_meta==input_meta,'authored actual projected metadata/inventory mismatch')
    for group,g in groups.items():
        identity=exact(g['occupied_union_identity'],IDENTITY_KEYS,'authored occupied union identity')
        require(identity==input_ids[group]==output_ids[group] and group in projected['immutable_geometry_parts'] and group not in {r['part'] for r in projected['preserved_representations']},'authored occupied source union changed or excluded from material')
    require(all(delivered[n]==source[n] for n in participants),'authored actual immutable displayed participant arrays changed')
    require(all(input_ids[n]==source[n] and delivered[n]==output_ids[n] for n in names if n not in participants),'authored unrelated input/display arrays differ from source/actual engine output')
    bundle=SourceBundle(assets['authored_source_bundle'],pre.model_id)
    _complete_bundle(bundle,profile)
    _source_arrays(rows,bundle,original,source_rows)
    _reference_inventory(rows,bundle,pre.model_id)
    _indexed_affiliation(rows,bundle,assets['canonical_payload'].path,original,source_rows)
    _ancestry_arrays(profile,bundle,original,source_rows,source,delivered)
    require(independent.get('input_sha256')==post.primary.sha256==audit.get('receipt',{}).get('primary_sha256'),'authored saved-original independent report unbound')
    ac.validate_saved_envelope(profile,saved,rows,saved_sha256=post.primary.sha256,proof=proof,base=base,transport=transport)
    _relationships(profile,audit,saved)
    return post.primary.sha256
