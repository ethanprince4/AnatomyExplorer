"""Reference views: fixed states of a model (or the atlas) rendered through the app's own viewport, with a pick sample
and the exact camera and state used, so any other renderer can reproduce the same view.

    python make_reference.py model <model_id> <out_dir>
    python make_reference.py atlas <out_dir>

Writes <out_dir>/<name>/<state>.png (2560x1600), <state>.json (camera, state, settings, 16x10 pick grid) and
<name>/index.json. States: default; outer_hidden_zoomed_out; cut_plane; ghosted; exploded_mid; animation_mid (animated
models only). Item names/keys are stored next to indices so the same view can be rebuilt by name.
"""
import json
import math
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.perf import perfkit as pk                                  # noqa: E402
from tools.perf.viewer_session import LOGICAL_H, LOGICAL_W              # noqa: E402

GRID = (16, 10)
MODEL_STATES = ("default", "outer_hidden_zoomed_out", "cut_plane", "ghosted", "exploded_mid", "animation_mid")
ATLAS_STATES = ("default", "outer_hidden_zoomed_out", "cut_plane", "ghosted")


def camera_dict(c):
    return {"target": [float(x) for x in c.target], "distance": float(c.distance), "yaw_rad": float(c.yaw),
            "pitch_rad": float(c.pitch), "fov_deg": float(c.fov), "ortho": bool(getattr(c, "ortho", False)),
            "ortho_width": float(getattr(c, "ortho_width", 0.0)), "aspect": float(getattr(c, "aspect", 0.0)),
            "convention": "yaw 0 = camera on +Z looking toward -Z; y up; target orbited at distance"}


def rsettings_dict(r):
    import dataclasses
    return {k: (list(v) if isinstance(v, (tuple, list)) else v) for k, v in dataclasses.asdict(r).items()}


def save_png(arr, path):
    from PIL import Image
    Image.fromarray(arr).save(path, optimize=False, compress_level=1)


def pick_grid(pick_fn, name_fn):
    """pick_fn(QPointF) -> item id (or -1). 16 columns x 10 rows over the logical window, at cell centres."""
    from PySide6.QtCore import QPointF
    gx, gy = GRID
    ids, pts = [], []
    for j in range(gy):
        row = []
        for i in range(gx):
            x, y = (i + 0.5) * LOGICAL_W / gx, (j + 0.5) * LOGICAL_H / gy
            sid = int(pick_fn(QPointF(x, y)))
            row.append(sid)
            pts.append({"col": i, "row": j, "x_logical": x, "y_logical": y,
                        "x_px": x * pk.DPR, "y_px": y * pk.DPR, "id": sid, "name": name_fn(sid)})
        ids.append(row)
    return {"grid": [gx, gy], "logical_size": [LOGICAL_W, LOGICAL_H], "ids": ids, "points": pts}


# ---------------------------------------------------------------------------------------------- model viewer
def outer_items(model, visible):
    """Deterministic 'outer layers': among the visible items, those whose bounding box encloses the boxes of at least
    two other visible items (shells such as skin, wall, capsule), most-enclosing first, at most 40 percent of the
    visible items. If nothing encloses anything: the highest layer rank, else the two items with the largest box."""
    idx = [int(i) for i in np.flatnonzero(visible)]
    boxes = {i: model.item_bounds([i]) for i in idx}
    count = {}
    for i in idx:
        lo, hi = boxes[i]
        pad = 0.02 * float(np.linalg.norm(hi - lo))
        n = 0
        for j in idx:
            if j != i and np.all(boxes[j][0] >= lo - pad) and np.all(boxes[j][1] <= hi + pad):
                n += 1
        count[i] = n
    shells = sorted((i for i in idx if count[i] >= 2), key=lambda i: (-count[i], i))
    shells = shells[:max(1, int(0.4 * len(idx)))]
    if shells:
        return shells, "visible items whose bounding box encloses at least two other visible items (most enclosing first, at most 40 percent)"
    ranks = {i: model.items[i].rank for i in idx}
    top = max(ranks.values()) if ranks else 0
    hi_rank = [i for i in idx if ranks[i] == top]
    if hi_rank and len(hi_rank) < len(idx):
        return hi_rank, f"visible items of the highest layer rank ({top})"
    sizes = sorted(((float(np.linalg.norm(boxes[i][1] - boxes[i][0])), i) for i in idx), reverse=True)
    return [i for _, i in sizes[:2]], "the two visible items with the largest bounding box"


