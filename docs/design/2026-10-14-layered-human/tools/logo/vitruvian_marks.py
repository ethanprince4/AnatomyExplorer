"""The Vitruvian marks: layered compositions of the figure (see vitruvian_geom.py), as lists of filled shapes.

A mark is a list of (geometry, role, alpha) in frame units, drawn in order. Roles are "ink" and "brass"; the
palette turns them into colours. Everything is a filled path (frames and rings too), and every overlap is
resolved here with explicit boolean geometry, so the SVGs need no clipPath or mask (QtSvg)."""
import math

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

import vitruvian_geom as G

C = (0, G.NAVEL)                         # circle centre
_cache = {}


def layer(name, pose):
    key = (name, pose)
    if key not in _cache:
        _cache[key] = {"skin": G.skin, "muscle": G.muscle, "bone": G.skeleton}[name](pose)
    return _cache[key]


def ring(r, w, c=C):
    return Point(*c).buffer(r + w / 2, 256).difference(Point(*c).buffer(r - w / 2, 256))


def square_frame(w, x0=-500, y0=0, s=1000):
    return G.box(x0 - w / 2, y0 - w / 2, x0 + s + w / 2, y0 + s + w / 2).difference(
        G.box(x0 + w / 2, y0 + w / 2, x0 + s - w / 2, y0 + s - w / 2))


def shift(g, d, k=1.0):
    return affinity.translate(g, d[0] * k, d[1] * k)


def knock(items, gap):
    """Painter's order with occlusion: each item loses whatever the items drawn after it cover (plus a gap).
    items: [(geom, role, alpha, opaque)]; transparent ones (opaque False) occlude nothing."""
    out = []
    for i, (g, role, a, _) in enumerate(items):
        front = [it[0] for it in items[i + 1:] if it[3]]
        if front:
            g = g.difference(unary_union(front).buffer(gap, 16))
        if not g.is_empty:
            out.append((g, role, a))
    return out


def double(name, primary="circle"):
    """Both poses of one layer: (primary pose, the other pose's limbs outside it)."""
    other = "square" if primary == "circle" else "circle"
    a, b = layer(name, primary), layer(name, other)
    return a, b.difference(a)


# ---- the variations -------------------------------------------------------------------------------------------------

DEPTH = (64, -64)        # one layer of depth in the oblique view: up and to the right


def v_plates(gap=14, step=1.0):
    """Three exploded sheets, skin in front framed by the circle and square, muscle and bone behind."""
    d = (DEPTH[0] * 1.6 * step, DEPTH[1] * 1.6 * step)
    items = []
    bone = unary_union(double("bone"))
    musc = unary_union(double("muscle"))
    skin_a, skin_b = double("skin")
    items.append((shift(bone, d, 2), "ink", .45, True))
    items.append((shift(musc, d, 1), "brass", 1, True))
    items.append((skin_b, "ink", .5, True))
    items.append((skin_a, "ink", 1, True))
    out = knock(items, gap)
    out.append((square_frame(9).difference(unary_union([skin_a, skin_b]).buffer(gap)), "ink", .55))
    out.append((ring(G.R, 9).difference(unary_union([skin_a, skin_b]).buffer(gap)), "brass", 1))
    return out


QUAD = G.box(0, -400, 800, G.NAVEL)        # the upper right quadrant, from the navel


def v_section(gap=12, poses="double"):
    """The Section tool on the figure: a quadrant of skin cut away from the navel, and inside it a smaller
    quadrant of muscle, each step set back in depth so the cut has thickness."""
    d = (DEPTH[0] * .55, DEPTH[1] * .55)
    if poses == "double":
        sa, sb = double("skin")
        ma, mb = double("muscle")
        ba, bb = double("bone")
        skin, musc, bone = unary_union([sa, sb]), unary_union([ma, mb]), unary_union([ba, bb])
    else:
        skin, musc, bone = layer("skin", poses), layer("muscle", poses), layer("bone", poses)
        sb = None
    q1 = QUAD
    q2 = shift(G.box(0, -400, 800, G.NAVEL), (60, -60))
    front = skin.difference(q1)
    items = [
        (shift(bone.intersection(q2), d, 2), "ink", .5, True),
        (shift(musc.intersection(q1).difference(q2), d, 1), "brass", 1, True),
        # the cut face of the skin: the band between the cut skin and its copy one step back
        (shift(skin.intersection(q1), d, 1).difference(shift(musc, d, 1)).difference(q1.buffer(-1)), "ink", .3, True),
        (front, "ink", 1, True),
    ]
    out = knock(items, gap)
    out.append((ring(G.R, 9).difference(skin.buffer(gap)), "brass", 1))
    out.append((square_frame(9).difference(skin.buffer(gap)), "ink", .5))
    return out


