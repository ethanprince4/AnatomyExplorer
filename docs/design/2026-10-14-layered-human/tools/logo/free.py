"""Layered Human logo option "free": Quarter. The body with the skin cut away from its upper right quarter
(crown to hip, and the whole arm), showing the app's own superficial muscle layer in brass beneath. The cut faces of
the skin show its thickness; the cut at the hip is seen from a little above, so it curves round the body.

Rebuild everything (symbols, lockups, icons, favicon, notes' numbers, presentation board, exploration sheet):

  /home/user/AnatomyExplorer/.venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/free.py

That python has numpy, scipy, scikit-image, shapely and Pillow. The Literata wordmark comes from
tools/build_identity.py's wordmark(), which needs fontTools and uharfbuzz; it runs in the identity venv
(SCRATCH/../idvenv/bin/python). Rasterising and the board capture use node with Playwright (tools/raster_svg.mjs).
`free.py symbols` writes only the SVGs and icons; `free.py board` and `free.py explore` redo one picture each.

Sources: assets/plates/peel_00_skin.webp and peel_26_superficial.webp (alpha = outline of each layer), placed in the
shared camera frame with the boxes in assets/plates/plates.js. Frame: height 1000, top 0, centre x 0, like
identity/plate/figure.json.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build_identity as bi  # noqa: E402
import free_pixels as fp  # noqa: E402

n, svg, write = bi.n, bi.svg, bi.write
OUT = ROOT / "identity/options/free"
RENDERS = ROOT / "renders/checkpoint-1/logo"
SCRATCH = Path("/tmp/claude-0/-home-user-AnatomyExplorer/effa1011-ff25-5650-b9af-b091db4dac0b/scratchpad/logo-free")
IDPY = SCRATCH.parent / "idvenv/bin/python"
PLATES = ROOT / "assets/plates"
BIG = 4000

# ---- the drawing --------------------------------------------------------------------------------------------------
CUT_Y = 470        # the cross cut, at the iliac crest (frame units)
SKIN_T = 10        # thickness of the skin's cut faces
TILT = .37         # how far we look down on the cross cut (ry / rx)
SHADE_W = 13       # the skin's shadow on the muscle, beside the midline face
FIG_H = 48         # symbol: figure height in SVG units

DARK = {"ink": "#efece6", "accent": "#d4b47e", "lit": .72, "shade": .4, "shadow": .22, "paper": "#2a3138"}
LIGHT = {"ink": "#1d2024", "accent": "#8c6c37", "lit": .3, "shade": .55, "shadow": .16, "paper": "#ece8e0"}
MONO = {"ink": "currentColor", "accent": "currentColor", "accent_op": .45}
SLATE = bi.palette("specimen", "dark")          # wall #2a3138 to #1d2227, spot #3d4750

# macOS tile: the figure's height as a share of the 824 tile; small sizes are drawn on the pixel grid
MAC_FIG = .78
MAC_SMALL = {32: (5, 22), 16: (2, 12)}           # top pixel row and grid (figure height) in output pixels


def mask(name):
    """Alpha of a plate placed in the shared camera frame (3200 x 2322)."""
    from PIL import Image
    js = (PLATES / "plates.js").read_text()
    box_ = json.loads(js[js.index("=") + 1:].strip().rstrip(";"))["plates"][name]["box"]
    a = np.asarray(Image.open(PLATES / f"{name}.webp").convert("RGBA"))[..., 3]
    full = np.zeros((2322, 3200), bool)
    full[box_[1]:box_[3], box_[0]:box_[2]] = a > 127
    return full


def trace():
    """Symmetric, smoothed outlines of the skin and the superficial muscle layer, in the 1000 frame. The figure's
    right side (the viewer's left) is mirrored, so the midline is exactly x 0."""
    from scipy import ndimage
    from skimage import measure
    skin = mask("peel_00_skin")
    ys, xs = np.nonzero(skin)
    top, scale, cx = ys.min() - .5, 1000 / (ys.max() - ys.min() + 1), (xs.min() + xs.max()) / 2
    side = np.zeros_like(skin)                       # the columns of the hanging hands, clear of the thighs
    side[:, :int(cx - 250)] = side[:, int(cx + 250):] = True
    hands = side.copy()
    hands[:int(top + 540 / scale), :] = False
    near = side.copy()
    near[:int(top + 500 / scale), :] = False

    def outline(m, sigma):
        m = ndimage.binary_fill_holes(m)
        lab, k = ndimage.label(m)
        m = lab == 1 + int(np.argmax(ndimage.sum(m, lab, range(1, k + 1))))
        m = m | (ndimage.binary_closing(m, iterations=22) & near)     # fingers closed into a hand
        pad = 40
        m = np.pad(m, pad).astype(float)
        w = ndimage.gaussian_filter(np.pad(hands, pad).astype(float), 30) * np.pad(side, pad)   # a softer hand
        sm = (1 - w) * ndimage.gaussian_filter(m, sigma) + w * ndimage.gaussian_filter(m, 3 * sigma)
        c = max(measure.find_contours(sm, .5), key=len)
        c = measure.approximate_polygon(c, 1.0)
        g = Polygon([((x - pad - cx) * scale, (y - pad - top) * scale) for y, x in c]).buffer(0)
        g = max(getattr(g, "geoms", [g]), key=lambda p: p.area)
        h = g.intersection(box(-BIG, -BIG, 0, BIG))
        s = unary_union([h, affinity.scale(h, -1, 1, origin=(0, 0))]).buffer(.5).buffer(-.5)
        return max(getattr(s, "geoms", [s]), key=lambda p: p.area)

    # The muscle plate's hands are fringed tendons: draw them as the skin's hands, a little inside it.
    muscle = (mask("peel_26_superficial") & ~hands) | (ndimage.binary_erosion(skin, iterations=7) & hands)
    return outline(skin, 7), outline(muscle, 7)


def polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [q for x in getattr(g, "geoms", []) for q in polys(x)]


def segments(g, y):
    r = LineString([(-BIG, y), (BIG, y)]).intersection(g)
    return [(min(c[0] for c in q.coords), max(c[0] for c in q.coords))
            for q in getattr(r, "geoms", [r]) if not q.is_empty and q.length > 4]


def half_ellipse(cx, cy, rx, ry, steps=96):
    """The front half of a cross-section ellipse seen from above (below cy on screen), right of the midline."""
    pts = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in np.linspace(0, math.pi, steps)]
    return Polygon(pts).intersection(box(0, cy, BIG, BIG))


