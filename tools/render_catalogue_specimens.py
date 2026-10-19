"""Render catalogue plates from installed geometry and the viewer's tissue defaults.

Uses the approved reference's black/white render pair to retain real silhouette
coverage, including translucent tissue. No model or source material is changed.
"""
import gc
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['AE_LOCAL_MODEL_LIBRARY'] = str(ROOT / 'data/local_model_library')
from app.__main__ import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication
from PIL import Image
import moderngl
from tools.render_model import find_entry
from app.ui.model_view import tissue_opacity
from app.viewer.camera import OrbitCamera
from app.viewer.model_loading import LoadToken
from app.viewer.renderer import FrameState, Renderer, Settings


def render(model_id, ctx):
    entry = find_entry(model_id)
    model = entry.prepare_cpu(LoadToken()) if hasattr(entry, 'prepare_cpu') else entry.load()
    visible = np.ones(len(model.items), dtype=bool)
    _, alpha = tissue_opacity(model, model_id)
    frame = FrameState(visible=visible, alpha=alpha, opaque_materials=False)
    settings = Settings()
    for key, value in getattr(model, 'look_defaults', {}).items():
        setattr(settings, key, value)
    settings.bounce = 0.0
    settings.shadows = False
    settings.background_spot = None
    settings.background_spot_strength = 0.0
    camera = OrbitCamera()
    camera.set_scene(model.bounds_min, model.bounds_max)
    camera.aspect = 1.0
    low, high = model.world_bounds(visible_only=False, visible=visible)
    yaw, pitch = getattr(model, 'home', None) or (math.radians(35), math.radians(24))
    radius = float(np.linalg.norm(high-low)) / 2
    camera.animate_to((low+high)/2, camera.fit_distance(radius*.95, 1), yaw, pitch, 0)
    model.evaluate(model.clip_range[0], None, 1.0)
    renderer = Renderer(ctx)
    renderer.set_model(model)
    size = (960, 960)
    target = ctx.framebuffer([ctx.renderbuffer(size, 4)])
    captures = []
    for colour in ((0., 0., 0.), (1., 1., 1.)):
        settings.background = (colour, colour)
        for _ in range(3):
            renderer.render(target, size, camera, settings, frame)
        captures.append(renderer.read_final(target, size).astype(np.float64))
    black, white = captures
    black_wall = np.median(np.concatenate((black[:4].reshape(-1, 3), black[-4:].reshape(-1, 3))), axis=0)
    white_wall = np.median(np.concatenate((white[:4].reshape(-1, 3), white[-4:].reshape(-1, 3))), axis=0)
    coverage = np.clip(1-((white-black)/np.maximum(white_wall-black_wall, 1)).mean(axis=2), 0, 1)
    coverage[coverage < .004] = 0
    colour = np.clip((black-black_wall*(1-coverage[..., None]))/np.maximum(coverage[..., None], 1e-3), 0, 255)
    rgba = np.dstack((colour, coverage*255)).round().astype(np.uint8)
    yy, xx = np.nonzero(coverage > .01)
    if not len(xx):
        raise RuntimeError(f'Empty specimen render: {model_id}')
    bounds = (max(0, int(xx.min())-24), max(0, int(yy.min())-24),
              min(960, int(xx.max())+25), min(960, int(yy.max())+25))
    plate = Image.fromarray(rgba).crop(bounds)
    filename = 'cardiac_muscle' if model_id == 'cardiac_muscle' else 'thumb_'+model_id
    destination = ROOT/'app/ui/resources/studio/model-vitrines'/f'{filename}.webp'
    destination.parent.mkdir(parents=True, exist_ok=True)
    plate.save(destination, quality=94, method=6)
    record = {'model': model_id, 'file': str(destination.relative_to(ROOT)),
              'size': list(plate.size), 'parts': len(model.items),
              'minimum_tissue_alpha': float(alpha.min()), 'renderer': 'application OpenGL',
              'method': 'black/white coverage pair from installed source geometry'}
    print(json.dumps(record), flush=True)
    target.release()
    renderer.release()
    return record


if __name__ == '__main__':
    app = QApplication([])
    context = moderngl.create_standalone_context(require=410)
    records = []
    requested=sys.argv[1:]
    if not requested or requested==['--missing']:
        from app.viewer.catalog import load_catalog
        from app.ui.model_vitrines import specimen_image
        requested=[entry.id for entry in load_catalog().values() if specimen_image(entry).isNull()]
    for model_id in requested:
        records.append(render(model_id, context))
        gc.collect()
    output = ROOT/'Reports/checkpoint3-alignment/catalogue-renders.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding='utf-8')
