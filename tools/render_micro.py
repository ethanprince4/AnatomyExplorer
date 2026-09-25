"""Render a microanatomy model offscreen with the app's own renderer.

Same shaders, ambient occlusion, cut-away caps and tissue shading the viewer uses, so what comes out is what the
model will look like in the app.

Usage: python tools/render_micro.py <model_id> [-o out.png] [--yaw 40] [--pitch 25] [--zoom 1] [--size 900]
       [--no-cut | --cut] [--explode 0] [--hide substr,...] [--only substr,...] [--focus substr,...]
       [--time T] [--frames N [--slow S]]

<model_id> can also be a downloaded Sketchfab model: sketchfab:<uid>, or just the first characters of its uid.
--focus selects the matching parts and ghosts everything else, as X-ray does in the viewer.
An animated model is drawn at --time T seconds into its cycle (default: its rest pose, as built). --frames N renders N frames evenly over
one cycle into an animated GIF (-o should end in .gif, played S times slower than real time) plus a contact strip
(<out>_strip.png).
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
    ap.add_argument("--center", default=None, help="x,y,z the camera orbits and zooms on (default: the model's middle)")
    ap.add_argument("--time", type=float, default=None, help="seconds into an animated model's cycle")
    ap.add_argument("--frames", type=int, default=0, help="render one animation cycle as N frames (GIF)")
    ap.add_argument("--slow", type=float, default=1.0, help="GIF playback this many times slower than real time")
    a = ap.parse_args()

    import moderngl
    from PIL import Image
    from PySide6.QtGui import QGuiApplication  # noqa: F401
    from app.camera import OrbitCamera
    from app.micro.anim import dataset_for
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
        ds = dataset_for(model)
        # the viewer's opening camera (MicroView.reset_view)
        yaw, pitch = (math.degrees(x) for x in getattr(model, "home_view", (-0.62, 0.42)))
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
    cam.target = (bmin + bmax) / 2 if not a.center else np.array([float(v) for v in a.center.split(",")])
    cam.distance = float(np.linalg.norm(bmax - bmin)) * 1.25 / max(a.zoom, 1e-3)
    cam.yaw, cam.pitch = math.radians(yaw), math.radians(pitch)

    # same planes as the viewer: cutaway normals through cut_at, the second one flipped (MicroView.__init__)
    n0 = np.array(model.cutaway[0], float)
    n1 = -np.array(model.cutaway[1], float)
    cx, cz = getattr(model, "cut_at", (0.0, 0.0))
    planes = [(*n0, -float(n0 @ (cx, 0.0, 0.0))), (*n1, -float(n1 @ (0.0, 0.0, cz))), (0.0, 1.0, 0.0, 0.0)]
    # same default as the viewer: the model's cut-away is on unless the model opens uncut (MicroModel.cut_on)
    cut = (getattr(model, "cut_on", True) or a.cut) and not a.no_cut
    on = (1, 1, 0) if cut else (0, 0, 0)
    out_fbo = ctx.framebuffer([ctx.renderbuffer((S, S), 4)])
    anim = getattr(ds, "animation", None)

    def shot(t):
        if anim is not None and t is not None:
            phase = (t / anim.period) % 1.0
            r.set_animation(ds.anim_frame(phase), phase)
        r.render(out_fbo, cam, settings, (planes, on, 1), has_selection=bool(state.selected))
        return Image.frombytes("RGB", (S, S), out_fbo.read(components=3)).transpose(Image.FLIP_TOP_BOTTOM)

    out = a.out or str(ROOT / "logs" / f"app_{a.model.replace(':', '_')}.{'gif' if a.frames else 'png'}")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if a.frames and anim is not None:
        times = [anim.period * k / a.frames for k in range(a.frames)]
        frames = [shot(t) for t in times]
        ms = int(round(anim.period / a.frames * 1000 * a.slow))
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=ms, loop=0, optimize=False)
        cols = min(a.frames, 6)
        rows = -(-a.frames // cols)
        th = S // 3
        strip = Image.new("RGB", (cols * th, rows * th))
        for k, f in enumerate(frames):
            strip.paste(f.resize((th, th)), ((k % cols) * th, (k // cols) * th))
        strip.save(str(Path(out).with_suffix("")) + "_strip.png")
    else:
        shot(a.time).save(out)
    print(out, ds.counts)


if __name__ == "__main__":
    main()