def model_states(sess):
    w, st, m = sess.w, sess.state, sess.model

    def reset():
        st.hidden[:] = False
        st.forced[:] = False
        st.isolated = None
        st.ghost_focus = None
        st.depth_cut = st.depth_band = 0.0
        w.sections = [None, None, None]
        w.cut_on = False
        w.set_explode(0.0)
        w.anim_t = float(m.clip_range[0]) if w.anim_kind() == "clip" else 0.0
        w.playing = False
        st._vis_dirty()
        w.reset_view(animate=False)
        w.camera.snap()
        w.invalidate_labels()

    reset()
    home = (w.camera.target.copy(), w.camera.distance, w.camera.yaw, w.camera.pitch)
    out = {}
    for name in MODEL_STATES:
        reset()
        info = {}
        if name == "outer_hidden_zoomed_out":
            ids, rule = outer_items(m, st.visible_mask())
            st.set_hidden(ids, True, undo=False)
            w.camera.distance = home[1] * 1.6
            info = {"hidden_item_indices": ids, "hidden_item_keys": [m.items[i].key for i in ids], "rule": rule,
                    "distance_factor": 1.6}
        elif name == "cut_plane":
            lo, hi = np.asarray(m.bounds_min, float), np.asarray(m.bounds_max, float)
            cl = [i for i in range(len(m.items)) if m.items[i].clip]
            cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
            pos = float(np.median(cx)) if cx else float(lo[0] + (hi[0] - lo[0]) * 0.5)
            w.sections[0] = [pos, False]
            info = {"sections": [{"axis": 0, "name": "Sagittal", "position_world": pos, "flip": False}, None, None],
                    "rule": "sagittal plane at the median x of the centres of the cuttable items",
                    "cuttable_items": len(cl), "items": len(m.items)}
        elif name == "ghosted":
            focus = [i for i in range(len(m.items)) if i % 3 == 0]
            st.set_ghost_focus(focus)
            info = {"ghost_focus_item_indices": focus, "ghost_focus_item_keys": [m.items[i].key for i in focus],
                    "rule": "items with index % 3 == 0 stay solid, the rest are ghosted"}
        elif name == "exploded_mid":
            w.set_explode(0.5)
            info = {"explode": 0.5}
        elif name == "animation_mid":
            kind = w.anim_kind()
            if kind is None:
                continue
            if kind == "procedural":
                w.anim_t = 0.5
            else:
                w.anim_t = float((m.clip_range[0] + m.clip_range[1]) / 2)
            info = {"anim_kind": kind, "anim_t": w.anim_t, "playing": False}
        out[name] = info
        yield name, info
    reset()


