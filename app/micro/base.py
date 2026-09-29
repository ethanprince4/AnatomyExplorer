"""Micro-model infrastructure: parts and models. The model viewer turns a built model into a viewer model
(app/viewer/procedural.py)."""
from PySide6.QtGui import QColor


def rgb(hex_color):
    c = QColor(hex_color)
    return [c.redF(), c.greenF(), c.blueF()]


def tone(color, ceiling=0.78):
    """Pull a colour down until the renderer's key light and tone map stop clipping it to white.

    Micro models are lit from close range with a bright key, so pale tissue (keratin, colloid, cartilage, the
    corneal stroma) blows out and loses all of its surface relief. Scaling brightness while keeping the hue keeps
    the authored colours readable and lets the shading show."""
    m = max(color)
    return color if m <= ceiling else [c * ceiling / m for c in color]


# Surface texturing for the shader's tissue mode, per material category:
# (colour mottling, cells per unit on cut faces, fraction of cells showing a nucleus, fibre axis 0 none/1 x/2 y/3 z)
DETAIL_DEFAULTS = {
    "skin": (0.10, 95.0, 0.55, 0), "mucosa": (0.12, 115.0, 0.75, 0), "gland": (0.10, 120.0, 0.85, 0),
    "muscle": (0.08, 70.0, 0.35, 1), "fascia": (0.14, 55.0, 0.18, 0), "fat": (0.06, 28.0, 0.12, 0),
    "nerve": (0.07, 65.0, 0.30, 1), "artery": (0.06, 80.0, 0.25, 0), "vein": (0.06, 80.0, 0.25, 0),
    "cartilage": (0.07, 45.0, 0.50, 0), "bone": (0.10, 40.0, 0.30, 0), "lymph": (0.10, 160.0, 0.95, 0),
    "ligament": (0.10, 60.0, 0.15, 1), "tendon": (0.08, 55.0, 0.15, 1), "serosa": (0.06, 80.0, 0.20, 0),
    "nucleus": (0.10, 140.0, 0.90, 0), "brain": (0.08, 90.0, 0.30, 0), "white_matter": (0.06, 60.0, 0.15, 0),
    "organ": (0.10, 100.0, 0.70, 0), "csf": (0.02, 0.0, 0.0, 0), "nail": (0.06, 30.0, 0.05, 0),
    "lung": (0.08, 90.0, 0.40, 0), "eye": (0.03, 0.0, 0.0, 0), "other": (0.08, 60.0, 0.30, 0),
}


class Part:
    def __init__(self, name, group, color, mesh, description, alpha=1.0, category="other", label=True, rank=0,
                 clip=False, bulk=False, detail=None):
        self.clip = clip or bulk
        self.bulk = bulk
        self.name = name
        self.group = group
        self.color = color
        self.mesh = mesh
        self.description = description
        self.alpha = alpha
        self.category = category
        self.label = label
        self.rank = rank
        self.detail = tuple(detail) if detail is not None else DETAIL_DEFAULTS.get(category, DETAIL_DEFAULTS["other"])


class MicroModel:
    def __init__(self, id, name, summary, builder, targets=None, histology=(), related=(), scale_note="",
                 cutaway=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), cut_at=(0.0, 0.0), clinical=()):
        self.id = id
        self.name = name
        self.summary = summary
        self.builder = builder
        self.targets = targets or {}
        self.histology = list(histology)
        self.related = list(related)
        self.scale_note = scale_note
        self.cutaway = cutaway
        self.cut_at = cut_at
        self.clinical = list(clinical)
        self._parts = None

    def parts(self):
        if self._parts is None:
            from .cache import load_parts, save_parts, source_digest
            digest = source_digest(self)
            parts = load_parts(self.id, digest)
            if parts is None:
                parts = self.build()
                try:
                    save_parts(self.id, parts, digest)
                except OSError:
                    pass
            self._parts = parts
        return self._parts

    def build(self):
        return [p for p in self.builder() if p.mesh.parts]
