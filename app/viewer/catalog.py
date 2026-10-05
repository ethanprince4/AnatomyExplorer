"""Every 3D model the app can open in its model viewer, in one catalogue keyed by id.

* In-house procedural microanatomy models built by code (app/micro, registered in app/micro/registry*.py).
* In-house GLB models (models/<name>/<name>.glb with a .viewer.json sidecar), described by
  data/content/models/<id>.json: their display name and summary, the atlas structures that offer them in Details,
  histology and related models, clinical notes, a readable name and description for every group and part, links
  back to the atlas, and aliases for the names lessons and practice items use.
* Models downloaded once from Sketchfab (data/sketchfab_models/<uid>), with their creator's credit, the catalogue
  entry in data/content/sketchfab.json and the hand-written part names in data/content/sketchfab_parts/<uid>.json.

A catalogue entry is light: the geometry is only read when the model is opened (``entry.load()``).
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict

from ..config import ROOT

META_DIR = ROOT / "data" / "content" / "models"
KIND_ORDER = {"glb": 0, "procedural": 1, "downloaded": 2}


def _norm(s):
    return " ".join(str(s or "").lower().split())


def singular(name):
    """'Cardiomyocytes' -> 'Cardiomyocyte', 'Cardiomyocyte nuclei' -> 'Cardiomyocyte nucleus', 'Capillaries' ->
    'Capillary'; a parenthesis is kept after the noun."""
    head, sep, tail = name.partition(" (")
    words = head.split()
    if not words:
        return name
    w = words[-1]
    if w.lower() == "nuclei":
        w = w[:-1] + "us"
    elif w.lower().endswith("ies"):
        w = w[:-3] + "y"
    elif w.lower().endswith(("ches", "shes", "sses", "xes")):
        w = w[:-2]
    elif w.lower().endswith("s") and not w.lower().endswith(("ss", "us", "is")):
        w = w[:-1]
    words[-1] = w
    return " ".join(words) + (sep + tail if sep else "")


class ModelEntry:
    """What the rest of the app knows about a model before it is opened."""

    kind = "model"
    oriented = False                  # drawn in anatomical position (+Z anterior, +X left): show the A/P/L/R gizmo
    order = 100                       # in-house models: their place in lists (the whole heart before a tissue block)

    def __init__(self, id, name, summary="", targets=None, histology=(), related=(), clinical=(), scale_note=""):
        self.id = id
        self.name = "Heart" if id == "whole_heart" else name
        self.summary = summary
        self.targets = targets or {}
        self.histology = list(histology)
        self.related = list(related)
        self.clinical = [tuple(c) for c in clinical]
        self.scale_note = scale_note
        self.credit_html = ""
        self.aliases = {}

    @property
    def kind_name(self):
        return "downloaded 3D model" if self.kind == "downloaded" else ""

    def load(self):
        raise NotImplementedError

    def resolve(self, model, names):
        """Item indices for names from a lesson or practice item - exact item name, item key, group name, then the
        catalogue's aliases - and the names that matched nothing."""
        by_name, by_group = {}, {}
        for it in model.items:
            by_name.setdefault(_norm(it.name), []).append(it.index)
            by_name.setdefault(_norm(it.key), []).append(it.index)
        for g in model.groups:
            by_group[_norm(g.title)] = list(g.items)
            by_group[_norm(g.key)] = list(g.items)
        key_of = {it.key: it.index for it in model.items}
        group_items = {}
        for g in model.groups:
            for sid in {model.items[i].parts[0].structure_id for i in g.items if model.items[i].parts}:
                if sid:
                    group_items.setdefault(sid, []).extend(g.items)
        aliases = {_norm(k): v for k, v in self.aliases.items()}
        out, missing = [], []
        for n in names or ():
            k = _norm(n)
            hit = by_name.get(k) or by_group.get(k)
            if not hit and k in aliases:
                hit = []
                for target in aliases[k]:
                    if target.startswith("group:"):
                        g = target[6:]
                        hit.extend(group_items.get(g) or by_group.get(_norm(g), []))
                    elif target in key_of:
                        hit.append(key_of[target])
                    else:
                        hit.extend(by_name.get(_norm(target), []))
            if hit:
                out.extend(i for i in hit if i not in out)
            else:
                missing.append(n)
        return out, missing


class ProceduralEntry(ModelEntry):
    kind = "procedural"

    def __init__(self, micro):
        super().__init__(micro.id, micro.name, micro.summary, micro.targets, micro.histology, micro.related,
                         micro.clinical, micro.scale_note)
        self.micro = micro
        self.aliases = dict(getattr(micro, "aliases", {}) or {})

    def load(self):
        from .procedural import ProceduralModel
        return ProceduralModel(self.micro)


