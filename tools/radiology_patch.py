"""Apply, brief and index tool for the radiology-case swarm.

Reviewer agents with no shell edit one radiology case per round by writing a patch file <case_id>.json.  Between
rounds the lead runs this tool once:

  apply  DIR [--dry-run]   validate every patch in DIR, write the accepted ones, rebuild the findings, run
                           tools/check_radiology.py and write DIR/_results.json
  brief  CASE_ID [--out DIR]   DIR/<id>.md: everything an agent needs to edit that case
  names  --out DIR         atlas_structures.txt, findings.txt, micro_<model>.txt (+ cases.txt)
  guide  --out DIR         FINDINGS_GUIDE.md
  scratch DIR              a throw-away copy of the editable files, for testing apply with --root DIR

Patch format (one JSON object per file; every key but "id" optional):
  {"id": "...", "scene": {complete replacement scene}, "label_structures": {"3": ["Renal artery"], "5": []},
   "findings_add": [spec], "findings_replace": [spec], "findings_remove": ["name"], "note": "why"}

--root R makes apply/brief/names/guide read and write R/data/content, R/tools/findings_specs.json,
R/data/findings and R/data/anatomy/anatomy.json instead of the repository's own (the geometry in the real
data/anatomy and the real app/ are still used).  Default: the repository this file is in.
"""
import argparse
import copy
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

REAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REAL))

PATCH_KEYS = {"id", "scene", "label_structures", "findings_add", "findings_replace", "findings_remove", "note"}
SCENE_BOOL = {"isolate", "layer_only", "frame", "xray", "reset_clips", "slice_only"}
SCENE_NAMES = ("show", "focus", "ghost_focus", "frame_on")
SCENE_LISTS = ("systems", "regions") + SCENE_NAMES + ("micro_focus", "micro_context")
SCENE_KEYS = set(SCENE_LISTS) | SCENE_BOOL | {"side", "dissect", "clip", "view", "camera", "landmark", "micro",
                                              "model_view", "histology", "reference_labels"}
SCENE_DOC = """\
| key | value | meaning |
|---|---|---|
| systems | ["skeletal", ...] | which systems are on (NOT "findings": list findings in show). Omit = inherit the last case's |
| regions | ["abdomen", ...] | which body regions are on. Always set it, or the case inherits the previous one's |
| side | "Left" / "Right" | keep only that side's (and unsided) structures in show/focus/ghost_focus/frame_on |
| show | [names] | forced visible, whatever systems/regions say. Atlas structure, group, collection or finding names |
| focus | [names] | forced visible, selected, x-rayed context, framed (not when there is a clip) |
| ghost_focus | [names] | kept solid while everything in front goes translucent (the radiographic look) |
| isolate | true / false | hide everything except focus/show (+ghost) |
| frame_on | [names] | what the camera frames; need not be visible; wins over a clip's own framing |
| frame | false | do not auto-frame |
| xray | false | do not x-ray the context around focus |
| view | anterior posterior left right superior inferior | named camera view |
| clip | [axis, fraction, flip?] | axis 0 sagittal, 1 coronal, 2 axial/transverse (see FINDINGS_GUIDE.md) |
| camera | [[x,y,z], distance, yaw_deg, pitch_deg] | explicit camera, overrides view |
| dissect / layer_only | number / true | depth peeling (rare) |
| slice_only | true | CT/MRI with a clip get this automatically; hides everything but the cut face |
| landmark | "name" | a bony landmark to point at |
| micro, micro_focus, micro_context, model_view | model id, [part names], [part names], view name | show a reference model |
| reference_labels | [{"text","structures","side","at"}] | author the 3D reference labels by hand (rare) |
"""


# ============================================================ formatting
def dumps(obj, nl="\n"):
    """The convention of every radiology*.json and findings_specs.json: indent 1, UTF-8 not escaped, a final
    newline, and the file's own line ending (this checkout has CRLF; git normalises it)."""
    text = json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
    return text.replace("\n", nl) if nl != "\n" else text


def newline_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def read_text(path):
    return Path(path).read_bytes().decode("utf-8")


def write_text(path, text):
    Path(path).write_bytes(text.encode("utf-8"))


