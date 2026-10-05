"""Clinical correlations, histology and microanatomy lookups for structures and tree nodes."""
import json
from collections import OrderedDict, defaultdict

from .config import ROOT, USER_DIR
from .storage import load_json, write_json

CONTENT_DIR = ROOT / "data" / "content"
HISTOLOGY_DIR = ROOT / "data" / "histology"


def _norm(name):
    return (name or "").strip().lower()


class ContentIndex:
    def __init__(self, ds):
        self.ds = ds
        self.clinical = []
        self.clin_by_name = defaultdict(list)
        for path in sorted(CONTENT_DIR.glob("clinical*.json")):
            try:
                self.clinical.extend(json.loads(path.read_text(encoding="utf-8")))
            except ValueError as exc:
                print(f"Could not read {path.name}: {exc}")
        for i, entry in enumerate(self.clinical):
            entry["_id"] = i
            for t in entry["targets"]:
                self.clin_by_name[_norm(t)].append(entry)

        self.histology = {"tissues": [], "categories": []}
        path = HISTOLOGY_DIR / "catalog.json"
        if path.exists():
            self.histology = json.loads(path.read_text(encoding="utf-8"))
        self.tissues = {t["id"]: t for t in self.histology["tissues"]}
        self.tis_by_name = defaultdict(list)
        self.tis_by_group = defaultdict(list)
        self.tis_by_cat = defaultdict(list)
        for t in self.histology["tissues"]:
            for n in t.get("structures", []):
                self.tis_by_name[_norm(n)].append(t["id"])
            for g in t.get("groups", []):
                self.tis_by_group[_norm(g)].append(t["id"])
            for c in t.get("categories", []):
                self.tis_by_cat[c].append(t["id"])
        self.tis_contains = [(_norm(s), t["id"]) for t in self.histology["tissues"] for s in t.get("contains", [])]

        self.notes_path = USER_DIR / "notes.json"
        self.notes, self._notes_backup = load_json(
            self.notes_path,
            lambda raw: {key: value for key, value in raw.items() if isinstance(value, str)}
            if isinstance(raw, dict) else {})

        # every 3D model the model viewer opens: in-house GLB models, the procedural microanatomy models and the
        # downloaded ones (app/viewer/catalog.py)
        from .viewer.catalog import load_catalog
        MODELS = load_catalog()
        self.set_model_catalog(MODELS)

    def set_model_catalog(self, MODELS):
        self.micro_models = MODELS
        self.model_catalog_error = getattr(MODELS, "error", "")
        self.micro_by_name = defaultdict(list)
        self.micro_by_group = defaultdict(list)
        self.micro_by_cat = defaultdict(list)
        self.micro_by_subsystem = defaultdict(list)
        for m in MODELS.values():
            for n in m.targets.get("structures", []):
                self.micro_by_name[_norm(n)].append(m.id)
            for g in m.targets.get("groups", []):
                self.micro_by_group[_norm(g)].append(m.id)
            for c in m.targets.get("categories", []):
                self.micro_by_cat[c].append(m.id)
            for s in m.targets.get("subsystems", []):
                self.micro_by_subsystem[_norm(s)].append(m.id)
        self.micro_contains = [(_norm(s), m.id) for m in MODELS.values() for s in m.targets.get("contains", [])]

    def set_note(self, key, text):
        notes = dict(self.notes)
        if text:
            notes[key] = text
        else:
            notes.pop(key, None)
        write_json(self.notes_path, notes, backup=getattr(self, "_notes_backup", False))
        self.notes = notes
        self._notes_backup = False

    # ------------------------------------------------------------------ helpers
    def _group_names(self, sid):
        nid = self.ds.node_of_structure.get(sid)
        if nid is None:
            return []
        return [_norm(self.ds.nodes[a]["name"]) for a in reversed(self.ds.ancestors(nid))]

    def _category(self, sid):
        return self.ds.materials[self.ds.structures[sid]["material"]]["category"]

    def _bases(self, sids):
        return list(OrderedDict.fromkeys(_norm(self.ds.structures[s]["base"]) for s in sids))

    # ------------------------------------------------------------------ clinical
    def clinical_for_structures(self, sids):
        out = OrderedDict()
        for b in self._bases(sids):
            for e in self.clin_by_name.get(b, []):
                out[e["_id"]] = e
        return list(out.values())

    def clinical_for_name(self, name):
        return list(self.clin_by_name.get(_norm(name), []))

    # ------------------------------------------------------------------ histology
    def _ranked(self, sids, by_name, by_group, by_cat, by_sub=None, limit=8, contains=(), prefer=None):
        """Ids matching the structures, closest match first: the structure itself or something it contains, then
        its groups (the nearest first), its subsystem and its tissue category. ``prefer(id)`` orders the ids within
        one kind of match."""
        out = OrderedDict()                    # id -> how it matched (0 closest)
        for b in self._bases(sids):
            for t in by_name.get(b, []):
                out.setdefault(t, 0)
            for sub, t in contains:
                if sub in b:
                    out.setdefault(t, 0)
        if sids:
            sid = sids[0]
            for depth, g in enumerate(self._group_names(sid)):       # nearest group first
                for t in by_group.get(g, []):
                    out.setdefault(t, 1 + depth / 100.0)
            if by_sub is not None:
                for t in by_sub.get(_norm(self.ds.structures[sid]["subsystem"]), []):
                    out.setdefault(t, 2)
            for t in by_cat.get(self._category(sid), []):
                out.setdefault(t, 3)
        ids = list(out)
        if prefer is not None:
            pos = {t: i for i, t in enumerate(ids)}
            ids.sort(key=lambda t: (out[t], prefer(t), pos[t]))
        return ids[:limit]

    def histology_for_structures(self, sids):
        ids = self._ranked(sids, self.tis_by_name, self.tis_by_group, self.tis_by_cat, contains=self.tis_contains)
        return [self.tissues[i] for i in ids if self.tissues[i].get("images")]

    def histology_for_name(self, name):
        n = _norm(name)
        ids = list(OrderedDict.fromkeys(self.tis_by_name.get(n, []) + self.tis_by_group.get(n, [])))
        return [self.tissues[i] for i in ids if self.tissues[i].get("images")]

    def image_path(self, image):
        return HISTOLOGY_DIR / "images" / image["file"]

    def thumb_path(self, image):
        thumb = HISTOLOGY_DIR / "thumbs" / (image["file"].rsplit(".", 1)[0] + ".jpg")
        return thumb if thumb.exists() else self.image_path(image)

    # ------------------------------------------------------------------ microanatomy
    def micro_for_structures(self, sids):
        """The 3D models that show these structures: the closest match first, and within a match the in-house
        models (the whole heart before the cardiac muscle block), then the procedural ones, then the downloads."""
        kind_rank = {"glb": 0, "procedural": 1, "downloaded": 2}

        def prefer(mid):
            m = self.micro_models[mid]
            return kind_rank.get(m.kind, 3), m.order
        ids = self._ranked(sids, self.micro_by_name, self.micro_by_group, self.micro_by_cat, self.micro_by_subsystem,
                           limit=6, contains=self.micro_contains, prefer=prefer)
        return [self.micro_models[i] for i in ids]

    def micro_for_name(self, name):
        n = _norm(name)
        ids = list(OrderedDict.fromkeys(self.micro_by_name.get(n, []) + self.micro_by_group.get(n, [])))
        return [self.micro_models[i] for i in ids]
