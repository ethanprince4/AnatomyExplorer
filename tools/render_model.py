"""Render a 3D model offscreen with the app's own model viewer renderer.

Same shaders, lighting, ambient occlusion, cut faces and tissue shading as the model viewer, so what comes out is
what the model looks like in the app.

Usage: python tools/render_model.py <model> [-o out.png] [--view NAME] [--state teased] [--yaw 40] [--pitch 25]
       [--zoom 1] [--size 900] [--no-cut | --cut] [--section axis:pos[:flip]] [--explode 0]
       [--hide substr,...] [--only substr,...] [--focus substr,...] [--center x,y,z] [--time T] [--frames N [--slow S]]

<model> is a catalogue id (whole_heart, kidney_nephron, cardiac_muscle, a procedural model such as thin_skin, or a
downloaded model: sketchfab:<uid> or the first characters of its uid), or the path of any .glb / .gltf file.
--view picks one of the model's stored views (V1, "Corpuscle", ...); otherwise the camera frames the model from its
home direction (--yaw / --pitch in degrees override it). --section cuts the model like Section in the viewer:
axis 0 sagittal, 1 coronal, 2 transverse, pos 0..1 across the model. --focus selects the matching parts and x-rays
everything else, as X-ray does in the viewer. An animated model is drawn at --time T seconds into its cycle (default:
its rest pose); --frames N renders N frames evenly over one cycle into an animated GIF (-o should end in .gif, played
S times slower than real time) plus a contact strip (<out>_strip.png).
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def find_entry(key):
    from app.viewer.catalog import FileEntry, load_catalog
    if key.lower().endswith((".glb", ".gltf")) and Path(key).is_file():
        return FileEntry(key)
    cat = load_catalog()
    if key in cat:
        return cat[key]
    tail = key.split(":", 1)[-1]
    hits = [e for e in cat.values() if e.kind == "downloaded" and e.uid.startswith(tail)]
    if len(hits) == 1:
        return hits[0]
    raise SystemExit(f"no model {key!r}; ids: {', '.join(sorted(cat))}")


def main(argv=None, default_prefix="model"):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--view", default=None)
    ap.add_argument("--state", default=None)
    ap.add_argument("--yaw", type=float, default=None)
    ap.add_argument("--pitch", type=float, default=None)
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--size", default="900", help="N (square) or WxH")
    ap.add_argument("--no-cut", action="store_true")
    ap.add_argument("--cut", action="store_true", help="apply the cut-away even to a model that opens uncut")
    ap.add_argument("--section", default=None, help="axis:pos[:flip], e.g. 1:0.5:1 for a coronal cut")
    ap.add_argument("--explode", type=float, default=0.0)
    ap.add_argument("--hide", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--focus", default=None)
    ap.add_argument("--center", default=None, help="x,y,z the camera orbits and zooms on (default: the model's middle)")
    ap.add_argument("--time", type=float, default=None, help="seconds into an animated model's cycle")
    ap.add_argument("--frames", type=int, default=0, help="render one animation cycle as N frames (GIF)")
    ap.add_argument("--slow", type=float, default=1.0, help="GIF playback this many times slower than real time")
    a = ap.parse_args(argv)

    import moderngl
    from PIL import Image
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])     # QColor needs the Qt GUI module loaded
    from app.viewer.camera import OrbitCamera
    from app.viewer.procedural import cutaway_planes
    from app.viewer.renderer import FrameState, Renderer, Settings
    from app.viewer.viewport import SECTION_AXES

    entry = find_entry(a.model)
    model = entry.load()
    n = len(model.items)
    if "x" in a.size.lower():
        W, H = (int(v) for v in a.size.lower().split("x"))
    else:
        W = H = int(a.size)
    vis = np.ones(n, dtype=bool)
    if a.only or a.hide:
        only = [s.strip().lower() for s in a.only.split(",")] if a.only else None
        hide = [s.strip().lower() for s in a.hide.split(",")] if a.hide else []
        for it in model.items:
            nm = f"{it.name} {it.key} {it.group}".lower()
            if (only and not any(s in nm for s in only)) or any(s in nm for s in hide):
                vis[it.index] = False
    fs = FrameState(visible=vis)
    if a.focus:
        want = [s.strip().lower() for s in a.focus.split(",")]
        sel = [it.index for it in model.items if any(w in f"{it.name} {it.key}".lower() for w in want)]
        if sel:
            fs.selected = frozenset(sel)
            ghost = vis.copy()
            ghost[sel] = False
            fs.ghost = ghost
    cut = getattr(model, "cutaway", None)
    if a.section:
        bits = a.section.split(":")
        axis, frac = int(bits[0]), float(bits[1])
        flip = len(bits) > 2 and bits[2] not in ("0", "")
        lo, hi = model.bounds_min, model.bounds_max
        k = [0, 2, 1][axis]
        pos = lo[k] + (hi[k] - lo[k]) * frac
        nrm = -np.array(SECTION_AXES[axis]) if flip else np.array(SECTION_AXES[axis])
        p = np.zeros(3)
        p[k] = pos
        planes = [(0.0, 1.0, 0.0, 0.0)] * 3
        planes[axis] = (*nrm, -float(nrm @ p))
        on = [False] * 3
        on[axis] = True
        fs.clip_planes, fs.clip_on, fs.clip_mode = tuple(planes), tuple(on), 0
    elif cut is not None and ((cut["on"] or a.cut) and not a.no_cut):
        fs.clip_planes, fs.clip_on, fs.clip_mode = tuple(cutaway_planes(cut)), (True, True, False), 1
    model.set_explode(a.explode)

    ctx = moderngl.create_standalone_context(require=410)
    r = Renderer(ctx)
    r.set_model(model)
    s = Settings()
    for k, v in getattr(model, "look_defaults", {}).items():
        setattr(s, k, v)
    cam = OrbitCamera()
    lo, hi = model.world_bounds(visible_only=False, visible=vis)
    cam.set_scene(model.bounds_min, model.bounds_max)
    cam.aspect = W / H
    rec = model.cameras.get(a.view) if a.view else None
    if a.view and rec is None:
        raise SystemExit(f"{entry.id} has no view {a.view!r}; views: {', '.join(model.camera_order) or 'none'}")
    if rec is not None:
        cam.set_record(rec, duration=0.0, fit=(model.bounds_min, model.bounds_max, W / H))
        hidden = set(rec.get("hidden") or ())          # what the view hides, as picking it in the viewer does
        for it in model.items:
            if it.key in hidden:
                vis[it.index] = False
        state = a.state or rec.get("state")
    else:
        home = getattr(model, "home", None)
        if home is None and "V1" in model.cameras:
            r1 = model.cameras["V1"]
            _t, _d, yaw0, pitch0, *_ = OrbitCamera.record_pose(r1, cam.fov)
            home = (yaw0, pitch0)
        yaw0, pitch0 = home or (math.radians(35.0), math.radians(24.0))
        cam.yaw = math.radians(a.yaw) if a.yaw is not None else yaw0
        cam.pitch = math.radians(a.pitch) if a.pitch is not None else pitch0
        centre = (lo + hi) / 2 if not a.center else np.array([float(v) for v in a.center.split(",")])
        radius = float(np.linalg.norm(hi - lo)) / 2
        cam.animate_to(centre, cam.fit_distance(radius * 0.95, W / H) / max(a.zoom, 1e-3), cam.yaw, cam.pitch, 0.0)
        state = a.state
    model.evaluate(model.clip_range[0], state if state and state != "assembled" else None, 1.0)
    fbo = ctx.framebuffer([ctx.renderbuffer((W, H), 4)])
    anim = getattr(model, "animation", None)

    def shot(t):
        if anim is not None:
            fs.anim_t = ((t or 0.0) / anim.period) % 1.0
            fs.anim_frame = model.anim_frame(fs.anim_t)
        for _ in range(3):             # the screen-space bounce reads the previous frame: let it settle
            r.render(fbo, (W, H), cam, s, fs)
        return Image.fromarray(r.read_final(fbo, (W, H)).copy())

    out = a.out or str(ROOT / "logs" / f"{default_prefix}_{entry.id.replace(':', '_')}.{'gif' if a.frames else 'png'}")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if a.frames and anim is not None:
        times = [anim.period * k / a.frames for k in range(a.frames)]
        frames = [shot(t) for t in times]
        ms = int(round(anim.period / a.frames * 1000 * a.slow))
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=ms, loop=0, optimize=False)
        cols = min(a.frames, 6)
        rows = -(-a.frames // cols)
        tw, th = W // 3, H // 3
        strip = Image.new("RGB", (cols * tw, rows * th))
        for k, f in enumerate(frames):
            strip.paste(f.resize((tw, th)), ((k % cols) * tw, (k // cols) * th))
        strip.save(str(Path(out).with_suffix("")) + "_strip.png")
    else:
        shot(a.time).save(out)
    print(out, {"parts": n, "triangles": model.triangle_count})
    r.release()


if __name__ == "__main__":
    main()
