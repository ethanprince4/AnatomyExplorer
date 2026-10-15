"""Build the Layered Human identity: symbols, lockups, app icons and favicons for the three directions
(overlay, specimen, plate). Everything is written to identity/<direction>/; the icon source SVGs go to src/.
Usage:
  build_identity.py outline   trace the body silhouette into identity/plate/figure.json (scipy, scikit-image)
  build_identity.py build     write the SVGs, rasterise them with Chromium (tools/raster_svg.mjs) and pack
                              .icns/.ico (fontTools, uharfbuzz, brotli, Pillow, numpy)"""
import io
import json
import math
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "tools"
OUT = ROOT / "identity"
FONTS = ROOT / "assets/fonts"
PLATES = ROOT / "assets/plates"
FIGURE = OUT / "plate/figure.json"
SCHEMES = json.loads((ROOT / "system/schemes.json").read_text())
DIRECTIONS = ("overlay", "specimen", "plate")

# Brand palettes: the scheme each direction takes its dark and light colours from, and its default appearance.
BRAND = {
    "overlay": {"dark": "graphite", "light": "clear", "default": "dark"},
    "specimen": {"dark": "slate", "light": "plaster", "default": "dark"},
    "plate": {"dark": "night", "light": "bristol", "default": "light"},
}
MONO = {"ink": "currentColor", "accent": "currentColor", "paper": "none"}

# Wordmarks: font file, variation axes, tracking in em.
WORDMARK = "Layered Human"
FONT = {
    "overlay": ("Archivo-latin-normal-100_900.woff2", {"wght": 640, "wdth": 90}, -0.01),
    "specimen": ("Literata-latin-normal-200_900.woff2", {"wght": 450, "opsz": 36}, -0.005),
    "plate": ("AtkinsonHyperlegibleNext-latin-normal-200_800.woff2", {"wght": 700}, -0.01),
}

# Overlay "Films": start, step, size, corner radius in the 48 box; the small sizes are snapped to whole pixels.
FILMS = (3, 6, 30, 7)
FILMS_PX = {16: (1, 2, 10, 2), 24: (2, 3, 14, 3), 32: (2, 4, 20, 4.5), 48: (3, 6, 30, 7)}
FILM_ALPHA = {"dark": .22, "light": .16, "mono": .2}
FILM_ALPHA_SMALL = {"dark": .34, "light": .26, "mono": .3}
FILM_EDGE, FILM_EDGE_PX = .2, 1.25          # acetate edge on icons of 128 px and up: ink alpha, width in px

# Specimen "Section": skin outer/inner, muscle outer/inner, core radius. Small sizes open the gaps.
SECTION = (21, 17.5, 15, 9, 6.5)
SECTION_SMALL = (21, 16.5, 13.5, 9, 6)
SECTION_PX = {16: (7, 5.5, 4.5, 3, 2), 24: (10.5, 8.5, 7, 4.5, 3), 32: (14, 11, 9, 6, 4), 48: (21, 16.5, 13.5, 9, 6)}
MUSCLE_ALPHA = {"dark": .55, "light": .5, "mono": .55}
MUSCLE_ALPHA_SMALL = {"dark": .62, "light": .58, "mono": .6}

# Plate: the figure plate. Heights are fractions of the art box; the anchors are named in figure.json.
FIG_ALPHA = {"dark": .18, "light": .16, "mono": .16}
FIG_LINE, LABEL_ALPHA, LABEL_BARS = .45, .7, True
BICEPS, THIGH = "biceps.vl", "rectus_femoris.vr"
PLATE_SYMBOL_H, PLATE_SMALL_H = .875, .86
PL_GAP, PL_LEN, PL_STROKE, PL_DOT = .32, 1.15, .07, .2   # label lockup leader, in em
DILATE = 14                                               # outline: thickening of the small figure, in source px
# plates.js has no pectoralis.vr; pectoralis.vl stands in. sartorius.vr is the thigh point of the old 48-box mockups.
ANCHORS = ("biceps.vl", "rectus_femoris.vr", "sartorius.vr", "deltoid.vl", "pectoralis.vl", "sartorius.vl",
           "tibialis_anterior.vl")

# Lockups: visible symbol height and gap, both in cap heights.
LOCKUP = {"overlay": (2.1, .8), "specimen": (1.7, .7)}

