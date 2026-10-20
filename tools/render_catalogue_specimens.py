"""Render catalogue plates from installed geometry and the viewer's tissue defaults.

Uses the approved reference's black/white render pair to retain real silhouette
coverage, including translucent tissue. No model or source material is changed.
"""
import argparse
import gc
import hashlib
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
from app.viewer.procedural import cutaway_planes
from app.viewer.renderer import FrameState, Renderer, Settings

# The spleen's authored coordinate home faces its capsule. Its teaching front
# is the exposed cutaway, matching the supplied overview camera on the -Z side.
CATALOGUE_ANGLES = {'spleen': (math.radians(145.22), math.radians(27.48))}

# Catalogue illustrations have their own composition; these records never change
# the model's saved cameras, opening view or visibility. Start with an authored
# teaching view so its hidden parts, reveal state and native clipping are retained.
PREVIEW_PROFILES = {
    'vein_wall': {'view': '01 Overview', 'yaw': 75, 'pitch': 18, 'cut_on': False},
    'muscular_artery': {'view': '01 Overview', 'yaw': 75, 'pitch': 18, 'cut_on': False},
    'elastic_artery': {'view': '01 Overview', 'yaw': 75, 'pitch': 18, 'cut_on': False},
    'trachea_wall': {'view': '02 Wall layers', 'yaw': 65, 'pitch': 25},
    'blood_cells': {'view': 'Overview', 'pitch': 65},
    'cardiac_muscle': {'view': 'Longitudinal section', 'yaw': 155, 'pitch': 18},
    # Full anatomy with all authored cutaway insets, oblique toward their +X
    # cut-face side. Render after the breast-skin repair is integrated.
    'female_reproductive': {
        'view': 'Anterior pelvic overview', 'yaw': 45, 'pitch': 18, 'hidden': [],
    },
    'hepatobiliary': {'view': 'Visceral overview', 'yaw': 15, 'pitch': -20},
    'thyroid_parathyroid_review_v2': {
        # The native corner cut falls between the follicle rows. Use the same
        # coronal Section display as the viewer through the front row instead.
        'view': '01 Tissue architecture', 'yaw': -8, 'pitch': 20,
        'section': {'axis': 'z', 'at': 0.28, 'keep': 'negative'},
    },
    'compact_bone': {'view': '01 Overview', 'yaw': 28, 'pitch': 48},
}


def preview_frame(model, model_id, profile):
    """Resolve an illustration's authored display state before framing it."""
    visible = np.ones(len(model.items), dtype=bool)
    rec = model.cameras.get(profile.get('view')) if profile else None
    if profile and rec is None:
        raise ValueError(f"{model_id}: missing preview view {profile['view']!r}")
    hidden = set((profile or {}).get('hidden', (rec or {}).get('hidden')) or ())
    show_groups = set((profile or {}).get('show_groups') or ())
    for item in model.items:
        visible[item.index] = item.key not in hidden or item.group in show_groups
    _, alpha = tissue_opacity(model, model_id)
    frame = FrameState(visible=visible, alpha=alpha, opaque_materials=False)
    state = (rec or {}).get('state')
    model.evaluate(model.clip_range[0], state if state != 'assembled' else None, 1.0)
    cut = getattr(model, 'cutaway', None)
    cut_on = (profile or {}).get('cut_on', (rec or {}).get('cut_on', False))
    if cut is not None and cut_on:
        frame.clip_planes = tuple(cutaway_planes(cut))
        frame.clip_on, frame.clip_mode = (True, True, False), 1
    section = (profile or {}).get('section')
    if section:
        axis = {'x': 0, 'z': 1, 'y': 2}[section['axis']]
        normal = np.zeros(3)
        normal[[0, 2, 1][axis]] = -1 if section['keep'] == 'negative' else 1
        planes = [(0., 1., 0., 0.)] * 3
        planes[axis] = (*normal.tolist(), -float(normal[[0, 2, 1][axis]]) * section['at'])
        frame.clip_planes = tuple(planes)
        frame.clip_on = tuple(i == axis for i in range(3))
        frame.clip_mode = 0
    return frame, rec