def run_model(model_id, out_dir):
    pk.env_setup()
    from tools.perf.viewer_session import ViewerSession, timed_prepare
    entry, model, load = timed_prepare(model_id)
    sess = ViewerSession(entry, model)
    if sess.error:
        raise RuntimeError(sess.error)
    root = Path(out_dir) / model_id
    root.mkdir(parents=True, exist_ok=True)
    w = sess.w
    index = {"model": model_id, "states": {}}
    for name, info in model_states(sess):
        sess.warm(2)
        arr = sess.grab_array()
        picks = pick_grid(lambda p: w.pick_at(p), lambda s: model.items[s].key if 0 <= s < len(model.items) else None)
        save_png(arr, root / f"{name}.png")
        replay = {
            "kind": "model_viewer", "model": model_id, "state": name, "state_detail": info,
            "window": {"logical": [LOGICAL_W, LOGICAL_H], "device_pixel_ratio": pk.DPR,
                       "physical": [pk.PHYS_W, pk.PHYS_H], "render_size": list(sess.render_size)},
            "camera": camera_dict(w.camera),
            "visible_item_indices": [int(i) for i in np.flatnonzero(sess.state.visible_mask())],
            "renderer_settings": rsettings_dict(w.rsettings),
            "user_settings": sess.settings,
            "opaque_materials": bool(sess.state.opaque_materials),
            "items": [{"index": it.index, "key": it.key, "name": it.name, "group": it.group} for it in model.items],
            "explode": w.explode, "anim_t": w.anim_t, "reveal_amount": w.reveal_amount,
            "gl_renderer": sess.ctx.info.get("GL_RENDERER"),
            "image": {"file": f"{name}.png", "size": [int(arr.shape[1]), int(arr.shape[0])],
                      "mean_rgb": [round(float(x), 3) for x in arr.reshape(-1, 3).mean(0)]},
            "picks": picks,
        }
        (root / f"{name}.json").write_text(json.dumps(replay, indent=1), encoding="utf-8")
        index["states"][name] = {"mean_rgb": replay["image"]["mean_rgb"],
                                 "distinct_ids": len({i for r in picks["ids"] for i in r if i >= 0})}
    index["states_missing"] = [s for s in MODEL_STATES if s not in index["states"]]
    (root / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    sess.close()
    return index


# ---------------------------------------------------------------------------------------------- atlas
def run_atlas(out_dir):
    pk.env_setup()
    from tools.perf.atlas_session import AtlasSession
    sess = AtlasSession()
    w, st, ds = sess.w, sess.state, sess.ds
    root = Path(out_dir) / "atlas"
    root.mkdir(parents=True, exist_ok=True)
    muscular = ds.system_index["muscular"]
    cardio = ds.system_index["cardiovascular"]
    cardio_sids = [i for i in range(ds.n) if int(ds.system_of[i]) == cardio]
    index = {"model": "atlas", "states": {}}

    def reset():
        st.hidden[:] = False
        st.forced[:] = False
        st.isolated = None
        st.ghost_focus = None
        st.depth_cut = st.depth_band = 0.0
        st.system_on[:] = [s["default_visible"] for s in ds.systems]
        w.clip_on = [False, False, False]
        w.clip_pos = [0.0, 0.0, 0.9]
        w.clip_flip = [False, False, False]
        st._vis_dirty()
        w.reset_view(animate=False)
        w.camera.update()
        st.render_changed.emit()

    reset()
    home_dist = w.camera.distance
    for name in ATLAS_STATES:
        reset()
        info = {}
        if name == "outer_hidden_zoomed_out":
            st.set_system(muscular, False, undo=False)
            w.camera.distance = home_dist * 1.6
            info = {"systems_hidden": ["muscular"], "distance_factor": 1.6,
                    "rule": "the muscular system is the outer layer of the default atlas view"}
        elif name == "cut_plane":
            mid = float((ds.scene_bbox[0][0] + ds.scene_bbox[1][0]) / 2)
            w.clip_on = [True, False, False]
            w.clip_pos = [mid, 0.0, 0.9]
            info = {"clip_on": w.clip_on, "clip_pos": w.clip_pos, "clip_mode": w.clip_mode,
                    "rule": "sagittal plane through the middle of the scene bounding box"}
        elif name == "ghosted":
            st.set_ghost_focus(cardio_sids)
            info = {"ghost_focus": "cardiovascular system", "n_solid": len(cardio_sids)}
        sess.warm(2)
        arr = sess.grab_array()
        picks = pick_grid(lambda p: w.pick_at(p),
                          lambda s: ds.structures[s]["name"] if 0 <= s < ds.n else None)
        save_png(arr, root / f"{name}.png")
        replay = {
            "kind": "atlas", "state": name, "state_detail": info,
            "window": {"logical": [LOGICAL_W, LOGICAL_H], "device_pixel_ratio": pk.DPR,
                       "physical": [pk.PHYS_W, pk.PHYS_H], "render_size": list(sess.r.size)},
            "camera": camera_dict(w.camera),
            "visible_structure_count": int(st.visible_mask().sum()),
            "user_settings": sess.settings,
            "gl_renderer": sess.ctx.info.get("GL_RENDERER"),
            "image": {"file": f"{name}.png", "size": [int(arr.shape[1]), int(arr.shape[0])],
                      "mean_rgb": [round(float(x), 3) for x in arr.reshape(-1, 3).mean(0)]},
            "picks": picks,
        }
        (root / f"{name}.json").write_text(json.dumps(replay, indent=1), encoding="utf-8")
        index["states"][name] = {"mean_rgb": replay["image"]["mean_rgb"],
                                 "distinct_ids": len({i for r in picks["ids"] for i in r if i >= 0})}
    index["states_missing"] = [s for s in MODEL_STATES if s not in index["states"]]
    (root / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    sess.close()
    return index


def main():
    kind = sys.argv[1]
    t0 = time.perf_counter()
    try:
        if kind == "model":
            idx = run_model(sys.argv[2], sys.argv[3])
            name = sys.argv[2]
        else:
            idx = run_atlas(sys.argv[2])
            name = "atlas"
        print(f"reference {name}: {len(idx['states'])} states, missing {idx['states_missing']} "
              f"{time.perf_counter() - t0:.1f}s", flush=True)
    except Exception:
        print("reference failed:", traceback.format_exc()[-900:], flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
