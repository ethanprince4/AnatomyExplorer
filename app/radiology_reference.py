"""Radiology-only semantic links from the audited atlas correspondence.

These name collisions distinguish real muscle/bone from attachment patches and
surface-region proxies. They do not infer patient laterality or registration.
"""
GROUPS={'erector spinae':'grp:muscular:Erector spinae',
        'spinal cord':'grp:nervous:Spinal cord'}
HOSTS={'medial malleolus':(3660,3661),'lateral malleolus':(1015,1016)}
AUDITED={'diaphragm':(713,), 'medial head of gastrocnemius':(2016,2019)}


def resolve_reference(ds,resolver,names,side=''):
    result=set()
    for name in names:
        key=name.strip().lower()
        if key in GROUPS:ids=ds.node_structures(GROUPS[key])
        elif key in HOSTS:ids=HOSTS[key]
        elif key in AUDITED:ids=AUDITED[key]
        else:ids=resolver.resolve(name)
        for sid in ids:
            sid=int(sid)
            if not 0 <= sid < len(ds.structures):continue
            st=ds.structures[sid]
            if st['system'] in {'attachments','reference'}:continue
            if side and st['side'].lower() not in (side.lower(),''):continue
            result.add(sid)
    return sorted(result)


def framing_core(ids,centres):
    """The ids worth framing: drops a part sitting far from the rest (a detached diagram or label plate placed
    beside the model), which would shrink the real anatomy in the frame. Small sets are kept whole."""
    import numpy as np
    ids=list(ids)
    if len(ids)<6:return ids
    c=np.asarray(centres,float)
    d=np.linalg.norm(c-np.median(c,0),axis=1)
    keep=d<=3.0*np.percentile(d,90)
    return [i for i,k in zip(ids,keep) if k] or ids
