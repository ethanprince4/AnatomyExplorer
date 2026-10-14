"""Turn black/white plate captures into RGBA plates (PNG master + WebP) and compute label anchors from ID maps.

Atlas plates: captured by the app (`--script`, see make_script.py) on black and on white; the atlas background on
white is 255 * vignette(u, v), the vignette of COMPOSITE_FS in app/shaders.py. Anchors: the "most clearly visible
point" of a structure, i.e. the point deepest inside its visible region (distance transform), as the app's own label
placer does. Usage: process_plates.py RAW_DIR MASTER_DIR ASSET_DIR
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

RAW, MASTER, ASSETS = (Path(p) for p in sys.argv[1:4])
MASTER.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)


def vignette(h, w):
    v = (np.arange(h)[:, None] + 0.5) / h
    u = (np.arange(w)[None, :] + 0.5) / w
    return 1.0 - ((u - 0.5) ** 2 + (v - 0.5) ** 2) * 0.35


def solve(name):
    B = np.asarray(Image.open(RAW / f"{name}__b.png").convert("RGB")).astype(np.float64)
    W = np.asarray(Image.open(RAW / f"{name}__w.png").convert("RGB")).astype(np.float64)
    h, w = B.shape[:2]
    bw = 255.0 * vignette(h, w)[..., None]
    a = np.clip((1.0 - (W - B) / np.maximum(bw, 1.0)).mean(axis=2), 0, 1)
    a[a < 0.004] = 0
    rgb = np.where(a[..., None] > 1e-3, B / np.maximum(a[..., None], 1e-3), 0.0)
    return np.dstack([np.clip(rgb, 0, 255), a * 255]).round().astype(np.uint8), a


def box_of(a, pad=40):
    ys, xs = np.nonzero(a > 0.01)
    h, w = a.shape
    return [int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad)), int(min(w, xs.max() + pad)), int(min(h, ys.max() + pad))]


# plates that share one crop box (same camera, different selection colour)
GROUPS = {"hero": "hero_sel_", "hero26": "hero26_sel_"}
meta = {}
names = sorted({p.name.rsplit("__", 1)[0] for p in RAW.glob("*__b.png")})
shared = {}
prev = {}
if (ASSETS / "plates.json").exists():
    prev = json.loads((ASSETS / "plates.json").read_text()).get("plates", {})
for n in names:
    raw_t = max((RAW / f"{n}__b.png").stat().st_mtime, (RAW / f"{n}__w.png").stat().st_mtime)
    if n in prev and (ASSETS / f"{n}.webp").exists() and (ASSETS / f"{n}.webp").stat().st_mtime > raw_t:
        meta[n] = prev[n]
        group = next((g for g, pre in GROUPS.items() if n.startswith(pre)), None)
        if group:
            shared.setdefault(group, prev[n]["box"])
        continue
    rgba, a = solve(n)
    group = next((g for g, pre in GROUPS.items() if n.startswith(pre)), None)
    if group:
        shared.setdefault(group, box_of(a))
        box = shared[group]
    else:
        box = box_of(a)
    x0, y0, x1, y1 = box
    img = Image.fromarray(rgba[y0:y1, x0:x1], "RGBA")
    img.save(MASTER / f"{n}.png", optimize=True)
    img.save(ASSETS / f"{n}.webp", quality=90, method=6)
    meta[n] = {"box": box, "full": [int(a.shape[1]), int(a.shape[0])], "size": [x1 - x0, y1 - y0]}
    print(n, meta[n]["size"], flush=True)

# ------------------------------------------------------------------------------------------- anchors
# ID map -> plate it belongs to (same camera)
IDMAPS = {"hero": "hero_sel_7cc8da", "hero26": "hero26_sel_7cc8da", "peel40": "peel40_ids", "thorax": "thorax_close",
          "thoraxpeeled": "thorax_peeled", "cxr": "cxr_model", "cxreff": "cxr_effusion_model", "secinf": "section_inferior",
          "secobl": "section_oblique", "thoraxchest": "thorax_chest"}
TARGETS = {
    "hero": {
        "biceps": ["Long head of biceps brachii", "Short head of biceps brachii"],
        "deltoid": ["Acromial part of deltoid muscle", "Clavicular part of deltoid muscle"],
        "pectoralis": ["Abdominal part of pectoralis major muscle", "Clavicular head of pectoralis major muscle",
                       "Sternocostal head of pectoralis major muscle"],
        "brachioradialis": ["Brachioradialis muscle"],
        "brachialis": ["Brachialis muscle"],
        "rectus_abdominis": ["Rectus abdominis muscle"],
        "serratus": ["Serratus anterior muscle"],
        "sternocleidomastoid": ["Sternocleidomastoid muscle"],
        "sartorius": ["Sartorius muscle"],
        "rectus_femoris": ["Rectus femoris muscle"],
        "vastus_lateralis": ["Vastus lateralis muscle"],
        "vastus_medialis": ["Vastus medialis muscle"],
        "tibialis_anterior": ["Tibialis anterior muscle"],
        "gracilis": ["Gracilis muscle"],
        "adductor_longus": ["Adductor longus"],
        "flexor_carpi_radialis": ["Flexor carpi radialis"],
        "frontalis": ["Frontalis muscle"],
        "platysma": ["Platysma"],
        "patella": ["Patella"],
        "clavicle": ["Clavicle"],
        "linea_alba": ["Linea alba"],
        "gastrocnemius": ["Medial head of gastrocnemius"],
        "temporalis": ["Temporalis muscle"],
    },
    "peel40": {
        "liver": ["Liver"], "stomach": ["Stomach"], "smallint": ["Jejunum"], "transverse_colon": ["Transverse colon"],
        "ascending_colon": ["Ascending colon"], "descending_colon": ["Descending colon"], "heart": ["Right ventricle"],
        "pleura": ["Pleura"], "diaphragm": ["Diaphragm"], "ribs": ["External intercostal muscles", "Internal intercostal muscles"],
        "quadratus": ["Iliacus muscle"], "rectus_femoris": ["Rectus femoris muscle"], "adductor": ["Adductor magnus", "Adductor longus"],
        "tibia": ["Tibia"], "biceps": ["Long head of biceps brachii"], "brachialis": ["Brachialis muscle"],
    },
    "cxr": {
        "c1": ["Trachea"], "c2": ["Clavicle"], "c3": ["Scapula"], "c4": ["Humerus"], "c5": ["Superior vena cava"],
        "c6": ["Thoracic aorta"], "c7": ["Right atrium"], "c8": ["Right ventricle"], "c9": ["Right pulmonary artery"],
        "c11": ["Sixth rib"], "c12": ["Diaphragm"], "c16": ["Middle lobe of right lung", "Superior lobe of right lung", "Inferior lobe of right lung"],
        "c17": ["Superior lobe of left lung", "Inferior lobe of left lung"], "c18": ["Vertebra T5"], "arch": ["Aortic arch"],
    },
    "secinf": {
        "lv": ["Left ventricle"], "rv": ["Right ventricle"], "ra": ["Right atrium"], "la": ["Left atrium"],
        "lung_l": ["Inferior lobe of left lung", "Superior lobe of left lung"], "lung_r": ["Middle lobe of right lung", "Inferior lobe of right lung"],
        "vert": ["Vertebra T8"], "sternum": ["Body of sternum"], "pec": ["Sternocostal head of pectoralis major muscle"],
        "lat": ["Latissimus dorsi muscle"], "serratus": ["Serratus anterior muscle"], "liver": ["Posterior medial segment of liver (VIII)"],
        "diaphragm": ["Diaphragm"], "pleura": ["Pleura"], "aorta": ["Thoracic aorta"], "oesophagus": ["Oesophagus", "Esophagus"],
        "trapezius": ["Descending part of trapezius muscle"], "papillary": ["Inferior papillary muscle of left ventricle"],
        "intercostal": ["External intercostal muscles", "Internal intercostal muscles"],
    },
    "thoraxpeeled": {
        "serratus": ["Serratus anterior muscle"], "ext_ic": ["External intercostal muscles"], "int_ic": ["Internal intercostal muscles"],
        "ext_oblique": ["External abdominal oblique muscle"], "sternum": ["Body of sternum"],
    },
}
TARGETS["thoraxchest"] = dict(TARGETS["thoraxpeeled"], clavicle=["Clavicle"], deltoid=["Clavicular part of deltoid muscle", "Acromial part of deltoid muscle"],
                              rectus_abdominis=["Rectus abdominis muscle"], biceps=["Long head of biceps brachii", "Short head of biceps brachii"],
                              sternocleidomastoid=["Sternocleidomastoid muscle"], costal=["Costal cartilage"], lat=["Latissimus dorsi muscle"])
TARGETS["hero26"] = TARGETS["hero"]


def anchors_for(idname, plate, targets):
    data = np.load(RAW / f"{idname}__ids.npz")["ids"]
    names = {int(k): v for k, v in json.loads((RAW / f"{idname}__ids.json").read_text()).items()}
    x0, y0, x1, y1 = meta[plate]["box"]
    out = {}
    body = data >= 0
    xs = np.nonzero(body.any(axis=0))[0]
    mid = (xs.min() + xs.max()) / 2
    for key, wanted in targets.items():
        sids = [s for s, n in names.items() if n in wanted]
        mask = np.isin(data, sids)
        if not mask.any():
            print("anchor missing", key)
            continue
        for side, sl in (("vl", slice(0, int(mid))), ("vr", slice(int(mid), data.shape[1]))):
            m = np.zeros_like(mask)
            m[:, sl] = mask[:, sl]
            if m.sum() < 30:
                continue
            lab, n = ndimage.label(m)
            sizes = ndimage.sum(m, lab, range(1, n + 1))
            big = lab == (1 + int(np.argmax(sizes)))
            dist = ndimage.distance_transform_edt(big)
            y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
            ys, xs_ = np.nonzero(big)
            out[f"{key}.{side}"] = {"x": int(x - x0), "y": int(y - y0), "r": float(dist[y, x]),
                                    "bbox": [int(xs_.min() - x0), int(ys.min() - y0), int(xs_.max() - x0), int(ys.max() - y0)],
                                    "area": int(big.sum())}
    return out


anchors = {}
for idname, plate in IDMAPS.items():
    if (RAW / f"{idname}__ids.npz").exists() and plate in meta and idname in TARGETS:
        anchors[plate] = anchors_for(idname, plate, TARGETS[idname])
        print("anchors", plate, len(anchors[plate]))
(ASSETS / "plates.json").write_text(json.dumps({"plates": meta, "anchors": anchors}, indent=1))
