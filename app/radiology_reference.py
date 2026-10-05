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
