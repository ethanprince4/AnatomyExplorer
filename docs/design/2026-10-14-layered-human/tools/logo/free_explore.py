"""Exploration sheet for the "free" logo agent: every variation tried, each on the slate tile at 256, 64, 32 and
16 px, labelled. Saved as renders/checkpoint-1/logo/free-explore.webp. Run through free.py (`free.py explore`).
Early rounds use identity/plate/figure.json; later rounds use the symmetric traces made by free.trace()."""
import base64
import json
import math
import re
import subprocess

import numpy as np
from PIL import Image
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import transform, unary_union

import free as F

INK, BRASS, BIG = "#efece6", "#d4b47e", 4000


def P(g, fill, op=1):
    return F.path(g, fill, op, smooth=False, tol=.6)


def SP(g, fill, op=1):
    return F.path(g, fill, op, tol=1.2)


def ell(cx, cy, rx, ry, a0=0, a1=360, steps=64):
    return Polygon([(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
                    for a in np.linspace(a0, a1, steps)])


def segs(g, y):
    return F.segments(g, y)


def reflect(g, p0, p1, f=1):
    ang = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
    g = affinity.rotate(g, -ang, origin=p0)
    g = affinity.scale(g, 1, -f, origin=p0)
    return affinity.rotate(g, ang, origin=p0)


def side(p0, p1):
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    return Polygon([(x0 - ux * BIG, y0 - uy * BIG), (x1 + ux * BIG, y1 + uy * BIG),
                    (x1 + ux * BIG + uy * BIG, y1 + uy * BIG - ux * BIG), (x0 - ux * BIG + uy * BIG, y0 - uy * BIG - ux * BIG)])


def variants():
    fig = json.loads(F.bi.FIGURE.read_text())
    S = Polygon(fig["smooth"]).buffer(0).buffer(4, join_style=1).buffer(-4, join_style=1)
    X0, Y0, X1, Y1 = S.bounds
    V = []

    def add(label, art):
        V.append((label, art))

    # 1 quarter cutaways on the plate figure
    def cutaway(cy=430, a=18, b=40, step=22, gap=7, three=True):
        mus, deep = S.buffer(-a, join_style=1), S.buffer(-b, join_style=1)
        Q, Q2 = box(0, -BIG, BIG, cy), box(step, -BIG, BIG, cy - step)
        out = P(S.difference(Q.buffer(gap, join_style=2)), INK)
        m = mus.intersection(Q)
        if three:
            return out + P(m.difference(Q2.buffer(gap, join_style=2)), BRASS) + P(deep.intersection(Q2), INK, .55)
        return out + P(m, BRASS)
    add("Stepped quarter cut, three layers", cutaway())
    add("Quarter cut, two layers", cutaway(three=False, a=14))

    # 2 midline ecorche
    left = S.intersection(box(-BIG, -BIG, 0, BIG))
    add("Midline split with the skin's cut face", P(left, INK) + P(S.intersection(box(0, -BIG, 10, BIG)), INK, .45)
        + P(S.buffer(-16, join_style=1).intersection(box(15, -BIG, BIG, BIG)), BRASS))

    # 3 peels
    def peel(p0, p1, a=12, lift=1., under=("#c9c5bc", 1), flip=False):
        far = side(p1, p0) if flip else side(p0, p1)
        fl = reflect(S.intersection(far), p0, p1, lift)
        sh = affinity.translate(fl, 9, 12).buffer(4).difference(fl).intersection(S)
        return (P(S.difference(far), INK) + P(S.buffer(-a, join_style=1).intersection(far), BRASS)
                + P(sh, "#000", .35) + P(fl, *under))
    add("Corner peeled like a page", peel((-30, 60), (200, 520)))
    add("Peel lifted off the flank", peel((210, 240), (-60, 560), flip=True, lift=.75, under=(INK, .42)))
    add("Half the torso peeled, opaque flap", peel((-160, 560), (160, 140), lift=.7, under=("#8f9399", 1)))

    # 4 strata
    def strata(cuts, gap, tilt, rings=True, face=BRASS):
        out, ys = [], [Y0 - 5, *cuts, Y1 + 5]
        for i in range(len(ys) - 1):
            y0, y1, off = ys[i], ys[i + 1], i * gap
            band = S.intersection(box(-BIG, y0, BIG, y1))
            extra = [ell((a + b) / 2, y1, (b - a) / 2, (b - a) / 2 * tilt, 0, 180) for a, b in segs(S, y1 - .5)] if y1 < Y1 else []
            out.append(P(affinity.translate(unary_union([band, *extra]), 0, off), INK))
            if y0 > Y0:
                for a, b in segs(S, y0 + .5):
                    cx, rx = (a + b) / 2, (b - a) / 2
                    out.append(P(ell(cx, y0 + off, rx, rx * tilt), face))
                    if rings and rx > 30:
                        out.append(P(ell(cx, y0 + off, rx * .5, rx * .5 * tilt), INK, .6))
        return "".join(out)
    add("Strata lifted apart, section rings", strata((150, 330, 520, 720), 26, .28))
    add("Two cuts, deeper faces", strata((260, 560), 40, .3))
    add("Exploded sections, two cuts", strata((400, 720), 56, .5))
    add("One cut at the waist", strata((410,), 70, .55))

    # 5 nested passes, contour slices, porthole
    out = ""
    for g, c, op in ((S, INK, 1), (S.buffer(-20, join_style=1), BRASS, 1), (S.buffer(-40, join_style=1), INK, .5)):
        out += P(g.difference(g.buffer(-9, join_style=1)), c, op)
    add("Three nested passes of one figure", out)
    out, y, i = "", Y0 + 20, 0
    while y < Y1 - 4:
        for a, b in segs(S, y):
            cx, rx = (a + b) / 2, (b - a) / 2
            ry = max(rx * .3, 3)
            ring = ell(cx, y, rx, ry).difference(ell(cx, y, max(rx - 7, 1), max(ry - 5, .5)))
            out += P(ring.difference(box(-BIG, y, BIG, BIG)), INK, .35) + P(ring.intersection(box(-BIG, y, BIG, BIG)), BRASS if i % 4 == 2 else INK)
        y += 34
        i += 1
    add("Contour slices, like a 3D print", out)
    c = Point(0, 290)
    add("Section window in the chest", P(S.difference(c.buffer(62)), INK)
        + P(c.buffer(50).difference(c.buffer(30)).intersection(S), BRASS) + P(c.buffer(20), INK, .55))

    # 6 flaps and films
    right = S.intersection(box(0, -BIG, BIG, BIG))
    op = affinity.scale(right, -.42, 1, origin=(0, 0))
    add("Skin opened like a page at the midline", P(left, INK) + P(S.buffer(-14, join_style=1).intersection(box(4, -BIG, BIG, BIG)), BRASS)
        + P(affinity.translate(op, -10, 8).difference(op).intersection(S), "#000", .3) + P(op, "#bdb9b0"))
    win = box(-62, 250, 62, 470)
    flap = affinity.skew(affinity.scale(S.intersection(win), -.55, 1, origin=(-62, 0)), 0, -12, origin=(-62, 360))
    add("Lift-the-flap panel", P(S.difference(win), INK) + P(win.intersection(S).buffer(-6, join_style=2), BRASS) + P(flap, INK, .5))
    p0, p1 = (-120, 300), (200, 40)
    far = side(p0, p1)
    fl = reflect(S.intersection(far), p0, p1, .35)
    add("A film peeling from the shoulder", P(S.difference(far), INK) + P(S.buffer(-12, join_style=1).intersection(far), BRASS) + P(fl, INK, .55))

    # 7 fanned pages, progressive strata
    W, H = X1 - X0, Y1 - Y0

    def lift(g, c):
        def f(x, y, z=None):
            x, y = np.asarray(x), np.asarray(y)
            s = 1 - c * ((x - X0) / W + (y - Y0) / H) / 2
            return X0 + (x - X0) * s, Y0 + (y - Y0) * s
        return transform(f, g)
    add("Layers lifting like pages from the head", P(lift(S, 0), INK, .45) + P(lift(S, .05), BRASS) + P(lift(S, .1), INK))
    out, ys, ins = [], [Y0 - 5, 390, 690, Y1 + 5], (0, 12, 26)
    tones = ((INK, 1), (BRASS, 1), (INK, .55))
    for i in range(3):
        L = S.buffer(-ins[i], join_style=1) if ins[i] else S
        g = affinity.translate(L.intersection(box(-BIG, ys[i], BIG, ys[i + 1])), 0, i * 38)
        out.append(P(g, *tones[i]))
        if i:
            for a, b in segs(S, ys[i] + .5):
                rr = (b - a) / 2 - ins[i]
                out.append(P(ell((a + b) / 2, ys[i] + i * 38, rr, rr * .45), *tones[i]))
    add("Each slab one layer deeper", "".join(out))

    # 8 the traced, symmetric body: candidates and the finished mark
    skin, muscle = F.trace()
    add("Traced body, half ecorche", SP(skin.intersection(box(-BIG, -BIG, 0, BIG)), INK)
        + SP(muscle.intersection(box(8, -BIG, BIG, BIG)), BRASS) + SP(skin.intersection(box(0, -BIG, 8, BIG)), INK, .5))
    for cy, label in ((430, "Quarter cut at the navel: a glove"), (340, "Quarter cut at the armpits"),
                      (F.CUT_Y, "Chosen: Quarter, arm and hip section")):
        r = F.quarter(skin, muscle, cy=cy)
        if cy != F.CUT_Y:   # earlier rounds cut the arm too
            r["skin"] = r["skin"].union(skin.intersection(box(60, cy, BIG, BIG)))
            r["brass"] = r["brass"].difference(box(60, cy, BIG, BIG))
        add(label, F.art(r, F.DARK, 1, 0, 0))
    return V


def tile(art):
    nums = [tuple(map(float, m)) for m in re.findall(r"(-?[\d.]+) (-?[\d.]+)", art)]
    xs, ys = [a for a, _ in nums], [b for _, b in nums]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    s = .78 * 824 / max(y1 - y0, (x1 - x0) / .9)
    t = F.bi.superellipse(512, 512, 412)
    body = (F.bi.ground(t, True) + f'<g transform="translate({F.n(512 - (x0 + x1) / 2 * s)} {F.n(512 - (y0 + y1) / 2 * s)}) '
            f'scale({s:.5f})">{art}</g>')
    return F.svg(1024, 1024, body, defs=F.bi.ground_defs(F.SLATE, True))


def sheet():
    V = variants()
    d = F.SCRATCH / "explore"
    d.mkdir(parents=True, exist_ok=True)
    cells = []
    for i, (label, art) in enumerate(V):
        f = d / f"v{i:02d}.svg"
        f.write_text(tile(art))
        src = "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode()
        imgs = "".join(f'<img src="{src}" width="{px}" height="{px}">' for px in (256, 64, 32, 16))
        cells.append(f'<div class="c"><p><b>{i + 1}</b> {label}</p><div class="r">{imgs}</div></div>')
    html = f"""<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="file://{F.ROOT / 'assets/fonts/fonts.css'}">
<style>*{{margin:0;box-sizing:border-box}}body{{background:#15181b;width:1600px;padding:28px;font-family:'Fira Sans';color:#c7c6c1}}
h1{{font-family:Literata;font-weight:450;font-size:28px;color:#efece6;margin:0 0 6px 8px}}
.g{{display:grid;grid-template-columns:repeat(4,1fr);gap:18px 10px}}.c p{{font-size:13px;margin:6px 8px}}.c b{{color:#d4b47e;margin-right:4px}}
.r{{display:flex;align-items:flex-end;gap:6px}}.r img:first-child{{width:220px;height:220px}}
.h{{font-size:14px;margin:0 0 18px 8px}}</style></head><body>
<h1>Free: explorations</h1><p class="h">Each variation on the slate tile at about 220, 64, 32 and 16 px. The last one is the finished mark.</p>
<div class="g">{''.join(cells)}</div></body></html>"""
    page = d / "explore.html"
    page.write_text(html)
    png = d / "explore.png"
    (d / "shot.mjs").write_text(f"""import {{ chromium }} from '/opt/node-tools/node_modules/playwright/index.mjs';
const b = await chromium.launch({{ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--allow-file-access-from-files'] }});
const p = await b.newPage({{ viewport: {{ width: 1600, height: 1000 }}, deviceScaleFactor: 1 }});
await p.goto('file://{page}'); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
await p.screenshot({{ path: '{png}', fullPage: true }});
await b.close();
""")
    subprocess.run(["node", str(d / "shot.mjs")], check=True)
    Image.open(png).convert("RGB").save(F.RENDERS / "free-explore.webp", quality=90, method=6)
    print("explore:", F.RENDERS / "free-explore.webp", len(V), "variations")
