"""Bounded native checks for the reviewed tongue integration; no model writes.

Run from the repository root with its Python environment:
  python docs/model-integrations/2026-10-21-tongue-papillae/verify_integration.py
Add --source PATH to recheck the protected supplied file too.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ['AE_LOCAL_MODEL_LIBRARY'] = str(ROOT / 'data/local_model_library')
os.environ['ANATOMY_PREPARED_CACHE'] = 'off'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.dont_write_bytecode = True

import numpy as np
from app.__main__ import configure_qt
configure_qt()
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PIL import Image
import moderngl
from app.variants.local_runtime import decode_local_npz
from app.viewer.model_loading import LoadToken
from app.viewer.catalog import load_catalog
from app.viewer.part_guide import load_part_guide
from app.viewer.camera import OrbitCamera
from app.viewer.renderer import FrameState, Renderer, Settings
from app.ui import theme
from app.ui.search_panel import ModelCatalogPanel, ROLE_ENTRY
from tools.render_catalogue_specimens import preview_frame, fit_preview

EXPECTED_SHA = '965291ab046d0869e5d7e424407e4ece676df56bd851c34eb8319fbf9c8f2783'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path)
    args = ap.parse_args()
    app = QApplication([])
    theme.apply_theme(app)
    path = ROOT / 'data/local_model_library/models/tongue_papillae/native-20261021/model.npz'
    assert sha(path) == EXPECTED_SHA
    source_before = sha(args.source) if args.source else None
    if args.source:
        assert source_before == EXPECTED_SHA
    warnings = []
    meta, rows = decode_local_npz(path, warnings=warnings)
    names = [r[0]['name'] for r in rows]
    assert len(names) == len(set(names)) == 29
    inventory = []
    with np.load(path, allow_pickle=False) as archive:
        for i, (row, positions, normals, faces, colors) in enumerate(rows):
            raw_normals = archive[f'n{i}']
            lengths = np.linalg.norm(raw_normals, axis=1)
            assert np.isfinite(positions).all() and np.isfinite(normals).all()
            assert np.allclose(np.linalg.norm(normals, axis=1), 1, atol=2e-6)
            assert faces.min() >= 0 and faces.max() < len(positions)
            assert colors is None  # supplied asset uses its authored material colors
            assert row.get('source_name', row['name']) == row['name']
            assert len(row['color']) == 7 and 0 <= row['alpha'] <= 1
            inventory.append(dict(index=i, key=row['name'], group=row['group'],
                color=row['color'], alpha=row['alpha'], category=row['category'],
                clip=row['clip'], bulk=row['bulk'], detail=row['detail'],
                vertices=len(positions), triangles=len(faces),
                bounds=[positions.min(0).tolist(), positions.max(0).tolist()],
                zero_source_normals=int((lengths <= 1e-20).sum()),
                array_sha256={prefix: hashlib.sha256(archive[f'{prefix}{i}'].tobytes()).hexdigest()
                              for prefix in ('p', 'n', 'i')}))
    catalog = load_catalog()
    entry = catalog['tongue_papillae']
    model = entry.prepare_cpu(LoadToken())
    assert Path(entry.descriptor.primary.path).resolve() == path.resolve()
    assert [it.key for it in model.items] == names
    assert [it.index for it in model.items] == list(range(29))
    assert model.triangle_count == 4083312
    guide = load_part_guide('tongue_papillae')
    assert set(guide.descriptions) <= set(names)
    assert set(guide.names) <= set(names)
    assert set(guide.order) == {r[0]['group'] for r in rows}
    for name in model.camera_order:
        assert set(model.cameras[name].get('hidden', ())) <= set(names)
    assert model.sidecar['start_view'] == 'Overview'
    assert model.metres_per_unit == .005
    lesson_checks = []
    for file in (ROOT / 'data/content').glob('lessons*.json'):
        for lesson in json.loads(file.read_text(encoding='utf-8')):
            for index, step in enumerate(lesson.get('steps', [])):
                if step.get('micro') != 'tongue_papillae':
                    continue
                ids, missing = entry.resolve(model, step.get('micro_focus', []))
                assert not missing, (lesson['id'], missing)
                assert step['micro_view'] in model.cameras
                hidden = set(model.cameras[step['micro_view']].get('hidden', ()))
                assert all(model.items[i].key not in hidden for i in ids)
                lesson_checks.append(dict(lesson=lesson['id'], step=index,
                    view=step['micro_view'], keys=[model.items[i].key for i in ids]))
            for practice in lesson.get('practice', []):
                if practice.get('model') == 'tongue_papillae':
                    ids, missing = entry.resolve(model, [practice['part']])
                    assert ids and not missing
    assert len(lesson_checks) == 5

    panel = ModelCatalogPanel(SimpleNamespace(micro_models=catalog, tissues={}))
    panel.setAttribute(Qt.WA_DontShowOnScreen, True)
    panel.resize(1500, 900)
    panel.edit.setText('tongue')
    panel.show()
    app.processEvents()
    # The accessible catalog retains hidden rows when filtering.
    assert panel.shown == 1
    panel.list.setCurrentRow(0)
    app.processEvents()
    assert panel.list.currentItem().data(ROLE_ENTRY).id == 'tongue_papillae'
    assert panel.grab().save(str(OUT / 'selector.png'))
    panel.close()

    ctx = moderngl.create_standalone_context(require=410)
    renderer = Renderer(ctx)
    renderer.set_model(model)
    settings = Settings()
    for key, value in model.look_defaults.items():
        setattr(settings, key, value)
    size = (900, 760)
    target = ctx.framebuffer([ctx.renderbuffer(size, 4)])
    view_checks = []
    for index, name in enumerate(model.camera_order):
        frame, record = preview_frame(model, entry.id, {'view': name})
        camera = OrbitCamera()
        camera.set_scene(model.bounds_min, model.bounds_max)
        camera.aspect = size[0] / size[1]
        camera.set_record(record, duration=0)
        for _ in range(3):
            renderer.render(target, size, camera, settings, frame)
        assert renderer.frame_ok
        image = Image.fromarray(renderer.read_final(target, size).copy())
        filename = f'view-{index:02d}.webp'
        image.save(OUT / filename, quality=94, method=6)
        ids = renderer._read_prepass(2, 1).reshape(-1, 2)[:, 0]
        picked = sorted(set(np.rint(ids[np.isfinite(ids)]).astype(int)) - {0})
        assert picked and min(picked) >= 1 and max(picked) <= len(names)
        view_checks.append(dict(name=name, image=filename,
            visible_parts=int(frame.visible.sum()),
            rasterized_pick_keys=[model.items[i-1].key for i in picked]))
    # Each actual part is isolated once using the same renderer and integer ID
    # buffer. This checks selectable identity even for structures inside tissue.
    pick_checks = []
    for item in model.items:
        visible = np.zeros(len(names), dtype=bool)
        visible[item.index] = True
        frame = FrameState(visible=visible, alpha=np.ones(len(names), np.float32))
        camera = OrbitCamera()
        camera.set_scene(model.bounds_min, model.bounds_max)
        camera.aspect = size[0] / size[1]
        camera.yaw, camera.pitch = .7, .5
        fit_preview(model, camera, frame)
        renderer.render(target, size, camera, settings, frame)
        ids = renderer._read_prepass(2, 1).reshape(-1, 2)[:, 0]
        hits = np.flatnonzero(np.rint(ids) == item.index + 1)
        assert len(hits), item.key
        flat = int(hits[len(hits)//2])
        y, x = divmod(flat, size[0])
        picked, _world, _cut = renderer.pick(x, size[1]-1-y)
        assert picked == item.index, (item.key, picked)
        pick_checks.append(dict(key=item.key, id=item.index, pixels=len(hits),
                                pick_returned=picked))
    target.release()
    renderer.release()
    report = dict(model='tongue_papillae', source_sha256_before=source_before,
        source_sha256_after=sha(args.source) if args.source else None,
        installed_sha256=sha(path), exact_source_copy=True,
        schema={k:v for k,v in meta.items() if k != 'parts'},
        counts=dict(parts=29, vertices=sum(r['vertices'] for r in inventory),
                    triangles=model.triangle_count,
                    groups=dict(Counter(r['group'] for r in inventory))),
        bounds=[model.bounds_min.tolist(), model.bounds_max.tolist()],
        nominal_metres_per_unit=model.metres_per_unit,
        scale_note=model.runtime_controls['native']['scale_note'],
        decoder_warnings=warnings, native_warnings=model.runtime_warnings,
        guide_groups={g:dict(path=list(guide.path(g)[0]),title=guide.path(g)[1])
                      for g in guide.order},
        inventory=inventory, lesson_checks=lesson_checks,
        views=view_checks, gpu_pick_checks=pick_checks,
        gpu={k:ctx.info[k] for k in ('GL_VENDOR','GL_RENDERER','GL_VERSION')},
        selector=dict(file='selector.png', widget='ModelCatalogPanel',
                      platform=os.environ['QT_QPA_PLATFORM'],
                      thumbnail_sha256=sha(ROOT/'app/ui/resources/studio/model-vitrines/thumb_tongue_papillae.webp')),
        limits=['Full buffer/schema checks and 29 isolated GPU picks; no exhaustive collision or anatomical validation.',
                'Zero source normals are repaired only in memory by the unchanged native loader.',
                'Selector is the actual native Qt widget rendered offscreen; views use the application standalone OpenGL renderer.',
                'No macOS, packaged-install, wgpu or production-release validation in this worktree.'])
    if args.source:
        assert report['source_sha256_before'] == report['source_sha256_after'] == EXPECTED_SHA
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(parts=29, triangles=model.triangle_count,
        views=len(view_checks), isolated_gpu_picks=len(pick_checks),
        lesson_steps=len(lesson_checks), source_unchanged=bool(args.source),
        warnings=len(model.runtime_warnings), gpu=report['gpu']),indent=2))


if __name__ == '__main__':
    main()