def quarter(skin, muscle, cy=CUT_Y, t=SKIN_T, tilt=TILT, sh=SHADE_W):
    """The regions of the mark, in the 1000 frame."""
    a, b = next(s for s in segments(skin, cy + .3) if s[0] < 0 < s[1])
    rx = b
    outer, inner = half_ellipse(0, cy, rx, rx * tilt), half_ellipse(0, cy, rx - t, (rx - t) * tilt)
    arm = unary_union([p for p in polys(skin.intersection(box(0, cy - 1, BIG, BIG))) if p.bounds[0] > 60])
    gone = unary_union([box(0, -BIG, BIG, cy), outer, arm.buffer(1)])
    look = unary_union([box(0, -BIG, BIG, cy), inner, arm.buffer(3)])
    brass = muscle.intersection(look).difference(box(-BIG, -BIG, t, BIG))
    mid = unary_union([skin.intersection(box(0, -BIG, t, cy)), skin.intersection(box(0, cy, t, BIG)).intersection(outer)])
    waist = outer.difference(inner).intersection(skin).difference(box(-BIG, -BIG, t, BIG))
    return {"skin": skin.difference(gone), "brass": brass, "shadow": brass.intersection(box(t, -BIG, t + sh, BIG)),
            "mid": mid.difference(waist), "waist": waist}


# ---- SVG -----------------------------------------------------------------------------------------------------------

def smooth_ring(c, k, ox, oy, corner=38):
    """A closed ring as cubic Beziers (Catmull-Rom), keeping corners that turn more than `corner` degrees."""
    m = len(c)
    pts = [np.array(p, float) for p in c]

    def sharp(i):
        u, v = pts[i] - pts[i - 1], pts[(i + 1) % m] - pts[i]
        cos = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9)
        return math.degrees(math.acos(max(-1, min(1, cos)))) > corner
    hard = [sharp(i) for i in range(m)]

    def tangent(i):
        return np.zeros(2) if hard[i] else (pts[(i + 1) % m] - pts[i - 1]) / 6

    def f(p):
        return f"{n(ox + p[0] * k)} {n(oy + p[1] * k)}"
    out = "M" + f(pts[0])
    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        c1, c2 = a + tangent(i), b - tangent((i + 1) % m)
        span = np.linalg.norm(b - a) / 2.2
        for c_, base in ((c1, a), (c2, b)):
            v = c_ - base
            if np.linalg.norm(v) > span:
                c_[:] = base + v * span / np.linalg.norm(v)
        out += ("L" + f(b)) if hard[i] and hard[(i + 1) % m] else f"C{f(c1)} {f(c2)} {f(b)}"
    return out + "Z"


