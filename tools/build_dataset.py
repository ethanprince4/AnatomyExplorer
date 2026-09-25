"""Convert the raw Blender extraction (data/extracted) into the app's runtime dataset (data/anatomy).

Outputs:
  vertices.bin   interleaved float32 pos(3) + float32 normal(3) + uint16 structure id + uint16 material id
  indices.bin    uint32 triangle indices
  anatomy.json   systems, materials, structures, tree, landmarks, search metadata
  definitions.json  cleaned definition texts keyed by definition key
"""
import colorsys
import csv
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "extracted"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "anatomy"
OUT.mkdir(parents=True, exist_ok=True)

t0 = time.time()
report = []


def rep(*a):
    s = " ".join(str(x) for x in a)
    report.append(s)
    print(s)


meta = json.loads((SRC / "meta.json").read_text(encoding="utf-8"))
texts = json.loads((SRC / "texts.json").read_text(encoding="utf-8"))
positions = np.fromfile(SRC / "positions.f32", dtype=np.float32).reshape(-1, 3)
normals = np.fromfile(SRC / "normals.f32", dtype=np.float32).reshape(-1, 3)
indices = np.fromfile(SRC / "indices.u32", dtype=np.uint32).reshape(-1, 3)
tri_slot = np.fromfile(SRC / "tri_material_slot.u8", dtype=np.uint8)
assert len(tri_slot) == len(indices)

# --------------------------------------------------------------------------- systems
SYSTEMS = [
    # key, display name, source collection, default visible, legend color
    ("skeletal", "Skeletal system", "1: Skeletal system", True, "#e3d9c6"),
    ("joints", "Joints & ligaments", "3: Joints", True, "#b9bfa8"),
    ("muscular", "Muscular system", "4: Muscular system", True, "#b5433a"),
    ("fascia", "Fascia", None, False, "#cfd8cc"),
    ("attachments", "Muscle attachments", "2: Muscular insertions", False, "#d8422e"),
    ("cardiovascular", "Cardiovascular system", "5: Cardiovascular system", True, "#c62828"),
    ("lymphatic", "Lymphatic system", "6: Lymphoid organs", True, "#7cc46a"),
    ("nervous", "Nervous system & sense organs", "7: Nervous system & Sense organs", True, "#f2d04b"),
    ("visceral", "Visceral organs", "8: Visceral systems", True, "#cf7f76"),
    ("regions", "Skin & surface regions", "9: Regions of human body", False, "#e3b79a"),
    ("reference", "Reference lines & planes", "Reference lines, reference planes, movements", False, "#8fa3b8"),
]
SYS_BY_COLL = {s[2]: i for i, s in enumerate(SYSTEMS) if s[2]}
TREE_GROUP_SUBSYSTEMS = {"skeletal", "joints", "regions"}

