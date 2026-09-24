"""Hand-written supplementary content merged into the atlas at load time.

The Wikipedia-derived texts in data/anatomy/definitions.json leave some structures without a description, and only
part of the muscles carry innervation. Rather than rebuild data/anatomy, data/content/descriptions_extra*.json fill
the gaps. Each file maps an exact structure name (its "base", the name without side), tree-group name or landmark
name to an entry:

    "Superior gluteal nerve": {"description": "...", "innervation": ["..."], "action": "...",
                               "blood_supply": "..."}

Every field is optional. "description" uses the same mini-format as definitions.json (paragraphs on their own lines,
"== Heading ==" sections, "- " bullets) and is only used where the atlas has no description. "innervation" (nerve
names; ones that exist in the atlas become links) replaces the list the build derived from the model's collections,
which is missing for many muscles and wrong for a few; an empty list clears it. "action" and "blood_supply" are shown
as key facts. Checked by tools/check_descriptions.py.
"""
import json

GLOB = "descriptions_extra*.json"
FIELDS = ("description", "innervation", "action", "blood_supply")
PREFIX = "extra:"            # definition keys of hand-written texts, so they never collide with Wikipedia ones


def load(content_dir):
    """{name: entry} from every descriptions_extra*.json; entries for one name in several files are merged field by
    field (a later file wins a field both set)."""
    entries = {}
    for path in sorted(content_dir.glob(GLOB)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"Could not read {path.name}: {exc}")
            continue
        for name, entry in data.items():
            if not name.startswith("_") and isinstance(entry, dict):
                entries.setdefault(name, {}).update(entry)
    return entries


def apply(ds, entries):
    """Fill missing descriptions, action and blood supply, and set innervation, on the dataset's structures, tree
    nodes and landmarks in place. Returns {definition key: text} for the descriptions that were used.

    Something counts as described when it has a definition key: the built dataset never keeps a key without text."""
    texts = {}

    def fill_def(item, name):
        e = entries.get(name)
        if e and e.get("description") and not item.get("def"):
            key = PREFIX + name
            texts[key] = e["description"]
            item["def"] = key

    for s in ds.structures:
        fill_def(s, s["base"])
        e = entries.get(s["base"])
        if not e or s.get("role"):                   # origin / insertion patches keep only the muscle's text
            continue
        if "innervation" in e:                       # hand-checked; replaces the list derived from collections
            s["innervation"] = list(e["innervation"])
        for field in ("action", "blood_supply"):
            if e.get(field) and not s.get(field):
                s[field] = e[field]
    for node in ds.nodes.values():
        if "sid" not in node:
            fill_def(node, node["name"])
    for lm in ds.landmarks:
        fill_def(lm, lm["name"])
    return texts