def d(g, k=1., ox=0., oy=0., tol=1.4, smooth=True):
    out = []
    for p in polys(g.simplify(tol) if tol else g):
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.coords)[:-1]
            out.append(smooth_ring(c, k, ox, oy) if smooth else
                       "M" + "L".join(f"{n(ox + x * k)} {n(oy + y * k)}" for x, y in c) + "Z")
    return "".join(out)


def path(g, fill, op=1, cls=None, **kw):
    if g.is_empty:
        return ""
    paint = f' class="{cls}"' if cls else f' fill="{fill}"' + (f' fill-opacity="{n(op)}"' if op != 1 else "")
    return f"<path{paint} d=\"{d(g, **kw)}\"/>"


def art(r, pal, k, ox, oy, mono=False):
    """The mark: skin in ink, muscle in the accent, the skin's shadow on the muscle, the two cut faces."""
    kw = {"k": k, "ox": ox, "oy": oy}
    if mono:   # one colour: the muscle as a tint, the cut faces left open so the step still shows
        return path(r["skin"], pal["ink"], **kw) + path(r["brass"].difference(r["shadow"]), pal["accent"], pal["accent_op"], **kw)
    out = path(r["skin"], pal["ink"], **kw) + path(r["brass"], pal["accent"], **kw)
    if "shadow" in r:
        out += (path(r["shadow"], "#000", pal["shadow"], **kw) + path(r["mid"], pal["ink"], pal["shade"], **kw)
                + path(r["waist"], pal["ink"], pal["lit"], **kw))
    return out


def bounds(r, k):
    x0, y0, x1, y1 = unary_union(list(r.values())).bounds
    return x0 * k, y0 * k, x1 * k, y1 * k


def symbol(r, pal, mono=False, h=FIG_H, pad=.5):
    k = h / 1000
    x0, y0, x1, y1 = bounds(r, k)
    half = math.ceil((max(-x0, x1) + pad) * 100) / 100       # centred on the midline
    x0, y0 = -half, math.floor((y0 - pad) * 100) / 100
    w, hh = 2 * half, math.ceil((y1 + pad) * 100) / 100 - y0
    return svg(w, hh, art(r, pal, k, 0, 0, mono), view=f"{n(x0)} {n(y0)} {n(w)} {n(hh)}")


def small_symbol(pal, px=32):
    """symbol-small: the pixel-grid drawing (free_pixels.py) in a px box, figure 30 of 32 (or 15 of 16) pixels high,
    midline on a pixel edge."""
    g = fp.G30 if px == 32 else fp.G15
    return svg(px, px, fp.rects(g, px / 2, 1 if px == 32 else 0, 1, pal["ink"], pal["accent"]))


# ---- lockups -------------------------------------------------------------------------------------------------------
LOCK_H, LOCK_GAP = 2.25, .42     # figure height and gap, in cap heights; the figure is centred on the caps


def wordmark():
    code = ("import sys, json; sys.path.insert(0, %r); import build_identity as bi; w = bi.wordmark('specimen'); "
            "w['bounds'] = list(w['bounds']); print(json.dumps(w))" % str(ROOT / "tools"))
    return json.loads(subprocess.run([str(IDPY), "-c", code], check=True, capture_output=True, text=True).stdout)


def lockup(r, pal, word, mono=False):
    X0, Y0, X1, Y1 = word["bounds"]
    cap = word["cap"]
    k = LOCK_H * cap / 1000
    fx0, fy0, fx1, fy1 = bounds(r, k)
    ox = X0 - LOCK_GAP * cap - fx1
    oy = -cap / 2 - (fy0 + fy1) / 2
    mark = art(r, pal, k, ox, oy, mono)
    bx = (ox + fx0, min(Y0, oy + fy0), X1, max(Y1, oy + fy1))
    x0, y0 = math.floor(bx[0]), math.floor(bx[1])
    w, h = math.ceil(bx[2]) - x0, math.ceil(bx[3]) - y0
    s = 24 / cap
    return svg(w * s, h * s, mark + f'<path fill="{pal["ink"]}" d="{word["d"]}"/>', view=f"{x0} {y0} {w} {h}")


def recipe(word, r):
    """Live-text recipe: an inline symbol-dark.svg (centred on the midline) beside Literata."""
    em, cap = word["upm"], word["cap"]
    k = LOCK_H * cap / 1000
    fx0, fy0, fx1, fy1 = bounds(r, k)
    pad = .5 * k * 1000 / FIG_H                       # symbol-dark.svg pads the figure by 0.5 of 48 units
    half = max(-fx0, fx1) + pad
    hgt = fy1 - fy0 + 2 * pad
    margin = (LOCK_GAP * cap + fx1 - half - word["bounds"][0]) / em
    lift = (cap / 2 - hgt / 2) / em
    return (f"symbol `width:{2 * half / em:.3f}em; height:{hgt / em:.3f}em; margin-right:{margin:.3f}em; "
            f"vertical-align:{lift:.3f}em`")


