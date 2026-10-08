"""Reading guides for the parts of a 3D model: data/content/model_parts/<model id>.json.

A model's parts carry a group key, often an internal path such as "Gross / renal capsule". A guide arranges those groups
under plain categories for the parts tree, gives each a readable title, and holds what Details shows for a structure: a
teaching description (in place of build notes, when replace_part_descriptions is set), clinical notes about that
structure, and the histology tissues that show it. Everything is optional, and anything malformed is ignored, so a model
without a guide keeps working; its groups are then nested by the segments of their own keys.

    {"schema": 1,
     "tree": [{"path": ["Kidney", "Blood vessels"], "groups": ["Gross / renal artery", ...]}, ...],
     "titles": {"Gross / renal artery": "Renal artery", ...},
     "groups": {"Gross / renal artery": {"description": "...", "replace_part_descriptions": false,
                                         "clinical": [["Title", "Text"], ...], "histology": ["muscular_artery"]}},
     "exclude": {"groups": [...], "targets": [...], "aliases": [...], "histology": [...]}}

"exclude" retires what does not belong to the model (the adrenal gland that came with the kidney): those groups' parts
are not loaded, and the atlas structures, aliases and tissues listed stop pointing at the model.
"""
import json
from dataclasses import dataclass, field

from ..config import ROOT

GUIDE_DIR = ROOT / "data" / "content" / "model_parts"


@dataclass
class GroupGuide:
    description: str = ""
    replace_part_descriptions: bool = False
    clinical: list = field(default_factory=list)      # [(title, text)]
    histology: list = field(default_factory=list)     # tissue ids


@dataclass
class PartGuide:
    paths: dict = field(default_factory=dict)         # group key -> tuple of category titles
    order: list = field(default_factory=list)         # group keys in outline order
    titles: dict = field(default_factory=dict)        # group key -> display title
    groups: dict = field(default_factory=dict)        # group key -> GroupGuide
    excluded_groups: frozenset = frozenset()
    excluded_targets: frozenset = frozenset()
    excluded_aliases: frozenset = frozenset()
    excluded_histology: frozenset = frozenset()

    def path(self, key, title=None):
        """Category titles above a group, and its title: from the guide, else from the key's own " / " segments,
        else the group's own title."""
        if key in self.paths:
            return self.paths[key], self.titles.get(key) or _last_segment(key)
        segments = [s.strip() for s in str(key).split(" / ") if s.strip()]
        if len(segments) > 1:
            return tuple(_sentence(s) for s in segments[:-1]), self.titles.get(key) or _sentence(segments[-1])
        return (), self.titles.get(key) or title or str(key)

    def group(self, key):
        return self.groups.get(key) or GroupGuide()


def _sentence(text):
    text = str(text).strip()
    return text[:1].upper() + text[1:]


def _last_segment(key):
    return _sentence(str(key).split(" / ")[-1])


def _strings(value, limit=None):
    if not isinstance(value, list):
        return []
    out = [v.strip() for v in value if isinstance(v, str) and v.strip()]
    return out[:limit] if limit else out


def load_part_guide(model_id, tissue_ids=None):
    """The guide for a model, validated; an empty guide when there is none or it cannot be read."""
    guide = PartGuide()
    try:
        data = json.loads((GUIDE_DIR / f"{model_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return guide
    if not isinstance(data, dict):
        return guide
    exclude = data.get("exclude") if isinstance(data.get("exclude"), dict) else {}
    guide.excluded_groups = frozenset(_strings(exclude.get("groups")))
    guide.excluded_targets = frozenset(_strings(exclude.get("targets")))
    guide.excluded_aliases = frozenset(_strings(exclude.get("aliases")))
    guide.excluded_histology = frozenset(_strings(exclude.get("histology")))
    for node in data.get("tree") or []:
        if not isinstance(node, dict):
            continue
        path = tuple(_sentence(p) for p in _strings(node.get("path"), 3))
        for key in _strings(node.get("groups")):
            if key not in guide.paths:
                guide.paths[key] = path
                guide.order.append(key)
    titles = data.get("titles")
    if isinstance(titles, dict):
        guide.titles = {k: v.strip() for k, v in titles.items() if isinstance(k, str) and isinstance(v, str) and v.strip()}
    for key, raw in (data.get("groups") or {}).items() if isinstance(data.get("groups"), dict) else ():
        if not isinstance(key, str) or not isinstance(raw, dict):
            continue
        description = raw.get("description") if isinstance(raw.get("description"), str) else ""
        clinical = [(c[0].strip(), c[1].strip()) for c in raw.get("clinical") or []
                    if isinstance(c, (list, tuple)) and len(c) == 2 and all(isinstance(x, str) and x.strip() for x in c)]
        histology = _strings(raw.get("histology"), 3)
        if tissue_ids is not None:
            histology = [t for t in histology if t in tissue_ids]
        guide.groups[key] = GroupGuide(description.strip(), raw.get("replace_part_descriptions") is True and
                                       bool(description.strip()), clinical[:3], histology)
    return guide
