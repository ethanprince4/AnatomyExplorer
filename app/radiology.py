"""Offline scan teaching cases and their image provenance.

The atlas is an anatomical reference, not a patient-specific registered scan.
Missing images are omitted from the browser but remain visible to validation.
"""
import json

from .config import ROOT

CONTENT_DIR = ROOT / "data" / "content"
IMAGE_DIR = ROOT / "data" / "radiology" / "images"
SOURCES = ROOT / "data" / "radiology" / "sources.json"
ATLAS_NOTE = ("The atlas illustrates related anatomy. It is not registered to this image; "
              "shape, scan level and pathology may differ. Image orientation comes from the source, "
              "not from an assumed atlas match.")


class Label:
    __slots__ = ("x", "y", "text", "note", "structures", "side")

    def __init__(self, raw):
        self.x = float(raw["x"])
        self.y = float(raw["y"])
        self.text = raw["text"]
        self.note = raw.get("note", "")
        self.side = raw.get("side", "")
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
        self.plane = raw.get("plane", self._infer_plane(raw))
        self.finding = raw.get("finding", "Anatomy")
        self.tags = raw.get("tags", [])
        self.references = raw.get("references", [])
        self.questions = raw.get("questions", [])
        self.atlas_note = raw.get("atlas_note", ATLAS_NOTE)
        self.illustration = raw.get("illustration", {})
        self.illustration_path = (ROOT / "data" / "radiology" / "illustrations" /
                                  self.illustration.get("file", ""))
        self.scene = dict(raw.get("scene", {}))
        # Slice scans must not show the unbounded anatomy behind their plane.
        # Explicit overrides allow projection/volume scans within a modality.
        if self.modality in ("CT", "MRI") and self.scene.get("clip"):
            self.scene.setdefault("slice_only", True)
        self.labels = [Label(x) for x in raw.get("labels", [])]
        self.crop = raw.get("crop")
        self.source = source or {}
        self.image = IMAGE_DIR / (self.source.get("file") or raw.get("image", ""))

    @staticmethod
    def _infer_plane(raw):
        clip = raw.get("scene", {}).get("clip")
        if clip:
            return {0: "Sagittal", 1: "Coronal", 2: "Axial"}.get(clip[0], "Unspecified")
        title = raw.get("title", "").lower()
        if "lateral" in title:
            return "Lateral projection"
        return "Projection" if raw.get("modality", "X-ray") == "X-ray" else "Unspecified"

    @property
    def has_image(self):
        return self.image.is_file()

    def credit(self):
        s = self.source
        if not s:
            return ""
        bits = [b for b in (s.get("author", "").strip(), s.get("licence", "").strip()) if b]
        return " · ".join(bits) or "Wikimedia Commons"

    @property
    def search_text(self):
        fields = [self.title, self.summary, self.region, self.modality,
                  self.plane, self.finding, *self.tags, *self.reading]
        for label in self.labels:
            fields.extend((label.text, label.note, *label.structures))
        return " ".join(fields).casefold()


def load_cases(include_missing=False):
    sources = {}
    if SOURCES.exists():
        try:
            sources = json.loads(SOURCES.read_text(encoding="utf-8"))
            if not isinstance(sources, dict):
                raise ValueError("image sources must be an object")
        except (OSError, ValueError):
            sources = {}
    out = []
    for path in sorted(CONTENT_DIR.glob("radiology*.json")):
        try:
            raw_cases = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw_cases, list):
                raise ValueError("case document must contain a list")
        except (OSError, ValueError) as exc:
            print(f"Could not read {path.name}: {exc}")
            continue
        for raw in raw_cases:
            try:
                case = Case(raw, sources.get(raw["id"]))
            except (KeyError, TypeError, ValueError) as exc:
                print(f"Could not read a case in {path.name}: {exc}")
                continue
            if include_missing or case.has_image:
                out.append(case)
    return out