def v_planes(gap=14):
    """The square and the circle as two planes at different depths, the figure standing between them."""
    d = (DEPTH[0] * 1.2, DEPTH[1] * 1.2)
    sa, sb = double("skin")
    fig = unary_union([sa, sb])
    plane = shift(G.box(-500, 0, 500, 1000), d)
    hoop = ring(G.R, 22)
    # the hoop passes in front of the figure at the hands and behind it at the feet
    front_arc = hoop.intersection(G.box(-900, -300, 900, 250))
    back_arc = hoop.difference(front_arc)
    items = [(plane, "ink", .13, True), (back_arc, "brass", 1, True), (sb, "ink", .5, True), (sa, "ink", 1, True),
             (front_arc, "brass", 1, True)]
    return knock(items, gap)


def outline(g, w):
    return g.difference(g.buffer(-w, 32))


def v_contours(gap=10):
    """Nested contours offset in depth: skin, muscle and bone drawn as lines, Leonardo's pen."""
    d = (DEPTH[0] * .9, DEPTH[1] * .9)
    pose = "circle"
    sk, mu, bo = layer("skin", pose), layer("muscle", pose), layer("bone", pose)
    items = [(shift(bo, d, 2), "ink", .5, True),
             (shift(outline(mu, 12), d, 1), "brass", 1, True),
             (outline(sk, 13), "ink", 1, True)]
    out = knock(items, gap)
    out.append((ring(G.R, 8).difference(sk.buffer(gap)), "ink", .6))
    out.append((square_frame(8).difference(sk.buffer(gap)), "ink", .35))
    return out


def v_ecorche(gap=12):
    """Half skin, half muscle: the right half of the body set back one layer, the cut face at the midline."""
    d = (DEPTH[0] * .7, DEPTH[1] * .7)
    pose = "circle"
    sk, mu = layer("skin", pose), layer("muscle", pose)
    right = G.box(0, -400, 800, 1200)
    face = shift(sk.intersection(G.box(-40, -400, 0, 1200)), d).union(sk.intersection(G.box(-40, -400, 0, 1200)))
    items = [(shift(mu.intersection(right), d), "brass", 1, True),
             (sk.difference(right), "ink", 1, True)]
    out = knock(items, gap)
    out.append((ring(G.R, 10).difference(sk.buffer(gap)).difference(shift(mu, d).buffer(gap)), "ink", .55))
    return out


def v_poses(gap=14):
    """The two poses are the two layers: the square pose in skin in front, the circle pose in muscle behind."""
    d = (DEPTH[0] * .9, DEPTH[1] * .9)
    front = layer("skin", "square")
    back = shift(layer("muscle", "circle"), d)
    items = [(shift(ring(G.R, 9), d), "brass", .8, True), (back, "brass", 1, True),
             (square_frame(9), "ink", .45, True), (front, "ink", 1, True)]
    return knock(items, gap)


def perspective(g, theta, z, f=2600, cx=0, cy=500):
    """Rotate a sheet about the vertical axis through (cx, *), push it back by z and project."""
    ct, st = math.cos(theta), math.sin(theta)

    def tr(x, y):
        X, Z = (x - cx) * ct, z + (x - cx) * st
        k = f / (f + Z)
        return X * k, (y - cy) * k + cy
    from shapely.ops import transform
    return transform(lambda x, y, zz=None: tuple(np.array(tr(np.asarray(x), np.asarray(y)))), g)


def v_cards(gap=12):
    """Three sheets in perspective, like the peel slider: skin in front, muscle, then bone."""
    th = math.radians(-38)
    pose = "circle"
    sheets = [("bone", "ink", .5), ("muscle", "brass", 1), ("skin", "ink", 1)]
    items = []
    for i, (name, role, a) in enumerate(sheets):
        z = (2 - i) * 520
        dx = (2 - i) * 330
        fig = perspective(layer(name, pose), th, z)
        frame = perspective(square_frame(10), th, z)
        items.append((affinity.translate(frame, dx), "ink", .35, False))
        items.append((affinity.translate(fig, dx), role, a, True))
    return knock(items, gap)


