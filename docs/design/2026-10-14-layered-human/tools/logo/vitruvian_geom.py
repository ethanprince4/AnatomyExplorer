"""Geometry for the Vitruvian logo: Leonardo's figure in two poses, built from shaped primitives with shapely.

Frame: height 1000 (crown at y 0, soles at y 1000), centre line x 0, y down.
Leonardo's canon: arm span = height, head = 1/8, shoulders = 1/4, the square (side 1000) is centred on the pubis
(y 500) and the circle on the navel; the circle touches the square's base.

Pose "square": arms level, legs together.  Pose "circle": arms raised to the crown line, legs spread, feet on the
circle.  Three layers per pose: skin (the silhouette), muscle (skin less the subcutaneous layer, the head bare) and
bone (a skeleton from simple bone shapes)."""
import math

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

H = 1000
NAVEL = 393                 # circle centre; Leonardo's circle radius is about 0.607 of the height
R = H - NAVEL               # so the circle touches the base of the square
PUBIS = 500                 # square centre
SHOULDER = {"square": (100, 196), "circle": (97, 186)}   # glenohumeral joint (right side)
HIP = (50, 492)
ARM = 400                   # shoulder joint to fingertip: span 2 * (100 + 400) = height
LEG = 466                   # hip joint to ankle centre
ANKLE_SOLE = 36             # ankle centre to the sole

# Two-sided profiles along a limb, t from the proximal joint (0) to the tip (1): (t, side a, side b).
# Arm: a = cranial edge (deltoid, biceps, brachioradialis, thumb), b = caudal edge (triceps, ulnar side).
ARM_PROFILE = [(0, 42, 40), (.08, 41, 37), (.17, 35, 33), (.26, 30, 31.5), (.33, 27, 27), (.37, 25, 23.5),
               (.43, 28, 24), (.52, 24.5, 21), (.64, 19, 16.5), (.72, 16, 14.5), (.765, 19, 16.5),
               (.80, 23, 17.5), (.84, 20.5, 18), (.90, 17.5, 16), (.955, 14, 12.5), (.985, 10, 9), (1, 7, 7)]
# Leg: a = lateral edge (gluteus medius, vastus lateralis, lateral gastrocnemius), b = medial edge.
LEG_PROFILE = [(0, 64, 44), (.08, 63, 46), (.2, 57, 42), (.32, 50, 37), (.4, 44, 35.5), (.46, 37, 34.5),
               (.5, 31, 29), (.54, 28.5, 25), (.6, 30.5, 27), (.67, 32.5, 32), (.74, 29.5, 30), (.83, 22, 20),
               (.92, 16.5, 14.5), (1, 15.5, 14)]
# Torso half widths by height.
TORSO = [(140, 25), (152, 30), (166, 62), (180, 96), (196, 112), (226, 106), (250, 102), (290, 95), (330, 86),
         (370, 80), (395, 80), (425, 86), (455, 94), (482, 97), (505, 90), (520, 60)]
# Head: right half outline, crown to chin.
HEAD = [(0, 0), (22, 3), (37, 13), (45, 29), (47.5, 48), (46, 68), (42, 86), (35, 103), (24, 117), (11, 124),
        (0, 126)]


def interp(profile, t):
    ts = [p[0] for p in profile]
    return float(np.interp(t, ts, [p[1] for p in profile])), float(np.interp(t, ts, [p[2] for p in profile]))


def limb(a, b, profile, steps=60, scale=1.0):
    """A tapered limb from a to b; side 'a' of the profile lies to the left of the direction a->b
    (for a right limb pointing outwards/down that is the cranial or lateral side, see pose())."""
    a, b = np.array(a, float), np.array(b, float)
    d = b - a
    L = np.hypot(*d)
    u = d / L
    nrm = np.array([u[1], -u[0]])      # left of the direction in a y-down frame
    discs = []
    for i in range(steps + 1):
        t = i / steps
        ra, rb = interp(profile, t)
        ra, rb = ra * scale, rb * scale
        c = a + d * t + nrm * (ra - rb) / 2
        discs.append(Point(*c).buffer((ra + rb) / 2, 32))
    return unary_union([discs[i].union(discs[i + 1]).convex_hull for i in range(steps)])