def pretty(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def is_vec(x, n=3):
    return isinstance(x, list) and len(x) == n and all(is_num(v) for v in x)


def num_or_vec(x):
    return is_num(x) or is_vec(x)


def load_bf():
    spec = importlib.util.spec_from_file_location("build_findings_mod", REAL / "tools" / "build_findings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ============================================================ finding specs
SPEC_KEYS = {"name", "latin", "material", "subsystem", "regions", "note", "shape"}
AT_KEYS = {"structure", "x", "y", "z", "side", "surface", "offset_mm", "shift_mm"}
SIDES = ("Left", "Right")


def _req(shape, kinds, errs):
    for key, check in kinds.items():
        if key not in shape:
            errs.append(f"shape needs {key!r}")
        elif not check(shape[key]):
            errs.append(f"shape[{key!r}] is not valid: {shape[key]!r}")


def _opt(shape, kinds, errs):
    for key, check in kinds.items():
        if key in shape and not check(shape[key]):
            errs.append(f"shape[{key!r}] is not valid: {shape[key]!r}")


def _names(x):
    return isinstance(x, list) and bool(x) and all(isinstance(v, str) and v for v in x)


def _side(x):
    return isinstance(x, str) and (x == "" or x in SIDES)


def _pos(x):
    return is_num(x) and x > 0


def _window(x):
    return (isinstance(x, dict) and set(x) <= {"x", "y", "z"}
            and all(is_vec(v, 2) and v[0] < v[1] for v in x.values()))


# shape type -> (required checks, optional checks, which fields are "at" anchors)
def _isdict(x):
    return isinstance(x, dict)


SHAPES = {
    "blob": ({"at": _isdict, "radii_mm": lambda v: num_or_vec(v) and (min(v) if isinstance(v, list) else v) > 0},
             {"irregular": is_num, "seed": lambda v: isinstance(v, int) and not isinstance(v, bool)}, ("at",)),
    "cluster": ({"at": _isdict, "spread_mm": num_or_vec},
                {"count": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 500,
                 "size_mm": _pos, "seed": lambda v: isinstance(v, int) and not isinstance(v, bool)}, ("at",)),
    "tube": ({"from": _isdict, "to": _isdict, "radius_mm": _pos}, {}, ("from", "to")),
    "swollen": ({"structures": _names}, {"side": _side, "mm": is_num}, ()),
    "scaled": ({"structures": _names, "factors": num_or_vec}, {"side": _side}, ()),
    "moved": ({"structures": _names, "offset_mm": lambda v: is_vec(v, 3)}, {"side": _side}, ()),
    "layer": ({"structures": _names, "thickness_mm": _pos}, {"side": _side, "window": _window}, ()),
    "breast": ({"side": lambda v: v in SIDES}, {"depth_mm": _pos, "radius_mm": _pos}, ()),
}


def spec_anchors(spec):
    """[(field, at-dict)] for every placement anchor in a spec's shape."""
    shape = spec.get("shape") if isinstance(spec, dict) else None
    if not isinstance(shape, dict) or shape.get("type") not in SHAPES:
        return []
    return [(f, shape[f]) for f in SHAPES[shape["type"]][2] if isinstance(shape.get(f), dict)]


def spec_structure_names(spec):
    """Atlas-or-finding names a spec's shape points at (at.structure and structures)."""
    out = [at.get("structure") for _f, at in spec_anchors(spec)]
    shape = spec.get("shape") if isinstance(spec, dict) else None
    if isinstance(shape, dict) and isinstance(shape.get("structures"), list):
        out += shape["structures"]
    return [n for n in out if isinstance(n, str)]


class Atlas:
    """What build_findings.Atlas.records needs, from the metadata alone."""

    def __init__(self, structures):
        self.by_name = {}
        self.by_sub = {}
        for s in structures:
            if s["system"] == "findings":
                continue
            self.by_name.setdefault(s["name"], []).append(s["side"])
            self.by_sub.setdefault(s["subsystem"], []).append(s["side"])

    def has(self, name, side=""):
        sides = self.by_sub.get(name[1:], []) if name.startswith("@") else self.by_name.get(name, [])
        return any(not side or s.lower() in (side.lower(), "") for s in sides)


def validate_spec(spec, materials, region_keys, atlas, earlier, fixed_names):
    """Reasons a spec cannot be built.  `earlier` is the set of spec-finding names before it in the list."""
    errs = []
    if not isinstance(spec, dict):
        return ["spec is not an object"]
    for k in spec:
        if k not in SPEC_KEYS:
            errs.append(f"unknown spec key {k!r} (allowed: {sorted(SPEC_KEYS)})")
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip() or name != name.strip() or name.startswith("@"):
        errs.append(f"name must be a non-empty string without edge spaces or a leading '@': {name!r}")
    if spec.get("material") not in materials:
        errs.append(f"material {spec.get('material')!r} is not one of {sorted(materials)}")
    for k in ("latin", "subsystem", "note"):
        if k in spec and not isinstance(spec[k], str):
            errs.append(f"{k} must be a string")
    if "regions" in spec:
        r = spec["regions"]
        if not (isinstance(r, list) and r and all(x in region_keys for x in r)):
            errs.append(f"regions must be a non-empty list of {sorted(region_keys)}: {r!r}")
    shape = spec.get("shape")
    if not isinstance(shape, dict):
        return errs + ["spec needs a shape object"]
    kind = shape.get("type")
    if kind not in SHAPES:
        return errs + [f"unknown shape type {kind!r} (supported: {sorted(SHAPES)}; 'moved' has no real example)"]
    req, opt, anchors = SHAPES[kind]
    for k in shape:
        if k != "type" and k not in req and k not in opt:
            errs.append(f"unknown {kind} field {k!r} (allowed: {sorted(set(req) | set(opt))})")
    _req(shape, req, errs)
    _opt(shape, opt, errs)
    for field in anchors:
        at = shape.get(field)
        if not isinstance(at, dict):
            continue
        errs += [f"{field}: {e}" for e in validate_at(at, atlas, earlier, fixed_names)]
    if "structures" in shape and _names(shape["structures"]):
        side = shape.get("side", "")
        for n in shape["structures"]:
            if not atlas.has(n, side):
                hint = " (a finding cannot be used here, only an atlas structure)" if n in earlier else ""
                errs.append(f"structures: no atlas structure {n!r}" + (f" on the {side} side" if side else "") + hint)
    if kind == "breast" and shape.get("side") in SIDES and not atlas.has("Mammary region", shape["side"]):
        errs.append("breast: no 'Mammary region' on that side")
    return errs


def validate_at(at, atlas, earlier, fixed_names):
    errs = []
    for k in at:
        if k not in AT_KEYS:
            errs.append(f"unknown placement key {k!r} (allowed: {sorted(AT_KEYS)})")
    s = at.get("structure")
    if not isinstance(s, str) or not s:
        return errs + ["placement needs a structure name"]
    for k in ("x", "y", "z"):
        if k in at and not is_num(at[k]):
            errs.append(f"{k} must be a number")
    if "side" in at and not _side(at["side"]):
        errs.append(f"side must be 'Left' or 'Right': {at['side']!r}")
    if "surface" in at and not isinstance(at["surface"], bool):
        errs.append("surface must be true/false")
    if "offset_mm" in at and not is_num(at["offset_mm"]):
        errs.append("offset_mm must be a number")
    if "shift_mm" in at and not is_vec(at["shift_mm"]):
        errs.append("shift_mm must be [x,y,z] numbers")
    if s in earlier:
        pass                                           # anchored on an earlier finding: bbox fractions + shift_mm
    elif s in fixed_names:
        errs.append(f"{s!r} is a built-in finding: anchor on an atlas structure instead")
    elif not atlas.has(s, at.get("side", "")):
        errs.append(f"{s!r} is not an atlas structure" + (f" on the {at['side']} side" if at.get("side") else "")
                    + " (names are exact and case-sensitive; or '@Subsystem'; or a finding EARLIER in the specs)")
    return errs


def spec_warnings(spec, earlier):
    out = []
    if "regions" not in spec:
        out.append(f"{spec.get('name')!r}: regions defaults to ['thorax']")
    for field, at in spec_anchors(spec):
        if at.get("structure") in earlier:
            for k in ("surface", "offset_mm", "side"):
                if k in at:
                    out.append(f"{spec['name']!r}.{field}: {k!r} is ignored when anchored on a finding")
        elif at.get("surface") and "shift_mm" in at:
            out.append(f"{spec['name']!r}.{field}: shift_mm is ignored when surface is true")
        for k in "xyz":
            if is_num(at.get(k)) and not -0.5 <= at[k] <= 1.5:
                out.append(f"{spec['name']!r}.{field}.{k}={at[k]} is outside -0.5..1.5 (clamped on atlas anchors)")
    return out


# ============================================================ the world: files + datasets
class Problem(Exception):
    pass


class World:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.content = self.root / "data" / "content"
        self.specs_path = self.root / "tools" / "findings_specs.json"
        self.find_dir = self.root / "data" / "findings"
        self.anat = self.root / "data" / "anatomy"
        if not (self.anat / "anatomy.json").is_file():
            raise SystemExit(f"{self.anat}/anatomy.json not found (for a scratch root run: radiology_patch.py scratch DIR)")
        # case files, exactly as on disk
        self.files = {}            # Path -> {"text", "data", "canonical"}
        self.where = {}            # case id -> Path
        for p in sorted(self.content.glob("radiology*.json")):
            text = read_text(p)
            data = json.loads(text)
            nl = newline_of(text)
            self.files[p] = {"text": text, "data": data, "nl": nl, "canonical": dumps(data, nl) == text}
            for c in data:
                self.where.setdefault(c["id"], p)
        self.specs_text = read_text(self.specs_path) if self.specs_path.is_file() else "[]\n"
        self.specs0 = json.loads(self.specs_text)
        self.specs_nl = newline_of(self.specs_text)
        self.specs_canonical = dumps(self.specs0, self.specs_nl) == self.specs_text
        self.cases0 = {c["id"]: c for p in self.files.values() for c in p["data"]}
        self._ds = self._res = self._catalog = self._atlas = self._bf = self._geo_atlas = None
        self._models = {}
        self._rs = {}
        self.stale = []

    # ---- lazily loaded heavy things
    @property
    def ds(self):
        if self._ds is None:
            from app.data import Dataset
            self._ds = Dataset(self.anat)
        return self._ds

    @property
    def res(self):
        if self._res is None:
            from app.lessons import Resolver
            self._res = Resolver(self.ds)
        return self._res

    @property
    def atlas(self):
        if self._atlas is None:
            self._atlas = Atlas(self.ds.structures)
        return self._atlas

    @property
    def bf(self):
        if self._bf is None:
            self._bf = load_bf()
        return self._bf

    @property
    def system_keys(self):
        return [s["key"] for s in self.ds.systems if s["key"] != "findings"]

    @property
    def region_keys(self):
        return [r["key"] for r in self.ds.regions]

    @property
    def fixed_names(self):
        """Findings in findings.json that findings_specs.json does not define (hard-coded in build_findings.main)."""
        p = self.find_dir / "findings.json"
        if not p.is_file():
            return []
        have = [r["name"] for r in json.loads(read_text(p)).get("findings", [])]
        spec = {s["name"] for s in self.specs0}
        return [n for n in have if n not in spec]

    # ---- model (micro) resolution
    def catalog(self):
        if self._catalog is None:
            from app.viewer.catalog import load_catalog
            self._catalog = load_catalog()
        return self._catalog

    def model(self, mid):
        """(resolver-entry, model) for a micro model id, prepared once."""
        if mid not in self._models:
            entry = self.catalog().get(mid)
            if entry is None:
                raise Problem(f"model {mid!r} is unavailable")
            token = type("Token", (), {"cancelled": False, "check": lambda self: None})()
            model = entry.load() if hasattr(entry, "load") else entry.prepare_cpu(token)
            self._models[mid] = (getattr(model, "runtime_entry", entry), model)
        return self._models[mid]

    def model_missing(self, mid, names):
        entry, model = self.model(mid)
        try:
            return entry.resolve(model, list(names))[1]
        except AttributeError as exc:
            if "_lookups" not in str(exc):
                raise
            # stopgap while the catalog fix is absent: bind the viewer's own _lookups to the entry
            from app.viewer.catalog import ModelEntry
            import types
            entry._lookups = types.MethodType(ModelEntry._lookups, entry)
            self.stopgap_used = True
            return entry.resolve(model, list(names))[1]


# ============================================================ resolution against a virtual set of findings
class View:
    """The findings that would exist: fixed + the given specs.  Name resolution that is aware of them."""

    def __init__(self, world, specs):
        self.w = world
        self.specs = specs
        self.fl = {n.lower() for n in world.fixed_names} | {s["name"].lower() for s in specs if "name" in s}
        self.cols = {"findings"} | {s.get("subsystem", "Pathology").lower() for s in specs}
        fixed = set(world.fixed_names)
        if fixed:
            recs = json.loads(read_text(world.find_dir / "findings.json"))["findings"]
            self.cols |= {r["subsystem"].lower() for r in recs if r["name"] in fixed}

    def sids(self, name):
        w = self.w
        if name not in w._rs:
            w._rs[name] = w.res.resolve(name)
        return w._rs[name]

    def ok(self, name):
        """Does the name resolve to something that would exist."""
        key = (name or "").strip().lower()
        if key in self.fl or key in self.cols:
            return True
        ds = self.w.ds
        left = [s for s in self.sids(name)
                if ds.structures[s]["system"] != "findings" or ds.structures[s]["name"].lower() in self.fl]
        return bool(left)

    def finding_names_of(self, name):
        """Lower-case finding names that this scene name points at (itself, or through a group/collection)."""
        key = (name or "").strip().lower()
        out = set()
        if key in self.fl:
            out.add(key)
        ds = self.w.ds
        for s in self.sids(name):
            if ds.structures[s]["system"] == "findings":
                out.add(ds.structures[s]["name"].lower())
        if key in self.cols:                              # a subsystem collection names every finding in it
            if key == "findings":
                out |= self.fl
            out |= {x["name"].lower() for x in self.specs if x.get("subsystem", "Pathology").lower() == key}
        return out


def case_names(case):
    """Every atlas/finding name a case's scene and labels point at (not model parts)."""
    sc = case.get("scene", {})
    names = []
    for k in SCENE_NAMES:
        v = sc.get(k)
        if isinstance(v, list):
            names += [n for n in v if isinstance(n, str)]
    for k in ("isolate", "dissect"):
        if isinstance(sc.get(k), list):
            names += [n for n in sc[k] if isinstance(n, str)]
    for e in sc.get("reference_labels") or []:
        if isinstance(e, dict):
            names += [n for n in e.get("structures", []) if isinstance(n, str)]
    if not sc.get("micro"):
        for lab in case.get("labels", []):
            s = lab.get("structures", lab.get("structure", []))
            names += [s] if isinstance(s, str) else [n for n in s if isinstance(n, str)]
    return names


def finding_refs(view, case):
    out = set()
    for n in case_names(case):
        out |= view.finding_names_of(n)
    return out


# ============================================================ scene validation
def validate_scene(w, view, scene, case_id):
    errs, warns = [], []
    if not isinstance(scene, dict):
        return ["scene must be an object"], warns
    from app.viewport import VIEWS
    for k in scene:
        if k not in SCENE_KEYS:
            errs.append(f"unknown scene key {k!r} (allowed: {sorted(SCENE_KEYS)})")
    n_unknown = len(errs)
    for k in SCENE_LISTS:
        if k in scene and not (isinstance(scene[k], list) and all(isinstance(x, str) for x in scene[k])):
            errs.append(f"scene[{k!r}] must be a list of strings")
    for k in SCENE_BOOL - {"isolate"}:
        if k in scene and not isinstance(scene[k], bool):
            errs.append(f"scene[{k!r}] must be true or false")
    iso = scene.get("isolate")
    if iso is not None and not (isinstance(iso, bool) or (isinstance(iso, list) and all(isinstance(x, str) for x in iso))):
        errs.append("scene['isolate'] must be true/false")
    dis = scene.get("dissect")
    if dis is not None and not (is_num(dis) or (isinstance(dis, list) and all(isinstance(x, str) for x in dis))):
        errs.append("scene['dissect'] must be a number")
    if len(errs) > n_unknown:                       # wrong types: the checks below would only add noise
        return errs, warns
    for k in ("systems",):
        for key in scene.get(k, []):
            if key == "findings":
                errs.append("'findings' must not be in systems (it switches on every finding): list the findings you "
                            "want in show instead")
            elif key not in w.system_keys:
                errs.append(f"unknown system {key!r} (valid: {w.system_keys})")
    for key in scene.get("regions", []):
        if key not in w.region_keys:
            errs.append(f"unknown region {key!r} (valid: {w.region_keys})")
    if "regions" not in scene and not scene.get("micro_focus"):
        warns.append("no 'regions' key: the case inherits whatever regions the previous case left on")
    if "side" in scene and scene["side"] not in ("", "Left", "Right", "left", "right"):
        errs.append(f"side must be 'Left' or 'Right': {scene['side']!r}")
    for k in ("view", "model_view"):
        if k in scene and scene[k] not in VIEWS:
            errs.append(f"{k} {scene[k]!r} is not one of {sorted(VIEWS)}")
    clip = scene.get("clip")
    if clip is not None:
        if not (isinstance(clip, list) and len(clip) in (2, 3) and clip[0] in (0, 1, 2) and is_num(clip[1])
                and 0.0 <= clip[1] <= 1.0 and (len(clip) == 2 or isinstance(clip[2], bool))):
            errs.append(f"clip must be [axis 0|1|2, fraction 0..1, optional flip true/false]: {clip!r}")
    cam = scene.get("camera")
    if cam is not None and not (isinstance(cam, list) and len(cam) == 4 and is_vec(cam[0]) and all(is_num(v) for v in cam[1:])):
        errs.append("camera must be [[x,y,z], distance, yaw_deg, pitch_deg]")
    if "landmark" in scene and (scene["landmark"] or "").strip().lower() not in w.res.landmarks:
        errs.append(f"landmark {scene['landmark']!r} is not an atlas landmark")
    side = (scene.get("side") or "").lower()
    names = []
    for k in SCENE_NAMES + (("isolate",) if isinstance(iso, list) else ()) + (("dissect",) if isinstance(dis, list) else ()):
        for n in scene.get(k, []) if k in SCENE_NAMES else scene[k]:
            names.append((k, n))
    for k, n in names:
        if not view.ok(n):
            import difflib
            pool = list(w.res.by_lower) + list(w.res.groups) + list(w.res.collections) + list(w.res.landmarks)
            pool += sorted(view.fl)
            errs.append(f"scene[{k}] {n!r} does not resolve to an atlas structure or finding "
                        f"(close: {difflib.get_close_matches(n.lower(), pool, n=4, cutoff=0.6)})")
        elif side and k in SCENE_NAMES:
            sids = view.sids(n)
            if sids and not any(w.ds.structures[s]["side"].lower() in (side, "") for s in sids):
                warns.append(f"scene[{k}] {n!r} exists only on the other side: the app drops it for side={scene['side']!r}")
    mid = scene.get("micro")
    if "micro_focus" in scene and not mid:
        errs.append("micro_focus needs scene['micro'] (the model id)")
    if mid:
        try:
            w.model(mid)
        except Problem as exc:
            errs.append(str(exc))
        except Exception as exc:
            errs.append(f"model {mid!r} could not be prepared: {type(exc).__name__}: {exc}")
        else:
            for k in ("micro_focus", "micro_context"):
                for n in w.model_missing(mid, scene.get(k, [])):
                    errs.append(f"scene[{k}] model part {n!r} does not exist in model {mid!r} (see micro_{mid}.txt)")
            if not scene.get("micro_focus"):
                warns.append("micro without micro_focus opens the model tab instead of the beside-the-scan reference")
    elif "micro_context" in scene:
        errs.append("micro_context needs scene['micro']")
    for e in scene.get("reference_labels") or []:
        if not (isinstance(e, dict) and isinstance(e.get("text"), str) and isinstance(e.get("structures", []), list)):
            errs.append("reference_labels entries need text and structures")
            break
        for n in e.get("structures", []):
            if not view.ok(n):
                errs.append(f"reference_labels {n!r} does not resolve")
    if scene.get("clip") and scene.get("frame_on") is None and scene.get("frame") is not False:
        warns.append("clip without frame_on: the camera frames everything the plane cuts (a long tendon can zoom it out)")
    return errs, warns


def label_missing(w, view, scene, names):
    mid = scene.get("micro")
    if mid:
        try:
            return w.model_missing(mid, names)
        except Problem:
            return list(names)
    return [n for n in names if not view.ok(n)]


# ============================================================ labels
def relink(label, names):
    """The label with its structure link replaced, keeping key order and the file's existing key convention."""
    names = list(names)
    has_single = "structure" in label and "structures" not in label
    if has_single and len(names) == 1:
        key, val = "structure", names[0]
    else:
        key, val = "structures", names
    out, done = {}, False
    for k, v in label.items():
        if k in ("structure", "structures"):
            if not done:
                out[key] = val
                done = True
        else:
            out[k] = v
    if not done:
        out[key] = val
    return out


def label_names(label):
    s = label.get("structures", label.get("structure", []))
    return [s] if isinstance(s, str) else list(s)


# ============================================================ patches
class Verdict:
    def __init__(self, pid):
        self.id = pid
        self.reasons, self.warnings = [], []
        self.ops = []                 # replayable effects
        self.touches_findings = False
        self.geometry = {}
        self.changed_findings = []

    @property
    def ok(self):
        return not self.reasons


def load_patches(dirpath):
    out, bad = {}, {}
    for p in sorted(Path(dirpath).glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            doc = json.loads(read_text(p))
        except ValueError as exc:
            bad[p.stem] = [f"not valid JSON: {exc}"]
            continue
        if not isinstance(doc, dict):
            bad[p.stem] = ["patch must be a JSON object"]
        elif doc.get("id") != p.stem:
            bad[p.stem] = [f"file name {p.name!r} does not match id {doc.get('id')!r}"]
        else:
            out[p.stem] = doc
    return out, bad


def apply_ops(w, ops):
    """Replay ops on fresh copies of the original files.  -> ({path: text} of changed files, specs list)."""
    files = {p: copy.deepcopy(f["data"]) for p, f in w.files.items()}
    specs = copy.deepcopy(w.specs0)
    loc = {}
    for p, data in files.items():
        for i, c in enumerate(data):
            loc.setdefault(c["id"], (p, i))
    for op in ops:
        kind = op[0]
        if kind == "scene":
            p, i = loc[op[1]]
            files[p][i]["scene"] = copy.deepcopy(op[2])
        elif kind == "labels":
            p, i = loc[op[1]]
            labs = files[p][i]["labels"]
            for idx, names in op[2].items():
                labs[idx] = relink(labs[idx], names)
        elif kind == "spec_replace":
            specs[[s["name"] for s in specs].index(op[1]["name"])] = copy.deepcopy(op[1])
        elif kind == "spec_remove":
            del specs[[s["name"] for s in specs].index(op[1])]
        elif kind == "spec_add":
            specs.append(copy.deepcopy(op[1]))
    out = {}
    for p, data in files.items():
        text = dumps(data, w.files[p]["nl"])
        if text != w.files[p]["text"]:
            out[p] = text
    spec_text = dumps(specs, w.specs_nl)
    if spec_text != w.specs_text:
        out[w.specs_path] = spec_text
    return out, specs


class State:
    """The cases and specs after the patches accepted so far."""

    def __init__(self, w):
        self.w = w
        self.cases = copy.deepcopy(w.cases0)
        self.specs = copy.deepcopy(w.specs0)

    def view(self, specs=None):
        return View(self.w, self.specs if specs is None else specs)


def geometry_of(w, specs, names):
    """Build the meshes of the named spec findings with build_findings itself (no atlas write).  -> {name: report}"""
    import numpy as np
    bf = w.bf
    if w._geo_atlas is None:
        w._geo_atlas = bf.Atlas()
    by_name = {s["name"]: i for i, s in enumerate(specs)}
    cache = {}

    def build(name):
        if name not in cache:
            spec = specs[by_name[name]]
            built = {}
            for _f, at in spec_anchors(spec):
                dep = at.get("structure")
                if dep in by_name and by_name[dep] < by_name[name]:
                    built[dep] = build(dep)[0]
            cache[name] = bf.from_spec(w._geo_atlas, spec, built)
        return cache[name]

    out = {}
    for n in names:
        try:
            pos, tris = build(n)
        except Exception as exc:                                    # noqa: BLE001 - any failure rejects the patch
            out[n] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        pos = np.asarray(pos, dtype=np.float64)
        if len(pos) == 0 or len(tris) == 0 or not np.isfinite(pos).all():
            out[n] = {"error": "mesh is empty or has non-finite vertices"}
            continue
        lo, hi = pos.min(axis=0), pos.max(axis=0)
        out[n] = {"verts": int(len(pos)), "tris": int(len(tris)),
                  "centroid": [round(float(v), 4) for v in pos.mean(axis=0)],
                  "size_mm": [round(float(v) * 1000, 1) for v in hi - lo]}
    return out


def check_patch(w, st, pid, patch):
    v = Verdict(pid)
    for k in patch:
        if k not in PATCH_KEYS:
            v.reasons.append(f"unknown patch key {k!r} (allowed: {sorted(PATCH_KEYS)})")
    if pid not in st.cases:
        v.reasons.append(f"no case with id {pid!r}")
        return v
    loc = w.where[pid]
    if not w.files[loc]["canonical"]:
        v.reasons.append(f"{loc.name} does not round-trip byte-identically; refusing to rewrite it")
    if not w.specs_canonical and any(k.startswith("findings_") for k in patch):
        v.reasons.append("findings_specs.json does not round-trip byte-identically; refusing to rewrite it")
    if "note" in patch and not isinstance(patch["note"], str):
        v.reasons.append("note must be a string")
    case = st.cases[pid]
    specs = copy.deepcopy(st.specs)
    atlas = w.atlas
    materials = set(w.bf.MATERIALS)
    region_keys = set(w.region_keys)
    fixed = set(w.fixed_names)
    spec_names = [s["name"] for s in specs]
    removed, replaced, added = [], [], []

    # ---- findings
    for key in ("findings_add", "findings_replace"):
        if key in patch and not (isinstance(patch[key], list) and all(isinstance(s, dict) for s in patch[key])):
            v.reasons.append(f"{key} must be a list of spec objects")
            patch = {k: x for k, x in patch.items() if k != key}
    if "findings_remove" in patch and not (isinstance(patch["findings_remove"], list)
                                           and all(isinstance(s, str) for s in patch["findings_remove"])):
        v.reasons.append("findings_remove must be a list of names")
        patch = {k: x for k, x in patch.items() if k != "findings_remove"}
    atlas_lower = {n.lower() for n in atlas.by_name}
    used_lower = {n.lower() for n in spec_names} | {n.lower() for n in fixed}
    seen = set()
    for name in patch.get("findings_remove", []):
        if name in fixed:
            v.reasons.append(f"cannot remove {name!r}: it is a built-in finding (hard-coded in build_findings.py)")
        elif name not in spec_names:
            v.reasons.append(f"cannot remove {name!r}: no such finding in findings_specs.json")
        elif name in seen:
            v.reasons.append(f"{name!r} is removed twice")
        else:
            removed.append(name)
        seen.add(name)
    for spec in patch.get("findings_replace", []):
        name = spec.get("name")
        if name in fixed:
            v.reasons.append(f"cannot replace {name!r}: it is a built-in finding")
        elif name not in spec_names:
            v.reasons.append(f"cannot replace {name!r}: no such finding (use findings_add for a new one)")
        elif name in seen:
            v.reasons.append(f"{name!r} appears in more than one of remove/replace")
        else:
            replaced.append(spec)
        seen.add(name)
    for spec in patch.get("findings_add", []):
        name = spec.get("name")
        if isinstance(name, str):
            if name.lower() in used_lower:
                v.reasons.append(f"new finding {name!r} collides with an existing finding (names compare "
                                 "case-insensitively)")
            elif name.lower() in atlas_lower:
                v.reasons.append(f"new finding {name!r} has the same name as an atlas structure")
            elif name.lower() in w.res.groups or name.lower() in w.res.collections or name.lower() in w.res.landmarks:
                v.reasons.append(f"new finding {name!r} has the same name as an atlas group, collection or landmark: "
                                 "scenes that name that group would resolve to your finding instead")
            elif name in seen:
                v.reasons.append(f"{name!r} is added twice in this patch")
            seen.add(name)
        added.append(spec)
    if removed or replaced or added:
        v.touches_findings = True
    # ownership: other cases' scenes and labels, and other specs' anchors
    old_view = st.view()
    refs = {cid: finding_refs(old_view, c) for cid, c in st.cases.items() if cid != pid}
    in_patch = {s["name"] for s in replaced} | set(removed)
    for name in sorted(in_patch):
        users = sorted(cid for cid, r in refs.items() if name.lower() in r)
        if users:
            v.reasons.append(f"finding {name!r} is also named by case(s) {users}; only the owning case may "
                             f"change it (give your case its own copy under a new name with findings_add)")
        deps = sorted(s["name"] for s in specs if name in spec_structure_names(s) and s["name"] not in in_patch)
        if deps and name in removed:
            v.reasons.append(f"cannot remove {name!r}: other findings are placed on it: {deps}")
        elif deps:
            v.warnings.append(f"{name!r} is replaced; findings placed on it move with it: {deps}")
    # build the candidate spec list
    cand = []
    rep = {s["name"]: s for s in replaced}
    for s in specs:
        if s["name"] in removed:
            continue
        cand.append(copy.deepcopy(rep.get(s["name"], s)))
    cand += copy.deepcopy(added)
    # validate each changed spec, and the ordering of every anchor in the list
    names_before = []
    changed = {s.get("name") for s in replaced} | {s.get("name") for s in added}
    for s in cand:
        earlier = set(names_before)
        if s.get("name") in changed:
            for e in validate_spec(s, materials, region_keys, atlas, earlier, fixed):
                v.reasons.append(f"finding {s.get('name')!r}: {e}")
            v.warnings += spec_warnings(s, earlier)
        else:
            later = {x["name"] for x in cand} - earlier
            for _f, at in spec_anchors(s):
                if at.get("structure") in later or (at.get("structure") in removed):
                    v.reasons.append(f"finding {s['name']!r} is placed on {at.get('structure')!r}, which would no "
                                     "longer come before it in the specs list")
        names_before.append(s.get("name"))
    taken = set(w.res.groups) | set(w.res.collections) | set(w.res.landmarks)
    for s in added:
        sub = s.get("subsystem") if isinstance(s.get("subsystem"), str) else None
        if sub and sub.lower() in taken and sub.lower() not in {x.get("subsystem", "").lower() for x in specs}:
            v.warnings.append(f"subsystem {sub!r} is also an atlas group/collection name: scenes naming it would also "
                              "pick up this finding")
    v.changed_findings = [s["name"] for s in replaced + added if isinstance(s.get("name"), str)]
    cview = View(w, [s for s in cand if isinstance(s.get("name"), str)])

    # ---- scene
    new_scene = case.get("scene", {})
    if "scene" in patch:
        errs, warns = validate_scene(w, cview, patch["scene"], pid)
        v.reasons += errs
        v.warnings += warns
        if not errs:
            new_scene = copy.deepcopy(patch["scene"])
            v.ops.append(("scene", pid, new_scene))
    elif removed or replaced:
        gone = {n.lower() for n in removed}
        for n in case_names({"scene": new_scene, "labels": []}):
            if n.strip().lower() in gone:
                v.reasons.append(f"the case's own scene still names removed finding {n!r}: send a new scene")
    # ---- labels
    labels = copy.deepcopy(case.get("labels", []))
    changes = {}
    if "label_structures" in patch:
        ls = patch["label_structures"]
        if not isinstance(ls, dict):
            v.reasons.append("label_structures must be an object {\"1\": [names], ...}")
        else:
            for key, names in ls.items():
                try:
                    idx = int(key)
                except (TypeError, ValueError):
                    v.reasons.append(f"label_structures key {key!r} is not a label number")
                    continue
                if not 1 <= idx <= len(labels):
                    v.reasons.append(f"label {idx} does not exist (the case has {len(labels)} labels)")
                    continue
                if not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
                    v.reasons.append(f"label {idx}: value must be a list of names ([] for no link)")
                    continue
                miss = label_missing(w, cview, new_scene, names)
                for n in miss:
                    where = f"model {new_scene.get('micro')!r}" if new_scene.get("micro") else "the atlas or findings"
                    v.reasons.append(f"label {idx} ({labels[idx - 1].get('text')!r}): {n!r} not found in {where}")
                changes[idx - 1] = names
    # a scene change that moves the case into or out of a model re-resolves every label: only new misses count
    if "scene" in patch and bool(patch["scene"].get("micro")) != bool(case.get("scene", {}).get("micro")):
        for i, lab in enumerate(labels):
            if i in changes:
                continue
            before = label_missing(w, old_view, case.get("scene", {}), label_names(lab))
            after = label_missing(w, cview, new_scene, label_names(lab))
            for n in set(after) - set(before):
                v.reasons.append(f"label {i + 1} ({lab.get('text')!r}): {n!r} no longer resolves after the scene's "
                                 "micro change; fix it with label_structures")
    if changes:
        v.ops.append(("labels", pid, changes))
    # ---- the case should show what it adds
    final = {"scene": new_scene, "labels": [relink(l, changes[i]) if i in changes else l for i, l in enumerate(labels)]}
    used = finding_refs(cview, final)
    for s in added + replaced:
        n = s.get("name")
        if isinstance(n, str) and n.lower() not in used:
            v.warnings.append(f"finding {n!r} is not named by the case's scene (show) or labels, so it will not appear")
    if len(patch.get("findings_remove", [])) or replaced or added:
        pass
    # ---- geometry
    if not v.reasons and (replaced or added):
        try:
            geo = geometry_of(w, cand, [s["name"] for s in replaced + added])
        except Exception as exc:                                    # noqa: BLE001
            geo = {}
            v.reasons.append(f"could not run the geometry dry-run: {type(exc).__name__}: {exc}")
        for n, rep_ in geo.items():
            if "error" in rep_:
                v.reasons.append(f"finding {n!r} cannot be built: {rep_['error']}")
        v.geometry = geo
    if not v.reasons:
        for s in removed:
            v.ops.append(("spec_remove", s))
        for s in replaced:
            v.ops.append(("spec_replace", s))
        for s in added:
            v.ops.append(("spec_add", s))
        v.candidate = (cand, final)
    return v


# ============================================================ apply
def run_sub(args, log, timeout):
    with open(log, "wb") as fh:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), *args], stdout=fh,
                           stderr=subprocess.STDOUT, timeout=timeout)
    return r.returncode


