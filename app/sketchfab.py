"""Downloaded 3D models, opened offline.

Each model was fetched once from Sketchfab, where its creator offered it for download under a Creative Commons
licence (tools/fetch_sketchfab.py). It lives in data/sketchfab_models/<uid>/ as model.glb plus info.json with its
creator, licence and source page. The app draws it with its own renderer, so it needs no internet connection, and
it keeps the creator credited wherever the model appears.

The catalogue in data/content/sketchfab.json describes each downloaded model and the atlas structures it depicts,
so selecting a structure can offer the matching model. An entry whose model.glb and info.json are not on disk is
ignored. tools/check_sketchfab.py validates the catalogue.
"""
import json

from .config import ROOT, USER_DIR

CATALOG_PATH = ROOT / "data" / "content" / "sketchfab.json"
LOCAL_DIR = ROOT / "data" / "sketchfab_models"         # downloaded models, fetched by tools/fetch_sketchfab.py
TOKEN_PATH = USER_DIR / "sketchfab_token.txt"

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
        self.local = (here / "model.glb").exists() and (here / "info.json").exists()   # downloaded, opens offline

    @property
    def topic_name(self):
        return TOPIC_NAME.get(self.topic, "Other")

    @property
    def credit(self):
        bits = [f"by {self.author}" if self.author else "", self.license, "via Sketchfab"]
        return " · ".join(b for b in bits if b)


def load_catalog(path=CATALOG_PATH):
    """The downloaded models, grouped by topic: catalogue entries whose model.glb and info.json are on disk."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = [SketchfabModel(m) for m in raw.get("models", []) if m.get("uid") and m.get("name")]
    models = [m for m in models if m.local]
    models.sort(key=lambda m: (TOPIC_ORDER.get(m.topic, 99), m.pathology, m.name.lower()))
    return models