# ---- icons ---------------------------------------------------------------------------------------------------------

def mac_icon(r, px, mode="dark"):
    """macOS: 1024 canvas, 824 superellipse tile at 100 with the drop shadow and the spotlight, as build_identity."""
    p = SLATE if mode == "dark" else {**bi.palette("specimen", "light"), "spot": "#f7f5f1"}
    pal = DARK if mode == "dark" else LIGHT
    u = 1024 / px
    tile = bi.superellipse(512, 512, 412)
    defs = bi.ground_defs(p, True) + '<filter id="sh" x="-.2" y="-.2" width="1.4" height="1.4"><feGaussianBlur stdDeviation="14"/></filter>'
    if px in MAC_SMALL:
        top, h = MAC_SMALL[px]
        mark = fp.rects(fp.GRIDS[h], 512, top * u, u, pal["ink"], pal["accent"])
    else:
        h = MAC_FIG * 824
        k = h / 1000
        x0, y0, x1, y1 = bounds(r, k)
        mark = art(r, pal, k, 512, 512 - (y0 + y1) / 2)
    body = (f'<path d="{tile}" fill="#000" fill-opacity=".3" transform="translate(0 11)" filter="url(#sh)"/>'
            + bi.ground(tile, True) + mark)
    if mode == "dark":
        body += bi.edge(512, 512, 412, max(2, u))
    return svg(1024, 1024, body, defs=defs)


def favicon():
    """The 16 px pixel drawing, transparent; ink and accent follow the browser's light or dark scheme."""
    def rules(pal):
        return f".i{{fill:{pal['ink']}}}.a{{fill:{pal['accent']}}}"
    style = f"<style>{rules(LIGHT)}@media (prefers-color-scheme: dark){{{rules(DARK)}}}</style>"
    return svg(16, 16, fp.rects(fp.G15, 8, 0, 1, None, None, classes=("i", "a")), style=style)


def raster(jobs):
    tmp = SCRATCH / "build"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "jobs.json").write_text(json.dumps([{"svg": str(a), "out": str(b), "size": s} for a, b, s in jobs]))
    subprocess.run(["node", str(ROOT / "tools/raster_svg.mjs"), str(tmp / "jobs.json")], check=True)


def contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in c]
        return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
    la, lb = sorted((lum(a), lum(b)))
    return (lb + .05) / (la + .05)


def build(only=None):
    skin, muscle = trace()
    r = quarter(skin, muscle)
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "symbol-dark.svg", symbol(r, DARK))
    write(OUT / "symbol-light.svg", symbol(r, LIGHT))
    write(OUT / "symbol-mono.svg", symbol(r, MONO, mono=True))
    write(OUT / "symbol-small.svg", small_symbol(DARK, 32))
    write(OUT / "src/symbol-small-16.svg", small_symbol(DARK, 16))
    write(OUT / "src/symbol-small-light.svg", small_symbol(LIGHT, 32))
    write(OUT / "favicon.svg", favicon())
    word = wordmark()
    write(OUT / "lockup-dark.svg", lockup(r, DARK, word))
    write(OUT / "lockup-light.svg", lockup(r, LIGHT, word))
    write(OUT / "lockup-mono.svg", lockup(r, MONO, word, mono=True))
    jobs, mac = [], {}
    for px in bi.MAC_SIZES:
        src = write(OUT / f"src/macos-{px}.svg", mac_icon(r, px))
        mac[px] = OUT / f"icon-{px}.png" if px in (1024, 128, 64, 32, 16) else SCRATCH / f"build/icon-{px}.png"
        jobs.append((src, mac[px], px))
    jobs.append((write(OUT / "src/macos-1024-light.svg", mac_icon(r, 1024, "light")), OUT / "icon-1024-light.png", 1024))
    raster(jobs)
    bi.write_icns(OUT / "icon.icns", mac)
    facts = {"recipe": recipe(word, r), "accent_light_on_paper": round(contrast(LIGHT["accent"], LIGHT["paper"]), 2),
             "accent_dark_on_wall": round(contrast(DARK["accent"], SLATE["top"]), 2),
             "ink_dark_on_wall": round(contrast(DARK["ink"], SLATE["top"]), 2),
             "accent_light_vs_ink": round(contrast(LIGHT["accent"], LIGHT["ink"]), 2)}
    print(json.dumps(facts, indent=1))
    return facts


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("all", "symbols"):
        build()
    if cmd in ("all", "board"):
        import free_board
        free_board.board()
    if cmd in ("all", "explore"):
        import free_explore
        free_explore.sheet()
