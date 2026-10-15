"""Logo option "layers" (Vitrine): three glass plates standing one behind the other, turned 34 degrees, each carrying
one of the app's own layers, traced from the peel plates' alpha channels: the skin, the superficial muscle and the
skeleton (drawn on measured landmarks) in brass.

Rebuild everything with one command, from the repository root:
  .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/layers.py
That Python has numpy, scipy, scikit-image and Pillow. Subcommands: `explore` (the contact sheet of every variation,
renders/checkpoint-1/logo/layers-explore.webp), `build` (identity/options/layers/ and the board,
renders/checkpoint-1/logo/layers.webp); no argument runs both.
Also needed: node with Playwright and Chromium (tools/raster_svg.mjs, the board and sheet captures), and the identity
venv with fontTools and uharfbuzz for the outlined wordmark (build_identity.wordmark("specimen")): by default
<scratchpad>/idvenv, or set LH_IDVENV. Scratch files go to $LH_SCRATCH/logo-layers.
Helpers: layers_trace.py (tracing, fields, cuts), layers_draw.py (curves, 3D camera, the skeleton)."""
import json
import math
import os
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(HERE)]

import numpy as np  # noqa: E402

import build_identity as BI  # noqa: E402
import layers_trace as T  # noqa: E402
from layers_draw import (Camera, affine, bounds, fit, mirror, muscle_lines, on_plate, render,  # noqa: E402
                         sample, skeleton)
from build_identity import n, superellipse, ground_defs, ground, edge, svg  # noqa: E402

SLUG = "layers"
OPT = ROOT / "identity/options" / SLUG
RENDERS = ROOT / "renders/checkpoint-1/logo"
SCRATCH = Path(os.environ.get("LH_SCRATCH", "/tmp/claude-0/-home-user-AnatomyExplorer/"
                              "effa1011-ff25-5650-b9af-b091db4dac0b/scratchpad")) / "logo-layers"
IDVENV = Path(os.environ.get("LH_IDVENV", SCRATCH.parent / "idvenv")) / "bin/python"

# Brand colours for this option (brief): slate tile, ink and brass; paper, dark ink and a darker brass.
DARK = {"ink": "#efece6", "accent": "#d4b47e", "top": "#2a3138", "bottom": "#1d2227", "spot": "#3d4750",
        "paper": "#2a3138"}
LIGHT = {"ink": "#1d2024", "accent": "#8d6c35", "top": "#ece8e0", "bottom": "#ddd8ce", "spot": "#f6f3ee",
         "paper": "#ece8e0"}


# ---- traced layers -------------------------------------------------------------------------------------------------

def rings(f, tol=1.4, min_area=60):
    return [([(float(x), float(y)) for x, y in c], True) for c in T.contours(f, tol=tol, min_area=min_area)]


@lru_cache(None)
def layer(name, small=False):
    """Rings of a traced layer. small: thickened by 12 plate px, coarser."""
    f = T.field(name, grow=12 if small else 0)
    return rings(f, tol=2.6 if small else 1.4)


def fill(rs, role="ink", op=1.0, smooth=True, **kw):
    return dict(kind="fill", rings=rs, role=role, op=op, smooth=smooth, **kw)


def stroke(rs, w, role="ink", op=1.0, smooth=True, **kw):
    return dict(kind="stroke", rings=rs, role=role, op=op, w=w, smooth=smooth, **kw)


