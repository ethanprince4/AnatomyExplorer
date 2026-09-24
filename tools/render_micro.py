"""Render a microanatomy model offscreen with the app's own renderer.

Same shaders, ambient occlusion, cut-away caps and tissue shading the viewer uses, so what comes out is what the
model will look like in the app.

Usage: python tools/render_micro.py <model_id> [-o out.png] [--yaw 40] [--pitch 25] [--zoom 1] [--size 900]
       [--no-cut | --cut] [--explode 0] [--hide substr,...] [--only substr,...] [--focus substr,...]

<model_id> can also be a downloaded Sketchfab model: sketchfab:<uid>, or just the first characters of its uid.
--focus selects the matching parts and ghosts everything else, as X-ray does in the viewer.
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULTS = {
    "fov": 32.0, "render_scale": 1.0, "ssao": True, "ao_strength": 1.0, "antialias": True,
    "background_top": "#20242b", "background_bottom": "#12141a", "selection_color": "#4dc7ff",
    "hover_color": "#ffd966", "ghost_alpha": 0.1, "color_mode": 0, "outline": True,
}


class Settings(dict):
    def get(self, key, default=None):
        return dict.get(self, key, DEFAULTS.get(key, default))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--yaw", type=float, default=None)
    ap.add_argument("--pitch", type=float, default=None)
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--no-cut", action="store_true")
    ap.add_argument("--cut", action="store_true", help="apply the cut-away even to a model that opens uncut")
    ap.add_argument("--explode", type=float, default=0.0)
    ap.add_argument("--hide", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--focus", default=None)
    a = ap.parse_args()

    import moderngl
    from PIL import Image
    from PySide6.QtGui import QGuiApplication  # noqa: F401
    from app.camera import OrbitCamera
    from app.micro.base import MicroDataset
    from app.micro.registry import MODELS
    from app.renderer import Renderer
    from app.state import SceneState

    from app.sketchfab_local import load_local, local_uids
    local = [u for u in local_uids() if u == a.model.split(":", 1)[-1] or u.startswith(a.model.split(":", 1)[-1])]
    if a.model not in MODELS and local:
        model = load_local(local[0])
        ds = model.dataset()
        yaw, pitch = (math.degrees(x) for x in model.home_view)
    else:
        model = MODELS[a.model]
        ds = MicroDataset(model)
        yaw, pitch = 40.0, 25.0
    yaw = a.yaw if a.yaw is not None else yaw
    pitch = a.pitch if a.pitch is not None else pitch
    settings = Settings()
    state = SceneState(ds, settings)
    if a.only or a.hide:
        only = [s.strip().lower() for s in a.only.split(",")] if a.only else None
        hide = [s.strip().lower() for s in a.hide.split(",")] if a.hide else []
        for sid, st in enumerate(ds.structures):
            n = st["name"].lower()
            if (only and not any(s in n for s in only)) or any(s in n for s in hide):
                state.hidden[sid] = True
        state._vis_dirty()
    if a.focus:
        want = [s.strip().lower() for s in a.focus.split(",")]
        sids = [sid for sid, st in enumerate(ds.structures) if any(w in st["name"].lower() for w in want)]
        if sids:
            state.select(sids)
            state.set_ghost_focus(sids)

    ctx = moderngl.create_standalone_context()
    verts, idx = ds.load_geometry() if not a.explode else (ds.vertex_bytes(a.explode),
                                                           ds._indices.view(np.uint8).ravel())
    r = Renderer(ctx, ds, verts, idx, cap_depth=getattr(ds, "cap_depth", False))
    S = a.size
    r.resize(S, S)
    r.screen_size = (S, S)
    r.update_state(state.build_texture())

    bmin, bmax = ds.scene_bbox
    cam = OrbitCamera(settings.get("fov", 32.0))
    cam.target = (bmin + bmax) / 2
    cam.distance = float(np.linalg.norm(bmax - bmin)) * 1.25 / max(a.zoom, 1e-3)
    cam.yaw, cam.pitch = math.radians(yaw), math.radians(pitch)

    n0 = np.array(model.cutaway[0], float)
    n1 = -np.array(model.cutaway[1], float)
    planes = [(*n0, 0.0), (*n1, 0.0), (0.0, 1.0, 0.0, 0.0)]
    # same default as the viewer: the model's cut-away is on unless the model opens uncut (MicroModel.cut_on)
    cut = (getattr(model, "cut_on", True) or a.cut) and not a.no_cut
    on = (1, 1, 0) if cut else (0, 0, 0)
    out_fbo = ctx.framebuffer([ctx.renderbuffer((S, S), 4)])
    r.render(out_fbo, cam, settings, (planes, on, 1), has_selection=bool(state.selected))
    img = Image.frombytes("RGB", (S, S), out_fbo.read(components=3)).transpose(Image.FLIP_TOP_BOTTOM)
    out = a.out or str(ROOT / "logs" / f"app_{a.model.replace(':', '_')}.png")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(out, ds.counts)


if __name__ == "__main__":
    main()