# Rule-based subsystems. Each rule: (name, tags) where a tag matches collection names, ancestor tree-group
# names (lowercase substring) or the structure name. First match wins; unmatched structures go to "Other".
SUBSYSTEM_RULES = {
    "muscular": [("Bursae & tendon sheaths", ["bursa", "tendon sheath"]),
                 ("Muscles of head", ["cranial part", "muscles of head", "facial muscles"]),
                 ("Muscles of neck", ["cervical part", "muscles of neck"]),
                 ("Muscles of upper limb", ["upper limb"]),
                 ("Muscles of lower limb", ["lower limb"]),
                 ("Muscles of trunk & back", ["dorsal part", "thoracic part", "abdominal part", "pelvic part",
                                              "perine", "back", "thorax", "abdomen", "trunk"])],
    "fascia": [("Head & neck fascia", ["@head", "@neck"]),
               ("Upper limb fascia", ["@upper_limb_l", "@upper_limb_r"]),
               ("Lower limb fascia", ["@lower_limb_l", "@lower_limb_r"]),
               ("Trunk & pelvic fascia", [""])],
    "attachments": [("Origins", ["$Origin"]), ("Insertions", ["$Insertion"])],
    "cardiovascular": [("Heart", ["heart", "cardiac"]),
                       ("Pulmonary vessels", ["pulmonary"]),
                       ("Arteries", ["arterial system", "systemic arteries", "artery", "arteries", "aorta"]),
                       ("Veins", ["venous system", "systemic veins", "vein", "sinus", "plexus"])],
    "lymphatic": [("Lymph nodes", ["node"]), ("Lymphoid organs", [""])],
    "nervous": [("Brain", ["#nucleus of solitary", "#optic tract", "#olfactory tract", "#mammillothalamic"]),
                ("Spinal cord", ["#cauda equina", "#root of spinal nerve", "#filum terminale", "#conus medullaris",
                                 "#spinal cord", "#tract","#fasciculus", "#horn of spinal", "#intermedio", "#central canal",
                                 "#intermediate substance"]),
                ("Brain", ["#nucle"]),
                ("Cranial nerves", ["#cochlear nerve", "#vestibular nerve", "#chorda tympani", "#nerve (i", "#nerve (v", "#nerve (x"]),
                ("Sense organs",["sense organs", "eyeball", "eye", " ear", "auricle", "tympan", "cochle", "vestibul",
                                  "semicircular", "cornea", "lens", "iris", "auditory tube", "retina", "lacrimal"]),
                ("Cranial nerves", ["cranial nerves"]),
                ("Spinal cord", ["spinal cord", "tract", "fasciculus", "horn of spinal", "central canal",
                                 "intermediolateral", "intermediomedial", "intermediate substance"]),
                ("Brain", ["brain", "cerebr", "cerebell", "telencephalon", "diencephalon", "mesencephalon",
                           "medulla", "pons", "nucleus", "choroid plexus", "falx", "ventricle", "meninges"]),
                ("Peripheral nerves & plexuses", ["peripheral nervous system", "nerve", "plexus", "ganglion"])],
    "visceral": [("Digestive system", ["digestive system", "pharynx", "soft palate", "oral"]),
                 ("Respiratory system", ["respiratory system", "nasal"]),
                 ("Urinary system", ["urinary system"]),
                 ("Genital system", ["genital system"]),
                 ("Endocrine glands", ["endocrine", "parathyroid", "thyroid", "adrenal", "pituitary"]),
                 ("Peritoneum & mesenteries", ["omentum", "meso", "peritone", "abdominopelvic cavity",
                                               "thoracic cavity"])],
    "reference": [("Planes", ["planes"]), ("Lines", ["lines", " line"]), ("Movements", ["movements"]),
                  ("Orientation terms", ["general terms", "orientations"])],
}

DEFAULT_OFF_SUBSYSTEMS = set()

REGIONS = [
    ("head", "Head", ["Head"]),
    ("neck", "Neck", ["Neck"]),
    ("thorax", "Thorax", ["Thorax"]),
    ("abdomen", "Abdomen & pelvis", ["Abdomen", "Pelvis", "Perineum"]),
    ("back", "Back", ["Back"]),
    ("upper_limb_r", "Right upper limb", ["Right upper limb", "Right hand"]),
    ("upper_limb_l", "Left upper limb", ["Left upper limb", "Left hand"]),
    ("lower_limb_r", "Right lower limb", ["Right lower limb", "Right foot"]),
    ("lower_limb_l", "Left lower limb", ["Left lower limb", "Left foot"]),
]

# --------------------------------------------------------------------------- materials
MUSCLE_FUNCTIONS = ["Abductor", "Adductor", "Biarticular", "Depressor", "Diaphragm", "Extension", "Extension fingers",
                    "Extension hand/foot", "Extensor extremities", "External rotation", "Flexion", "Flexion fingers",
                    "Flexion hand/foot", "Ingestion", "Internal rotator", "Levator", "Masticator",
                    "Orbicularis/Constrictor", "Phonation", "Superficial", "Trapezius", "Heart"]

RAINBOW = {  # Z-Anatomy's segment indices -> distinguishable, softened hues
    str(i): colorsys.hsv_to_rgb(((i - 1) * 0.125) % 1.0, 0.55, 0.92) for i in range(1, 10)
}


def hexrgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def material_style(name):
    """Returns (category, realistic hex, alpha, distinct rgb or None)."""
    n = name or ""
    num = re.search(r"-(\d+)'*$", n)
    seg = RAINBOW.get(num.group(1)) if num else None
    if n.startswith("Origin") or n == "Muscular origin":
        return "origin", "#d9472f", 1.0, None
    if n.startswith("End-") or n == "Muscular ending":
        return "insertion", "#3f74d9", 1.0, None
    if n.startswith("Bone"):
        return "bone", "#e6dcc8", 1.0, seg
    if n.startswith("Suture"):
        return "suture", "#b3a283", 1.0, seg
    if n.startswith("Teeth-roots"):
        return "tooth", "#e2cfa8", 1.0, None
    if n in ("Teeth", "Dentine"):
        return "tooth", "#f3efe4", 1.0, None
    if n.startswith("Cartilage"):
        return "cartilage", "#b9d3d8", 1.0, None
    if n == "Ligament":
        return "ligament", "#c8cbb4", 1.0, None
    if n == "Articular capsule":
        return "capsule", "#bdb1c9", 1.0, None
    if n == "Bursa":
        return "bursa", "#8fbbe3", 0.55, None
    if n == "Tendon":
        return "tendon", "#ebe6d8", 1.0, None
    if n == "Fascia":
        return "fascia", "#d5ddd2", 1.0, None
    if n in MUSCLE_FUNCTIONS:
        if n == "Heart":
            return "heart", "#a8352f", 1.0, None
        i = MUSCLE_FUNCTIONS.index(n)
        return "muscle", "#a8453d", 1.0, colorsys.hsv_to_rgb((i * 0.61803) % 1.0, 0.55, 0.85)
    if n == "Artery":
        return "artery", "#c7292b", 1.0, None
    if n == "Pulmonary artery":
        return "pulm_artery", "#4058d6", 1.0, None
    if n == "Vein":
        return "vein", "#2f55b8", 1.0, None
    if n == "Pulmonary vein":
        return "pulm_vein", "#d23c4b", 1.0, None
    if n == "Ductus":
        return "duct", "#79b85a", 1.0, None
    if n.startswith("Nerve"):
        return "nerve", "#f0cf45", 1.0, seg
    if n.startswith("Nucleus (afferent"):
        return "nucleus", "#4f86ad", 1.0, None
    if n.startswith("Nucleus (efferent"):
        return "nucleus", "#b0504b", 1.0, None
    if n.startswith("Nucleus"):
        return "nucleus", "#a3614e", 1.0, None
    if n == "White matter":
        return "white_matter", "#efe8dc", 1.0, None
    if n in ("Brain", "Brain-Inner", "Interlobar sulci"):
        return "brain", "#e0aa9c" if n != "Interlobar sulci" else "#bb8676", 1.0, None
    if n in ("Frontal lobe", "Parietal lobe", "Temporal lobe", "Occipital lobe", "Limbic lobe", "Insula"):
        lobes = ["Frontal lobe", "Parietal lobe", "Temporal lobe", "Occipital lobe", "Limbic lobe", "Insula"]
        return "brain", "#e0aa9c", 1.0, colorsys.hsv_to_rgb(lobes.index(n) / 6.0, 0.5, 0.92)
    if n == "Cerebellum":
        return "brain", "#c98b7b", 1.0, None
    if n == "LCR":
        return "csf", "#86d4e0", 0.4, None
    if n == "Eye":
        return "eye", "#f3f0e8", 1.0, None
    if n == "Cornea":
        return "eye", "#a6d0de", 0.35, None
    if n == "Iris":
        return "eye", "#6b4a33", 1.0, None
    if n.startswith("Lymph"):
        return "lymph", "#86c46f", 1.0, seg
    if n == "Gland":
        return "gland", "#d6a06a", 1.0, None
    if n.startswith("Organ"):
        return "organ", "#b85f50", 1.0, seg
    if n.startswith("Lung"):
        return "lung", "#e4a7a2", 1.0, seg
    if n.startswith("Bronchi"):
        return "airway", "#cbdbe2", 1.0, seg
    if n == "Intestine":
        return "gut", "#d99d88", 1.0, None
    if n.startswith("Mucosa"):
        return "mucosa", "#cf7f76", 1.0, None
    if n == "Peritoneum":
        return "serosa", "#e9d692", 0.5, None
    if n in ("Biliary system", "Gallbladder"):
        return "biliary", "#5f8c3c", 1.0, None
    if n == "Fat":
        return "fat", "#e9c86c", 1.0, None
    if n == "Nail":
        return "nail", "#ecd0c0", 1.0, None
    if n == "Skin-in":
        return "skin", "#c98270", 1.0, None
    if n.startswith("Skin"):
        return "skin", "#e3b89c", 1.0, seg
    if n in ("Directions", "Lines", "Planes", "Movement", "Text") or n.startswith("Text"):
        return "reference", "#8fa3b8", 1.0, None
    if n == "Black":
        return "other", "#2a2a2a", 1.0, None
    return "other", "#c9b8a8", 1.0, None


SYSTEM_DEFAULT_MAT = {
    "skeletal": "Bone", "joints": "Ligament", "muscular": "Adductor", "attachments": "Muscular origin",
    "cardiovascular": "Artery", "lymphatic": "Lymph-1", "nervous": "Nerve", "visceral": "Organ",
    "regions": "Skin", "reference": "Lines", "fascia": "Fascia",
}