VARIANTS = {
    "plates": ("Three sheets, exploded", v_plates),
    "section": ("Section quadrant, stepped", v_section),
    "planes": ("Square and circle as planes", v_planes),
    "contours": ("Nested contours in depth", v_contours),
    "ecorche": ("Half skin, half muscle", v_ecorche),
    "poses": ("Two poses, two layers", v_poses),
    "cards": ("Sheets in perspective", v_cards),
}


# ---- output -----------------------------------------------------------------------------------------------------------

def bounds(items):
    return unary_union([g for g, _, _ in items]).bounds


def fit(items, size=48, ext=42, b=None):
    """A transform from frame units into a size box, the mark's larger side ext, centred."""
    x0, y0, x1, y1 = b or bounds(items)
    k = ext / max(x1 - x0, y1 - y0)
    ox, oy = size / 2 - k * (x0 + x1) / 2, size / 2 - k * (y0 + y1) / 2
    return (lambda p: (ox + k * p[0], oy + k * p[1])), k


def body(items, pal, f, k, tol=.035):
    """SVG elements for a mark: one path per shape, colours from the palette, alpha as fill-opacity."""
    out = []
    for g, role, a in items:
        d = G.path_d(g, f, tol=tol)
        if not d:
            continue
        op = f' fill-opacity="{a:g}"' if a < 1 else ""
        out.append(f'<path fill="{pal[role]}"{op} d="{d}"/>')
    return "".join(out)


# ---- round two -----------------------------------------------------------------------------------------------------

def hulls(g):
    parts = g.geoms if hasattr(g, "geoms") else [g]
    return [p for p in parts if not p.is_empty and p.area > 1e-6]


def sweep(g, d, k=1.0):
    """The solid swept by moving g by k*d (the side walls of an extruded sheet in the oblique view)."""
    moved = shift(g, d, k)
    return unary_union([a.union(b).convex_hull for a, b in zip(hulls(g), hulls(moved))] + [g, moved])


def wall(region, line_box, d, k):
    """The visible wall of a cut: the part of region on the cut line, swept back by k*d."""
    seg = region.intersection(line_box)
    return unary_union([sweep(p, d, k) for p in hulls(seg)]) if not seg.is_empty else seg


def cut_lines(x0, y0, w=1.0):
    """Thin boxes along the two cut planes of a quadrant whose corner is at (x0, y0) (upper right open)."""
    return G.box(x0 - w, -600, x0, y0), G.box(x0, y0, 900, y0 + w)


def muscle_lines(pose, w=7):
    """A few divisions that make the muscle sheet read as muscle: linea alba, pectoral and inguinal lines,
    the deltoid and the knee."""
    sx, sy = G.SHOULDER[pose]
    tip = G.arm_tip(pose)
    ak = G.ankle(pose)
    knee = G.lerp(G.HIP, ak, .5)
    lines = [[(0, 205), (0, 470)],                                     # linea alba
             [(6, 268), (40, 278), (78, 262), (100, 236)],             # lower edge of pectoralis
             [(18, 520), (52, 470), (88, 430)],                        # inguinal fold
             [(0, 330), (55, 325)], [(0, 395), (52, 392)]]             # tendinous intersections
    elbow = G.lerp((sx, sy), tip, .2)
    lines.append([G.lerp((sx, sy), tip, .05), elbow])                  # deltoid / biceps split, along the arm
    kx, ky = knee
    lines.append([(kx - 26, ky - 24), (kx, ky - 6), (kx + 26, ky - 24)])  # above the patella
    from shapely.geometry import LineString
    g = unary_union([LineString(l).buffer(w / 2, 8) for l in lines])
    return unary_union([g, mirror(g)])


def mirror(g):
    return affinity.scale(g, -1, 1, origin=(0, 0))


