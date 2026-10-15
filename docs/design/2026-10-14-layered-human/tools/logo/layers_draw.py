"""Drawing helpers for layers.py: smooth paths from polylines, a small 3D camera, the hand-drawn skeleton, and a
fitter that places a list of shapes in any box. Pure Python.

A drawing is a list of shapes: dicts with
  kind  "fill" or "stroke"
  rings list of (points, closed); points are (x, y) in the figure frame (1000 high, top 0, centre x 0)
  role  "ink", "accent" or "ground" (the tile colour, for knock-outs)
  op    opacity (fill-opacity or stroke-opacity)
  w     stroke width in frame units
  smooth  True: Catmull-Rom curves through the points; False: straight lines
  depth   only for sorting back to front (larger is further)"""
import math

from build_identity import n


# ---- paths -------------------------------------------------------------------------------------------------------

def area(p):
    return .5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def inside(pt, poly):
    x, y, c = pt[0], pt[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def orient(rings):
    """Outer rings counter-clockwise, holes clockwise (by nesting depth), so the nonzero rule cuts the holes."""
    out = []
    for i, (p, closed) in enumerate(rings):
        if not closed:
            out.append((p, closed))
            continue
        depth = sum(1 for j, (q, c) in enumerate(rings) if j != i and c and inside(p[0], q))
        want = 1 if depth % 2 == 0 else -1
        out.append((p if area(p) * want > 0 else p[::-1], closed))
    return out


def corners(p, closed, limit=62):
    """Points where the outline turns by more than `limit` degrees (cut edges, the crotch): kept sharp."""
    m, out = len(p), set()
    for i in range(m):
        if not closed and i in (0, m - 1):
            continue
        a, b, c = p[i - 1], p[i], p[(i + 1) % m]
        t = math.degrees(abs(math.atan2((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]),
                                        (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]))))
        if t > limit:
            out.add(i)
    return out


def controls(p, closed, k=1 / 6, sharp=()):
    """Bezier control points of the Catmull-Rom segments; zero tangents at sharp points."""
    m = len(p)
    segs = []
    for i in range(m if closed else m - 1):
        a = p[(i - 1) % m] if (closed or i > 0) else p[0]
        b, c = p[i], p[(i + 1) % m]
        e = p[(i + 2) % m] if (closed or i + 2 < m) else c
        kb = 0 if i in sharp else k
        kc = 0 if (i + 1) % m in sharp else k
        segs.append((b, (b[0] + (c[0] - a[0]) * kb, b[1] + (c[1] - a[1]) * kb),
                     (c[0] - (e[0] - b[0]) * kc, c[1] - (e[1] - b[1]) * kc), c))
    return segs


def catmull(p, closed, k=1 / 6):
    """Cubic Bezier path through the points (uniform Catmull-Rom); sharp corners stay sharp."""
    if len(p) < 3:
        return poly(p, closed)
    d = [f"M{n(p[0][0])} {n(p[0][1])}"]
    for b, c1, c2, c in controls(p, closed, k, corners(p, closed)):
        if c1 == b and c2 == c:
            d.append(f"L{n(c[0])} {n(c[1])}")
        else:
            d.append(f"C{n(c1[0])} {n(c1[1])} {n(c2[0])} {n(c2[1])} {n(c[0])} {n(c[1])}")
    return "".join(d) + ("Z" if closed else "")