material_names = sorted(set(n for o in meta["objects"] for n in o["materials"] if n) | set(SYSTEM_DEFAULT_MAT.values()))
mat_index = {n: i for i, n in enumerate(material_names)}
assert len(material_names) < 65535
materials_out = []
for n in material_names:
    cat, hx, alpha, distinct = material_style(n)
    real = hexrgb(hx)
    materials_out.append({
        "name": n, "category": cat, "color": [round(c, 4) for c in real], "alpha": alpha,
        "distinct": [round(c, 4) for c in (distinct if distinct is not None else real)],
    })
rep("materials", len(materials_out), Counter(m["category"] for m in materials_out))

# --------------------------------------------------------------------------- names
SUFFIX_RE = re.compile(r"^(?P<base>.*?)(?:\.(?P<kind>[oe])(?P<num>\d*)(?P<side1>[lr])?|\.(?P<side2>[lr]))?$")
DUP_RE = re.compile(r"\.\d{3}$")


def parse_name(raw):
    raw = DUP_RE.sub("", raw)
    m = SUFFIX_RE.match(raw)
    base = m.group("base")
    kind = m.group("kind")
    side = m.group("side1") or m.group("side2") or ""
    return base, kind, m.group("num") or "", side


def display(base):
    s = base.strip()
    if s.startswith("(") and s.endswith(")") and s.count("(") == 1:
        s = s[1:-1].strip()
    s = re.sub(r"\s+", " ", s)
    return s[:1].upper() + s[1:] if s else s


def has_letters(s):
    return any(ch.isalpha() and ord(ch) < 0x2000 for ch in s)


coll_count = Counter(c for o in meta["objects"] for c in o["collections"])
coll_parents = defaultdict(set)
for cname, cinfo in meta["collections"].items():
    for ch in cinfo["children"]:
        coll_parents[ch].add(cname)


def ancestor_collections(names):
    out = set()
    stack = list(names)
    while stack:
        c = stack.pop()
        if c in out:
            continue
        out.add(c)
        stack.extend(coll_parents.get(c, ()))
    return out


# --------------------------------------------------------------------------- latin / TA2
latin = {}
tr = texts.get("Translations", "")
for line in tr.splitlines()[1:]:
    parts = line.split(";")
    if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
        latin.setdefault(parts[0].strip().lower(), parts[1].strip())
ta2 = {}
with open(RAW / "TA2.csv", encoding="utf-8-sig") as f:
    for line in f:
        line = line.strip().strip('"')
        parts = line.split(";")
        if len(parts) >= 3 and parts[0].isdigit():
            ta2.setdefault(parts[1].strip().lower(), (parts[0], parts[2].strip()))


def lookup_terms(dname):
    k = dname.lower()
    cands = [k, re.sub(r"\s+muscle$", "", k), k + " muscle", re.sub(r"\s*\([^)]*\)$", "", k)]
    lat = next((latin[c] for c in cands if c in latin), None)
    t = next((ta2[c] for c in cands if c in ta2), None)
    if lat is None and t:
        lat = t[1]
    return lat, (t[0] if t else None)


# --------------------------------------------------------------------------- structures
objects = meta["objects"]
keep = []
for o in objects:
    if o["name"].endswith(".g"):
        continue
    if "Cross section planes" in o["collections"]:
        continue
    keep.append(o)
rep("objects kept", len(keep), "of", len(objects))

text_keys = set(texts.keys())
structures = []
name_to_sid = {}
for sid, o in enumerate(keep):
    base, kind, num, side = parse_name(o["name"])
    dbase, _, _, _ = parse_name(o["data_name"])
    sys_idx = next((SYS_BY_COLL[c] for c in o["collections"] if c in SYS_BY_COLL), None)
    colls_all = ancestor_collections(o["collections"])
    if sys_idx is None:
        sys_idx = next((SYS_BY_COLL[c] for c in colls_all if c in SYS_BY_COLL), len(SYSTEMS) - 1)
    skey = SYSTEMS[sys_idx][0]
    name = display(base)
    if not has_letters(name):
        specific = sorted((c for c in o["collections"] if c not in SYS_BY_COLL), key=lambda c: coll_count[c])
        name = f"Unlabeled branch ({specific[0]})" if specific else "Unlabeled structure"
    if kind:
        role = "Origin" if kind == "o" else "Insertion"
        label = f"{name} — {role.lower()}" + (f" {num}" if num else "")
    else:
        role = None
        label = name
    def_key = None
    for cand in (dbase.strip(), base.strip(), dbase, base, "(" + name + ")", name):
        if cand in text_keys:
            def_key = cand
            break
    lat, taid = lookup_terms(name)
    sub = None
    if skey == "muscular" and (o["materials"] == ["Fascia"] or "Fascia" in colls_all or "Fasciae" in colls_all):
        skey = "fascia"
    regions = [rk for rk, _, tags in REGIONS if any(t in colls_all for t in tags)]
    slot_mats = [mat_index.get(m) if m else None for m in o["materials"]]
    rec = {
        "id": sid,
        "raw": o["name"],
        "name": label,
        "base": name,
        "side": {"l": "Left", "r": "Right"}.get(side, ""),
        "role": role,
        "system": skey,
        "subsystem": sub,
        "type": o["type"],
        "def": def_key,
        "latin": lat,
        "ta2": taid,
        "regions": regions,
        "collections": sorted(c for c in o["collections"] if c not in SYS_BY_COLL and c != "Bonus collection"),
        "i_start": o["i_start"],
        "i_count": o["i_count"],
        "bbox": [o["bbox_min"], o["bbox_max"]],
        "centroid": o["centroid"],
        "_slot_mats": slot_mats,
        "_v": (o["v_start"], o["v_count"]),
        "_parent": o["parent"],
        "_colls": colls_all,
    }
    structures.append(rec)
    name_to_sid[o["name"]] = sid

