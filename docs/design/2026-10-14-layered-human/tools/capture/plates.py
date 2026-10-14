"""Atlas plate capture: each plate is grabbed on black and on white so its alpha can be solved exactly."""
import os, sys, traceback
# Raw captures go here (black and white PNGs, ID maps). Set LH_RAW before launching the app.
RAW = os.path.join(os.environ.get("LH_RAW", os.path.expanduser("~/lh-plates/raw")), "")
os.makedirs(RAW, exist_ok=True)

def log(*a):
    print("PLATE", *a, flush=True)

def safe(fn):
    def inner(w, *a, **k):
        try:
            return fn(w, *a, **k)
        except Exception:
            log("FAIL", fn.__name__, a)
            traceback.print_exc(); sys.stdout.flush()
    return inner

@safe
def prep(w, width, height):
    for key, val in (("section_labels", False), ("show_landmarks", False), ("show_structure_labels", False),
                     ("show_hover_tooltip", False), ("hover_outline", False), ("show_perf", False),
                     ("show_gizmo", False), ("custom_background", True), ("render_scale", 1.0)):
        try:
            w.on_setting(key, val, sync=True)
        except Exception:
            traceback.print_exc()
    w.left_dock.hide(); w.right_dock.hide()
    w.resize(width, height)
    log("prep", width, height, w.viewport.width(), w.viewport.height())

@safe
def bg(w, hexcolor):
    w.on_setting("bg_top", hexcolor, sync=True)
    w.on_setting("bg_bottom", hexcolor, sync=True)
    w.viewport.update()

@safe
def grab(w, name):
    img = w.viewport.grabFramebuffer()
    ok = img.save(RAW + name + ".png")
    log("grab", name, ok, img.width(), img.height())

@safe
def systems(w, keys):
    keys = keys.split(",") if isinstance(keys, str) else keys
    w.state.set_systems([s["key"] in keys for s in w.ds.systems])

@safe
def default_systems(w):
    w.state.reset_visibility()

@safe
def depth(w, cut, band=None):
    w.view_panel.set_depth(cut, band)

@safe
def selcolor(w, hexcolor):
    w.on_setting("selection_color", hexcolor, sync=True)

@safe
def clip(w, idx, on, frac=None, flip=None):
    w.view_panel.set_clip(idx, on, frac, flip)

@safe
def view(w, name):
    w.viewport.set_view(name)

@safe
def orbit(w, dx, dy):
    w.viewport.camera.orbit(float(dx), float(dy)); w.viewport.update()

@safe
def dolly(w, amount):
    w.viewport.camera.dolly(float(amount)); w.viewport.update()

@safe
def clear(w):
    w.escape(); w.escape()

import json
import numpy as np

@safe
def idmap(w, name):
    vp = w.viewport
    vp.makeCurrent()
    try:
        vp._ensure_pick_frame()
        tex = vp.renderer.id_tex
        W, H = tex.size
        a = np.frombuffer(tex.read(), dtype="f4").reshape(H, W)[::-1]
        ids = np.rint(a).astype(np.int32) - 1
    finally:
        vp.doneCurrent()
    np.savez_compressed(RAW + name + "__ids.npz", ids=ids)
    present = np.unique(ids[ids >= 0])
    names = {int(s): w.ds.structures[s]["name"] for s in present if s < w.ds.n}
    with open(RAW + name + "__ids.json", "w") as f:
        json.dump(names, f)
    log("ids", name, W, H, len(names))

@safe
def select_names(w, needles, exclude=""):
    needles = [n.lower() for n in needles.split("|")]
    excl = [e.lower() for e in exclude.split("|") if e]
    vis = w.state.visible_mask()
    sids = [i for i, s in enumerate(w.ds.structures)
            if any(n in s["name"].lower() for n in needles) and not any(e in s["name"].lower() for e in excl) and vis[i]]
    w.state.select(sids)
    log("select", needles, len(sids), [w.ds.structures[i]["name"] for i in sids][:8])

@safe
def deselect(w):
    w.state.clear_selection()

@safe
def radiology(w, case):
    w.open_radiology(case)

@safe
def info(w):
    vp = w.viewport
    log("viewport", vp.width(), vp.height(), "cam", getattr(vp.camera, "yaw", None), getattr(vp.camera, "pitch", None))

@safe
def radiology_nolabels(w, case):
    w.open_radiology(case)

@safe
def hide_rad_labels(w):
    try:
        w._show_radiology_labels(False)
    except Exception:
        traceback.print_exc()
    log("rad labels off", w.viewport.width(), w.viewport.height())

@safe
def hide_names(w, needles):
    needles = [n.lower() for n in needles.split("|")]
    sids = [i for i, s in enumerate(w.ds.structures) if any(n in s["name"].lower() for n in needles)]
    w.state.set_hidden(sids, True)
    log("hidden", len(sids))

@safe
def close_rad(w):
    try:
        w.close_radiology()
    except Exception:
        traceback.print_exc()

import math

@safe
def frame_names(w, needles, scale=1.4, dy=0.0, dx=0.0):
    """Anterior view framed on the bounds of the named structures: their height times `scale` fills the frame."""
    needles = [n.lower() for n in needles.split("|")]
    sids = [i for i, s in enumerate(w.ds.structures) if any(n in s["name"].lower() for n in needles)]
    b = w.ds.bounds_of(sids)
    lo, hi = np.asarray(b[0], float), np.asarray(b[1], float)
    cam = w.viewport.camera
    cam._anim = None
    cam.yaw, cam.pitch = 0.0, 0.0
    c = (lo + hi) / 2
    c[0] += dx; c[1] += dy
    cam.target = c
    cam.distance = (hi[1] - lo[1]) * scale / (2 * math.tan(math.radians(cam.fov) / 2)) + (hi[2] - lo[2]) / 2
    w.viewport.update()
    log("frame", len(sids), lo.round(3).tolist(), hi.round(3).tolist(), cam.target.round(3).tolist(), round(cam.distance, 3))