# Mark extent per icon family: films' visible size, section diameter or figure height, as a fraction of the tile.
MAC = {"overlay": .57, "specimen": .58, "plate": .76}
# macOS 16 and 32 px, in output pixels on the pixel grid (the 1024 canvas centre is a pixel corner).
# 16 px Specimen drops the muscle ring: at 10 px across, five bands blur into one.
FILMS_MAC = {16: (2, 2, 7, 1.5), 32: (6, 3, 14, 3)}
SECTION_MAC = {16: (5.5, 4, 0, 0, 2.25), 32: (10, 8, 6.5, 4.5, 3)}
WIN = {"overlay": .62, "specimen": .63, "plate": .82}
TOUCH = {"overlay": .6, "specimen": .62, "plate": .7}
MASKABLE = {"overlay": .56, "specimen": .62, "plate": .66}
MAC_SIZES = (16, 32, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# .icns entries (type, png size). Pillow's writer has no 16 px slot, so the file is packed here.
ICNS = (("icp4", 16), ("icp5", 32), ("ic11", 32), ("ic12", 64), ("ic07", 128), ("ic13", 256),
        ("ic08", 256), ("ic14", 512), ("ic09", 512), ("ic10", 1024))


def n(v):
    """A number for SVG: at most 2 decimals, no trailing zeros."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def palette(direction, mode):
    s = SCHEMES[direction]["schemes"][BRAND[direction][mode]]
    return {"ink": s["text"], "accent": s["accent"], "top": s["stage_top"], "bottom": s["stage_bottom"],
            "spot": s["spot"], "paper": s["stage_top"]}


def svg(w, h, body, view=None, defs="", style=""):
    view = view or f"0 0 {n(w)} {n(h)}"
    defs = f"<defs>{defs}</defs>" if defs else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{n(w)}" height="{n(h)}">'
            f"{style}{defs}{body}</svg>\n")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ---- outline ---------------------------------------------------------------------------------------------------

def outline():
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    from skimage import measure

    src = PLATES / "peel_00_skin.webp"
    alpha = np.asarray(Image.open(src).convert("RGBA"))[..., 3]
    mask = ndimage.binary_fill_holes(alpha > 127)
    labels, count = ndimage.label(mask)
    mask = labels == 1 + int(np.argmax(ndimage.sum(mask, labels, range(1, count + 1))))
    ys, xs = np.nonzero(mask)
    top, scale = ys.min() - .5, 1000 / (ys.max() - ys.min() + 1)
    cx = (xs.min() + xs.max()) / 2

    def frame(x, y):
        return [round(float((x - cx) * scale), 1), round(float((y - top) * scale), 1)]

    def trace(m, tolerance):
        pad = 40  # room for the blur, so the contour closes where the body meets the crop edge
        smooth = ndimage.gaussian_filter(np.pad(m, pad).astype(float), 9)
        c = max(measure.find_contours(smooth, .5), key=len)
        c = measure.approximate_polygon(c, tolerance=tolerance)
        if len(c) > 1 and (c[0] == c[-1]).all():
            c = c[:-1]
        return [frame(x - pad, y - pad) for y, x in c]

    # Anchors are in hero26's crop pixels; all body plates share one camera, so shift them into the skin crop.
    js = (PLATES / "plates.js").read_text()
    data = json.loads(js[js.index("=") + 1:].strip().rstrip(";"))
    hero, skin = data["plates"]["hero26_sel_7cc8da"]["box"], data["plates"]["peel_00_skin"]["box"]
    found = data["anchors"]["hero26_sel_7cc8da"]
    anchors = {}
    for name in ANCHORS:
        if name not in found:
            print("missing anchor", name)
            continue
        anchors[name] = frame(found[name]["x"] + hero[0] - skin[0], found[name]["y"] + hero[1] - skin[1])

    figure = {"source": str(src.relative_to(ROOT)), "frame": "height 1000, top 0, centre x 0",
              "smooth": trace(mask, 3), "small": trace(ndimage.binary_dilation(mask, iterations=DILATE), 4),
              "anchors": anchors}
    write(FIGURE, json.dumps(figure, separators=(",", ":")) + "\n")
    print(f"figure.json: {len(figure['smooth'])} smooth points, {len(figure['small'])} small points")
    for name, (x, y) in anchors.items():  # the old 48-box normalisation, as a sanity check
        print(f"  {name:22s} 48-box ({24 + x * .042:.2f}, {3 + y * .042:.2f})")


# ---- geometry ----------------------------------------------------------------------------------------------------

def core_path(ox, oy, s, d, w, r):
    """The triple overlap of the films as an explicit path (QtSvg has no clipPath)."""
    lo, hi = s + 2 * d, s + w

    def X(v):
        return n(ox + v)

    def Y(v):
        return n(oy + v)
    return (f"M{X(lo + r)} {Y(lo)}H{X(hi)}V{Y(hi - r)}A{n(r)} {n(r)} 0 0 1 {X(hi - r)} {Y(hi)}"
            f"H{X(lo)}V{Y(lo + r)}A{n(r)} {n(r)} 0 0 1 {X(lo + r)} {Y(lo)}Z")


def film_rects(ox, oy, s, d, w, r, attrs=""):
    return "".join(f'<rect x="{n(ox + s + i * d)}" y="{n(oy + s + i * d)}" width="{n(w)}" height="{n(w)}" '
                   f'rx="{n(r)}"{attrs}/>' for i in range(3))


def films(p, alpha, ox, oy, k, geo=FILMS, edge=0):
    """Three translucent films and the accent core; the 48-box geometry scaled by k and moved to (ox, oy)."""
    s, d, w, r = (v * k for v in geo)
    rects = film_rects(ox, oy, s, d, w, r)
    out = (f'<g fill="{p["ink"]}" fill-opacity="{n(alpha)}">{rects}</g>'
           f'<path fill="{p["accent"]}" d="{core_path(ox, oy, s, d, w, r)}"/>')
    if edge:
        out += (f'<g fill="none" stroke="{p["ink"]}" stroke-opacity="{n(FILM_EDGE)}" stroke-width="{n(edge)}">'
                f"{rects}</g>")
    return out


def sector(cx, cy, ro, ri, a0=0, a1=270):
    """A ring sector from a0 to a1 degrees, clockwise (0 = right, 90 = down)."""
    def pt(r, a):
        return f"{n(cx + r * math.cos(math.radians(a)))} {n(cy + r * math.sin(math.radians(a)))}"
    return f"M{pt(ro, a0)}A{n(ro)} {n(ro)} 0 1 1 {pt(ro, a1)}L{pt(ri, a1)}A{n(ri)} {n(ri)} 0 1 0 {pt(ri, a0)}Z"


def section(p, alpha, cx, cy, k, radii=SECTION):
    """Skin ring, muscle ring (a quarter cut away) and the accent core, centred on (cx, cy)."""
    so, si, mo, mi, cr = (v * k for v in radii)
    muscle = f'<path fill="{p["ink"]}" fill-opacity="{n(alpha)}" d="{sector(cx, cy, mo, mi)}"/>' if mo else ""
    return (f'<path fill="{p["ink"]}" d="{sector(cx, cy, so, si)}"/>{muscle}'
            f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(cr)}" fill="{p["accent"]}"/>')


def figure_path(points, cx, top, h):
    f = h / 1000
    return "M" + "L".join(f"{n(cx + x * f)} {n(top + y * f)}" for x, y in points) + "Z"


def plate_place(fig, box, figh):
    """Fit the figure to a square art box: returns its height, centre x, top and an anchor lookup."""
    x0, y0, size = box
    h = figh * size
    cx, top = x0 + size / 2, y0 + (size - h) / 2

    def at(name):
        x, y = fig["anchors"][name]
        return cx + x * h / 1000, top + y * h / 1000
    return h, cx, top, at


def bar(x, cy, w, h):
    return f'<rect x="{n(x)}" y="{n(cy - h / 2)}" width="{n(w)}" height="{n(h)}" rx="{n(h / 2)}"/>'


def plate_art(fig, p, alpha, box, figh, u, bars=LABEL_BARS, reach=.07):
    """The figure plate: tinted figure, two leaders from label bars, an accent dot (biceps) and a ring (thigh).
    u is the size of one output pixel in canvas units, so hairlines never drop below a pixel."""
    x0, y0, size = box
    h, cx, top, at = plate_place(fig, box, figh)
    (bx, by), (tx, ty) = at(BICEPS), at(THIGH)
    lw, dr, rr, ol = max(.009 * size, u), max(.03 * size, 1.8 * u), max(.026 * size, 1.6 * u), max(.0035 * size, .6 * u)
    ink = p["ink"]
    out = [f'<path fill="{ink}" fill-opacity="{n(alpha)}" stroke="{ink}" stroke-opacity="{n(FIG_LINE)}" '
           f'stroke-width="{n(ol)}" stroke-linejoin="round" d="{figure_path(fig["smooth"], cx, top, h)}"/>']
    left, right = x0 + reach * size, x0 + (1 - reach) * size
    if bars:  # greeked labels
        bh, bl, gap = max(.034 * size, 1.6 * u), .11 * size, .025 * size
        out.append(f'<g fill="{ink}" fill-opacity="{n(LABEL_ALPHA)}">{bar(left, by, bl, bh)}{bar(right - bl, ty, bl, bh)}</g>')
        left, right = left + bl + gap, right - bl - gap
    out.append(f'<path fill="none" stroke="{ink}" stroke-width="{n(lw)}" '
               f'd="M{n(left)} {n(by)}H{n(bx)}M{n(tx + rr)} {n(ty)}H{n(right)}"/>')
    out.append(f'<circle cx="{n(bx)}" cy="{n(by)}" r="{n(dr)}" fill="{p["accent"]}"/>')
    out.append(f'<circle cx="{n(tx)}" cy="{n(ty)}" r="{n(rr)}" fill="{p["paper"]}" stroke="{ink}" stroke-width="{n(lw)}"/>')
    return "".join(out)


def plate_dot(fig, box, figh, u):
    h, _, _, at = plate_place(fig, box, figh)
    bx, by = at(BICEPS)
    return bx, by, max(.06 * h, 1.25 * u), max(.025 * h, .6 * u)


def plate_small(fig, p, box, figh, u):
    """Small sizes: the thickened figure in solid ink and the biceps dot, set off by a ring of paper."""
    h, cx, top, _ = plate_place(fig, box, figh)
    bx, by, dr, halo = plate_dot(fig, box, figh, u)
    return (f'<path fill="{p["ink"]}" d="{figure_path(fig["small"], cx, top, h)}"/>'
            f'<circle cx="{n(bx)}" cy="{n(by)}" r="{n(dr + halo)}" fill="{p["paper"]}"/>'
            f'<circle cx="{n(bx)}" cy="{n(by)}" r="{n(dr)}" fill="{p["accent"]}"/>')


# ---- symbols, lockups, favicon.svg -----------------------------------------------------------------------------

def symbol(d, p, mode, fig):
    if d == "overlay":
        body = films(p, FILM_ALPHA[mode], 0, 0, 1)
    elif d == "specimen":
        body = section(p, MUSCLE_ALPHA[mode], 24, 24, 1)
    else:
        body = plate_art(fig, p, FIG_ALPHA[mode], (0, 0, 48), PLATE_SYMBOL_H, 1, bars=False, reach=.02)
    return svg(48, 48, body)


def wordmark(direction):
    """Outline the wordmark: instance the variable font, shape with HarfBuzz, draw the glyphs as one path.
    Font units, baseline at y 0, y down."""
    import uharfbuzz as hb
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    file, axes, tracking = FONT[direction]
    font = TTFont(FONTS / file)
    limits = {a.axisTag: min(max(axes.get(a.axisTag, a.defaultValue), a.minValue), a.maxValue)
              for a in font["fvar"].axes}
    static = instancer.instantiateVariableFont(font, limits)
    static.flavor = None
    buf = io.BytesIO()
    static.save(buf)
    data = buf.getvalue()
    static = TTFont(io.BytesIO(data))
    upm = static["head"].unitsPerEm

    text = hb.Buffer()
    text.add_str(WORDMARK)
    text.guess_segment_properties()
    hb.shape(hb.Font(hb.Face(data)), text, {"kern": True, "liga": True})
    glyphs, order = static.getGlyphSet(), static.getGlyphOrder()
    path, bounds = SVGPathPen(glyphs, ntos=n), BoundsPen(glyphs)
    x = 0
    for info, pos in zip(text.glyph_infos, text.glyph_positions):
        t = (1, 0, 0, -1, x + pos.x_offset, -pos.y_offset)
        glyph = glyphs[order[info.codepoint]]
        glyph.draw(TransformPen(path, t))
        glyph.draw(TransformPen(bounds, t))
        x += pos.x_advance + tracking * upm
    os2 = static["OS/2"]
    return {"d": path.getCommands(), "bounds": bounds.bounds, "upm": upm, "cap": os2.sCapHeight,
            "xh": os2.sxHeight, "advance": x, "axes": limits}


def lockup(d, p, mode, word):
    """Horizontal lockup in font units. Overlay and Specimen: symbol centred on the cap height, then the wordmark.
    Plate: the wordmark, then a leader at mid x-height ending in an accent dot."""
    X0, Y0, X1, Y1 = word["bounds"]
    cap, em = word["cap"], word["upm"]
    if d == "plate":
        y, r = -word["xh"] / 2, PL_DOT * em
        a = X1 + PL_GAP * em
        b = a + PL_LEN * em
        mark = (f'<path fill="none" stroke="{p["ink"]}" stroke-width="{n(PL_STROKE * em)}" d="M{n(a)} {n(y)}H{n(b)}"/>'
                f'<circle cx="{n(b)}" cy="{n(y)}" r="{n(r)}" fill="{p["accent"]}"/>')
        box = (X0, min(Y0, y - r), b + r, max(Y1, y + r))
    else:
        ratio, gap = LOCKUP[d]
        k = ratio * cap / 42          # the visible mark is 42 of the 48 box
        ox, oy = X0 - gap * cap - 45 * k, -cap / 2 - 24 * k
        if d == "overlay":
            mark = films(p, FILM_ALPHA[mode], ox, oy, k)
        else:
            mark = section(p, MUSCLE_ALPHA[mode], ox + 24 * k, oy + 24 * k, k)
        box = (ox + 3 * k, min(Y0, oy + 3 * k), X1, max(Y1, oy + 45 * k))
    x0, y0 = math.floor(box[0]), math.floor(box[1])
    w, h = math.ceil(box[2]) - x0, math.ceil(box[3]) - y0
    s = 24 / cap  # nominal size: a 24 px cap height
    return svg(w * s, h * s, mark + f'<path fill="{p["ink"]}" d="{word["d"]}"/>', view=f"{x0} {y0} {w} {h}")


def favicon_svg(d, fig):
    """Transparent favicon, small geometry; colours follow the browser's light or dark scheme."""
    def rules(mode):
        p = palette(d, mode)
        tint = {"overlay": f".f{{fill:{p['ink']};fill-opacity:{n(FILM_ALPHA_SMALL[mode])}}}",
                "specimen": f".i{{fill:{p['ink']}}}.m{{fill:{p['ink']};fill-opacity:{n(MUSCLE_ALPHA_SMALL[mode])}}}",
                "plate": f".i{{fill:{p['ink']}}}.h{{fill:{p['paper']}}}"}[d]
        return tint + f".a{{fill:{p['accent']}}}"
    style = f"<style>{rules('light')}@media (prefers-color-scheme: dark){{{rules('dark')}}}</style>"
    if d == "overlay":
        body = f'<g class="f">{film_rects(0, 0, *FILMS)}</g><path class="a" d="{core_path(0, 0, *FILMS)}"/>'
    elif d == "specimen":
        so, si, mo, mi, cr = SECTION_SMALL
        body = (f'<path class="i" d="{sector(24, 24, so, si)}"/><path class="m" d="{sector(24, 24, mo, mi)}"/>'
                f'<circle class="a" cx="24" cy="24" r="{n(cr)}"/>')
    else:
        box, figh = (0, 0, 48), .9
        h, cx, top, _ = plate_place(fig, box, figh)
        bx, by, dr, halo = plate_dot(fig, box, figh, 2.4)  # drawn for a 16-32 px tab
        body = (f'<path class="i" d="{figure_path(fig["small"], cx, top, h)}"/>'
                f'<circle class="h" cx="{n(bx)}" cy="{n(by)}" r="{n(dr + halo)}"/>'
                f'<circle class="a" cx="{n(bx)}" cy="{n(by)}" r="{n(dr)}"/>')
    return svg(48, 48, body, style=style)


# ---- icons -------------------------------------------------------------------------------------------------------

def superellipse(cx, cy, a, steps=360):
    """|x/a|^5 + |y/a|^5 = 1: continuous corners like Apple's icon tile."""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        pts.append(f"{n(cx + a * math.copysign(abs(c) ** .4, c))} {n(cy + a * math.copysign(abs(s) ** .4, s))}")
    return "M" + "L".join(pts) + "Z"


def ground_defs(p, spot):
    out = (f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{p["top"]}"/>'
           f'<stop offset="1" stop-color="{p["bottom"]}"/></linearGradient>')
    if spot:  # the lit museum case behind the specimen
        out += (f'<radialGradient id="spot" cx=".5" cy=".46" r=".52"><stop offset="0" stop-color="{p["spot"]}"/>'
                f'<stop offset=".55" stop-color="{p["spot"]}" stop-opacity=".5"/>'
                f'<stop offset="1" stop-color="{p["spot"]}" stop-opacity="0"/></radialGradient>')
    return out


def ground(shape, spot):
    return f'<path d="{shape}" fill="url(#bg)"/>' + (f'<path d="{shape}" fill="url(#spot)"/>' if spot else "")


def edge(cx, cy, a, w):
    """Hairline inner edge that separates a dark tile from a dark Dock or taskbar."""
    return f'<path d="{superellipse(cx, cy, a - w / 2)}" fill="none" stroke="#fff" stroke-opacity=".06" stroke-width="{n(w)}"/>'


def tile_mark(d, p, mode, fig, box, ext, u, edges=False, reach=.07):
    """The mark centred in a square box (x0, y0, size); ext is its extent as a fraction of the box."""
    x0, y0, size = box
    if d == "plate":
        return plate_art(fig, p, FIG_ALPHA[mode], box, ext, u, reach=reach)
    k = ext * size / 42
    cx, cy = x0 + size / 2, y0 + size / 2
    if d == "overlay":
        return films(p, FILM_ALPHA[mode], cx - 24 * k, cy - 24 * k, k, edge=FILM_EDGE_PX * u if edges else 0)
    return section(p, MUSCLE_ALPHA[mode], cx, cy, k)


def mac_icon(d, mode, px, fig):
    """macOS: 1024 canvas, 824 tile at 100 with a soft drop shadow. px is the output size (sets hairlines)."""
    p, small, u, spot = palette(d, mode), px <= 32, 1024 / px, d == "specimen"
    tile = superellipse(512, 512, 412)
    defs = ground_defs(p, spot) + '<filter id="sh" x="-.2" y="-.2" width="1.4" height="1.4"><feGaussianBlur stdDeviation="14"/></filter>'
    if not small:
        mark = tile_mark(d, p, mode, fig, (100, 100, 824), MAC[d], u, edges=px >= 128)
    elif d == "overlay":
        mark = films(p, FILM_ALPHA_SMALL[mode], 0, 0, u, FILMS_MAC[px])
    elif d == "specimen":
        mark = section(p, MUSCLE_ALPHA_SMALL[mode], 512, 512, u, SECTION_MAC[px])
    else:
        mark = plate_small(fig, p, (100, 100, 824), PLATE_SMALL_H, u)
    body = (f'<path d="{tile}" fill="#000" fill-opacity=".3" transform="translate(0 11)" filter="url(#sh)"/>'
            + ground(tile, spot) + mark)
    if mode == "dark":
        body += edge(512, 512, 412, max(2, u))
    return svg(1024, 1024, body, defs=defs)


def win_icon(d, mode, px, fig):
    """Windows 48-256: near full-bleed tile on a 256 canvas, no shadow."""
    p, u, spot = palette(d, mode), 256 / px, d == "specimen"
    tile = superellipse(128, 128, 120)
    body = ground(tile, spot) + tile_mark(d, p, mode, fig, (8, 8, 240), WIN[d], u, edges=px >= 128, reach=.06)
    if mode == "dark":
        body += edge(128, 128, 120, max(1.5, u))
    return svg(256, 256, body, defs=ground_defs(p, spot))


def win_small(d, mode, px, fig):
    """16-48 px: full-bleed tile, the mark drawn on the pixel grid, heavier tints, no hairlines."""
    p, spot = palette(d, mode), d == "specimen"
    if d == "overlay":
        mark = films(p, FILM_ALPHA_SMALL[mode], 0, 0, 1, FILMS_PX[px])
    elif d == "specimen":
        mark = section(p, MUSCLE_ALPHA_SMALL[mode], px / 2, px / 2, 1, SECTION_PX[px])
    else:
        mark = plate_small(fig, p, (0, 0, px), PLATE_SMALL_H, 1)
    return svg(px, px, ground(superellipse(px / 2, px / 2, px / 2), spot) + mark, defs=ground_defs(p, spot))


def square_icon(d, mode, px, ext, reach, fig):
    """Opaque full-bleed square: apple-touch-icon and the maskable PWA icons."""
    p, spot = palette(d, mode), d == "specimen"
    body = ground(f"M0 0H{px}V{px}H0Z", spot) + tile_mark(d, p, mode, fig, (0, 0, px), ext[d], 1, edges=px >= 128, reach=reach)
    return svg(px, px, body, defs=ground_defs(p, spot))


# ---- packing -----------------------------------------------------------------------------------------------------

def same(a, b):
    import numpy as np
    return a.size == b.size and np.array_equal(np.asarray(a.convert("RGBA")), np.asarray(b.convert("RGBA")))


def write_icns(path, pngs):
    """pngs: {size: png path}. Packs the PNGs as they are, with a table of contents like iconutil."""
    entries = [(t.encode(), pngs[px].read_bytes()) for t, px in ICNS]
    toc = b"TOC " + struct.pack(">I", 8 + 8 * len(entries)) + b"".join(t + struct.pack(">I", 8 + len(b)) for t, b in entries)
    data = b"".join(t + struct.pack(">I", 8 + len(b)) + b for t, b in entries)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(toc) + len(data)) + toc + data)
    # Read it back: every entry must be the PNG rendered for its size, and Pillow must list every size.
    from PIL import IcnsImagePlugin, Image
    raw, i, found = path.read_bytes(), 8, {}
    while i < len(raw):
        t, size = raw[i:i + 4].decode(), struct.unpack(">I", raw[i + 4:i + 8])[0]
        if t != "TOC ":
            found[t] = Image.open(io.BytesIO(raw[i + 8:i + size]))
        i += size
    for t, px in ICNS:
        assert t in found and same(found[t], Image.open(pngs[px])), f"{path}: {t} ({px} px) does not match"
    with open(path, "rb") as f:
        sizes = sorted(IcnsImagePlugin.IcnsFile(f).itersizes())
    want = {(16, 16, 1), (16, 16, 2), (32, 32, 1), (32, 32, 2), (128, 128, 1), (128, 128, 2),
            (256, 256, 1), (256, 256, 2), (512, 512, 1), (512, 512, 2)}
    assert want <= set(sizes), f"{path}: Pillow sees only {sizes}"
    return sizes