rep("system counts", Counter(s["system"] for s in structures))
rep("with definition", sum(1 for s in structures if s["def"]), "latin", sum(1 for s in structures if s["latin"]),
    "ta2", sum(1 for s in structures if s["ta2"]))

# Regions for untagged structures: nearest tagged centroid (same side of body where applicable)
tagged = [s for s in structures if s["regions"]]
tc = np.array([s["centroid"] for s in tagged])
filled = 0
for s in structures:
    if not s["regions"] and s["system"] != "reference":
        d = np.linalg.norm(tc - np.array(s["centroid"]), axis=1)
        s["regions"] = list(tagged[int(np.argmin(d))]["regions"])
        filled += 1
rep("regions inferred for", filled)

# Innervation: muscular structures tagged with a collection named after a nerve structure
nerve_bases = defaultdict(list)
for s in structures:
    if s["system"] == "nervous":
        nerve_bases[s["base"]].append(s["id"])
innerv_count = 0
for s in structures:
    if s["system"] in ("muscular",):
        nv = sorted(c for c in s["collections"] if display(c) in nerve_bases)
        if nv:
            s["innervation"] = [display(c) for c in nv]
            innerv_count += 1
rep("structures with innervation", innerv_count)

# --------------------------------------------------------------------------- vertex split by material
t1 = time.time()
n_tris = len(indices)
tri_obj = np.full(n_tris, -1, dtype=np.int32)
tri_gmat = np.zeros(n_tris, dtype=np.int64)
sys_default_mat = {k: mat_index[v] for k, v in SYSTEM_DEFAULT_MAT.items()}
for s in structures:
    a = s["i_start"] // 3
    b = a + s["i_count"] // 3
    tri_obj[a:b] = s["id"]
    lut = np.array([m if m is not None else sys_default_mat[s["system"]] for m in (s["_slot_mats"] or [None])], dtype=np.int64)
    slots = np.minimum(tri_slot[a:b], len(lut) - 1)
    tri_gmat[a:b] = lut[slots]

valid = tri_obj >= 0
tri_idx = indices[valid].astype(np.int64)
tri_obj_v = tri_obj[valid]
tri_mat_v = tri_gmat[valid]
corner_keys = tri_idx * 1024 + np.repeat(tri_mat_v, 3).reshape(-1, 3)
uniq, inverse = np.unique(corner_keys.ravel(), return_inverse=True)
src_vert = uniq // 1024
vmat = (uniq % 1024).astype(np.uint16)

vert_obj_src = np.full(len(positions), 0, dtype=np.uint16)
for s in structures:
    vs, vc = s["_v"]
    vert_obj_src[vs:vs + vc] = s["id"]

nV = len(uniq)
vbuf = np.zeros(nV, dtype=[("pos", "<f4", 3), ("nrm", "<f4", 3), ("obj", "<u2"), ("mat", "<u2")])
vbuf["pos"] = positions[src_vert]
vbuf["nrm"] = normals[src_vert]
vbuf["obj"] = vert_obj_src[src_vert]
vbuf["mat"] = vmat
new_idx = inverse.reshape(-1, 3).astype(np.uint32)

# Triangles must stay grouped per structure: recompute ranges from tri_obj_v ordering
order = np.argsort(tri_obj_v, kind="stable")
new_idx = new_idx[order]
tri_obj_sorted = tri_obj_v[order]
starts = np.searchsorted(tri_obj_sorted, np.arange(len(structures)), side="left")
ends = np.searchsorted(tri_obj_sorted, np.arange(len(structures)), side="right")
for s in structures:
    s["i_start"] = int(starts[s["id"]]) * 3
    s["i_count"] = int(ends[s["id"]] - starts[s["id"]]) * 3