def sample(p, closed, steps=10):
    """The smooth curve as a dense polyline (for rasterising)."""
    if len(p) < 3:
        return list(p)
    out = []
    for b, c1, c2, c in controls(p, closed, sharp=corners(p, closed)):
        for j in range(steps):
            t = j / steps
            u = 1 - t
            out.append((u ** 3 * b[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * c[0],
                        u ** 3 * b[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * c[1]))
    if not closed:
        out.append(p[-1])
    return out


def poly(p, closed):
    return "M" + "L".join(f"{n(x)} {n(y)}" for x, y in p) + ("Z" if closed else "")


# ---- 3D ----------------------------------------------------------------------------------------------------------

class Camera:
    """Perspective camera looking along +z at the figure's chest. A point (x, y) of a plate at depth z is turned by
    yaw about the vertical axis through the plate stack's centre, then projected; y is measured from yc."""

    def __init__(self, yaw=0, pitch=0, f=3200, yc=470, zc=0):
        self.yaw, self.pitch, self.f, self.yc, self.zc = math.radians(yaw), math.radians(pitch), f, yc, zc

    def point(self, x, y, z):
        y, z = y - self.yc, z - self.zc
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        x, z = x * c + z * s, -x * s + z * c
        c, s = math.cos(self.pitch), math.sin(self.pitch)
        y, z = y * c - z * s, y * s + z * c
        k = self.f / (self.f + z)
        return x * k, self.yc + y * k, k

    def ring(self, pts, z, dx=0, dy=0):
        return [self.point(x + dx, y + dy, z)[:2] for x, y in pts]

    def scale(self, z):
        return self.point(0, self.yc, z)[2]


def on_plate(shapes, cam, z, dx=0, dy=0, depth=None):
    """Put a flat drawing on a plate at depth z; stroke widths follow the perspective."""
    k = cam.scale(z)
    out = []
    for s in shapes:
        t = dict(s)
        t["rings"] = [(cam.ring(p, z, dx, dy), c) for p, c in s["rings"]]
        if "w" in s:
            t["w"] = s["w"] * k
        t["depth"] = z if depth is None else depth
        out.append(t)
    return out


def affine(shapes, k=1, dx=0, dy=0, cx=0, cy=0):
    """Scale about (cx, cy), then move."""
    out = []
    for s in shapes:
        t = dict(s)
        t["rings"] = [([((x - cx) * k + cx + dx, (y - cy) * k + cy + dy) for x, y in p], c) for p, c in s["rings"]]
        if "w" in s:
            t["w"] = s["w"] * k
        out.append(t)
    return out


# ---- the skeleton, drawn -----------------------------------------------------------------------------------------
# Landmarks measured on body_skeleton.webp in the figure frame (skull top 18, soles 996), then drawn as a few
# strokes and two filled shapes. Right half only (x > 0); mirrored.

SKULL = [(0, 17), (22, 20), (36, 31), (42, 49), (42, 64), (40, 77), (34, 84), (28, 86), (29, 97), (24, 107),
         (14, 114), (0, 117)]
ORBIT = [(15, 58), (24, 61), (25, 70), (17, 75), (7, 72), (6, 63)]
PELVIS = [(0, 446), (12, 432), (34, 418), (58, 410), (75, 418), (81, 436), (77, 458), (67, 478), (60, 494),
          (47, 505), (30, 510), (15, 507), (4, 503), (0, 504)]
INLET = [(0, 448), (16, 446), (27, 458), (24, 474), (12, 484), (0, 486)]
# (points, width): spine, clavicle, ribcage side, costal arch, ribs, limbs
BONES = [
    ([(0, 118), (0, 300), (0, 446)], 9),
    ([(7, 184), (50, 187), (93, 181)], 8),
    ([(14, 192), (44, 194), (64, 210), (75, 240), (79, 282), (76, 324), (69, 358), (60, 378)], 7.5),
    ([(0, 276), (18, 300), (36, 330), (50, 356), (60, 378)], 7.5),
    ([(9, 222), (36, 228), (58, 244), (72, 266)], 6),
    ([(9, 252), (34, 262), (56, 284), (70, 312)], 6),
    ([(92, 204), (108, 280), (121, 350)], 11),
    ([(125, 368), (137, 430), (147, 490)], 10),
    ([(150, 506), (154, 533), (157, 556)], 10),
    ([(60, 506), (52, 610), (45, 716)], 14),
    ([(44, 736), (44, 840), (45, 926)], 12),
    ([(46, 938), (52, 968), (61, 990)], 10),
]
# Small sizes: fewer, heavier strokes; the ribcage becomes one closed oval with the spine through it.
SMALL_SKULL = [(0, 14), (24, 19), (40, 38), (42, 66), (32, 96), (16, 114), (0, 120)]
SMALL_BONES = [
    ([(0, 118), (0, 470)], 18),
    ([(96, 194), (112, 280), (124, 356), (138, 430), (152, 510)], 18),
    ([(58, 506), (50, 620), (45, 730), (45, 840), (47, 950)], 22),
]
SMALL_CAGE = [(0, 190), (52, 194), (74, 232), (80, 290), (70, 350), (48, 378), (0, 360)]
SMALL_PELVIS = [(0, 430), (40, 414), (76, 426), (78, 462), (60, 500), (22, 510), (0, 504)]


# A few lines of the superficial muscles, for the large drawing: the linea alba, the lower borders of pectoralis
# major, the inguinal ligaments and sartorius. Right half; mirrored.
MUSCLE_LINES = [
    [(0, 200), (0, 300), (0, 440)],
    [(6, 262), (40, 266), (72, 252), (94, 228)],
    [(74, 428), (44, 462), (14, 494)],
    [(72, 446), (64, 540), (42, 640), (26, 702)],
]


def muscle_lines(role="ink", op=.5, w=3.5):
    rings = []
    for p in MUSCLE_LINES:
        rings += [(q, False) for q in (both(p) if any(x for x, _ in p) else [p])]
    return [{"kind": "stroke", "rings": rings, "role": role, "op": op, "w": w, "smooth": True}]


def mirror(half):
    """A closed ring from a right half that starts and ends on the axis."""
    return half + [(-x, y) for x, y in reversed(half[1:-1])]


def both(p):
    return [p, [(-x, y) for x, y in p]]


def skeleton(role="accent", op=1, wk=1, small=False):
    if small:
        shapes = [{"kind": "fill", "rings": [(mirror(SMALL_SKULL), True), (mirror(SMALL_PELVIS), True)],
                   "role": role, "op": op, "smooth": True},
                  {"kind": "stroke", "rings": [(mirror(SMALL_CAGE), True)], "role": role, "op": op,
                   "w": 16 * wk, "smooth": True}]
        for p, w in SMALL_BONES:
            shapes.append({"kind": "stroke", "rings": [(q, False) for q in (both(p) if p[0][0] else [p])],
                           "role": role, "op": op, "w": w * wk, "smooth": True})
        return shapes
    orbits = [(ORBIT, True), ([(-x, y) for x, y in ORBIT][::-1], True)]
    shapes = [{"kind": "fill", "rings": [(mirror(SKULL), True)] + orbits + [(mirror(PELVIS), True), (mirror(INLET), True)],
               "role": role, "op": op, "smooth": True}]
    for p, w in BONES:
        rings = [(q, False) for q in (both(p) if any(x for x, _ in p) else [p])]
        shapes.append({"kind": "stroke", "rings": rings, "role": role, "op": op, "w": w * wk, "smooth": True})
    return shapes


# ---- fitting and output --------------------------------------------------------------------------------------------

def bounds(shapes):
    xs, ys = [], []
    for s in shapes:
        h = s.get("w", 0) / 2 if s["kind"] == "stroke" else 0
        for p, _ in s["rings"]:
            xs += [x - h for x, _ in p] + [x + h for x, _ in p]
            ys += [y - h for _, y in p] + [y + h for _, y in p]
    return min(xs), min(ys), max(xs), max(ys)


def fit(shapes, box, ext, b=None, align=(.5, .5)):
    """Scale the drawing so its larger side is ext * size and centre it in box (x0, y0, size)."""
    x0, y0, size = box
    bx0, by0, bx1, by1 = b or bounds(shapes)
    k = ext * size / max(bx1 - bx0, by1 - by0)
    ox = x0 + (size - (bx1 - bx0) * k) * align[0] - bx0 * k
    oy = y0 + (size - (by1 - by0) * k) * align[1] - by0 * k
    return affine(shapes, k, ox, oy), k


def render(shapes, p):
    """SVG elements; consecutive shapes with the same style share one path."""
    colour = {"ink": p["ink"], "accent": p["accent"], "ground": p.get("ground", p.get("paper", "none"))}
    out = []
    for s in sorted(shapes, key=lambda s: -s.get("depth", 0)) if any("depth" in s for s in shapes) else shapes:
        rings = orient(s["rings"]) if s["kind"] == "fill" else s["rings"]
        d = "".join((catmull if s.get("smooth", True) else poly)(q, c) for q, c in rings)
        c = colour[s["role"]]
        if s["kind"] == "fill":
            o = f' fill-opacity="{n(s["op"])}"' if s["op"] < 1 else ""
            out.append(f'<path fill="{c}"{o} d="{d}"/>')
        else:
            o = f' stroke-opacity="{n(s["op"])}"' if s["op"] < 1 else ""
            cap = s.get("cap", "round")
            out.append(f'<path fill="none" stroke="{c}"{o} stroke-width="{n(s["w"])}" stroke-linecap="{cap}" '
                       f'stroke-linejoin="round" d="{d}"/>')
    return "".join(out)