def write_ico(path, pngs):
    """pngs: {size: png path}. Pillow resizes the largest image for any size it is not handed, so read the file
    back and check every frame is the image rendered for that size."""
    from PIL import Image
    images = {px: Image.open(f).convert("RGBA") for px, f in pngs.items()}
    sizes = sorted(images)
    images[sizes[-1]].save(path, format="ICO", sizes=[(s, s) for s in sizes],
                           append_images=[images[s] for s in sizes[:-1]])
    raw, got = path.read_bytes(), {}
    for i in range(struct.unpack_from("<H", raw, 4)[0]):
        w, _, _, _, _, _, size, offset = struct.unpack_from("<BBBBHHII", raw, 6 + 16 * i)
        got[w or 256] = Image.open(io.BytesIO(raw[offset:offset + size]))
    for s in sizes:
        assert s in got and same(got[s], images[s]), f"{path}: the {s} px frame is not the {s} px render"
    return sorted(got)


# ---- build -------------------------------------------------------------------------------------------------------

def recipes(words):
    """Live-text lockup recipes for the README, measured from the outlined wordmarks."""
    out = []
    for d, size in (("overlay", 15.5), ("specimen", 23)):
        w = words[d]
        em, cap = w["upm"], w["cap"]
        ratio, gap = LOCKUP[d]
        k = ratio * cap / 42
        box = 48 * k / em
        margin = (gap * cap - 3 * k - w["bounds"][0]) / em   # symbol box edge to the text's origin
        lift = (cap / 2 - 24 * k) / em                      # vertical-align that centres the symbol on the caps
        out.append(f"- {d.title()}: symbol `width:{box:.3f}em; height:{box:.3f}em; margin-right:{margin:.3f}em; "
                   f"vertical-align:{lift:.3f}em`. At {size}px: symbol {box * size:.1f}px, margin {margin * size:.1f}px.\n")
    w = words["plate"]
    em = w["upm"]
    margin = (w["bounds"][2] + PL_GAP * em - w["advance"]) / em
    lift = (w["xh"] / 2 - PL_DOT * em) / em
    out.append(f"- Plate: leader `<svg viewBox=\"0 0 {round((PL_LEN + PL_DOT) * 1000)} {round(2 * PL_DOT * 1000)}\">` "
               f"`width:{PL_LEN + PL_DOT:.2f}em; height:{2 * PL_DOT:.2f}em; margin-left:{margin:.3f}em; vertical-align:{lift:.3f}em`.\n")
    for d in DIRECTIONS:
        w = words[d]
        out.append(f"- {d.title()} metrics: cap {w['cap']}, x-height {w['xh']}, units per em {w['upm']}, "
                   f"ink left {w['bounds'][0]:.0f}, axes {w['axes']}.\n")
    return "".join(out)