def glass(x0, y0, x1, y1):
    return [([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True)]


@lru_cache(None)
def skel_field(small=False):
    return T.raster(skeleton(small=small), sample)


def cut(f, *planes):
    for a, b, c in planes:
        f = np.minimum(f, T.halfplane(a, b, c))
    return f


# ---- variations ----------------------------------------------------------------------------------------------------
# Each returns a drawing (list of shapes) in the figure frame. small=True is the 16-32 px drawing.

def vitrine(small=False, yaw=34, gap=300):
    """Three glass plates standing one behind the other, turned to show the stack: skin, muscle, skeleton."""
    cam = Camera(yaw=yaw, f=2600, zc=gap)
    plate = glass(-235, -45, 235, 1045)
    out = []
    for z, art in ((2 * gap, skeleton(small=small)),
                   (gap, [fill(layer("muscle", small), op=.5)]),
                   (0, [fill(layer("skin", small), op=.92)])):
        if not small:
            out += on_plate([fill(plate, op=.05, smooth=False), stroke(plate, 4, op=.4, smooth=False)], cam, z)
        out += on_plate(art, cam, z)
    return out


def stack(small=False, step=(105, -62), shrink=.93):
    """An exploded stack, receding up and to the right: skin as a glass outline, muscle, brass skeleton."""
    out = []
    layers = [skeleton(small=small), [fill(layer("muscle", small), op=.5)],
              [fill(layer("skin", small), op=.16 if not small else .3), stroke(layer("skin", small), 6 if not small else 14)]]
    for i, art in enumerate(layers):
        k = 2 - i
        for s in affine(art, shrink ** k, step[0] * k, step[1] * k, 0, 500):
            s["depth"] = k
            out.append(s)
    return out


def terrace(small=False, m=-.35, t=None, c1=560, c2=330):
    """One figure, cut in diagonal terraces: skin below, muscle above it, the skeleton at the top. Each cut shows
    its face, the thickness of the layer."""
    t = t or (16 if not small else 30)   # the cut lines y = c + m x: skin below c1, muscle below c2

    def below(c):
        return (-m, 1, -c)

    def above(c):
        return (m, -1, c)
    skin, mus = T.field("skin", grow=12 if small else 0), T.field("muscle", grow=12 if small else 0)
    sk = skel_field(small)
    tol = 1.4 if not small else 2.6
    return [fill(rings(cut(sk, above(c2 - t)), tol), role="accent"),
            fill(rings(cut(mus, below(c2 - t), above(c2)), tol), op=.26),       # the muscle's cut face
            fill(rings(cut(mus, below(c2), above(c1 - t)), tol), op=.5),
            fill(rings(cut(skin, below(c1 - t), above(c1)), tol), op=.66),      # the skin's cut face
            fill(rings(cut(skin, below(c1)), tol), op=1)]


def page(small=False, angle=62):
    """The skin turned back like a page on a hinge at the figure's left, showing the muscle and the skeleton."""
    import math
    hinge = -235
    a = math.radians(angle)
    cam = Camera(f=2400)

    def swing(shapes):
        out = []
        for s in shapes:
            t = dict(s)
            t["rings"] = [([cam.point(hinge + (x - hinge) * math.cos(a), y, -(x - hinge) * math.sin(a))[:2]
                            for x, y in p], c) for p, c in s["rings"]]
            if "w" in s:
                t["w"] = s["w"]
            out.append(t)
        return out
    plate = glass(hinge, -45, 235, 1045)
    back = on_plate([fill(layer("muscle", small), op=.5)] + skeleton(small=small), cam, 0)
    front = [fill(layer("skin", small), op=.92)]
    if not small:
        front = [fill(plate, op=.06, smooth=False), stroke(plate, 4, op=.45, smooth=False)] + front
    return back + swing(front)


def split(small=False, t=14):
    """Half and half: skin on the figure's right, the muscle on its left with the skeleton inside, the skin's
    cut edge showing its thickness."""
    skin, mus = T.field("skin", grow=12 if small else 0), T.field("muscle", grow=12 if small else 0)
    tol = 1.4 if not small else 2.6
    sk = skel_field(small)
    return [fill(rings(cut(mus, (1, 0, 0)), tol), op=.42),
            fill(rings(cut(sk, (1, 0, -4)), tol), role="accent"),
            fill(rings(cut(skin, (-1, 0, 0)), tol), op=1),
            fill(rings(cut(skin, (1, 0, 0), (-1, 0, t)), tol), op=.62)]


def nested(small=False):
    """Nested in depth: the skin outline in front, the muscle smaller behind it, the skeleton deepest, all
    receding to one point at the chest."""
    out = [stroke(layer("skin", small), 7 if not small else 16)]
    out += [dict(s, depth=1) for s in affine([fill(layer("muscle", small), op=.45)], .84, 0, 0, 0, 330)]
    out += [dict(s, depth=2) for s in affine(skeleton(small=small), .68, 0, 0, 0, 330)]
    return out


def section(small=False, A=600, B=318, e=.3, t=11):
    """One figure cut by two level planes, seen a little from above: skin below, muscle between, the skeleton on
    top. Each cut shows its face: the skin's thickness as a ring, the muscle around the bones."""
    sk_f, mu_f = T.field("skin", grow=12 if small else 0), T.field("muscle", grow=12 if small else 0)
    mu_f = np.minimum(mu_f, T.inset(sk_f, t))          # keep the skin's thickness visible all round
    bone = skel_field(small)
    tol = 1.4 if not small else 2.6

    def faces(f, y, shrink=0):
        g = np.zeros_like(f)
        for x0, x1 in T.spans(f, y):
            rx = (x1 - x0) / 2 - shrink
            g = np.maximum(g, T.ellipse((x0 + x1) / 2, y, rx, rx * e))
        return g
    below = lambda y: (0, 1, -y)     # noqa: E731
    above = lambda y: (0, -1, y)     # noqa: E731
    out = []
    # skin: the legs below A, and the cut face
    out.append(fill(rings(cut(sk_f, below(A)), tol), op=1))
    out.append(fill(rings(faces(sk_f, A), tol), op=.62))
    # muscle: from A up to B; at A it stands on the face, its base the front half of an ellipse
    base = np.minimum(faces(mu_f, A), T.halfplane(0, 1, -A))
    out.append(fill(rings(np.maximum(cut(mu_f, below(B), above(A)), base), tol), op=.46))
    face_b = faces(mu_f, B)
    out.append(fill(rings(face_b, tol), op=.26))
    # bone sections in the face: the humeri and the ribcage (a ring), as they leave the muscle
    sec = np.zeros_like(face_b)
    for x in (-117, 117):
        sec = np.maximum(sec, T.ellipse(x, B, 9, 9 * e))
    out.append(fill(rings(sec, tol), role="accent"))
    rib = [s for s in T.spans(mu_f, B) if s[0] < 0 < s[1]][0]
    rx = (rib[1] - rib[0]) / 2 - 12
    ring = np.minimum(T.ellipse(0, B, rx, rx * e), 1 - T.ellipse(0, B, rx - 7, (rx - 7) * e))
    out.append(fill(rings(ring, tol), role="accent"))
    # the skeleton above B
    out.append(fill(rings(cut(bone, above(B)), tol), role="accent"))
    return out


def vitrine_close(small=False):
    return vitrine(small, yaw=30, gap=150)


def pane(y0, y1, cut_y=None, m=0.0, x0=-235, x1=235):
    """A glass pane from y0 to y1; with cut_y its top edge is the line y = cut_y + m x."""
    if cut_y is None:
        return [([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True)]
    return [([(x0, cut_y + m * x0), (x1, cut_y + m * x1), (x1, y1), (x0, y1)], True)]


def tiers(small=False, yaw=28, gap=120, c1=560, c2=300, m=0.0, panes=True, skin_op=1.0):
    """Three glass panes one behind the other, each cut lower than the one behind: the skin pane holds the legs,
    the muscle pane rises to the chest, the skeleton pane is whole. Seen turned, the cuts step back in depth."""
    cam = Camera(yaw=yaw, f=2600, zc=gap)
    sk_f, mu_f = T.field("skin", grow=12 if small else 0), T.field("muscle", grow=12 if small else 0)
    tol = 1.4 if not small else 2.6
    below = lambda c: (-m, 1, -c)     # noqa: E731
    out = []
    for z, art, top in ((2 * gap, skeleton(small=small), None),
                        (gap, [fill(rings(cut(mu_f, below(c2)), tol), op=.5)], c2),
                        (0, [fill(rings(cut(sk_f, below(c1)), tol), op=skin_op)], c1)):
        if panes and not small:
            g = pane(-45, 1045, top, m)
            out += on_plate([fill(g, op=.05, smooth=False), stroke(g, 4, op=.42, smooth=False)], cam, z)
        out += on_plate(art, cam, z)
    return out


def inside_out(small=False, yaw=26, gap=150, panes=True):
    """The plates in reverse: the brass skeleton in front, the muscle behind it, the skin at the back, close
    enough to read as one body whose layers step back in depth."""
    cam = Camera(yaw=yaw, f=2600, zc=gap)
    plate = glass(-235, -45, 235, 1045)
    out = []
    for z, art in ((2 * gap, [fill(layer("skin", small), op=.9)]),
                   (gap, [fill(layer("muscle", small), op=.5)]),
                   (0, skeleton(small=small))):
        if panes and not small:
            out += on_plate([fill(plate, op=.05, smooth=False), stroke(plate, 4, op=.4, smooth=False)], cam, z)
        out += on_plate(art, cam, z)
    return out


# ---- round 2: the two strongest, with drawings for 32 px ("S") and 16 px ("XS") --------------------------------------
GROW = {False: 0, "M": 5, "S": 10, "XS": 20}  # thickening of the traced layers, plate px
PX = {False: 0, "S": 46, "XS": 92}             # about one output pixel, in frame units, for the small drawings


def layer2(name, size):
    return rings(T.field(name, grow=GROW[size]), tol={False: 1.4, "M": 2}.get(size, 3))


def bones(size, role="accent", op=1.0):
    """The skeleton for each size: drawn bones; at 32 px heavier and simpler; at 16 px a brass silhouette."""
    if size == "XS":
        return [fill(rings(T.inset(T.field("muscle", grow=GROW["XS"]), 8), 3), role=role, op=op)]
    if size == "S":
        return skeleton(role, op, wk=2.3, small=True)
    return skeleton(role, op, wk=2.2 if size == "M" else 1.2)


def vitrine2(size=False, yaw=34, gap=300, base=False, panes=None, two=False):
    """Final A: three glass plates, one behind the other, turned 34 degrees: the skin, the superficial muscle and
    the skeleton in brass. Sizes: False (large), "M" (64 px), "S" (32 px), "XS" (16 px: no glass)."""
    panes = size != "XS" if panes is None else panes
    if size == "XS":  # 16 px: the skin and a brass figure only, far enough apart that each keeps its head
        cam = Camera(yaw=40, f=2600, zc=380)
        return (on_plate([fill(rings(T.field("muscle", grow=6), 3), role="accent")], cam, 760)
                + on_plate([fill(rings(T.field("skin", grow=6), 3))], cam, 0))
    cam = Camera(yaw=yaw, f=2600, zc=gap)
    plate = glass(-235, -45, 235, 1045)
    out = []
    if base:  # a low plinth the plates stand in
        z0, z1 = -60, 2 * gap + 60
        top = [cam.point(x, 1045, z)[:2] for x, z in ((-260, z0), (260, z0), (260, z1), (-260, z1))]
        front = [cam.point(x, y, z0)[:2] for x, y in ((-260, 1045), (260, 1045), (260, 1080), (-260, 1080))]
        out += [dict(fill([(top, True)], op=.1, smooth=False), depth=3 * gap),
                dict(fill([(front, True)], op=.28, smooth=False), depth=-1)]
    w = 4
    edge_op = {False: .4, "M": .36, "S": .32, "XS": .28}[size]
    muscle = [fill(layer2("muscle", size), op=.5)] + (muscle_lines(op=.42) if not size else [])
    stack = [(2 * gap, bones(size)), (gap, muscle), (0, [fill(layer2("skin", size))])]
    if two:  # 16 px: the skin and the skeleton only, one pane apart
        stack = [stack[0], stack[2]]
    for z, art in stack:
        if panes:
            edge = stroke(plate, w, op=edge_op, smooth=False)
            edge["px" if size in ("S", "XS") else "minpx"] = 1
            out += on_plate([fill(plate, op=.05, smooth=False), edge], cam, z)
        out += on_plate(art, cam, z)
    return out


def terrace2(size=False, m=.35, c1=560, c2=330):
    """Final B: one figure cut in slanting terraces: skin below, muscle above it, the skeleton at the top; each cut
    shows its face, the thickness of the layer."""
    t = {False: 24, "M": 30, "S": 40, "XS": 0}[size]
    below = lambda c: (-m, 1, -c)    # noqa: E731
    above = lambda c: (m, -1, c)     # noqa: E731
    skin, mus = T.field("skin", grow=GROW[size]), T.field("muscle", grow=GROW[size])
    sk = T.inset(mus, 8) if size == "XS" else T.raster(bones(size), sample)
    tol = {False: 1.4, "M": 2}.get(size, 3)
    out = [fill(rings(cut(sk, above(c2 - t)), tol), role="accent"),
           fill(rings(cut(mus, below(c2), above(c1 - t)), tol), op=.5),
           fill(rings(cut(skin, below(c1)), tol), op=1)]
    if t:
        out[1:1] = [fill(rings(cut(mus, below(c2 - t), above(c2)), tol), op=.26)]
        out[-1:-1] = [fill(rings(cut(skin, below(c1 - t), above(c1)), tol), op=.66)]
    return out


# The contact sheet: round 1 (six directions), round 2 (the strongest pushed further), round 3 (the finals).
VARIATIONS = {
    "vitrine": ("1 Vitrine: three glass plates, turned", vitrine),
    "stack": ("1 Exploded stack, up and back", stack),
    "terrace": ("1 Terraced cutaway, one figure", terrace),
    "page": ("1 Skin turned back like a page", page),
    "split": ("1 Half skin, half muscle and bone", split),
    "nested": ("1 Nested, receding to the chest", nested),
    "section": ("2 Level sections seen from above", section),
    "vitrine-close": ("2 Vitrine, plates close", vitrine_close),
    "tiers-diag": ("2 Tiered panes, slanted cuts", lambda small=False: tiers(small, c1=600, c2=340, m=-.4)),
    "inside-out": ("2 Inside out: skeleton in front", inside_out),
    "vitrine-26": ("2 Vitrine, 26 degrees, deeper", lambda small=False: vitrine(small, 26, 360)),
    "terrace-up": ("2 Terrace, cuts rising", lambda small=False: terrace(small, -.35, 24 if not small else 34)),
    "v2-two": ("3 Vitrine, glass kept at 16 px", lambda small=False: vitrine2(small, two=small == "XS", panes=True)),
    "terrace-final": ("3 Terrace, pushed further (not taken)", lambda small=False: terrace2(small)),
    "layers": ("3 Vitrine, finished", lambda small=False: vitrine2(small)),
}


# ---- icons ---------------------------------------------------------------------------------------------------------

def mac_tile(shapes, p, px, ext=.74):
    """macOS icon: 1024 canvas, 824 superellipse tile with the spotlight; the drawing fitted to ext of the tile."""
    u = 1024 / px
    tile = superellipse(512, 512, 412)
    defs = ground_defs(p, True) + ('<filter id="sh" x="-.2" y="-.2" width="1.4" height="1.4">'
                                   '<feGaussianBlur stdDeviation="14"/></filter>')
    mark = place(shapes, (100, 100, 824), ext, u, snap=px <= 32)
    body = (f'<path d="{tile}" fill="#000" fill-opacity=".3" transform="translate(0 11)" filter="url(#sh)"/>'
            + ground(tile, True) + render(mark, p) + edge(512, 512, 412, max(2, u)))
    return svg(1024, 1024, body, defs=defs)


def place(shapes, box, ext, u, snap=False):
    """Fit a drawing into box; u is one output pixel in box units. Shapes with "px" get strokes of that many output
    pixels. snap moves the drawing so the outer glass edges fall on whole pixels."""
    mark, k = fit(shapes, box, ext)
    for s in mark:
        if "px" in s:
            s["w"] = s["px"] * u
        if "minpx" in s:
            s["w"] = max(s["w"], s["minpx"] * u)
    if snap:
        x0, y0, _, _ = bounds(mark)
        dx, dy = (round(x0 / u) - x0 / u) * u, (round(y0 / u) - y0 / u) * u
        mark = affine(mark, 1, dx, dy)
    return mark


def raster(jobs):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(jobs, f)
    subprocess.run(["node", str(ROOT / "tools/raster_svg.mjs"), f.name], check=True)
    os.unlink(f.name)


def shoot(html, out, w, h, scale=2):
    """Capture an HTML file with Chromium (Playwright) to PNG."""
    js = f"""import {{ chromium }} from '/opt/node-tools/node_modules/playwright/index.mjs';
const b = await chromium.launch({{ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' }});
const p = await b.newPage({{ viewport: {{ width: {w}, height: {h} }}, deviceScaleFactor: {scale} }});
await p.goto('file://{html}'); await p.waitForTimeout(400);
await p.screenshot({{ path: '{out}', fullPage: true }}); await b.close();"""
    script = SCRATCH / "shoot.mjs"
    script.write_text(js)
    subprocess.run(["node", str(script)], check=True)


def webp(png, out, quality=90):
    from PIL import Image
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.open(png).convert("RGB").save(out, quality=quality, method=5)


def explore(names=None, tag="explore"):
    names = names or list(VARIATIONS)
    work = SCRATCH / tag
    work.mkdir(parents=True, exist_ok=True)
    jobs, rows = [], []
    for name in names:
        label, fn = VARIATIONS[name]
        big, small, tiny = fn(), fn(small="S"), fn(small="XS")
        BI.write(work / f"{name}-symbol.svg", svg(*_sym(big, DARK)))
        cells = []
        for px in (256, 64, 32, 16):
            src = work / f"{name}-{px}.svg"
            art = {32: small, 16: tiny}.get(px, big)
            BI.write(src, mac_tile(art, DARK, px, {256: .74, 64: .8, 32: .88, 16: .92}[px]))
            jobs.append({"svg": str(src), "out": str(work / f"{name}-{px}.png"), "size": px})
            cells.append(f"{name}-{px}.png")
        rows.append((name, label, cells))
    raster(jobs)
    html = ['<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="file://'
            f'{ROOT}/assets/fonts/fonts.css"><style>body{{margin:0;background:#1d2227;color:#efece6;'
            'font:15px "Fira Sans";padding:28px 32px}h1{font:400 26px Literata;margin:0 0 6px}p{color:#a9aeb3;margin:0 0 18px}'
            '.r{display:flex;align-items:center;gap:26px;padding:14px 0;border-top:1px solid #3e4851}'
            '.l{width:210px}.l b{font:500 17px Literata;display:block;margin-bottom:4px}'
            '.l span{color:#a9aeb3;font-size:13px}.z{image-rendering:pixelated}'
            '.sym{width:150px;height:150px;background:#2a3138}</style><h1>Layers: explorations</h1><p>Each row: the icon at 256, 64, 32 and 16 px, '
            'then 32 and 16 enlarged four times, then the symbol. Numbers give the round.</p>']
    for name, label, cells in rows:
        a, b, c, d = cells
        html.append(f'<div class="r"><div class="l"><b>{name}</b><span>{label}</span></div>'
                    f'<img src="{a}" width="256"><img src="{b}" width="64"><img src="{c}" width="32">'
                    f'<img src="{d}" width="16"><img class="z" src="{c}" width="128">'
                    f'<img class="z" src="{d}" width="64"><img class="sym" src="{name}-symbol.svg"></div>')
    page = work / "sheet.html"
    page.write_text("".join(html))
    shoot(page, work / "sheet.png", 1100, 400)
    if tag == "explore" and names == list(VARIATIONS):
        webp(work / "sheet.png", RENDERS / f"{SLUG}-explore.webp")
    return work / "sheet.png"


def _sym(shapes, p, pad=0):
    x0, y0, x1, y1 = bounds(shapes)
    body = render(shapes, p)
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    return w / 10, h / 10, body, f"{n(x0 - pad)} {n(y0 - pad)} {n(w)} {n(h)}"


# ---- the finished options -------------------------------------------------------------------------------------------

OPTIONS = {
    "layers": {"name": "Vitrine", "art": vitrine2, "lockup": (3.3, .45), "header": 2.0,
               "line": "Three glass plates stand one behind the other, each carrying one of the app's own layers: "
                       "the skin, the muscle, the skeleton in brass."},
}
MONO = {"ink": "currentColor", "accent": "currentColor", "paper": "none"}
SIZES = {1024: False, 128: False, 64: "M", 32: "S", 16: "XS"}
EXT = {1024: .74, 128: .76, 64: .8, 32: .88, 16: .92}   # the drawing's larger side, as a fraction of the 824 tile


@lru_cache(None)
def art(slug, size):
    return OPTIONS[slug]["art"](size)


@lru_cache(None)
def word():
    """The outlined Literata wordmark from build_identity.wordmark("specimen"), run in the identity venv."""
    code = (f"import sys, json; sys.path.insert(0, {str(ROOT / 'tools')!r}); import build_identity as B; "
            "w = B.wordmark('specimen'); print(json.dumps(w))")
    return json.loads(subprocess.run([str(IDVENV), "-c", code], check=True, capture_output=True, text=True).stdout)


def hairlines(shapes, unit):
    """Strokes marked in output pixels ("px", "minpx") for a drawing where one pixel is `unit` frame units."""
    out = []
    for s in shapes:
        s = dict(s)
        if "px" in s:
            s["w"] = s["px"] * unit
        if "minpx" in s:
            s["w"] = max(s["w"], s["minpx"] * unit)
        out.append(s)
    return out


def symbol(shapes, p, h=48, px=None):
    """Tight viewBox around the drawing, nominal height h px. px: the height at which its hairlines are 1 px."""
    x0, y0, x1, y1 = bounds(shapes)
    if px:
        shapes = hairlines(shapes, (y1 - y0) / px)
        x0, y0, x1, y1 = bounds(shapes)
    k = h / (y1 - y0)
    mark = affine(shapes, k, -x0 * k, -y0 * k)
    return svg((x1 - x0) * k, h, render(mark, p))


def lockup(slug, p, mode="M"):
    """Symbol (visible height r cap heights, centred on the caps) and the wordmark, gap g cap heights."""
    w = word()
    r, g = OPTIONS[slug]["lockup"]
    X0, Y0, X1, Y1 = w["bounds"]
    cap = w["cap"]
    shapes = art(slug, False if mode == "L" else mode)
    bx0, by0, bx1, by1 = bounds(shapes)
    shapes = hairlines(shapes, (by1 - by0) / (r * 24))     # 1 px glass edges at the nominal 24 px cap height
    bx0, by0, bx1, by1 = bounds(shapes)
    k = r * cap / (by1 - by0)
    right = X0 - g * cap
    top = -cap / 2 - (by1 - by0) * k / 2
    mark = affine(shapes, k, right - bx1 * k, top - by0 * k)
    mx0, my0, _, my1 = bounds(mark)
    box = (mx0, min(Y0, my0), X1, max(Y1, my1))
    x0, y0 = math.floor(box[0]), math.floor(box[1])
    wd, ht = math.ceil(box[2]) - x0, math.ceil(box[3]) - y0
    sc = 24 / cap
    return svg(wd * sc, ht * sc, render(mark, p) + f'<path fill="{p["ink"]}" d="{w["d"]}"/>', view=f"{x0} {y0} {wd} {ht}")


def favicon(slug):
    """Transparent, the 16 px drawing, colours from the browser's light or dark scheme."""
    shapes = art(slug, "XS")
    x0, y0, x1, y1 = bounds(shapes)
    side = max(x1 - x0, y1 - y0) * 1.04
    k = 48 / side
    mark = affine(shapes, k, (48 - (x1 - x0) * k) / 2 - x0 * k, (48 - (y1 - y0) * k) / 2 - y0 * k)
    body = render(mark, {"ink": "INK", "accent": "ACC"})
    body = body.replace('fill="INK"', 'class="i"').replace('fill="ACC"', 'class="a"')
    body = body.replace('stroke="INK"', 'class="si"').replace('stroke="ACC"', 'class="sa"')

    def rules(q):
        return (f".i{{fill:{q['ink']}}}.a{{fill:{q['accent']}}}.si{{stroke:{q['ink']}}}.sa{{stroke:{q['accent']}}}")
    style = f"<style>{rules(LIGHT)}@media (prefers-color-scheme: dark){{{rules(DARK)}}}</style>"
    return svg(48, 48, body, style=style)


def build(slug):
    out = OPT if slug == SLUG else OPT.parent / slug
    src = out / "src"
    for mode, p in (("dark", DARK), ("light", LIGHT), ("mono", MONO)):
        BI.write(out / f"symbol-{mode}.svg", symbol(art(slug, False), p))
    BI.write(out / "symbol-small.svg", symbol(art(slug, "S"), DARK, 32, px=30))
    for mode, p in (("dark", DARK), ("light", LIGHT)):
        BI.write(out / f"lockup-{mode}.svg", lockup(slug, p))
    BI.write(out / "favicon.svg", favicon(slug))
    jobs = []
    for px, size in SIZES.items():
        f = BI.write(src / f"macos-{px}.svg", mac_tile(art(slug, size), DARK, px, EXT[px]))
        jobs.append({"svg": str(f), "out": str(out / f"icon-{px}.png"), "size": px})
    raster(jobs)
    return out


def board(slug):
    """The presentation board: 1600 x 1000 css px, captured at 2x to renders/checkpoint-1/logo/<slug>.webp."""
    out = OPT if slug == SLUG else OPT.parent / slug
    o = OPTIONS[slug]
    work = SCRATCH / "board"
    work.mkdir(parents=True, exist_ok=True)
    fav = (out / "favicon.svg").read_text()
    style = fav[fav.index("<style>"):fav.index("</style>") + 8]
    for mode, q in (("light", LIGHT), ("dark", DARK)):  # the favicon as each tab bar sees it
        rule = f".i{{fill:{q['ink']}}}.a{{fill:{q['accent']}}}.si{{stroke:{q['ink']}}}.sa{{stroke:{q['accent']}}}"
        (work / f"{slug}-fav-{mode}.svg").write_text(fav.replace(style, f"<style>{rule}</style>"))
    w = word()
    r, g = o["lockup"]
    cap = w["cap"] / w["upm"]
    head_px = 22                                   # the app header's wordmark size
    sym_h = o["header"] * cap * head_px            # the small drawing: shorter than in the big lockup
    gap = g * cap * head_px
    f = f"file://{out}"

    def tabs(mode):
        bar, act, fg, ph = (("#dee1e6", "#ffffff", "#1f1f1f", "#b9bdc3") if mode == "light"
                            else ("#1f2023", "#35363a", "#e8eaed", "#56595e"))
        grey = (f'<div class="tab"><i style="background:{ph}"></i><b style="background:{ph}"></b></div>')
        return (f'<div class="bar" style="background:{bar}">{grey}<div class="tab on" style="background:{act};'
                f'color:{fg}"><img src="file://{work}/{slug}-fav-{mode}.svg" width="16" height="16">'
                f'<span>Layered Human</span></div>{grey}{grey}</div>')
    html = f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="file://{ROOT}/assets/fonts/fonts.css">
<style>
*{{box-sizing:border-box;margin:0}}
body{{width:1600px;height:1000px;overflow:hidden;background:#1d2227;color:#efece6;font:15px "Fira Sans";
  padding:36px 40px;display:grid;grid-template-columns:470px 560px 1fr;grid-template-rows:auto 560px 1fr;gap:20px}}
.bottom{{grid-column:1/4;display:flex;gap:20px}}
header{{grid-column:1/4;display:flex;align-items:baseline;gap:22px}}
h1{{font:400 34px/1 Literata;font-variation-settings:"opsz" 36}}
header p{{color:#b8bcc0;font-size:16px;max-width:900px}}
.wall{{border-radius:6px;display:grid;place-items:center;
  background:radial-gradient(ellipse 60% 55% at 50% 44%,#3d4750 0%,#323a42 45%,#2a3138 70%,#1d2227 100%)}}
.wall img{{height:440px}}
.icon{{border-radius:6px;background:#15181b;display:grid;place-items:center}}
.icon img{{width:512px;height:512px}}
.locks{{display:grid;grid-template-rows:1fr 1fr;gap:20px}}
.locks div{{border-radius:6px;display:grid;place-items:center}}
.locks img{{height:92px}}
.ladder{{width:660px;border-radius:6px;background:#2a3138;display:flex;align-items:end;gap:22px;padding:22px 26px 30px}}
.ladder figure{{display:flex;flex-direction:column;align-items:center;gap:8px;color:#8f969c;font-size:12px}}
.px{{image-rendering:pixelated}}
.right{{flex:1;display:flex;flex-direction:column;gap:14px}}
.app{{height:52px;background:#2a3138;border-radius:6px;display:flex;align-items:center;padding:0 22px;gap:40px}}
.brand{{display:flex;align-items:center;gap:{gap:.1f}px;font:450 {head_px}px Literata;
  font-variation-settings:"opsz" 36;letter-spacing:-.005em;color:#efece6}}
.brand img{{height:{sym_h:.1f}px}}
.nav{{display:flex;gap:26px;color:#c9ccce;font-size:15px}}.nav b{{font-weight:500;color:#efece6}}
.bar{{height:42px;border-radius:6px;display:flex;align-items:end;padding:0 10px;gap:2px}}
.tab{{height:34px;width:190px;border-radius:9px 9px 0 0;display:flex;align-items:center;gap:9px;padding:0 13px;font:13px "Fira Sans"}}
.tab i{{width:16px;height:16px;border-radius:3px;display:block}}.tab b{{width:96px;height:8px;border-radius:4px;display:block}}
.cap{{color:#8f969c;font-size:12px;margin-top:-6px}}
</style>
<header><h1>{o["name"]}</h1><p>{o["line"]}</p></header>
<div class="wall"><img src="{f}/symbol-dark.svg"></div>
<div class="icon"><img src="{f}/icon-1024.png"></div>
<div class="locks"><div style="background:#2a3138"><img src="{f}/lockup-dark.svg"></div>
  <div style="background:#ece8e0"><img src="{f}/lockup-light.svg"></div></div>
<div class="bottom"><div class="ladder">
  <figure><img src="{f}/icon-128.png" width="128">128</figure><figure><img src="{f}/icon-64.png" width="64">64</figure>
  <figure><img src="{f}/icon-32.png" width="32">32</figure><figure><img src="{f}/icon-16.png" width="16">16</figure>
  <figure><img class="px" src="{f}/icon-32.png" width="128">32 &times;4</figure>
  <figure><img class="px" src="{f}/icon-16.png" width="64">16 &times;4</figure></div>
<div class="right">
  <div class="app"><div class="brand"><img src="{f}/symbol-small.svg">Layered Human</div>
    <div class="nav"><b>Atlas</b><span>Lessons</span><span>Models</span><span>Radiology</span><span>Histology</span></div></div>
  <div class="cap">App header, 52 px: the 32 px drawing at {sym_h:.0f} px beside the wordmark at {head_px} px</div>
  {tabs("light")}{tabs("dark")}
  <div class="cap">Favicon in light and dark tab bars</div>
</div></div>"""
    page = work / f"{slug}.html"
    page.write_text(html)
    png = work / f"{slug}.png"
    shoot(page, png, 1600, 1000)
    webp(png, RENDERS / f"{slug}.webp")
    return png


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "all":
        print(explore())
        print(build(SLUG), board(SLUG))
    if cmd == "explore":
        out = explore(sys.argv[2:] or None)
        print(out)
    elif cmd == "build":
        for slug in sys.argv[2:] or OPTIONS:
            print(build(slug), board(slug))