def smooth_curve(pts, n=200):
    """Catmull-Rom through points, sampled densely."""
    p = np.array(pts, float)
    p = np.vstack([p[0], p, p[-1]])
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for t in np.linspace(0, 1, max(2, n // len(pts)), endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                             + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(p[-2])
    return np.array(out)


def mirror_poly(half):
    """A symmetric polygon from its right half (x >= 0), listed top to bottom."""
    half = np.array(half)
    left = half[::-1].copy()
    left[:, 0] *= -1
    return Polygon(np.vstack([half, left])).buffer(0)


def head():
    return mirror_poly(smooth_curve(HEAD, 120))


def torso():
    half = smooth_curve([(w, y) for y, w in TORSO], 200)
    return mirror_poly(np.vstack([[0, TORSO[0][0]], half, [0, TORSO[-1][0]]]))


def circle_point_at(origin, length, inset=0.0, side=1, lower=False):
    """The point at distance `length` from origin that lies on the circle of radius R - inset (right side)."""
    ox, oy = origin
    best = None
    for k in range(20000):
        a = -math.pi / 2 + math.pi * k / 20000 if not lower else math.pi * k / 20000 - math.pi / 2
        x, y = ox + length * math.cos(a), oy + length * math.sin(a)
        e = abs(math.hypot(x, y - NAVEL) - (R - inset))
        if (not lower and y < oy) or (lower and y > oy):
            if best is None or e < best[0]:
                best = (e, x, y)
    return best[1], best[2]


def arm_tip(pose):
    sx, sy = SHOULDER[pose]
    if pose == "square":
        return sx + ARM, sy
    a = math.asin(sy / ARM)                     # fingertips level with the crown, as Leonardo writes
    return sx + ARM * math.cos(a), 0.0


def ankle(pose):
    hx, hy = HIP
    if pose == "square":
        return 32, H - ANKLE_SOLE
    # spread until the soles reach the circle: the nearest the circle comes to the hip joint
    a = math.atan2(hx, hy - NAVEL)
    return hx + LEG * math.sin(a), hy + LEG * math.cos(a)


def foot(pose, scale=1.0):
    ax, ay = ankle(pose)
    hx, hy = HIP
    ang = math.atan2(ax - hx, ay - hy)          # leg tilt from vertical
    # front view: heel and malleoli above, the foot widening to the toes, turned out a little
    pts = [(-14, -14), (14, -14), (20, 6), (27, 22), (30, 31), (24, 36), (4, 36), (-14, 35), (-19, 28), (-17, 8)]
    poly = Polygon([(x * scale, y * scale) for x, y in pts]).buffer(5 * scale, 16).buffer(-3 * scale, 16)
    poly = affinity.rotate(poly, -math.degrees(ang) * .8, origin=(0, 0))
    return affinity.translate(poly, ax, ay)


def side(pose, scale=1.0):
    """The right arm and leg of a pose (scale thins the profiles for inner layers)."""
    s, t = SHOULDER[pose], arm_tip(pose)
    arm = limb(s, t, ARM_PROFILE, scale=scale)
    leg = limb(HIP, ankle(pose), [(p[0], p[2], p[1]) for p in LEG_PROFILE], scale=scale)
    return unary_union([arm, leg, foot(pose, scale)])


def mirror(g):
    return affinity.scale(g, -1, 1, origin=(0, 0))


def neck():
    return Polygon([(-26, 108), (26, 108), (29, 160), (-29, 160)])


def close(g, r):
    return g.buffer(r, 32).buffer(-r, 32)


def box(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def skin(pose):
    r = side(pose)
    body = unary_union([head(), neck(), torso(), r, mirror(r)])
    # fillets: a broad one over the shoulders (trapezius into deltoid), small ones in the armpits and the crotch
    shoulders = unary_union([box(18, 110, 175, 240), box(-175, 110, -18, 240)])
    body = unary_union([close(body, 7), close(body, 34).intersection(shoulders)])
    body = body.buffer(-2, 16).buffer(2, 16)
    return largest(body)


def largest(g):
    if isinstance(g, MultiPolygon):
        g = max(g.geoms, key=lambda p: p.area)
    return Polygon(g.exterior)


def muscle(pose, depth=9):
    """Skin less the subcutaneous layer; the head without its soft tissue."""
    g = skin(pose).buffer(-depth, 32)
    parts = g.geoms if isinstance(g, MultiPolygon) else [g]
    return unary_union([p for p in parts if p.area > 150])


# ---- skeleton ------------------------------------------------------------------------------------------------------

def bone(a, b, r0, rm, r1, steps=30):
    prof = [(0, r0, r0), (.18, rm * 1.15, rm * 1.15), (.5, rm, rm), (.82, rm * 1.1, rm * 1.1), (1, r1, r1)]
    return limb(a, b, prof, steps=steps)


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def skeleton(pose):
    sx, sy = SHOULDER[pose]
    tip = arm_tip(pose)
    elbow, wrist, knuck = lerp((sx, sy), tip, .365), lerp((sx, sy), tip, .725), lerp((sx, sy), tip, .86)
    ak = ankle(pose)
    knee = lerp(HIP, ak, .5)
    parts = []
    # skull and mandible
    skull = Point(0, 50).buffer(1, 64)
    skull = affinity.scale(skull, 41, 47)
    face = Polygon([(-31, 62), (31, 62), (27, 100), (14, 116), (-14, 116), (-27, 100)]).buffer(4)
    parts += [skull, face]
    # spine
    parts.append(Polygon([(-7, 118), (7, 118), (9, 470), (-9, 470)]))
    # rib cage: a barrel with the costal arch cut from below
    cage = mirror_poly(smooth_curve([(0, 178), (40, 182), (68, 200), (80, 240), (78, 290), (68, 330), (56, 350),
                                     (0, 352)], 120))
    arch = Polygon([(-40, 360), (0, 282), (40, 360)]).buffer(6)
    cage = cage.difference(arch)
    gaps = unary_union([LineString([(x, y + 22 * (x / 80) ** 2 + 10 * abs(x) / 80) for x in range(-90, 91, 6)]).buffer(4.5)
                        for y in (212, 240, 268, 296, 324)]).difference(box(-8, 0, 8, 600))
    parts.append(cage.difference(gaps))
    # clavicles and the shoulder girdle
    for m in (1, -1):
        parts.append(affinity.scale(LineString([(4, 182), (sx * .55, 178), (sx + 8, sy - 10)]).buffer(5.5), m, 1, origin=(0, 0)))
    # pelvis: ilia, sacrum and the pubic arch
    pel = mirror_poly(smooth_curve([(0, 420), (30, 418), (62, 406), (84, 418), (86, 450), (72, 482), (50, 505),
                                    (22, 515), (0, 512)], 120))
    pel = pel.difference(Polygon([(-14, 520), (0, 494), (14, 520)]).buffer(3))
    for m in (1, -1):   # obturator holes
        pel = pel.difference(affinity.scale(affinity.translate(affinity.scale(Point(0, 0).buffer(1, 24), 12, 9), 30, 492), m, 1, origin=(0, 0)))
    parts.append(pel)
    for m in (1, -1):
        def M(g):
            return affinity.scale(g, m, 1, origin=(0, 0))
        parts += [M(bone((sx, sy), elbow, 14, 9, 12)),
                  M(bone(elbow, wrist, 10, 8, 10)),
                  M(limb(wrist, knuck, [(0, 9, 9), (.5, 12, 12), (1, 11, 11)])),
                  M(limb(knuck, tip, [(0, 10, 10), (1, 4, 4)])),
                  M(bone(HIP, knee, 16, 11, 16)),
                  M(Point(*lerp(HIP, knee, .985)).buffer(10)),
                  M(bone(lerp(knee, ak, .03), ak, 15, 10, 12)),
                  M(foot(pose, .75))]
    return unary_union(parts)


# ---- output ---------------------------------------------------------------------------------------------------------

def rings(g):
    """Every closed ring of a (multi)polygon, exteriors and holes, as coordinate arrays."""
    polys = g.geoms if hasattr(g, "geoms") else [g]
    out = []
    for p in polys:
        if p.is_empty:
            continue
        out.append(np.array(p.exterior.coords)[:-1])
        out += [np.array(r.coords)[:-1] for r in p.interiors]
    return out


def path_d(g, f=None, tol=1.0, corner=60, fmt=None):
    """Smooth cubic Bezier path through the rings of g. f maps frame points to output points; tol is the
    simplification tolerance in output units; turns sharper than `corner` degrees stay sharp."""
    fmt = fmt or (lambda v: f"{v:.2f}".rstrip("0").rstrip(".").replace("-0", "-0") if abs(v) >= .005 else "0")
    f = f or (lambda p: p)
    out = []
    polys = g.geoms if hasattr(g, "geoms") else [g]
    for poly in polys:
        if poly.is_empty:
            continue
        for ring in [poly.exterior] + list(poly.interiors):
            pts = np.array([f(p) for p in np.array(ring.coords)])
            ls = LineString(pts).simplify(tol, preserve_topology=False)
            p = np.array(ls.coords)[:-1]
            if len(p) < 3:
                continue
            out.append(bezier_ring(p, corner, fmt))
    return "".join(out)


def bezier_ring(p, corner, fmt):
    n = len(p)

    def turn(i):
        a, b, c = p[i - 1], p[i], p[(i + 1) % n]
        v1, v2 = b - a, c - b
        cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        return math.degrees(math.acos(max(-1, min(1, cos))))
    sharp = [turn(i) > corner for i in range(n)]
    s = f"M{fmt(p[0][0])} {fmt(p[0][1])}"
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        if sharp[i] and sharp[(i + 1) % n]:
            s += f"L{fmt(b[0])} {fmt(b[1])}"
            continue
        prev, nxt = p[i - 1], p[(i + 2) % n]
        t1 = (b - prev) / 6 if not sharp[i] else (b - a) / 3
        t2 = (nxt - a) / 6 if not sharp[(i + 1) % n] else (b - a) / 3
        # keep handles shorter than a third of the segment, so tight bends do not loop
        seg = np.linalg.norm(b - a)
        for t in (t1, t2):
            m = np.linalg.norm(t)
            if m > seg / 2.2:
                t *= seg / 2.2 / m
        c1, c2 = a + t1, b - t2
        s += f"C{fmt(c1[0])} {fmt(c1[1])} {fmt(c2[0])} {fmt(c2[1])} {fmt(b[0])} {fmt(b[1])}"
    return s + "Z"