def tail(path, n=12):
    try:
        return read_text(path).strip().splitlines()[-n:]
    except OSError:
        return []


def parse_check(log, case_ids):
    """({case id: [problems]}, [unattributed], summary line)"""
    by_case, other, summary = {}, [], ""
    for line in read_text(log).splitlines():
        if not line.strip():
            continue
        if re.match(r"^(OK|\d+ problems)$", line) or re.match(r"^\d+ cases, ", line):
            summary = (summary + " | " + line) if summary else line
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+?)(?::| label| scene|\s)", line)
        if m and m.group(1) in case_ids:
            by_case.setdefault(m.group(1), []).append(line.strip())
        else:
            other.append(line.strip())
    return by_case, other, summary


def cmd_apply(args):
    w = World(args.root)
    pdir = Path(args.dir)
    patches, bad = load_patches(pdir)
    results = {}
    for pid, reasons in bad.items():
        results[pid] = {"status": "rejected", "reasons": reasons, "check_problems": []}
    st = State(w)
    verdicts, accepted = {}, []
    for pid in sorted(patches):
        try:
            v = check_patch(w, st, pid, patches[pid])
        except Exception as exc:                                   # noqa: BLE001 - a malformed patch is a rejection
            v = Verdict(pid)
            v.reasons.append(f"patch could not be checked ({type(exc).__name__}: {exc}); is it well-formed?")
        v.reasons = list(dict.fromkeys(v.reasons))
        v.warnings = list(dict.fromkeys(v.warnings))
        verdicts[pid] = v
        if v.ok:
            accepted.append(pid)
            cand, final = v.candidate
            st.specs = cand
            st.cases[pid] = dict(st.cases[pid], scene=final["scene"], labels=final["labels"])
        results[pid] = {"status": "rejected" if not v.ok else "accepted", "reasons": v.reasons,
                        "warnings": v.warnings, "check_problems": [], "note": patches[pid].get("note", "")}
        if v.geometry:
            results[pid]["findings_geometry"] = v.geometry
    ops_all = [op for pid in accepted for op in verdicts[pid].ops]
    out_all, _specs = apply_ops(w, ops_all)
    f_ids = [p for p in accepted if verdicts[p].touches_findings]
    summary = {"accepted": len(accepted), "rejected": len(results) - len(accepted)}
    if getattr(w, "stopgap_used", False):
        summary["stopgap_lookups_used"] = True
    if args.dry_run:
        for pid in accepted:
            results[pid]["status"] = "would_apply"
        results["_summary"] = dict(summary, would_write=[p.relative_to(w.root).as_posix() for p in out_all],
                                   would_rebuild_findings=bool(f_ids), dry_run=True)
        write_text(pdir / "_dryrun.json", json.dumps(results, indent=1, ensure_ascii=False) + "\n")
        print(f"DRY RUN: {len(accepted)} would apply, {len(results) - len(accepted) - 1} rejected; "
              f"files {[p.name for p in out_all]}; findings rebuild: {'yes' if f_ids else 'no'}; -> {pdir / '_dryrun.json'}")
        return 0

    # baseline check, so problems that were already there are not blamed on a patch
    base_log = pdir / "_check_before.log"
    run_sub(["_check", "--root", str(w.root)], base_log, 600)
    base_by_case, base_other, _s = parse_check(base_log, set(w.cases0))

    originals = {p: (read_text(p) if p.is_file() else None) for p in out_all}
    find_backup = {p.name: p.read_bytes() for p in w.find_dir.glob("*") if p.is_file()} if f_ids else {}
    for p, text in out_all.items():
        write_text(p, text)
    build = {"ran": False}
    if f_ids:
        log = pdir / "_build.log"
        build["ran"] = True
        try:
            code = run_sub(["_build", "--root", str(w.root)], log, 1800)
        except subprocess.TimeoutExpired:
            code = -1
        problems = []
        if code == 0:
            try:
                have = {r["name"]: r for r in json.loads(read_text(w.find_dir / "findings.json"))["findings"]}
            except (OSError, ValueError) as exc:
                have = {}
                problems.append(f"findings.json unreadable after the build: {exc}")
            for pid in f_ids:
                for n in verdicts[pid].changed_findings:
                    r = have.get(n)
                    if r is None or not r["v_count"]:
                        problems.append(f"{pid}: finding {n!r} missing or empty after the build")
                    elif pid in results:
                        results[pid].setdefault("findings_built", {})[n] = {
                            "verts": r["v_count"], "centroid": [round(x, 4) for x in r["centroid"]],
                            "size_mm": [round((b - a) * 1000, 1) for a, b in zip(*r["bbox"])]}
            for pid in f_ids:                       # removed findings must be gone
                pass
        if code != 0 or problems:
            reason = f"findings build failed (exit {code}): " + " / ".join(tail(log, 6) + problems)
            for p, text in originals.items():
                if text is not None:
                    write_text(p, text)
            for name, data in find_backup.items():
                (w.find_dir / name).write_bytes(data)
            keep_ops = [op for pid in accepted if pid not in f_ids for op in verdicts[pid].ops]
            keep_out, _ = apply_ops(w, keep_ops)
            for p, text in keep_out.items():
                write_text(p, text)
            for pid in f_ids:
                results[pid]["status"] = "rolled_back"
                results[pid]["reasons"].append(reason)
            build.update(ok=False, exit=code, tail=tail(log, 10), problems=problems,
                         restored="findings.json/npz restored byte-for-byte from before the build")
            accepted = [p for p in accepted if p not in f_ids]
        else:
            build.update(ok=True, log=str(log))
    for pid in accepted:
        results[pid]["status"] = "applied"
    # the final check
    chk_log = pdir / "_check.log"
    code = run_sub(["_check", "--root", str(w.root)], chk_log, 600)
    by_case, other, csum = parse_check(chk_log, set(w.cases0))
    check = {"ran": bool(csum), "exit": code, "summary": csum, "log": str(chk_log)}
    if not csum:
        check["tail"] = tail(chk_log, 10)
    for pid in results:
        if pid in w.cases0:
            probs = by_case.get(pid, [])
            results[pid]["check_problems"] = probs
            new = [x for x in probs if x not in base_by_case.get(pid, [])]
            results[pid]["new_check_problems"] = new
    check["problems_in_unpatched_cases"] = {c: p for c, p in by_case.items() if c not in results}
    check["unattributed"] = [x for x in other if x not in base_other]
    results["_build"] = build
    results["_check"] = check
    results["_summary"] = dict(summary, changed_files=[p.relative_to(w.root).as_posix() for p in out_all
                                                       if read_text(p) != originals[p]])
    write_text(pdir / "_results.json", json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    n_app = sum(1 for k, r in results.items() if not k.startswith("_") and r["status"] == "applied")
    n_rej = sum(1 for k, r in results.items() if not k.startswith("_") and r["status"] == "rejected")
    n_rb = sum(1 for k, r in results.items() if not k.startswith("_") and r["status"] == "rolled_back")
    n_new = sum(len(r.get("new_check_problems", [])) for k, r in results.items() if not k.startswith("_"))
    print(f"applied {n_app}, rejected {n_rej}, rolled back {n_rb}; findings build: "
          f"{'ok' if build.get('ok') else ('FAILED' if f_ids else 'not needed')}; check: "
          f"{csum or 'DID NOT RUN'} ({n_new} new problems in patched cases, "
          f"{len(check['problems_in_unpatched_cases'])} cases with problems elsewhere); -> {pdir / '_results.json'}")
    return 0


# ============================================================ names / brief / guide
def atlas_rows(w):
    rows = []
    for s in w.ds.structures:
        if s["system"] == "findings":
            continue
        rows.append(f"{s['name']} | {s['system']} | {s['subsystem']} | {s['side'] or '-'} | {','.join(s['regions'])}")
    return sorted(set(rows), key=str.lower)


def micro_models(w):
    ids = []
    for c in w.cases0.values():
        m = c.get("scene", {}).get("micro")
        if m and m not in ids:
            ids.append(m)
    return sorted(ids)


def model_text(w, mid):
    entry, model = w.model(mid)
    lines = [f"# model {mid}: {len(model.items)} parts, {len(model.groups)} groups",
             "# micro_focus / micro_context / label structures may use a part name, a part key or a group name (case-insensitive)",
             "", "## parts: name | key | groups"]
    member = {}
    for g in model.groups:
        for i in g.items:
            member.setdefault(i, []).append(g.title)
    for it in model.items:
        lines.append(f"{it.name} | {it.key} | {'; '.join(member.get(it.index, []))}")
    lines += ["", "## groups: title | key | parts"]
    for g in model.groups:
        lines.append(f"{g.title} | {g.key} | " + "; ".join(model.items[i].name for i in g.items))
    aliases = getattr(entry, "aliases", None) or {}
    if aliases:
        lines += ["", "## aliases (also accepted): alias -> targets"]
        lines += [f"{k} -> {', '.join(map(str, v))}" for k, v in sorted(aliases.items())]
    return "\n".join(lines) + "\n"


def cmd_names(args):
    w = World(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = atlas_rows(w)
    write_text(out / "atlas_structures.txt", "# name | system | subsystem | side | regions   (exact names; "
               "groups and collections such as 'Liver' or a subsystem also resolve in a scene)\n" + "\n".join(rows) + "\n")
    spec_names = {s["name"] for s in w.specs0}
    recs = json.loads(read_text(w.find_dir / "findings.json"))["findings"] if (w.find_dir / "findings.json").is_file() else []
    lines = ["# finding | subsystem | source | regions   (source: spec = tools/findings_specs.json, editable; "
             "built-in = hard-coded, cannot be changed by a patch)"]
    for r in recs:
        lines.append(f"{r['name']} | {r['subsystem']} | {'spec' if r['name'] in spec_names else 'built-in'} | "
                     f"{','.join(r['regions'])}")
    write_text(out / "findings.txt", "\n".join(lines) + "\n")
    cl = ["# case id | modality | region | file | micro model | labels | findings named"]
    view = View(w, w.specs0)
    for cid, c in w.cases0.items():
        cl.append(f"{cid} | {c.get('modality')} | {c.get('region')} | {w.where[cid].name} | "
                  f"{c.get('scene', {}).get('micro', '-')} | {len(c.get('labels', []))} | "
                  f"{len(finding_refs(view, c))}")
    write_text(out / "cases.txt", "\n".join(cl) + "\n")
    done = []
    for mid in micro_models(w):
        write_text(out / f"micro_{mid}.txt", model_text(w, mid))
        done.append(mid)
    print(f"{len(rows)} atlas structures, {len(recs)} findings, {len(w.cases0)} cases, micro models {done} -> {out}")
    return 0


def cmd_brief(args):
    w = World(args.root)
    cid = args.case_id
    if cid not in w.cases0:
        raise SystemExit(f"no case {cid!r}")
    case = w.cases0[cid]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    view = View(w, w.specs0)
    by_name = {s["name"]: s for s in w.specs0}
    refs = {c: finding_refs(view, k) for c, k in w.cases0.items()}
    mine = sorted(refs[cid])
    lower_to_name = {n.lower(): n for n in list(by_name) + w.fixed_names}
    scene = case.get("scene", {})
    try:
        src = w.where[cid].relative_to(w.root).as_posix()
    except ValueError:
        src = w.where[cid]
    L = [f"# Brief: {cid}", "", f"Case file: `{src}`  (the tool edits it for you; you only write the patch)", ""]
    sources = REAL / "data" / "radiology" / "sources.json"
    try:
        srcinfo = json.loads(read_text(sources)).get(cid, {})
    except (OSError, ValueError):
        srcinfo = {}
    img = srcinfo.get("file")
    if img:
        L += [f"Scan image: `data/radiology/images/{img}`" + (f"  (crop {case['crop']}: label x,y are fractions of the CROPPED image)"
                                                              if case.get("crop") else ""), ""]
    L += ["## Current case", "", "```json", pretty(case), "```", ""]
    L += ["## Numbered labels (use these numbers in label_structures)", ""]
    for i, lab in enumerate(case.get("labels", []), 1):
        L.append(f"{i}. {lab.get('text')!r} at ({lab.get('x')}, {lab.get('y')}) -> {label_names(lab) or 'no link'}")
    errs, warns = validate_scene(w, view, scene, cid)
    for i, lab in enumerate(case.get("labels", []), 1):
        for n in label_missing(w, view, scene, label_names(lab)):
            errs.append(f"label {i} ({lab.get('text')!r}): {n!r} does not resolve")
    if errs or warns:
        L += ["", "## Problems in the case as it stands",
              "A patch `scene` is checked on its own, so a scene copied from above must fix every ERROR here or the "
              "patch is rejected.", ""]
        L += [f"- ERROR: {e}" for e in errs] + [f"- warning: {x}" for x in warns]
    L += ["", "## What the scene currently names", ""]
    names = case_names({"scene": scene, "labels": []})
    seen = set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        sids = view.sids(n)
        if sids:
            ds = w.ds
            kinds = sorted({f"{ds.structures[s]['system']}/{ds.structures[s]['side'] or '-'}" for s in sids})
            L.append(f"- {n!r}: {len(sids)} structure(s) [{', '.join(kinds[:6])}]")
        else:
            L.append(f"- {n!r}: DOES NOT RESOLVE")
    L += ["", "## Findings this case uses", ""]
    if not mine:
        L.append("None. You may add findings with findings_add and name them in scene.show.")
    for low in mine:
        n = lower_to_name.get(low, low)
        users = sorted(c for c in refs if c != cid and low in refs[c])
        if n in by_name:
            L += [f"### {n}", f"Also named by: {users or 'no other case (you may replace or remove it)'}", "",
                  "```json", pretty(by_name[n]), "```", ""]
            for dep in spec_structure_names(by_name[n]):
                if dep in by_name and dep != n and dep.lower() not in refs[cid]:
                    L += [f"Anchor of the above (not named by the scene), spec for `{dep}`:", "```json",
                          pretty(by_name[dep]), "```", ""]
            kids = sorted(s["name"] for s in w.specs0 if n in spec_structure_names(s))
            if kids:
                L += [f"Placed on this finding (they move if you change it): {kids}", ""]
        else:
            rec = next((r for r in json.loads(read_text(w.find_dir / "findings.json"))["findings"] if r["name"] == n), None)
            L += [f"### {n}  (built-in: cannot be edited by a patch)", f"Also named by: {users or 'none'}",
                  f"Subsystem {rec['subsystem'] if rec else '?'}", ""]
    L += ["## Valid system keys (never 'findings')", "", ", ".join(w.system_keys), "",
          "## Valid region keys", "", ", ".join(f"{r['key']} ({r['name']})" for r in w.ds.regions), ""]
    mid = scene.get("micro")
    if mid:
        L += [f"## Micro model `{mid}` (this case shows beside-the-scan reference model parts)", ""]
        try:
            L += ["```", model_text(w, mid).rstrip(), "```", ""]
        except Exception as exc:                                      # noqa: BLE001
            L += [f"(model could not be loaded: {exc})", ""]
        L += ["Label `structures` of a micro case name MODEL parts (not atlas structures).", ""]
    L += ["## Scene keys", "", SCENE_DOC, "",
          "## Names", "",
          f"Grep `{args.names}/atlas_structures.txt` (atlas), `{args.names}/findings.txt` (existing findings)"
          + (f", `{args.names}/micro_{mid}.txt` (model parts)" if mid else "")
          + f". How to write a finding spec: `{args.names}/FINDINGS_GUIDE.md`.", "",
          "## Patch to write", "",
          f"One file `{cid}.json` in the round's patch folder. `scene` REPLACES the whole scene (copy the current one and "
          "edit it). `label_structures` changes only which structure(s) a numbered label links to. Every other key is "
          "optional. A patch with any error is rejected whole.", "", "```json",
          pretty({"id": cid, "scene": {"...": "complete replacement"}, "label_structures": {"1": ["Name"]},
                  "findings_add": [], "findings_replace": [], "findings_remove": [], "note": "what and why"}), "```", ""]
    write_text(out / f"{cid}.md", "\n".join(L))
    print(f"-> {out / (cid + '.md')}  ({len(mine)} findings, {len(case.get('labels', []))} labels)")
    return 0


GUIDE_HEAD = """\
# Writing a finding spec

A finding is a small piece of pathology geometry (a stone, a mass, a clot, a fracture line, a narrowed vessel) that
`tools/build_findings.py` builds from `tools/findings_specs.json` and the tool appends to the atlas. A case shows it by
naming it in `scene.show` (never by putting `findings` in `systems`). Everything is in ATLAS COORDINATES: metres,
x = patient's left, y = up, z = anterior; 1 mm = 0.001. Build errors reject the whole patch, so check names against
`atlas_structures.txt` and `findings.txt`.

## A spec

```json
{"name": "...", "latin": "...", "material": "...", "subsystem": "...", "regions": ["abdomen"], "note": "...", "shape": {...}}
```
- `name` (required): unique, case-insensitive, not an atlas structure name, no leading '@'. Prefer a name tied to your
  case (`"Gallstone (illustrative) (mri_choledocholithiasis)"`) so no other case shares the finding: a finding that
  another case names cannot be replaced or removed by your patch (add your own copy instead).
- `material` (required): one of MATERIALS_LIST.
- `subsystem` (default "Pathology"), `note` (shown as the definition), `latin`: free text.
- `regions` (default `["thorax"]`, so set it): list of region keys REGIONS_LIST: where the finding sits. A finding named
  in `scene.show` is visible whatever the scene's regions are (an explicit show beats region filters).
- `shape` (required): one of the types below. Unknown fields are rejected.

## Placement: the `at` object

Used by `blob`, `cluster` (field `at`) and `tube` (fields `from` and `to`).
- `structure` (required): an exact, case-sensitive ATLAS structure name (no groups, collections or landmarks), or
  `"@Subsystem"` for a whole subsystem, or the name of a finding EARLIER in the specs list.
- `side`: "Left" or "Right": keep only that side's structures (unsided ones always match). Needed for paired structures
  such as "Kidney" or "Hip bone"; without it both sides are combined and the box is wrong.
- `x`, `y`, `z`: a point as fractions of the structure's bounding box. x: patient right 0 -> patient left 1;
  y: inferior 0 -> superior 1; z: posterior 0 -> anterior 1. Default 0.5. Values outside 0..1 reach outside the box
  (clamped to -0.5..1.5).
- `surface: true`: snap the point to the NEAREST VERTEX of the structure's surface, then move `offset_mm` along that
  vertex's outward normal (positive = out of the surface, negative = into the organ). Use it for things lying on a surface.
- `shift_mm: [x,y,z]`: move the point by that many mm. Only used when `surface` is not true.
- On an earlier FINDING as `structure`: only `x,y,z` (fractions of that finding's box) and `shift_mm` apply;
  `surface`, `offset_mm` and `side` are ignored. A finding must come AFTER the finding it sits on in the list: new
  findings (`findings_add`) are appended at the end, which is always after anything that already exists. To place a
  finding on one you add in the same patch, list the base finding first.
- Built-in findings (Right pleural effusion, Enlarged heart, ...) cannot be anchors: use their atlas structure.

## Shape types
"""

GUIDE_TAIL = """\

## Scene keys

A patch's `scene` REPLACES the whole scene of the case. `apply_scene` (app/main_window.py) understands:

SCENE_DOC

Gotchas (docs/radiology_cases.md):
- Do NOT put `"findings"` in `systems`: it turns on every finding, and a cross-section then names an effusion, a
  pneumothorax and an enlarged heart all at once. List the findings you want in `show`; an explicit show beats a
  system that is switched off. (The tool rejects `findings` in systems.)
- Always set `regions`; a scene without it inherits the previous case's.
- Bone cases ask for `"systems": ["skeletal"]` alone: a joint capsule sits over the bones a plain film is read for.
  A label that names a joint still reveals it on click.
- `side` ("Left"/"Right") drops names that exist only on the other side (and keeps unsided ones). Put the normal side
  in `ghost_focus` so the healthy structure stays solid next to the abnormal one.
- `frame_on` names structures to frame; they need not be visible. Sub-part names (Olecranon, Head of femur, Tibial
  tuberosity) resolve to the WHOLE bone, so framing on them zooms out. `frame_on` wins over a `clip`'s own framing.
- Views put the patient's left on the right of the screen, like a film. Anterior is on the left in the `left` view
  and on the right in the `right` view, so a lateral with anterior at image-left wants `"view": "left"`.
- Axial CT/MR slice: `"view": "inferior"` and `clip: [2, f]` (f = (y + 0.0004) / 1.7437 of the body height 0..1.7433,
  y in metres); the default keeps the half ABOVE the plane, which from below shows the cut face. A third element
  `true` flips it (wrong for CT).
- Sagittal slice: `clip: [0, f, true]` keeps the patient's right half and `"view": "left"` looks at the cut face
  from the left with anterior on the left of the screen. Coronal clip is axis 1.
- A CT/MRI case with a `clip` is a slice view: only the cut face shows (slice_only), and the cut-through systems
  (skeletal, joints, muscular, cardiovascular, lymphatic, nervous, visceral) are switched on automatically.
- Label structures are looked up like scene names (atlas structure, group, collection or finding), except in a
  case with `micro`, where they name parts of the model.
"""

SHAPE_DOC = {
    "blob": ("An irregular ellipsoid (stone, mass, clot, cyst, haemorrhage).",
             "`at`; `radii_mm` [rx, ry, rz] (or one number)", "`irregular` 0..1 (0 = smooth ellipsoid), `seed` int"),
    "cluster": ("A scatter of tiny blobs (calcifications, stones, gas bubbles).",
                "`at`; `spread_mm` [sx, sy, sz] (or one number)", "`count` (default 12), `size_mm` (default 0.8), `seed`"),
    "tube": ("A straight cylinder between two points (fracture line, thrombus in a vessel, abnormal vessel).",
             "`from`, `to` (both `at` objects); `radius_mm`", "-"),
    "swollen": ("An atlas structure pushed out along its normals, a second surface over it (inflamed wall, oedema).",
                "`structures` [atlas names]", "`mm` (default 1.5), `side`"),
    "scaled": ("An atlas structure scaled about its centre (dilated chamber, enlarged organ).",
               "`structures`; `factors` [fx, fy, fz] (or one number)", "`side`"),
    "moved": ("An atlas structure translated (displaced organ). No example in findings_specs.json yet; build_findings.main "
              "calls `moved(atlas, HEART + [\"Trachea\"], (0.026, 0, 0))` for the mediastinal shift.",
              "`structures`; `offset_mm` [dx, dy, dz]", "`side`"),
    "layer": ("A shell lying on an organ (subdural collection, wall thickening, perinephric fluid), kept inside a window.",
              "`structures`; `thickness_mm`", "`side`; `window` {x|y|z: [f0, f1]} fractions of the organ's box"),
    "breast": ("An illustrative breast dome on the mammary region (mammography cases).",
               "`side` (Left/Right)", "`depth_mm` (default 48), `radius_mm`"),
}


def cmd_guide(args):
    w = World(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    mats = ", ".join(f"`{m}`" for m in w.bf.MATERIALS)
    text = GUIDE_HEAD.replace("MATERIALS_LIST", mats).replace("REGIONS_LIST", ", ".join(w.region_keys))
    parts = [text]
    for kind, (what, req, opt) in SHAPE_DOC.items():
        ex = sorted((s for s in w.specs0 if s["shape"]["type"] == kind), key=lambda s: len(json.dumps(s)))
        parts += [f"### `{kind}`", what, f"- required: {req}", f"- optional: {opt}"]
        if ex:
            parts += ["", f"Real example (from findings_specs.json, {len([1 for s in w.specs0 if s['shape']['type'] == kind])} such):",
                      "```json", pretty(ex[0]), "```", ""]
        else:
            parts += ["- no example exists in findings_specs.json", ""]
    anchored = [s for s in w.specs0 if any(at.get("structure") in {t["name"] for t in w.specs0} for _f, at in spec_anchors(s))]
    if anchored:
        parts += ["### A finding placed on another finding", "Real example (the base finding must be earlier in the list):",
                  "```json", pretty(min(anchored, key=lambda s: len(json.dumps(s)))), "```", ""]
    surf = [s for s in w.specs0 if any(at.get("surface") for _f, at in spec_anchors(s))]
    if surf:
        parts += ["### A finding on a surface (`surface` + `offset_mm`)", "```json",
                  pretty(min(surf, key=lambda s: len(json.dumps(s)))), "```", ""]
    parts.append(GUIDE_TAIL.replace("SCENE_DOC", SCENE_DOC))
    parts.append("\n## Patch checks\n\nA patch is rejected whole, with every reason listed, if: a scene key or value is unknown, a "
                 "name does not resolve, a spec is invalid or cannot be built, a new name is not unique, or it "
                 "replaces/removes a finding another case (scene or label) names or another finding is placed on. "
                 "Warnings (written to `_results.json`) do not reject.\n")
    write_text(out / "FINDINGS_GUIDE.md", "\n".join(parts))
    print(f"-> {out / 'FINDINGS_GUIDE.md'}")
    return 0


# ============================================================ scratch + internals
def cmd_scratch(args):
    dst = Path(args.dir).resolve()
    if dst.exists() and any(dst.iterdir()):
        raise SystemExit(f"{dst} is not empty")
    (dst / "data").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REAL / "data" / "content", dst / "data" / "content")
    shutil.copytree(REAL / "data" / "findings", dst / "data" / "findings")
    (dst / "tools").mkdir()
    shutil.copy2(REAL / "tools" / "findings_specs.json", dst / "tools" / "findings_specs.json")
    (dst / "data" / "anatomy").mkdir()
    for n in ("anatomy.json", "definitions.json"):
        shutil.copy2(REAL / "data" / "anatomy" / n, dst / "data" / "anatomy" / n)
    print(f"scratch root {dst} (content, findings, specs, anatomy.json; geometry/app stay the real ones)")
    return 0


def cmd_build(args):
    root = Path(args.root).resolve()
    import os
    if os.environ.get("RADIOLOGY_PATCH_FAIL_BUILD"):          # test hook: exercise the roll-back path
        print("RADIOLOGY_PATCH_FAIL_BUILD set: failing on purpose")
        return 3
    mod = load_bf()
    mod.OUT = root / "data" / "findings"
    mod.OUT.mkdir(parents=True, exist_ok=True)
    mod.SPECS = root / "tools" / "findings_specs.json"
    return mod.main()


def cmd_check(args):
    root = Path(args.root).resolve()
    import app.config as cfg
    cfg.DATA_DIR = root / "data" / "anatomy"
    import app.radiology as rad
    rad.CONTENT_DIR = root / "data" / "content"
    import runpy
    runpy.run_path(str(REAL / "tools" / "check_radiology.py"), run_name="__main__")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *positional, out=False):
        p = sub.add_parser(name)
        for a in positional:
            p.add_argument(a)
        p.add_argument("--root", default=str(REAL))
        if out:
            p.add_argument("--out", required=name != "brief", default=str(REAL / "logs" / "radiology_swarm" / "briefs"))
        p.set_defaults(fn=fn)
        return p

    p = add("apply", cmd_apply, "dir")
    p.add_argument("--dry-run", action="store_true")
    add("names", cmd_names, out=True)
    add("guide", cmd_guide, out=True)
    p = add("brief", cmd_brief, "case_id", out=True)
    p.add_argument("--names", default="logs/radiology_swarm/ref", help="names-folder path to quote in the brief")
    add("scratch", cmd_scratch, "dir")
    add("_build", cmd_build)
    add("_check", cmd_check)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