vbuf.tofile(OUT / "vertices.bin")
new_idx.tofile(OUT / "indices.bin")
rep(f"vertices {nV} (from {len(positions)}), triangles {len(new_idx)}; split took {time.time() - t1:.1f}s")

# Per-structure dominant material category (for coloring tree swatches / muscle detection)
mat_cat = [m["category"] for m in materials_out]
dom = np.zeros(len(structures), dtype=np.int64)
for s in structures:
    a = s["i_start"] // 3
    b = a + s["i_count"] // 3
    first_vertices = new_idx[a:b, 0]
    if len(first_vertices):
        dom[s["id"]] = np.bincount(vmat[first_vertices]).argmax()
    s["material"] = int(dom[s["id"]])

# --------------------------------------------------------------------------- tree
groups = {g["name"]: g for g in meta["groups"]}
all_objs = {o["name"]: o for o in objects}
label_parent = {l["name"]: l["parent"] for l in meta["labels"]}


def parent_of(name):
    if name in all_objs:
        return all_objs[name]["parent"]
    if name in groups:
        return groups[name]["parent"]
    return label_parent.get(name)


nodes = {}


def node(nid, name, kind, system=None):
    if nid not in nodes:
        nodes[nid] = {"id": nid, "name": name, "kind": kind, "system": system, "children": [], "parent": None}
    return nodes[nid]


for i, s in enumerate(SYSTEMS):
    node("sys:" + s[0], s[1], "system", s[0])


def norm_sysname(n):
    return re.sub(r"[^a-z]", "", n.lower())


SYS_NAME_ALIASES = {norm_sysname(s[1]): s[0] for s in SYSTEMS}
SYS_NAME_ALIASES.update({norm_sysname("Skeletal system"): "skeletal", norm_sysname("Joints"): "joints",
                         norm_sysname("Muscular system"): "muscular", norm_sysname("Lymphoid organs"): "lymphatic",
                         norm_sysname("Nervous system & Sense organs"): "nervous",
                         norm_sysname("Visceral systems"): "visceral",
                         norm_sysname("Regions of human body"): "regions",
                         norm_sysname("Reference lines"): "reference", norm_sysname("Reference planes"): "reference",
                         norm_sysname("Movements"): "reference", norm_sysname("General terms"): "reference",
                         norm_sysname("Fasciae"): "fascia"})


def group_node_id(gname, system):
    return f"grp:{system}:{gname}"


def attach(child_id, parent_id):
    ch = nodes[child_id]
    if ch["parent"] is not None:
        return
    ch["parent"] = parent_id
    nodes[parent_id]["children"].append(child_id)


def ensure_group_chain(gname, system, depth=0):
    """Create node for group gname (and its ancestors) inside system; returns node id."""
    base = gname[:-2] if gname.endswith(".g") else gname
    alias = SYS_NAME_ALIASES.get(norm_sysname(base))
    if alias == system:
        return "sys:" + system
    nid = group_node_id(base, system)
    if nid in nodes:
        return nid
    node(nid, display(base), "group", system)
    p = parent_of(gname)
    pid = None
    guard = 0
    while p is not None and guard < 50:
        guard += 1
        if p.endswith(".g") and p in groups:
            pid = ensure_group_chain(p, system, depth + 1)
            break
        p = parent_of(p)
    attach(nid, pid or ("sys:" + system))
    return nid


insertion_groups = {}
for s in structures:
    sysk = s["system"]
    sid_node = node(f"s:{s['id']}", s["name"] + (f" ({s['side'][0]})" if s["side"] else ""), "structure", sysk)
    sid_node["sid"] = s["id"]

for s in structures:
    nid = f"s:{s['id']}"
    sysk = s["system"]
    if sysk == "attachments":
        p = s["_parent"]
        guard = 0
        while p is not None and guard < 50:
            guard += 1
            if p in name_to_sid and structures[name_to_sid[p]]["system"] != "attachments":
                s["on"] = name_to_sid[p]
                break
            p = parent_of(p)
        muscle = s["base"]
        gid = f"grp:attachments:{muscle}"
        if gid not in nodes:
            node(gid, muscle, "group", sysk)
            attach(gid, "sys:attachments")
        attach(nid, gid)
        continue
    p = s["_parent"]
    target = None
    guard = 0
    while p is not None and guard < 50:
        guard += 1
        if p in name_to_sid and structures[name_to_sid[p]]["system"] == sysk:
            target = f"s:{name_to_sid[p]}"
            break
        if p.endswith(".g") and p in groups:
            target = ensure_group_chain(p, sysk)
            break
        p = parent_of(p)
    if target is None:
        sub = s["subsystem"]
        target = "sys:" + sysk
    attach(nid, target)

