"""Trace the app's own layers (skin, superficial muscle, skeleton) from the peel plates' alpha channels.
Helper for layers.py; needs numpy, scipy, scikit-image and Pillow (.venv312).

Every body plate was rendered by one camera; plates.js gives each plate's crop box in that camera's pixels, so the
alpha channels are pasted into one shared canvas before tracing. The frame is the one of identity/plate/figure.json:
the skin is 1000 units from the top of the head to the soles, top at 0, centred on x 0.

A layer is kept as a smooth field (a blurred mask, 0.5 on the outline), so cutaways and unions can be computed as
min / max of fields and traced once: the cut edges come out crisp and the body edges stay smooth."""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import measure

ROOT = Path(__file__).resolve().parents[2]
PLATES = ROOT / "assets/plates"
STEP = 2   # canvas pixels per traced pixel: the plates are ~2200 px tall, 1100 is plenty for curves

# layer: (plate, closing radius in plate px, blur sigma in plate px). The skeleton is closed so the ribs, the
# vertebrae and the small bones of hands and feet merge into a cage, a column, a hand and a foot.
LAYERS = {
    "skin": ("peel_00_skin", 0, 7),
    "muscle": ("body_muscles", 3, 7),
    "skeleton": ("body_skeleton", 7, 5),
}


@lru_cache(None)
def boxes():
    js = (PLATES / "plates.js").read_text()
    return json.loads(js[js.index("=") + 1:].strip().rstrip(";"))["plates"]


@lru_cache(None)
def canvas():
    """The camera canvas that holds every plate used here: origin and size in camera pixels."""
    bs = [boxes()[p]["box"][:4] for p, _, _ in LAYERS.values()]
    x0, y0 = min(b[0] for b in bs) - 80, min(b[1] for b in bs) - 80
    x1, y1 = max(b[2] for b in bs) + 80, max(b[3] for b in bs) + 80
    return x0, y0, x1 - x0, y1 - y0


def mask(plate, keep=.002):
    """The plate's alpha, holes filled, small specks dropped, pasted into the camera canvas."""
    x0, y0, w, h = canvas()
    bx, by = boxes()[plate]["box"][:2]
    a = np.asarray(Image.open(PLATES / f"{plate}.webp").convert("RGBA"))[..., 3] > 127
    out = np.zeros((h, w), bool)
    out[by - y0:by - y0 + a.shape[0], bx - x0:bx - x0 + a.shape[1]] = a
    return out


def clean(m, close, keep=.002):
    if close:
        m = ndimage.binary_closing(np.pad(m, close * 2), ndimage.generate_binary_structure(2, 1), close)
        m = m[close * 2:-close * 2, close * 2:-close * 2]
    m = ndimage.binary_fill_holes(m)
    lab, cnt = ndimage.label(m)
    sizes = ndimage.sum(m, lab, range(1, cnt + 1))
    return np.isin(lab, 1 + np.nonzero(sizes > keep * sizes.max())[0])


@lru_cache(None)
def frame():
    """(cx, top, scale) of the skin, in camera canvas pixels: maps canvas px to the 1000 frame."""
    m = mask("peel_00_skin")
    ys, xs = np.nonzero(m)
    return (xs.min() + xs.max()) / 2, ys.min() - .5, 1000 / (ys.max() - ys.min() + 1)


@lru_cache(None)
def field(layer, grow=0, holes=False):
    """Smooth field of a layer on the traced grid (STEP px). grow thickens it (plate px) for small sizes.
    holes=True keeps the skeleton's enclosed gaps (the pelvic inlet, the space between ribs and pelvis)."""
    plate, close, sigma = LAYERS[layer]
    m = mask(plate)
    m = clean(m, close) if not holes else _keep_big_holes(m, close)
    if grow:
        m = ndimage.binary_dilation(m, iterations=grow)
    f = ndimage.gaussian_filter(m.astype(np.float32), sigma)[::STEP, ::STEP]
    if layer == "skin":  # the model's hair flattens the crown: take the skull's curve from the muscle layer
        xs, ys = grid()
        head = inset(field("muscle", grow), -9)
        w = np.clip((165 - ys[:, None]) / 25, 0, 1) * np.ones((1, len(xs)), np.float32)
        f = f * (1 - w) + head * w
    if layer != "skeleton":  # mitten hands: the fingers merge into one tapered shape
        xs, ys = grid()
        w = np.clip((np.abs(xs[None, :]) - 120) / 25, 0, 1) * np.clip((ys[:, None] - 480) / 30, 0, 1)
        big = ndimage.gaussian_filter(ndimage.binary_dilation(m, iterations=6).astype(np.float32), 13)[::STEP, ::STEP]
        f = f * (1 - w) + big * w
    return f


