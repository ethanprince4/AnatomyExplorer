"""Online 3D models from Sketchfab, shown through Sketchfab's own embedded player.

Nothing is downloaded or copied: the app points a web view at the public embed URL that Sketchfab offers for
every published model, exactly as a web page would embed it. So these need an internet connection, keep the
creator's name and Sketchfab's branding on screen, and stream straight from sketchfab.com.

The catalogue in data/content/sketchfab.json lists the models worth showing and the atlas structures each one
depicts, so selecting a structure can offer the matching model in Details. tools/check_sketchfab.py validates it.
"""
import json

from .config import ROOT

CATALOG_PATH = ROOT / "data" / "content" / "sketchfab.json"
LOCAL_DIR = ROOT / "data" / "sketchfab_models"         # downloadable models, fetched by tools/fetch_sketchfab.py
TOKEN_PATH = ROOT / "data" / "user" / "sketchfab_token.txt"
EMBED = "https://sketchfab.com/models/{uid}/embed?autostart=1&ui_theme=dark&dnt=1&preload=1"
PAGE = "https://sketchfab.com/3d-models/{uid}"

TOPICS = [
    ("cardio", "Heart & vessels"),
    ("msk-skin", "Skin, bone & muscle"),
    ("viscera", "Organs"),
    ("neuro-senses", "Brain, nerves & senses"),
]
TOPIC_NAME = dict(TOPICS)
TOPIC_ORDER = {k: i for i, (k, _n) in enumerate(TOPICS)}


class SketchfabModel:
    def __init__(self, raw):
        self.uid = raw["uid"]
        self.name = raw["name"]
        self.author = raw.get("author", "")
        self.license = raw.get("license", "")
        self.summary = raw.get("summary", "")
        self.topic = raw.get("topic", "")
        self.animated = bool(raw.get("animated"))
        self.pathology = bool(raw.get("pathology"))
        self.structures = list(raw.get("structures", []))
        self.micro = list(raw.get("micro", []))
        self.histology = list(raw.get("histology", []))
        here = LOCAL_DIR / self.uid
        self.local = (here / "model.glb").exists() and (here / "info.json").exists()   # opens in the atlas too

    @property
    def embed_url(self):
        return EMBED.format(uid=self.uid)

    @property
    def page_url(self):
        return PAGE.format(uid=self.uid)

    @property
    def topic_name(self):
        return TOPIC_NAME.get(self.topic, "Other")

    @property
    def credit(self):
        bits = [f"by {self.author}" if self.author else "", self.license, "via Sketchfab"]
        return " · ".join(b for b in bits if b)


def load_catalog(path=CATALOG_PATH):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = [SketchfabModel(m) for m in raw.get("models", []) if m.get("uid") and m.get("name")]
    models.sort(key=lambda m: (TOPIC_ORDER.get(m.topic, 99), m.pathology, m.name.lower()))
    return models


class SketchfabIndex:
    """Which models to offer for a selection. Built once the lesson resolver exists, since it resolves names
    the same way lessons do."""

    def __init__(self, ds, models, resolver):
        self.ds = ds
        self.models = models
        self.by_uid = {m.uid: m for m in models}
        self.by_base = {}          # structure base name -> [model uid]
        self.sids = {}             # model uid -> resolved structure ids
        for m in models:
            sids = resolver.resolve_all(m.structures)
            self.sids[m.uid] = sids
            for base in {ds.structures[s]["base"] for s in sids}:
                self.by_base.setdefault(base, []).append(m.uid)

    def for_structures(self, sids, limit=8):
        """Models that depict the selection, most specific first: a model of the tricuspid valve beats a
        whole-body vascular map when the tricuspid valve is what is selected."""
        seen = set()
        for base in dict.fromkeys(self.ds.structures[s]["base"] for s in sids):
            seen.update(self.by_base.get(base, ()))
        ranked = sorted(seen, key=lambda uid: (len(self.sids[uid]), self.by_uid[uid].name.lower()))
        return [self.by_uid[uid] for uid in ranked[:limit]]

    def for_micro(self, micro_id):
        return [m for m in self.models if micro_id in m.micro]

    def local_models(self):
        return [m for m in self.models if m.local]