# prune empty groups, compute structure lists, sort children
def finalize(nid):
    n = nodes[nid]
    total = [n["sid"]] if "sid" in n else []
    kids = []
    for c in n["children"]:
        sub = finalize(c)
        if sub:
            kids.append(c)
            total.extend(sub)
    n["children"] = kids
    n["count"] = len(total)
    n["_all"] = total
    return total


for s in SYSTEMS:
    finalize("sys:" + s[0])


def sort_key(cid):
    c = nodes[cid]
    return (0 if c["kind"] == "group" or c["children"] else 1, c["name"].lower())


for n in nodes.values():
    n["children"].sort(key=sort_key)

live_nodes = {}


def collect(nid):
    n = nodes[nid]
    live_nodes[nid] = n
    for c in n["children"]:
        collect(c)


for s in SYSTEMS:
    collect("sys:" + s[0])
rep("tree nodes", len(live_nodes), Counter(n["kind"] for n in live_nodes.values()))
orphans = [s["id"] for s in structures if f"s:{s['id']}" not in live_nodes]
rep("orphan structures", len(orphans))

# --------------------------------------------------------------------------- subsystems
tree_parent = {}
for nid, n in live_nodes.items():
    for c in n["children"]:
        tree_parent[c] = nid


def tree_ancestors(nid):
    out = []
    p = tree_parent.get(nid)
    while p is not None:
        out.append(p)
        p = tree_parent.get(p)
    return out


subsystem_order = defaultdict(list)
for s in structures:
    nid = f"s:{s['id']}"
    anc = tree_ancestors(nid)
    sysk = s["system"]
    sub = None
    if sysk in TREE_GROUP_SUBSYSTEMS:
        top = anc[-2] if len(anc) >= 2 else None  # child of the system root
        if top is not None and live_nodes[top]["count"] > 1:
            sub = live_nodes[top]["name"]
    elif sysk in SUBSYSTEM_RULES:
        hay = [c.lower() for c in s["_colls"] if c not in SYS_BY_COLL and c not in ("Bonus collection",)] +[live_nodes[a]["name"].lower() for a in anc[:-1]] + [s["base"].lower()]
        for sname, tags in SUBSYSTEM_RULES[sysk]:
            hit = False
            for t in tags:
                if t == "":
                    hit = True
                elif t.startswith("@"):
                    hit = t[1:] in s["regions"]
                elif t.startswith("$"):
                    hit = s["role"] == t[1:]
                elif t.startswith("#"):
                    hit = t[1:] in s["base"].lower()
                else:
                    hit = any(t in h for h in hay)
                if hit:
                    break
            if hit:
                sub = sname
                break
    s["subsystem"] = sub or "Other"

for sysk, rules in SUBSYSTEM_RULES.items():
    subsystem_order[sysk] = list(dict.fromkeys(r[0] for r in rules))
for sysk in TREE_GROUP_SUBSYSTEMS:
    subsystem_order[sysk] = sorted({s["subsystem"] for s in structures if s["system"] == sysk and s["subsystem"] != "Other"},
                                   key=str.lower)
for sysk in list(subsystem_order):
    present = {s["subsystem"] for s in structures if s["system"] == sysk}
    subsystem_order[sysk] = [x for x in subsystem_order[sysk] if x in present] + (["Other"] if "Other" in present else [])
rep("subsystem counts", sorted(Counter((s["system"], s["subsystem"]) for s in structures).items()))

# --------------------------------------------------------------------------- landmarks
landmarks = []
for l in meta["labels"]:
    if l["anchor"] is None:
        continue
    raw = l["name"].rsplit(".", 1)[0]
    base_raw = l["data_name"].rsplit(".", 1)[0] if "." in l["data_name"] else raw
    p = l["parent"]
    target = None
    guard = 0
    while p is not None and guard < 50:
        guard += 1
        if p in name_to_sid:
            target = name_to_sid[p]
            break
        p = parent_of(p)
    if target is None:
        continue
    nm = display(base_raw)
    if not has_letters(nm):
        continue
    def_key = next((c for c in (base_raw, raw, "(" + nm + ")", nm) if c in text_keys), None)
    lat, taid = lookup_terms(nm)
    landmarks.append({"name": nm, "sid": target, "anchor": l["anchor"], "def": def_key, "latin": lat, "ta2": taid})
rep("landmarks", len(landmarks), "with def", sum(1 for x in landmarks if x["def"]))

