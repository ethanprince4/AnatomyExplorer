"""Model viewer plates on black and white with the app's own renderer (based on tools/render_model.py).
Usage: render_models.py JOBS.json  -> writes $LH_MODELS/mraw/<name>__b.png, __w.png and $LH_MODELS/mrgba/<name>.png"""
import json, math, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[5]; sys.path.insert(0, str(ROOT))
# mraw/ (black and white captures) and mrgba/ (matted plates and anchors) go under LH_MODELS
import os
OUT = Path(os.environ.get("LH_MODELS", os.path.expanduser("~/lh-plates/models")))
(OUT / "mraw").mkdir(parents=True, exist_ok=True); (OUT / "mrgba").mkdir(parents=True, exist_ok=True)

def run(job, ctx, cache):
    import moderngl
    from PIL import Image
    from app.viewer.camera import OrbitCamera
    from app.viewer.procedural import cutaway_planes
    from app.viewer.renderer import FrameState, Renderer, Settings
    from app.viewer.viewport import SECTION_AXES
    sys.argv = ["x"]
    from tools.render_model import find_entry
    key = job["model"]
    if key not in cache:
        entry = find_entry(key)
        if hasattr(entry, "prepare_cpu"):
            from app.viewer.model_loading import LoadToken
            cache[key] = entry.prepare_cpu(LoadToken())
        else:
            cache[key] = entry.load()
    model = cache[key]
    W, H = job.get("size", [1600, 1600])
    n = len(model.items)
    vis = np.ones(n, dtype=bool)
    only = [s.lower() for s in job.get("only", [])]; hide = [s.lower() for s in job.get("hide", [])]
    for it in model.items:
        nm = f"{it.name} {it.key} {it.group}".lower()
        if (only and not any(s in nm for s in only)) or any(s in nm for s in hide):
            vis[it.index] = False
    fs = FrameState(visible=vis)
    sel = []
    if job.get("select"):
        want = [s.lower() for s in job["select"]]
        sel = [it.index for it in model.items if any(w_ in f"{it.name} {it.key}".lower() for w_ in want)]
        fs.selected = frozenset(sel)
        if job.get("xray"):
            ghost = vis.copy(); ghost[sel] = False; fs.ghost = ghost
    cut = getattr(model, "cutaway", None)
    if job.get("section"):
        axis, frac, flip = job["section"]
        lo, hi = model.bounds_min, model.bounds_max
        k = [0, 2, 1][axis]; pos = lo[k] + (hi[k] - lo[k]) * frac
        nrm = -np.array(SECTION_AXES[axis]) if flip else np.array(SECTION_AXES[axis])
        p = np.zeros(3); p[k] = pos
        planes = [(0.0, 1.0, 0.0, 0.0)] * 3; planes[axis] = (*nrm, -float(nrm @ p))
        on = [False] * 3; on[axis] = True
        fs.clip_planes, fs.clip_on, fs.clip_mode = tuple(planes), tuple(on), 0
    elif cut is not None and ((cut["on"] or job.get("cut")) and not job.get("no_cut")):
        fs.clip_planes, fs.clip_on, fs.clip_mode = tuple(cutaway_planes(cut)), (True, True, False), 1
    model.set_explode(job.get("explode", 0.0))
    r = Renderer(ctx); r.set_model(model)
    s = Settings()
    for k_, v in getattr(model, "look_defaults", {}).items():
        setattr(s, k_, v)
    s.bounce = 0.0
    if job.get("outline"):
        h = job["outline"].lstrip("#"); s.outline = tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
    cam = OrbitCamera()
    lo, hi = model.world_bounds(visible_only=False, visible=vis)
    cam.set_scene(model.bounds_min, model.bounds_max); cam.aspect = W / H
    view = job.get("view"); rec = model.cameras.get(view) if view else None
    if view and rec is None:
        print("NO VIEW", key, view, "views:", model.camera_order); return
    if rec is not None:
        cam.set_record(rec, duration=0.0, fit=(model.bounds_min, model.bounds_max, W / H))
        for it in model.items:
            if it.key in set(rec.get("hidden") or ()):
                vis[it.index] = False
        state = job.get("state") or rec.get("state")
    else:
        home = getattr(model, "home", None)
        if home is None and "V1" in model.cameras:
            _t, _d, yaw0, pitch0, *_ = OrbitCamera.record_pose(model.cameras["V1"], cam.fov); home = (yaw0, pitch0)
        yaw0, pitch0 = home or (math.radians(35.0), math.radians(24.0))
        cam.yaw = math.radians(job["yaw"]) if "yaw" in job else yaw0
        cam.pitch = math.radians(job["pitch"]) if "pitch" in job else pitch0
        centre = (lo + hi) / 2
        radius = float(np.linalg.norm(hi - lo)) / 2
        cam.animate_to(centre, cam.fit_distance(radius * 0.95, W / H) / max(job.get("zoom", 1.0), 1e-3), cam.yaw, cam.pitch, 0.0)
        state = job.get("state")
    model.evaluate(model.clip_range[0], state if state and state != "assembled" else None, 1.0)
    fbo = ctx.framebuffer([ctx.renderbuffer((W, H), 4)])
    shots = {}
    for tag, col in (("b", (0.0, 0.0, 0.0)), ("w", (1.0, 1.0, 1.0))):
        s.background = (col, col)
        for _ in range(3):
            r.render(fbo, (W, H), cam, s, fs)
        img = r.read_final(fbo, (W, H)).copy()
        Image.fromarray(img).save(OUT / "mraw" / f"{job['name']}__{tag}.png")
        shots[tag] = img.astype(np.float64)
        if tag == "b" and job.get("anchors"):
            ids, _flags = r.read_ids()
            shots["ids"] = None if ids is None else ids.copy()
    B, Wt = shots["b"], shots["w"]
    bw = np.median(np.concatenate([Wt[:4].reshape(-1, 3), Wt[-4:].reshape(-1, 3)]), axis=0)
    bb = np.median(np.concatenate([B[:4].reshape(-1, 3), B[-4:].reshape(-1, 3)]), axis=0)
    a = 1.0 - ((Wt - B) / np.maximum(bw - bb, 1.0)).mean(axis=2)
    a = np.clip(a, 0, 1); a[a < 0.004] = 0
    rgb = np.clip((B - bb * (1 - a[..., None])) / np.maximum(a[..., None], 1e-3), 0, 255)
    rgba = np.dstack([rgb, a * 255]).round().astype(np.uint8)
    im = Image.fromarray(rgba, "RGBA")
    box = (0, 0, W, H)
    if job.get("crop", True):
        ys, xs = np.nonzero(a > 0.01)
        if len(xs):
            pad = 24
            box = (int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad)), int(min(W, xs.max() + pad)), int(min(H, ys.max() + pad)))
            im = im.crop(box)
    if job.get("anchors") and shots.get("ids") is not None:
        from scipy import ndimage
        ids = shots["ids"]
        out = {}
        for key, needles in job["anchors"].items():
            idx = [it.index for it in model.items if any(nd.lower() in it.name.lower() for nd in needles)]
            m = np.isin(ids, idx)
            if not m.any():
                print("ANCHOR MISSING", key, flush=True); continue
            lab, n_ = ndimage.label(m)
            sizes = ndimage.sum(m, lab, range(1, n_ + 1))
            big = lab == (1 + int(np.argmax(sizes)))
            dist = ndimage.distance_transform_edt(big)
            y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
            ys_, xs_ = np.nonzero(big)
            out[key] = {"x": int(x - box[0]), "y": int(y - box[1]), "r": float(dist[y, x]),
                        "bbox": [int(xs_.min() - box[0]), int(ys_.min() - box[1]), int(xs_.max() - box[0]), int(ys_.max() - box[1])]}
        (OUT / "mrgba" / f"{job['name']}.anchors.json").write_text(json.dumps(out, indent=1))
    im.save(OUT / "mrgba" / f"{job['name']}.png", optimize=True)
    print("MODEL", job["name"], im.size, "bg", bw.round(1), bb.round(1), "views:", ",".join(model.camera_order[:12]), flush=True)
    fbo.release(); r.release()

def main():
    import moderngl
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    jobs = json.loads(Path(sys.argv[1]).read_text())
    ctx = moderngl.create_standalone_context(require=410)
    cache = {}
    for job in jobs:
        try:
            run(job, ctx, cache)
        except Exception as e:
            import traceback; traceback.print_exc(); print("FAIL", job.get("name"), e, flush=True)

main()
