"""Radiology cases: a still radiograph beside the live 3D model, labelled on both sides.

A case is data (data/content/radiology*.json): the image to show, a numbered list of points on it, and the scene
setup that makes the 3D model show the same thing - which systems, which way up, where to cut. Each label may name
the structures it points at, so clicking it in the image selects them in 3D.

Images and their attribution come from data/radiology (see tools/fetch_radiology.py). A case whose image has not
been downloaded is skipped, so the feature degrades quietly rather than breaking.
"""
import json

from .config import ROOT

CONTENT_DIR = ROOT / "data" / "content"
IMAGE_DIR = ROOT / "data" / "radiology" / "images"
SOURCES = ROOT / "data" / "radiology" / "sources.json"


class Label:
    __slots__ = ("x", "y", "text", "note", "structures")

    def __init__(self, raw):
        self.x = float(raw["x"])
        self.y = float(raw["y"])
        self.text = raw["text"]
        self.note = raw.get("note", "")
        s = raw.get("structure") or raw.get("structures") or []
        self.structures = [s] if isinstance(s, str) else list(s)


class Case:
    def __init__(self, raw, source):
        self.id = raw["id"]
        self.title = raw["title"]
        self.modality = raw.get("modality", "X-ray")
        self.region = raw.get("region", "General")
        self.summary = raw.get("summary", "")
        self.text = raw.get("text", "")
        self.reading = raw.get("reading", [])
        self.scene = raw.get("scene", {})
        self.labels = [Label(x) for x in raw.get("labels", [])]
        self.crop = raw.get("crop")          # [x0, y0, x1, y1] in 0..1 of the file, if only part of it is wanted
        self.source = source or {}
        self.image = IMAGE_DIR / (self.source.get("file") or raw.get("image", ""))

    @property
    def has_image(self):
        return self.image.is_file()

    def credit(self):
        s = self.source
        if not s:
            return ""
        bits = [b for b in (s.get("author", "").strip(), s.get("licence", "").strip()) if b]
        return " · ".join(bits) or "Wikimedia Commons"


def load_cases():
    sources = {}
    if SOURCES.exists():
        try:
            sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        except ValueError:
            sources = {}
    out = []
    for path in sorted(CONTENT_DIR.glob("radiology*.json")):
        try:
            raw_cases = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Could not read {path.name}: {exc}")
            continue
        for raw in raw_cases:
            case = Case(raw, sources.get(raw["id"]))
            if case.has_image:
                out.append(case)
    return out