def v_section2(step=(26, -26), q2=(70, -70), gap=8, square=True, bone=True, ring_w=11, quad_ring=True,
               pose="circle", erode=None):
    """A quadrant of skin removed from the navel up and right; in it the muscle, one step deeper; a smaller
    quadrant of muscle removed in turn, showing the skeleton two steps deep. The cut walls give the depth."""
    sk = layer("skin", pose)
    mu = layer("muscle", pose) if erode is None else G.largest(sk.buffer(-erode, 32)) if False else sk.buffer(-erode, 32)
    bo = layer("bone", pose)
    x0, y0 = 0, G.NAVEL
    Q = G.box(x0, -600, 900, y0)
    Q2 = G.box(x0 + q2[0], -600, 900, y0 + q2[1])
    items = []
    if bone:
        items.append((shift(bo.intersection(Q2), step, 2), "ink", .5, True))
        mwall = unary_union([wall(shift(mu, step, 1), b, step, 1) for b in cut_lines(x0 + q2[0] + step[0], y0 + q2[1] + step[1])])
        items.append((mwall, "brass", .55, True))
        musc_vis = shift(mu.intersection(Q).difference(Q2), step, 1)
    else:
        musc_vis = shift(mu.intersection(Q), step, 1)
    items.append((musc_vis.difference(shift(muscle_lines(pose), step, 1)), "brass", 1, True))
    swall = unary_union([wall(sk, b, step, 1) for b in cut_lines(x0, y0)])
    items.append((swall, "ink", .42, True))
    items.append((sk.difference(Q), "ink", 1, True))
    out = knock(items, gap)
    rr = ring(G.R, ring_w)
    if quad_ring:
        front_ring = rr.difference(Q)
        back_ring = shift(rr.intersection(Q), step, 1)
        out.append((back_ring.difference(sk.buffer(gap)).difference(front_ring.buffer(gap)), "brass", .55))
        out.append((front_ring.difference(sk.buffer(gap)), "brass", 1))
    else:
        out.append((rr.difference(sk.buffer(gap)), "brass", 1))
    if square:
        out.append((square_frame(ring_w * .8).difference(sk.buffer(gap)).difference(rr.buffer(gap * .6)), "ink", .45))
    return out


def v_peel(theta=-30, spacing=430, depth=560, gap=12, plate_alpha=.06, circle=True, f=2600, lines=True,
           names=("skin", "muscle", "bone")):
    """Three square plates in perspective, receding to the right: skin in front (with the circle), then the
    muscle, then the skeleton. Each plate is a sheet of glass: faint fill, hairline edge."""
    th = math.radians(theta)
    pose = "circle"
    style = {"skin": ("ink", 1), "muscle": ("brass", 1), "bone": ("ink", .55)}
    n = len(names)
    items = []
    plate = G.box(-560, -60, 560, 1060)
    for i, name in enumerate(reversed(names)):
        j = n - 1 - i                         # 0 = front
        z, dx = j * depth, j * spacing
        role, a = style[name]
        fig = layer(name, pose)
        if name == "muscle" and lines:
            fig = fig.difference(muscle_lines(pose))
        P = lambda g: affinity.translate(perspective(g, th, z, f), dx)
        items.append((P(plate), "ink", plate_alpha, False))
        items.append((P(plate).difference(P(plate.buffer(-10))), "ink", .4, False))
        items.append((P(fig), role, a, True))
        if circle and j == 0:
            items.append((P(ring(G.R, 11)).difference(P(fig).buffer(gap)), "brass", 1, False))
    return knock(items, gap)


VARIANTS2 = {
    "section-a": ("Section, two steps, square", lambda: v_section2()),
    "section-b": ("Section, two steps, no square", lambda: v_section2(square=False)),
    "section-c": ("Section, one deep step", lambda: v_section2(step=(40, -40), bone=False, square=False)),
    "peel-a": ("Peel: three plates", lambda: v_peel()),
    "peel-b": ("Peel: tighter, flatter", lambda: v_peel(theta=-24, spacing=330, depth=420)),
    "peel-c": ("Peel: two plates", lambda: v_peel(names=("skin", "muscle"), spacing=520, depth=560)),
}


# ---- round three: the two finalists and their small drawings ------------------------------------------------------

def fat_layer(name, pose, fat):
    """A layer thickened for small sizes (frame units)."""
    g = layer(name, pose)
    return g.buffer(fat, 24) if fat else g