def build():
    if not FIGURE.exists():
        sys.exit("identity/plate/figure.json is missing: run `build_identity.py outline` first")
    fig = json.loads(FIGURE.read_text())
    words = {d: wordmark(d) for d in DIRECTIONS}
    jobs, rasters = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for d in DIRECTIONS:
            dest, src = OUT / d, OUT / d / "src"
            default = BRAND[d]["default"]
            alt = "light" if default == "dark" else "dark"
            for mode in ("dark", "light", "mono"):
                p = MONO if mode == "mono" else palette(d, mode)
                write(dest / f"symbol-{mode}.svg", symbol(d, p, mode, fig))
                write(dest / f"lockup-{mode}.svg", lockup(d, p, mode, words[d]))
            write(dest / "favicon.svg", favicon_svg(d, fig))

            def job(name, text, size, out=None):
                path = write(src / name, text)
                out = out or tmp / f"{d}-{path.stem}.png"
                jobs.append({"svg": str(path), "out": str(out), "size": size})
                return out
            mac = {px: job(f"macos-{px}.svg", mac_icon(d, default, px, fig), px,
                           dest / "icon-1024.png" if px == 1024 else None) for px in MAC_SIZES}
            job("macos-1024-alt.svg", mac_icon(d, alt, 1024, fig), 1024, dest / "icon-1024-alt.png")
            small = {px: job(f"windows-{px}.svg", win_small(d, default, px, fig), px,
                             dest / "favicon-32.png" if px == 32 else None) for px in (16, 24, 32)}
            small48 = job("windows-48-small.svg", win_small(d, default, 48, fig), 48)
            ico = {px: job(f"windows-{px}.svg", win_icon(d, default, px, fig), px) for px in (48, 64, 128, 256)}
            job("apple-touch-icon.svg", square_icon(d, default, 180, TOUCH, .15, fig), 180, dest / "apple-touch-icon.png")
            for px in (192, 512):
                job(f"icon-maskable-{px}.svg", square_icon(d, default, px, MASKABLE, .16, fig), px, dest / f"icon-{px}.png")
            rasters[d] = {"mac": mac, "ico": {**small, **ico}, "fav": {16: small[16], 32: small[32], 48: small48}}

        (tmp / "jobs.json").write_text(json.dumps(jobs))
        subprocess.run(["node", str(HERE / "raster_svg.mjs"), str(tmp / "jobs.json")], check=True)

        for d in DIRECTIONS:
            dest, r = OUT / d, rasters[d]
            sizes = write_icns(dest / "icon.icns", r["mac"])
            print(f"{d}: icon.icns {sorted({s[0] * s[2] for s in sizes})} px,",
                  f"icon.ico {write_ico(dest / 'icon.ico', r['ico'])},",
                  f"favicon.ico {write_ico(dest / 'favicon.ico', r['fav'])}")

    readme = OUT / "README.md"
    if readme.exists():
        text = re.sub(r"(<!-- recipes:start -->\n).*?(<!-- recipes:end -->)",
                      lambda m: m[1] + recipes(words) + m[2], readme.read_text(), flags=re.S)
        readme.write_text(text)
    print(recipes(words))


if __name__ == "__main__":
    commands = {"outline": outline, "build": build}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]]()