def _keep_big_holes(m, close):
    c = clean(m, close)
    filled = ndimage.binary_fill_holes(c)
    hole = filled & ~c
    lab, cnt = ndimage.label(hole)
    if cnt:
        sizes = ndimage.sum(hole, lab, range(1, cnt + 1))
        hole = np.isin(lab, 1 + np.nonzero(sizes > 2500)[0])
    return filled & ~hole


def grid():
    """Frame coordinates (x, y) of the traced grid's pixel centres: two 1D arrays."""
    x0, y0, w, h = canvas()
    cx, top, s = frame()
    xs = (np.arange(0, w, STEP) + (STEP - 1) / 2 - cx) * s
    ys = (np.arange(0, h, STEP) + (STEP - 1) / 2 - top) * s
    return xs, ys


def halfplane(a, b, c, soft=1.5):
    """Field of the half plane a*x + b*y + c > 0 in frame units, ramping over `soft` units: crisp cut edges."""
    xs, ys = grid()
    d = (a * xs[None, :] + b * ys[:, None] + c) / np.hypot(a, b)
    return np.clip(.5 + d / (2 * soft), 0, 1).astype(np.float32)


def contours(f, level=.5, tol=1.2, min_area=40):
    """Closed polylines of a field at `level`, in frame units, simplified to tol units. Outer rings run one way and
    holes the other, so they can share one path with the nonzero fill rule."""
    xs, ys = grid()
    pad = np.pad(f, 2)
    out = []
    for c in measure.find_contours(pad, level):
        r, k = c[:, 0] - 2, c[:, 1] - 2
        pts = np.stack([np.interp(k, np.arange(len(xs)), xs), np.interp(r, np.arange(len(ys)), ys)], 1)
        area = .5 * np.sum(pts[:-1, 0] * pts[1:, 1] - pts[1:, 0] * pts[:-1, 1])
        if abs(area) < min_area:
            continue
        p = measure.approximate_polygon(pts, tol)
        if len(p) > 1 and np.allclose(p[0], p[-1]):
            p = p[:-1]
        if len(p) >= 3:
            out.append(p)
    return out


def raster(shapes, sample):
    """A field from drawn shapes (fills and round-capped strokes in frame units), so drawn parts such as the
    skeleton can be cut like the traced layers."""
    from PIL import ImageDraw
    xs, ys = grid()
    u = xs[1] - xs[0]
    sup = 3
    im = Image.new("L", (len(xs) * sup, len(ys) * sup), 0)
    d = ImageDraw.Draw(im)

    def px(p):
        return [((x - xs[0]) / u * sup + sup / 2, (y - ys[0]) / u * sup + sup / 2) for x, y in p]
    for s in shapes:
        for p, closed in s["rings"]:
            q = px(sample(p, closed))
            if s["kind"] == "fill":  # a ring that starts inside an earlier one is a hole
                cx, cy = sum(x for x, _ in q) / len(q), sum(y for _, y in q) / len(q)
                d.polygon(q, fill=0 if im.getpixel((int(cx), int(cy))) else 255)
            else:
                w = s["w"] / u * sup
                d.line(q + q[:1] if closed else q, fill=255, width=max(1, round(w)), joint="curve")
                if not closed:
                    for x, y in (q[0], q[-1]):
                        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
    a = np.asarray(im.resize((len(xs), len(ys)), Image.BOX), np.float32) / 255
    return ndimage.gaussian_filter(a, .6)


def ellipse(cx, cy, rx, ry, soft=1.2):
    """Field of a filled ellipse in frame units, with a crisp edge."""
    xs, ys = grid()
    X, Y = (xs[None, :] - cx) / rx, (ys[:, None] - cy) / ry
    r = np.sqrt(X * X + Y * Y)
    g = np.hypot(X / rx, Y / ry) / np.maximum(r, 1e-6)   # 1 / local scale of r, for an edge of `soft` units
    return np.clip(.5 + (1 - r) / (g * 2 * soft + 1e-9), 0, 1).astype(np.float32)


def inset(f, d, soft=1.2):
    """The field's shape moved inward by d frame units (outward if d < 0), with a crisp edge."""
    xs, _ = grid()
    u = xs[1] - xs[0]
    m = f > .5
    dist = np.where(m, ndimage.distance_transform_edt(m), -ndimage.distance_transform_edt(~m)) * u
    return np.clip(.5 + (dist - d) / (2 * soft), 0, 1).astype(np.float32)


def spans(f, y, level=.5):
    """The runs of a field along the row at frame y: [(x0, x1), ...] in frame units."""
    xs, ys = grid()
    row = f[int(np.argmin(np.abs(ys - y)))] > level
    edges = np.flatnonzero(np.diff(np.r_[0, row.astype(int), 0]))
    return [(float(xs[a]), float(xs[b - 1])) for a, b in zip(edges[::2], edges[1::2])]


def bbox(f, level=.5):
    xs, ys = grid()
    on = f > level
    r, c = np.nonzero(on)
    return xs[c.min()], ys[r.min()], xs[c.max()], ys[r.max()]