def fit_preview(model, camera, frame):
    """Fit visible, sectioned geometry in the chosen direction, with a small margin.

    Bounded samples retain the cut surfaces when choosing the composition and
    avoid allocating another full transformed copy of a large tissue model.
    The final image is additionally cropped to its rendered silhouette.
    """
    points = []
    planes = np.asarray(frame.clip_planes)
    enabled = np.asarray(frame.clip_on, dtype=bool)
    for part in model.parts:
        if not frame.visible[part.item]:
            continue
        vertices = model.vertices[part.vertex_base:part.vertex_base + part.vertex_count, :3]
        vertices = vertices[::max(1, len(vertices) // 8192)]
        matrix = model.part_matrix(part)
        world = vertices @ matrix[:3, :3].T + matrix[:3, 3]
        if enabled.any() and model.items[part.item].clip:
            distances = world @ planes[enabled, :3].T + planes[enabled, 3]
            keep = (distances >= 0).any(axis=1) if frame.clip_mode else (distances >= 0).all(axis=1)
            world = world[keep]
        if len(world):
            points.append(world)
    if not points:
        raise RuntimeError('No visible preview geometry after clipping')
    points = np.concatenate(points)
    basis = np.asarray(camera.basis())
    projected = points @ basis.T
    low, high = projected.min(axis=0), projected.max(axis=0)
    camera.target = ((low + high) / 2) @ basis
    camera.ortho = True
    camera.ortho_width = float(max((high-low)[:2])) * 1.10
    camera.distance = camera.fit_distance(float(np.linalg.norm(high-low)) / 2, 1)


def render(model_id, ctx, *, profile=None, output_dir=None):
    entry = find_entry(model_id)
    model = entry.prepare_cpu(LoadToken()) if hasattr(entry, 'prepare_cpu') else entry.load()
    profile = PREVIEW_PROFILES.get(model_id) if profile is None else profile
    frame, rec = preview_frame(model, model_id, profile)
    visible, alpha = frame.visible, frame.alpha
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
    if rec is not None:
        camera.set_record(rec, duration=0)
        if 'yaw' in profile:
            camera.yaw = math.radians(profile['yaw'])
        if 'pitch' in profile:
            camera.pitch = math.radians(profile['pitch'])
        fit_preview(model, camera, frame)
    else:
        yaw, pitch = CATALOGUE_ANGLES.get(model_id) or getattr(model, 'home', None) or (math.radians(35), math.radians(24))
        radius = float(np.linalg.norm(high-low)) / 2
        camera.animate_to((low+high)/2, camera.fit_distance(radius*.95, 1), yaw, pitch, 0)
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
    destination = ((Path(output_dir) if output_dir else ROOT/'app/ui/resources/studio/model-vitrines')/f'{filename}.webp').resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    plate.save(destination, quality=94, method=6)
    record = {'model': model_id, 'file': str(destination.relative_to(ROOT)) if destination.is_relative_to(ROOT) else str(destination),
              'size': list(plate.size), 'parts': len(model.items),
              'visible_parts': int(visible.sum()), 'profile': profile,
              'hidden': [it.key for it in model.items if not visible[it.index]],
              'state': (rec or {}).get('state', 'assembled'),
              'clip_on': list(frame.clip_on), 'clip_planes': frame.clip_planes,
              'camera': {'yaw': math.degrees(camera.yaw), 'pitch': math.degrees(camera.pitch),
                         'target': camera.target.tolist(), 'orthographic': camera.ortho,
                         'width': camera.ortho_width, 'distance': camera.distance},
              'minimum_tissue_alpha': float(alpha.min()), 'renderer': 'application OpenGL',
              'method': 'black/white coverage pair from installed source geometry',
              'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}
    print(json.dumps(record), flush=True)
    target.release()
    renderer.release()
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models', nargs='*')
    parser.add_argument('--missing', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT/'Reports/checkpoint3-alignment/catalogue-renders.json')
    args = parser.parse_args()
    app = QApplication([])
    context = moderngl.create_standalone_context(require=410)
    records = []
    requested=args.models
    if not requested or args.missing:
        from app.viewer.catalog import load_catalog
        from app.ui.model_vitrines import specimen_image
        requested=[entry.id for entry in load_catalog().values() if specimen_image(entry).isNull()]
    for model_id in requested:
        records.append(render(model_id, context, output_dir=args.output_dir))
        gc.collect()
    output = args.report
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding='utf-8')