# --------------------------------------------------------------------------- definitions
PHALANX_TEXT = """The phalanges are the bones of the fingers and toes. Each digit has a proximal, middle and distal phalanx, except the thumb and great toe, which have only proximal and distal phalanges.

== Structure ==

Each phalanx is a miniature long bone with a base (proximal end), a shaft (body) and a head (distal end). The bases of the proximal phalanges articulate with the metacarpal or metatarsal heads at condyloid metacarpophalangeal / metatarsophalangeal joints. The heads of the proximal and middle phalanges are pulley-shaped (trochlear) and form hinge interphalangeal joints.

The distal phalanges end in an expanded, roughened ungual tuberosity that supports the pulp of the fingertip and the nail bed.

=== Attachments ===

-Flexor digitorum superficialis inserts on the sides of the middle phalanges; flexor digitorum profundus on the bases of the distal phalanges.
-The extensor expansion (dorsal digital expansion) inserts as a central slip on the middle phalanx and lateral bands on the distal phalanx.
-Lumbricals and interossei act through the extensor expansion to flex the MCP and extend the IP joints.

=== Development ===

Each phalanx ossifies from a primary centre in the shaft and a single secondary centre at its base; distal phalanges ossify first, from the tip.

== Clinical significance ==

Crush (tuft) fractures of the distal phalanx are among the most common hand fractures. Avulsion of the extensor insertion gives a mallet finger; avulsion of flexor digitorum profundus gives a jersey finger."""


def clean_def(txt):
    if "rectangular mass military" in txt:
        txt = PHALANX_TEXT
    txt = "\n".join(l for l in txt.split("\n") if not re.search(r"may (also )?refer to|most commonly refers to", l))
    lines = txt.replace("\r", "").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().upper() == lines[0].strip() and any(ch.isalpha() for ch in lines[0]):
        lines.pop(0)
    out = "\n".join(lines).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


used_keys = set(s["def"] for s in structures if s["def"]) | set(x["def"] for x in landmarks if x["def"])
group_def = {}
for n in live_nodes.values():
    if n["kind"] == "group":
        for cand in (n["name"], "(" + n["name"] + ")"):
            if cand in text_keys:
                n["def"] = cand
                used_keys.add(cand)
                break
        lat, taid = lookup_terms(n["name"])
        if lat:
            n["latin"] = lat
        if taid:
            n["ta2"] = taid
definitions = {k: clean_def(texts[k]) for k in sorted(used_keys)}
rep("definitions used", len(definitions))

# --------------------------------------------------------------------------- write
bb_all = np.array([s["bbox"] for s in structures if s["system"] not in ("reference",)])
scene_min = bb_all[:, 0, :].min(axis=0).tolist()
scene_max = bb_all[:, 1, :].max(axis=0).tolist()

for s in structures:
    for k in [k for k in s if k.startswith("_")]:
        del s[k]
for n in live_nodes.values():
    for k in [k for k in n if k.startswith("_")]:
        del n[k]

anatomy = {
    "version": 1,
    "attribution": [
        "BodyParts3D, (c) The Database Center for Life Science, CC BY-SA 2.1 Japan",
        "Z-Anatomy - The libre 3D atlas of anatomy, CC BY-SA 4.0 (Gauthier Kervyn et al.)",
        "Definitions: Wikipedia, CC BY-SA 3.0",
        "Terminologia Anatomica 2 (TA2) term list via Z-Anatomy",
    ],
    "vertex_format": {"stride": 28, "fields": ["pos:3f", "normal:3f", "structure:u2", "material:u2"]},
    "counts": {"vertices": int(nV), "triangles": int(len(new_idx))},
    "scene_bbox": [scene_min, scene_max],
    "systems": [{"key": s[0], "name": s[1], "default_visible": s[3], "color": hexrgb(s[4]),
                 "subsystems": [{"name": x, "default_visible": (s[0], x) not in DEFAULT_OFF_SUBSYSTEMS}
                                for x in subsystem_order.get(s[0], [])]} for s in SYSTEMS],
    "regions": [{"key": r[0], "name": r[1]} for r in REGIONS],
    "materials": materials_out,
    "structures": structures,
    "tree": {"roots": ["sys:" + s[0] for s in SYSTEMS], "nodes": live_nodes},
    "landmarks": landmarks,
}
(OUT / "anatomy.json").write_text(json.dumps(anatomy, ensure_ascii=False), encoding="utf-8")
(OUT / "definitions.json").write_text(json.dumps(definitions, ensure_ascii=False), encoding="utf-8")
(OUT / "build_report.txt").write_text("\n".join(report), encoding="utf-8")
rep(f"done in {time.time() - t0:.1f}s")
