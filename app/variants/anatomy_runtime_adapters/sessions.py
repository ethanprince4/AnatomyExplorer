"""View-local teaching/function lifecycles with stale-variant protection."""
from __future__ import annotations
from copy import deepcopy
from .runtime import _hook
from .registry import HERE,contract

STATE_FIELDS=('hidden','forced','isolated','ghost_focus','depth_cut','depth_band','selected','hovered','system_alpha','system_on','subsystem_on','region_on','_undo','custom_colors','part_alpha','opaque_materials')
VIEW_FIELDS=('sections','cut_on','cut_planes','labels_on','explode','reveal_state','reveal_amount','reveal_target','playing','auto_rotate','anim_t','_last_frame_time')
CAMERA_FIELDS=('target','distance','yaw','pitch','fov','ortho','ortho_width','_anim')

def _capture(obj,fields):return {k:deepcopy(getattr(obj,k)) for k in fields if hasattr(obj,k)}
def _restore(obj,values):
    for k,v in values.items():setattr(obj,k,deepcopy(v))

def _path(model_id,index=0):return HERE/contract(model_id)['source_documents'][index]['shipped_path']

class RuntimeSession:
    """Bind after ModelView construction; detach before replacing its model.

    Controls are static teaching unless an independently preserved animation
    explicitly exists. There are no implied physiological timer/flow updates.
    """
    def __init__(self,view):
        self.view=view;self.viewport=view.gl_widget;self.model=view.vmodel;self.state=view.state
        self.identity=self.model.runtime_identity;self.descriptor=self.model.runtime_descriptor
        self.model_id=self.descriptor.model_id;self.controls=self.model.runtime_controls
        self.docs=self.controls['documents'];self.closed=False;self.busy=False;self.connections=[]
        self.snapshot={'state':_capture(self.state,STATE_FIELDS),'view':_capture(self.viewport,VIEW_FIELDS),'camera':_capture(self.viewport.camera,CAMERA_FIELDS),'model':_capture(self.model,('item_offsets','node_offsets')),
                       'items':[(it,it.label,it.clip,it.description) for it in self.model.items],
                       'looks':[(p,deepcopy(p.look)) for p in self.model.parts]}
        self.skin_teaching=None;self.skin_function=None;self.tooth_function=None;self.trachea_function=None;self.trachea_teaching=None;self.ear_function=None
        if self.model_id in ('thin_skin','thick_skin'):
            teaching=_hook(self.model_id,'teaching');function=_hook(self.model_id,'function')
            self.skin_teaching=teaching.TeachingSession(self.viewport,self.model.source.viewer_teaching_design,variant=self.descriptor.variant+'_refine')
            self.skin_function=function.FunctionSession(self.viewport,self.model.source.viewer_function_design)
        if self.model_id=='tooth':self.tooth_function=_hook('tooth','function').StaticStepSession(view,self.docs[1])
        if self.model_id=='trachea_wall':
            settings=self.controls['verified_documents']['native_controls']
            handler=_hook('trachea_wall','teaching').bind_controls(view,settings)
            self.trachea_teaching=handler
            self.connections.append((self.viewport.viewChanged,handler))
            self.trachea_function=_hook('trachea_wall','function').NativeSequenceController(self.viewport,self.docs[1])
        if self.model_id=='ear':self.ear_function=_hook('ear','function').SequenceController(self.viewport,self.docs[0])
        self.handler=self._named_view_changed
        self.viewport.viewChanged.connect(self.handler);self.connections.append((self.viewport.viewChanged,self.handler))
        self.model.runtime_session=self

    def _live(self):
        if self.closed:raise ValueError('Teaching session is closed')
        if self.view.vmodel is not self.model or self.viewport.model is not self.model or self.view.state is not self.state or self.model.runtime_identity!=self.identity:raise ValueError('Stale teaching session: selected model/variant changed')

    def _reset(self):
        self._live();g=self.viewport;s=self.state
        s.opaque_materials=False
        for method,args in (('set_playing',(False,)),('set_explode',(0.0,))):
            fn=getattr(g,method,None)
            if callable(fn):fn(*args)
        g.sections=[None,None,None];g.cut_on=False;g.auto_rotate=False
        g.reveal_state=None;g.reveal_amount=0.;g.reveal_target=0.;self.model.node_offsets={}
        for method in ('clear_selection','clear_ghost'):
            fn=getattr(s,method,None)
            if callable(fn):fn()
        for field in ('system_on','subsystem_on','region_on'):
            if hasattr(s,field):getattr(s,field)[:]=True
        if hasattr(s,'system_alpha'):s.system_alpha[:]=1.
        if hasattr(s,'depth_cut'):s.depth_cut=0.
        if hasattr(s,'depth_band'):s.depth_band=0.
        if hasattr(s,'isolated'):s.isolated=None
        if hasattr(s,'ghost_focus'):s.ghost_focus=None
        s._vis_dirty()

    def _record(self,name):
        for v in self.controls['teaching_views']:
            names=[v.get(k) for k in ('id','title','name','camera_name','native_view_name','native_name')]
            if name in names:return v
        return None

    def _named_view_changed(self,name):
        if self.closed or self.busy:return
        self._live();self.busy=True
        try:self._apply_view_controls(name)
        finally:self.busy=False

    def _apply_view_controls(self,name):
        record=self._record(name)
        if self.model_id=='trachea_wall':
            self.trachea_teaching(name)
            return {'title':name,'caption':self.model.cameras.get(name,{}).get('note',''),'scale_note':self.controls['native']['scale_note']}
        if self.model_id=='tongue_papillae':
            return _hook('tongue_papillae','teaching').set_named_view_with_context_reset(self.view,name,model_id=self.model_id,contract=self.docs[0])
        if self.model_id=='muscular_artery' and record:
            return _hook(self.model_id,'teaching').apply_controls(self.view,record,self.docs[0])
        if self.model_id=='scalp' and record:
            anchors=self.controls['verified_documents'].get('construction',{}).get('anchors',{})
            return _hook('scalp','teaching').apply_view(self.view,record['id'],path=_path('scalp'),anchors=anchors)
        if self.model_id=='duodenum' and record:
            self.model.source.duodenum_teaching=self.docs[0]
            return _hook('duodenum','teaching').apply_to_viewport(self.viewport,view_id=record['id'])
        if self.model_id in ('thin_skin','thick_skin') and record and record.get('hosts'):
            return self.skin_teaching.apply(record['id'])
        # Remaining model documents already resolve named-camera visibility.
        # Reset context filters plus render-only label/clip/opacity/section state.
        self._reset()
        if name in self.model.cameras:self.viewport.set_named_view(name,animate=False,visibility=True)
        if record:
            if 'label_keys' in record:
                wanted=set(record['label_keys'])
                for item in self.model.items:item.label=item.key in wanted
            percent=record.get('tissue_opacity_percent')
            if percent is not None:
                if self.view.opacity is not None:self.view.opacity.setValue(percent)
                self.view._opacity(percent)
            self.viewport.cut_on=bool(record.get('cut_on',self.model.cameras.get(name,{}).get('cut_on',False)))
            if 'labels_on' in record:self.viewport.labels_on=bool(record['labels_on'])
        self.viewport.invalidate_labels();self.viewport.update()
        return {'title':name,'caption':(record or {}).get('caption',(record or {}).get('purpose','')),'scale_note':self.controls['native']['scale_note']}

    def open_view(self,name):
        self._live()
        if name not in self.model.cameras:raise ValueError('Unknown selected-model teaching view')
        self.busy=True
        try:
            self._reset();self.viewport.set_named_view(name,animate=False,visibility=True)
            return self._apply_view_controls(name)
        finally:self.busy=False

    def opening(self):
        result=self.open_view(self.model.sidecar.get('start_view',self.controls['native']['start_view']))
        if self.model_id=='thyroid_parathyroid_review_v2':result=_hook(self.model_id,'function').apply_opening(self.view,self.docs[0])
        return result

    def function(self,sequence_id,step_index=0):
        self._live()
        self.state.opaque_materials=False
        if type(step_index) is not int or step_index<0:raise ValueError('Function step must be a nonnegative integer')
        self.busy=True
        try:
            if self.skin_function:return self.skin_function.apply(sequence_id,step_index)
            if self.tooth_function:
                seq=next(x for x in self.docs[1]['functional_sequences'] if x['id']==sequence_id)
                return self.tooth_function.apply(sequence_id,seq['steps'][step_index]['id'])
            if self.ear_function:return self.ear_function.select(sequence_id,step_index)
            if self.trachea_function:
                self.trachea_function.begin(sequence_id);self.trachea_function.index=step_index;return self.trachea_function.apply()
            if self.model_id=='thyroid_parathyroid_review_v2':return _hook(self.model_id,'function').apply_sequence_step(self.view,self.docs[0],sequence_id,step_index)
            seq=next((x for x in self.controls['functional_sequences'] if x.get('id')==sequence_id),None)
            if seq is None:raise ValueError('Unknown model-specific function sequence')
            steps=seq.get('steps',seq.get('stages',[]))
            if step_index>=len(steps):raise ValueError('Function step outside sequence')
            step=steps[step_index]
            if self.model_id=='tongue_papillae':
                return _hook(self.model_id,'function').apply_step(self.view,self.docs[0]['function_hooks'],sequence_id,step.get('id'),context_reset=lambda view,name:_hook(self.model_id,'teaching').set_named_view_with_context_reset(self.view,name,model_id=self.model_id,contract=self.docs[0]))
            if self.model_id=='scalp':
                anchors=self.controls['verified_documents']['construction']['anchors']
                return _hook(self.model_id,'function').apply_stage_to_view(self.view,sequence_id,step['id'],anchors,data=self.docs[1],require_verified_geometry=True,available_geometry=self.controls['part_names'])
            if self.model_id=='duodenum':
                self.model.source.duodenum_teaching=self.docs[0]
                return _hook(self.model_id,'teaching').apply_to_viewport(self.viewport,sequence_id=sequence_id,step=step_index)
            if self.model_id in ('lymph_node','peripheral_nerve'):
                resolver=_hook(self.model_id,'function')
                if self.model_id=='lymph_node':frame=resolver.resolve(self.docs[1],sequence_id,step['id'],variant=self.descriptor.variant,model_sha256=self.descriptor.primary.sha256)
                else:
                    if seq.get('gate'):raise ValueError('This connected-route lesson needs a new saved-variant function certificate; historical R1 evidence cannot enable it')
                    frame=resolver.resolve(self.docs[1],sequence_id,step['id'],variant=self.descriptor.variant,model_sha256=self.descriptor.primary.sha256)
                step=dict(step,**frame['state']);step['native_view']=frame['state']['camera_preset']
            if self.model_id=='thyroid_follicles':
                animation=self.model.source.animation;animation.select_sequence(sequence_id)
                seconds=sum(x['duration_s'] for x in self.docs[1]['sequences'][sequence_id]['steps'][:step_index])
                frame=animation.state_at(seconds);step=dict(step,focus_parts=[x['name'] for x in frame['highlight']])
            name=step.get('native_stage_name',step.get('native_view',step.get('view',step.get('view_id',step.get('teaching_view_id',seq.get('view_id'))))))
            by_key={item.key:item.index for item in self.model.items}
            visible=step.get('visible_parts',seq.get('visible_parts'));focus=step.get('focus_parts',step.get('highlight_parts',step.get('parts',[])))
            resolved=[]
            if name and name not in self.model.cameras:raise ValueError('Function references missing named camera: '+name)
            if visible is not None and set(visible)-set(by_key):raise ValueError('Function references missing exact visible selectors')
            for k in focus:
                key=k.get('name') if isinstance(k,dict) else k
                if key not in by_key:raise ValueError('Function references missing exact focus selector: '+str(key))
                resolved.append(by_key[key])
            # Complete name/gate/camera preflight before touching the live scene.
            self._reset()
            if name:self.viewport.set_named_view(name,animate=False,visibility=True)
            if visible is not None:
                self.state.set_hidden(list(by_key.values()),True,undo=False);self.state.set_hidden([by_key[k] for k in visible],False,undo=False)
            if resolved:self.state.select(resolved)
            self.viewport.invalidate_labels();self.viewport.update()
            return {'sequence_id':sequence_id,'step_index':step_index,'title':step.get('title',step.get('label',seq.get('title',seq.get('mechanism','')))),
                    'caption':step.get('caption',step.get('text',step.get('narrative',step.get('anatomical_function',step.get('mechanism',''))))),'limitations':seq.get('schematic_limitations',seq.get('limitations',[])),
                    'scale_note':step.get('scale_note',self.controls['native']['scale_note']),'animation':False}
        finally:self.busy=False

    def close(self):
        if self.closed:return
        live=self.view.vmodel is self.model and self.viewport.model is self.model and self.view.state is self.state and self.model.runtime_identity==self.identity
        if live:
            for session in (self.skin_function,self.skin_teaching,self.tooth_function,self.trachea_function):
                if session:
                    fn=getattr(session,'restore',getattr(session,'clear',getattr(session,'close',None)))
                    if callable(fn):fn()
            _restore(self.state,self.snapshot['state']);_restore(self.viewport,self.snapshot['view']);_restore(self.viewport.camera,self.snapshot['camera']);_restore(self.model,self.snapshot['model'])
            for it,label,clip,text in self.snapshot['items']:it.label=label;it.clip=clip;it.description=text
            for part,look in self.snapshot['looks']:part.look=deepcopy(look)
            self.state._vis_dirty();self.viewport.invalidate_labels();self.viewport.update()
        # A stale session must not restore old arrays into a newly selected model.
        for signal,handler in self.connections:
            try:signal.disconnect(handler)
            except (RuntimeError,TypeError):pass
        self.closed=True
        if getattr(self.model,'runtime_session',None) is self:self.model.runtime_session=None


def bind_view(model_view):
    old=getattr(model_view.vmodel,'runtime_session',None)
    if old is not None:old.close()
    return RuntimeSession(model_view)
