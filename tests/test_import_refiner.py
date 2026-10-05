import json
from pathlib import Path
from tools.import_refiner import install,rollback

def test_independent_copy_and_rollback(tmp_path):
    source=tmp_path/'refiner';target=tmp_path/'library'
    model=source/'library'/'sample';model.mkdir(parents=True)
    (source/'library/models.json').write_text(json.dumps([{'id':'sample','name':'Sample','input':'original.npz'}]))
    (model/'original.npz').write_bytes(b'before')
    (model/'refined.npz').write_bytes(b'first')
    assert install(source,target)==['sample']
    initial=json.loads((target/'library.json').read_text())['models']['sample']
    (model/'refined.npz').write_bytes(b'second')
    install(source,target,['sample'])
    current=json.loads((target/'library.json').read_text())['models']['sample']
    assert current['variants']['pre']==initial['variants']['pre']
    assert (target/current['variants']['post']['path']).read_bytes()==b'second'
    assert (target/initial['variants']['post']['path']).read_bytes()==b'first'
    rollback(target,'sample')
    assert json.loads((target/'library.json').read_text())['models']['sample']==initial

def test_no_post_is_not_invented(tmp_path):
    source=tmp_path/'refiner';target=tmp_path/'library'
    model=source/'library'/'sample';model.mkdir(parents=True)
    (source/'library/models.json').write_text(json.dumps([{'id':'sample','name':'Sample','input':'original.glb'}]))
    (model/'original.glb').write_bytes(b'before')
    install(source,target)
    assert set(json.loads((target/'library.json').read_text())['models']['sample']['variants'])=={'pre'}


def test_registry_components_and_nested_assets_copy_independently(tmp_path):
    source=tmp_path/'refiner';target=tmp_path/'library';model=source/'library'/'axillary_skin';model.mkdir(parents=True)
    for name in ('original.npz','refined.npz','inset-before.npz','inset-after.npz','colors.npz'):(model/name).write_bytes(name.encode())
    (model/'controls.json').write_text('{"native": {"cut_on": false}}')
    components={'pre':{'cell_inset':{'path':'inset-before.npz'}},'post':{'cell_inset':{'path':'inset-after.npz','companions':{'colors':'colors.npz'},'runtime_controls':'controls.json'},'missing':{'path':'absent.npz'}}}
    (source/'library/models.json').write_text(json.dumps([{'id':'axillary_skin','name':'Skin','input':'original.npz','components':components}]))
    install(source,target)
    variants=json.loads((target/'library.json').read_text())['models']['axillary_skin']['variants']
    before=variants['pre']['components']['cell_inset'];after=variants['post']['components']['cell_inset']
    assert (target/before['path']).read_bytes()==b'inset-before.npz'
    assert (target/after['path']).read_bytes()==b'inset-after.npz'
    assert (target/after['companions']['colors']).read_bytes()==b'colors.npz'
    assert json.loads((target/after['runtime_controls']).read_text())['native']['cut_on'] is False
    assert 'missing' not in variants['post']['components']
    (model/'inset-after.npz').write_bytes(b'changed later')
    assert (target/after['path']).read_bytes()==b'inset-after.npz'
    rows=json.loads((source/'library/models.json').read_text());rows[0].pop('components')
    (source/'library/models.json').write_text(json.dumps(rows));install(source,target)
    later=json.loads((target/'library.json').read_text())['models']['axillary_skin']['variants']['post']
    assert later['components']['cell_inset']==after


def test_registry_cell_inset_companion_and_explicit_map(tmp_path):
    source=tmp_path/'refiner';target=tmp_path/'library';model=source/'library'/'sample';model.mkdir(parents=True)
    (model/'original.npz').write_bytes(b'original');(model/'inset.npz').write_bytes(b'inset')
    (source/'library/models.json').write_text(json.dumps([{'id':'sample','name':'Sample','input':'original.npz','companions':{'cell_inset':'inset.npz'}}]))
    extra=tmp_path/'extra.npz';extra.write_bytes(b'component')
    install(source,target,companions={'sample':{'components':{'cell_inset':{'path':str(extra),'runtime_controls':{'native':{'labels_on_open':True}}}}}})
    pre=json.loads((target/'library.json').read_text())['models']['sample']['variants']['pre']
    assert (target/pre['companions']['cell_inset']).read_bytes()==b'inset'
    assert (target/pre['components']['cell_inset']['path']).read_bytes()==b'component'
    assert pre['components']['cell_inset']['runtime_controls']['native']['labels_on_open'] is True