class GlbEntry(ModelEntry):
    kind = "glb"
    oriented = True

    def __init__(self, meta):
        # the model is offered for the structures its metadata names, and for every atlas structure one of its
        # groups or parts links to (Details -> 3D models, search)
        targets = dict(meta.get("targets") or {})
        linked = [a for sec in ("groups", "parts") for v in (meta.get(sec) or {}).values() for a in v.get("atlas") or ()]
        targets["structures"] = list(dict.fromkeys(list(targets.get("structures", [])) + linked))
        super().__init__(meta["id"], meta.get("name", meta["id"]), meta.get("summary", ""), targets,
                         meta.get("histology", ()), meta.get("related", ()), meta.get("clinical", ()),
                         meta.get("scale_note", ""))
        self.meta = meta
        self.order = int(meta.get("order", 100))       # among the in-house models, where lists put it
        self.path = ROOT / meta["file"]
        self.aliases = dict(meta.get("aliases") or {})
        self.oriented = bool(meta.get("oriented", True))

    def available(self):
        return self.path.is_file() and self.path.stat().st_size > 1024      # not an un-fetched Git LFS pointer

    def load(self):
        from .model import Model
        model = Model(self.path)
        apply_meta(model, self.meta)
        return model


class DownloadedEntry(ModelEntry):
    kind = "downloaded"
    oriented = False

    def __init__(self, uid, info, catalog_model=None, cur=None):
        cm = catalog_model
        cur = cur or {}
        name = cur.get("name") or (cm.name if cm else info.get("name", uid))
        summary = cur.get("summary") or (cm.summary if cm else "")
        structures = list(cm.structures) if cm else []
        super().__init__(f"sketchfab:{uid}", name, summary, {"structures": structures, "groups": structures},
                         list(cm.histology) if cm else [], list(cm.micro) if cm else [],
                         [tuple(x) for x in cur.get("clinical", []) if isinstance(x, (list, tuple)) and len(x) == 2])
        self.uid = uid
        self.info = info
        self.cur = cur
        self.structures = structures
        from .imported import credit_html
        self.credit_html = credit_html(info)
        self.license = info.get("license", "")

    def load(self):
        from .imported import LOCAL_DIR, ImportedModel
        return ImportedModel(LOCAL_DIR / self.uid / "model.glb", self.cur)


def apply_meta(model, meta):
    """Readable names, descriptions and atlas links from data/content/models/<id>.json onto a loaded GLB model."""
    groups = meta.get("groups") or {}
    parts = meta.get("parts") or {}
    group_name = {}
    for it in model.items:
        sid = it.parts[0].structure_id if it.parts else ""
        g = groups.get(sid) or {}
        if g.get("name"):
            group_name[it.group] = g["name"]
    numbered = re.compile(r"^(.*?)_*__0*(\d+)$")
    for it in model.items:
        sid = it.parts[0].structure_id if it.parts else ""
        g = groups.get(sid) or {}
        new_group = group_name.get(it.group, it.group)
        p = parts.get(it.key) or {}
        if p.get("name"):
            it.name = p["name"]
        else:
            m = numbered.match(it.key)
            if m:                                   # 'Perinuclear zones (sarcoplasm cones)' -> 'Perinuclear zone 9 (...)'
                head, sep, tail = singular(new_group).partition(" (")
                it.name = f"{head} {int(m.group(2))}" + (sep + tail if sep else "")
            elif re.match(r"^[a-z0-9_]+$", it.key):
                from .model import pretty
                it.name = pretty(it.key)
        it.description = p.get("description") or g.get("description", "")
        it.atlas = list(p.get("atlas") or g.get("atlas") or [])
        if "label" in p:
            it.label = bool(p["label"])
        it.group = new_group
    for gr in model.groups:
        if gr.key in group_name:
            gr.key = gr.title = group_name[gr.key]
    if meta.get("start_view"):
        model.sidecar = dict(model.sidecar, start_view=meta["start_view"])


class FileEntry(ModelEntry):
    """Any glTF / GLB file opened with File -> Open 3D model file (a new model to review, say)."""

    kind = "glb"

    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path).resolve()
        super().__init__(f"file:{self.path}", self.path.stem.replace("_", " "),
                         f"{self.path.name}, opened from {self.path.parent}.")
        self.oriented = False

    def load(self):
        from .model import Model
        return Model(self.path)


def load_meta(folder=META_DIR):
    out = []
    if not folder.exists():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Could not read {f.name}: {exc}")
            continue
        if meta.get("id") and meta.get("file"):
            out.append(meta)
    return out


def load_catalog():
    """Combine refined library entries with the two protected authored models."""
    from ..variants.catalog import load_active_catalog
    catalog = load_active_catalog()
    for meta in load_meta():
        if meta['id'] in ('whole_heart', 'cardiac_muscle'):
            catalog[meta['id']] = GlbEntry(meta)
    return catalog
