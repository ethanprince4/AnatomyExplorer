"""Clinical correlations, histology and microanatomy lookups for structures and tree nodes."""
import json
from collections import OrderedDict, defaultdict

from .config import ROOT, USER_DIR

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
        self.notes = {}
        if self.notes_path.exists():
            try:
                self.notes = json.loads(self.notes_path.read_text(encoding="utf-8"))
            except ValueError:
                self.notes = {}

        from .micro.registry import MODELS
        self.micro_models = MODELS
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
        if text:
            self.notes[key] = text
        else:
            self.notes.pop(key, None)
        self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        self.notes_path.write_text(json.dumps(self.notes, indent=1, ensure_ascii=False), encoding="utf-8")

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
    def _ranked(self, sids, by_name, by_group, by_cat, by_sub=None, limit=8, contains=()):
        out = OrderedDict()
        for b in self._bases(sids):
            for t in by_name.get(b, []):
                out[t] = True
            for sub, t in contains:
                if sub in b:
                    out.setdefault(t, True)
        if sids:
            sid = sids[0]
            for g in self._group_names(sid):
                for t in by_group.get(g, []):
                    out.setdefault(t, True)
            if by_sub is not None:
                for t in by_sub.get(_norm(self.ds.structures[sid]["subsystem"]), []):
                    out.setdefault(t, True)
            for t in by_cat.get(self._category(sid), []):
                out.setdefault(t, True)
        return list(out.keys())[:limit]

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
        ids = self._ranked(sids, self.micro_by_name, self.micro_by_group, self.micro_by_cat, self.micro_by_subsystem,
                           limit=4, contains=self.micro_contains)
        return [self.micro_models[i] for i in ids]

    def micro_for_name(self, name):
        n = _norm(name)
        ids = list(OrderedDict.fromkeys(self.micro_by_name.get(n, []) + self.micro_by_group.get(n, [])))
        return [self.micro_models[i] for i in ids]