def peel(theta=-28, spacing=372, depth=480, gap=13, plate_alpha=.07, circle=True, f=2600, lines=True,
         names=("skin", "muscle", "bone"), fat=0, edge=9, ring_w=12, edge_alpha=(.5, .36, .3), u=0, sheets=False):
    """Peel: Leonardo's square as three sheets of glass in perspective, receding to the right. Skin on the
    front sheet with the circle, the muscle on the next, the skeleton at the back. The fingertips of the
    raised arms touch the top of each square, as in the drawing."""
    th = math.radians(theta)
    pose = "circle"
    style = {"skin": ("ink", 1), "muscle": ("brass", 1), "bone": ("ink", .58)}
    edge, ring_w, gap = max(edge, .9 * u), max(ring_w, 1.15 * u), max(gap, .9 * u)
    n = len(names)
    items = []
    plate = G.box(-500, 0, 500, 1000)
    for i, name in enumerate(reversed(names)):
        j = n - 1 - i                         # 0 = front
        z, dx = j * depth, j * spacing
        role, a = style[name]

        def P(g):
            return affinity.translate(perspective(g, th, z, f), dx)
        if sheets and j > 0:
            # small sizes: the deeper sheets carry their layer's colour instead of a figure
            items.append((P(plate), role, a * (.62 if j == 1 else .4), True))
            continue
        fig = fat_layer(name, pose, fat)
        if name == "muscle" and lines:
            fig = fig.difference(muscle_lines(pose, max(7, .8 * u)))
        items.append((P(plate), "ink", plate_alpha, False))
        items.append((P(plate).difference(P(plate.buffer(-edge))), "ink", edge_alpha[j], False))
        items.append((P(fig), role, a, True))
        if circle and j == 0:
            items.append((P(ring(G.R, ring_w)).difference(P(fig).buffer(gap)), "brass", 1, True))
    return knock(items, gap)


def section(step=(40, -40), gap=8, ring_w=12, fat=0, lines=True, wall_alpha=.34, back_ring=.5, pose="circle",
            erode=9, u=0, circle=True):
    """Section: the figure in Leonardo's circle, a quadrant of skin removed from the navel up and to the right.
    In the opening the muscle lies one step deeper; the cut walls of the skin give the step its depth, and the
    quadrant of the circle steps back with it."""
    gap, ring_w = max(gap, .9 * u), max(ring_w, 1.15 * u)
    sk = fat_layer("skin", pose, fat)
    mu = sk.buffer(-erode, 32) if fat else layer("muscle", pose)
    x0, y0 = 0, G.NAVEL
    Q = G.box(x0, -600, 900, y0)
    musc = shift(mu.intersection(Q), step, 1)
    if lines:
        musc = musc.difference(shift(muscle_lines(pose, max(7, .8 * u)), step, 1))
    swall = unary_union([wall(sk, b, step, 1) for b in cut_lines(x0, y0)])
    items = [(musc, "brass", 1, True), (swall, "ink", wall_alpha, True), (sk.difference(Q), "ink", 1, True)]
    out = knock(items, gap)
    if not circle:
        return out
    rr = ring(G.R, ring_w)
    front_ring = rr.difference(Q)
    if back_ring:
        back = shift(rr.intersection(Q), step, 1)
        out.append((back.difference(sk.buffer(gap)).difference(front_ring.buffer(gap)).difference(musc.buffer(gap)),
                    "brass", back_ring))
    out.append((front_ring.difference(sk.buffer(gap)), "brass", 1))
    return out


# Small drawings. Weights are set in output pixels: in the macOS tile one pixel is about 95 frame units at 32 px
# and 140-190 at 16 px, so limbs, rings and gaps are drawn at least that wide.
FINAL = {
    "peel": ("Peel: three sheets", lambda: peel()),
    "peel-lockup": ("Peel, lockup and header: figure, circle, two sheets", lambda: peel(
        lines=False, fat=26, gap=55, edge=40, ring_w=60, sheets=True, plate_alpha=.1, edge_alpha=(.55, 0, 0),
        spacing=420, depth=480)),
    "peel-32": ("Peel, 32 px: figure in a heavy circle and two sheets", lambda: peel(
        lines=False, circle=True, ring_w=95, fat=40, gap=90, edge=1, sheets=True, plate_alpha=0,
        edge_alpha=(0, 0, 0), spacing=380, depth=420)),
    "peel-16": ("Peel, 16 px", lambda: peel(lines=False, circle=False, fat=62, gap=120, edge=1, sheets=True,
                                            plate_alpha=0, edge_alpha=(0, 0, 0), spacing=480, depth=420)),
    "section": ("Section: the cut quadrant", lambda: section()),
    "section-32": ("Section, 32 px and lockup", lambda: section(fat=30, gap=55, ring_w=72, lines=False,
                                                                step=(85, -85), back_ring=.5, erode=0, wall_alpha=.4)),
    "section-16": ("Section, 16 px: no circle", lambda: section(fat=60, gap=110, lines=False, step=(130, -130),
                                                                erode=0, wall_alpha=0, circle=False)),
}
