"""Peripheral nerve and skeletal muscle: bundles of bundles, opened like a telescope.

Both are built the same way. The whole organ - wrapped in its outer sheath (epineurium, epimysium) - fills most of
the block. At the +x end the sheath stops, and each level of the hierarchy is pulled out a little further than the
one that contains it: the fascicles in their own sheaths (perineurium, perimysium), then a few single fibres, and in
muscle one fibre fraying into its banded myofibrils. Every step ends in a flat face, so the model is also a stack of
classic transverse sections, and the default cut-away opens the intact half lengthwise.

Everything is placed on one bent axis with sections kept in planes x = const (a sheared rather than a swept tube), so
nested layers, fibres and the flat faces that end them stay exactly in register. The connective-tissue sheaths carry
their collagen as low ridges lying in the surface - a sheath, not a felt.
"""
import math

import numpy as np

from .base import Part
from .cells import hex_points, poisson_disk
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, ellipsoid, mesh_part, round_cone, sdf_part, sphere
from .organic import Sweep, collagen_felt, curved_path, lobed, rsum, surf_noise


# ==================================================================================================== shared tools
def _smooth01(x):
    t = np.clip(x, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _shear_sweep(xs, cy, cz, n_theta):
    """A Sweep whose sections stay in the planes x = const, with theta measured from +y towards +z.

    A normal Sweep tilts each section to the local tangent, so its end faces would not line up with fibres extruded
    along x. With the frames pinned, a point at (theta, r) is simply (x, cy + r cos theta, cz + r sin theta)."""
    xs = np.asarray(xs, np.float64)
    sw = Sweep(np.stack([xs, cy(xs), cz(xs)], -1), n_theta, len(xs))
    sw.nrm = np.tile([0.0, 1.0, 0.0], (len(xs), 1))
    sw.bi = np.tile([0.0, 0.0, 1.0], (len(xs), 1))
    return sw


def _press(mesh, x_face, side, lip=0.0012, keep=0.03):
    """Press whatever sticks out past the plane x = x_face (+x side when side > 0) into a thin lens just in front
    of it. A nucleus or cell placed across the end face of a fibre then shows as a flat outline on that face - how
    it looks in a transverse section - instead of a bump. (Squashing to `keep` of its depth rather than flat onto
    one plane keeps its front and back surfaces apart, so they cannot flicker.)"""
    out = Mesh()
    for p, _, i in mesh.parts:
        p = p.copy()
        d = (p[:, 0] - x_face) * side
        beyond = d > 0
        p[beyond, 0] = x_face + side * (lip * np.minimum(d[beyond] / 0.002, 1.0) + d[beyond] * keep)
        out.add(p, i)
    return out


def _rot_x(phi):
    """Rotation about x taking local y to the radial direction (cos phi, sin phi) in the (y, z) plane."""
    c, s = math.cos(phi), math.sin(phi)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _ring(centre_fn, x, radius, n=18):
    """Closed circle round the x axis at station x (T tubules, terminal cisternae)."""
    a = np.linspace(0.0, 2 * math.pi, n + 1)
    c = centre_fn(x)
    return np.stack([np.full(n + 1, x) + c[0] - x, c[1] + radius * np.cos(a), c[2] + radius * np.sin(a)], -1)


def _rounded(poly, gap, radius, segs=3):
    g = poly.buffer(-(gap + radius), join_style=2)
    if g.is_empty:
        return None
    g = g.buffer(radius, quad_segs=segs) if radius > 0 else g
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda q: q.area)
    return None if g.is_empty or g.area < 1e-5 else g


def _cells_in(points, region, gap, radius, segs=3):
    from shapely.geometry import MultiPoint
    from shapely.ops import voronoi_diagram
    vd = voronoi_diagram(MultiPoint([tuple(p) for p in points]), envelope=region.envelope.buffer(1.0))
    out = []
    for cell in vd.geoms:
        c = cell.intersection(region)
        if c.is_empty:
            continue
        if c.geom_type == "MultiPolygon":
            c = max(c.geoms, key=lambda q: q.area)
        if gap or radius:
            c = _rounded(c, gap, radius, segs)
        if c is not None and c.geom_type == "Polygon" and not c.is_empty:
            out.append(c)
    return out


def _junctions(points, region):
    """Voronoi vertices inside `region`: the corners where three cells meet (capillaries, perimysial vessels)."""
    from shapely.geometry import MultiPoint, Point
    from shapely.ops import voronoi_diagram
    vd = voronoi_diagram(MultiPoint([tuple(p) for p in points]), envelope=region.envelope.buffer(1.0))
    seen = {}
    for cell in vd.geoms:
        for x, y in list(cell.exterior.coords)[:-1]:
            key = (round(x, 4), round(y, 4))
            if key not in seen and region.contains(Point(x, y)):
                seen[key] = (x, y)
    return np.array(list(seen.values())) if seen else np.zeros((0, 2))


def _resample(poly, n):
    """n points evenly spaced along a polygon's outline."""
    ring = poly.exterior
    return np.array([ring.interpolate(t, normalized=True).coords[0] for t in np.linspace(0, 1, n, endpoint=False)])


def _extrude_region(poly, t_vals, ring_map):
    """Extrude a polygon with holes along x. `ring_map(k)` gives the (U, V, T) -> xyz mapping for ring k (0 is the
    outline, then the holes), so a hole can follow the fibre or fascicle it makes room for.

    Sheaths and fillers built this way never contain what they wrap: a solid wrapper would put its end cap right
    across the fibres inside, and the cut-away - which shows the inside of every clipped part - would show that
    cap through them."""
    import shapely
    from scipy.spatial import cKDTree
    from .cells import polygon_area
    rings = []
    for k, r in enumerate([poly.exterior] + list(poly.interiors)):
        r = np.array(r.coords)[:-1]
        if (k == 0) != (polygon_area(r) > 0):
            r = r[::-1]
        rings.append(r)
    t = np.asarray(t_vals, float)
    m = len(t)
    pos, tris, starts = [], [], []
    off = 0
    for k, r in enumerate(rings):
        n = len(r)
        U = np.broadcast_to(r[:, 0], (m, n))
        V = np.broadcast_to(r[:, 1], (m, n))
        T = np.broadcast_to(t[:, None], (m, n))
        x, y, z = ring_map(k)(U, V, T)
        pos.append(np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3))
        a = np.arange(m * n).reshape(m, n) + off
        q0, q1 = a[:-1, :].ravel(), np.roll(a[:-1, :], -1, axis=1).ravel()
        q2, q3 = np.roll(a[1:, :], -1, axis=1).ravel(), a[1:, :].ravel()
        tris += [np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)]
        starts.append((off, n))
        off += m * n
    flat = np.vstack(rings)
    ring_of = np.concatenate([np.full(len(r), k) for k, r in enumerate(rings)])
    idx_of = np.concatenate([np.arange(len(r)) for r in rings])
    tree = cKDTree(flat)
    tri2 = []
    for g in shapely.constrained_delaunay_triangles(shapely.Polygon(rings[0], rings[1:])).geoms:
        c = np.array(g.exterior.coords)[:3]
        _, j = tree.query(c)
        if polygon_area(c) < 0:
            j = j[::-1]
        tri2.append(j)
    mesh = Mesh().add(np.vstack(pos), np.vstack(tris))
    if tri2:
        # the end faces get their own vertices, so they shade flat instead of rounding off into the walls
        allpos = mesh.parts[0][0]
        tri2 = np.array(tri2)
        for row, flip in ((0, True), (m - 1, False)):
            vid = np.array([starts[ring_of[j]][0] + row * starts[ring_of[j]][1] + idx_of[j] for j in range(len(flat))])
            mesh.add(allpos[vid], tri2[:, ::-1] if flip else tri2)
    return mesh


def _polys(g, min_area=2e-6):
    if g.is_empty:
        return []
    geoms = list(g.geoms) if hasattr(g, "geoms") else [g]
    return [p for p in geoms if p.geom_type == "Polygon" and p.area > min_area]


def _finish(parts, seed, grain, across, along, micro, micro_freq):
    """The shared finishing warp (tissue grain and cell-sized micro-relief), moving points only across the axis.

    Every step of the telescope ends in a plane x = const where several parts meet flush; a warp with an x
    component would buckle those faces and let one poke through another."""
    from .organic import grain_field, warp_parts
    g = grain_field(grain, across, along, 0, seed + 31)
    mf = grain_field(micro, micro_freq, micro_freq, 0, seed + 57, octaves=2)
    mask = np.array([0.0, 1.0, 1.0])
    return warp_parts(parts, lambda p: (g(p) + mf(p)) * mask)


def _circle_poly(r, n=72):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.stack([r * np.cos(a), r * np.sin(a)], -1)


def _nucleus(centre, phi, radii, res=5):
    """Flattened nucleus: radii are (along x, radial, tangential), rotated so the flat side faces outwards."""
    return ellipsoid_mesh(centre, radii, res, rotation=_rot_x(phi))


def home_view(model, yaw=0.70, pitch=0.40):
    """Open a telescoped model looking at its +x end, where the telescope is, with the lengthwise cut-away
    behind it. The model viewer reads `home_view` (radians)."""
    model.home_view = (yaw, pitch)
    return model


# ==================================================================================================== muscle
MUSCLE_DESC = {
    "epimysium": "Epimysium: the dense irregular connective-tissue coat of the whole muscle, mostly type I "
                 "collagen. It is continuous inwards with the perimysium and outwards with the tendon and deep "
                 "fascia, so the pull of every fibre is summed onto the tendon. It is the plane developed "
                 "surgically between muscles.",
    "collagen": "Coarse type I collagen bundles of the epimysium, laid in two crossing helical sets (a cross-ply) so "
                "the sheath resists overstretch yet lets the belly shorten and widen as it contracts.",
    "perimysium": "Perimysium: thinner connective-tissue septa that divide the muscle into fascicles and wrap each "
                  "one. It carries the larger arterioles, venules and nerve branches and houses the muscle spindles. "
                  "Fascicles are the 'grain' of meat. In dermatomyositis the perimysial vessels are the target and "
                  "fibres at the edge of each fascicle waste (perifascicular atrophy).",
    "endomysium": "Endomysium: the delicate reticular (type III collagen) fibres and basal lamina around each "
                  "individual muscle fibre, carrying the capillaries; satellite cells sit beneath its basal lamina. "
                  "In cross-section it is the thin pale net between the polygonal fibres. Cytotoxic T cells invade "
                  "it in polymyositis and inclusion-body myositis.",
    "fibres": "Skeletal muscle fibres: each a single multinucleated cell (a syncytium formed by fusion of "
              "myoblasts), 10–100 µm wide and up to many centimetres long, packed with myofibrils whose aligned "
              "sarcomeres give the cross-striations. In transverse section they are polygonal, pressed together "
              "with endomysium between them, nuclei at the edge. Slow oxidative (type I) and fast glycolytic "
              "(type II) fibres are intermixed in a checkerboard; clumping of one type signals denervation and "
              "reinnervation.",
    "nuclei": "Myonuclei: hundreds of flattened, elongated nuclei per fibre lying at the periphery just beneath the "
              "sarcolemma - in a transverse section, dark dots at the edge of each fibre. Internal (central) "
              "nuclei mark regeneration or a myopathy (centronuclear myopathy, myotonic dystrophy).",
    "satellite": "Satellite cells: muscle stem cells (Pax7+) wedged between the sarcolemma and the basal lamina. "
                 "Injury or training activates them to divide and fuse into fibres, repairing and enlarging them; "
                 "their exhaustion drives the progression of Duchenne dystrophy. Cardiac muscle has none and "
                 "cannot regenerate.",
    "myofibrils": "Myofibrils: 1–2 µm cylinders filling the fibre, each a chain of sarcomeres in series. "
                  "Neighbouring myofibrils keep their bands in register, which is why the whole fibre looks "
                  "striated. Shown fraying out of the cut end of one fibre, enlarged and with fewer, longer "
                  "sarcomeres than life.",
    "a_band": "A band (anisotropic, dark): the length of the thick myosin filaments (~1.6 µm), including their "
              "overlap with thin filaments. Its width stays constant during contraction - the key observation "
              "behind the sliding-filament theory.",
    "i_band": "I band (isotropic, light): thin actin filaments only (with troponin and tropomyosin) either side "
              "of a Z disc. It shortens during contraction as the thin filaments slide towards the M line.",
    "h_zone": "H zone: the centre of the A band, where thick filaments are not overlapped by thin ones. It narrows "
              "and can vanish at full contraction.",
    "m_line": "M line: myomesin and M-protein (with creatine kinase) cross-linking the thick filaments at the "
              "centre of the sarcomere.",
    "z_disc": "Z disc (Z line): the α-actinin lattice anchoring the thin filaments and titin of neighbouring "
              "sarcomeres; a sarcomere runs from one Z disc to the next (~2.5 µm at rest). Desmin ties the Z discs "
              "to each other and to the sarcolemma. The rods of nemaline myopathy are Z-disc material.",
    "t_tubules": "Transverse (T) tubules: inward extensions of the sarcolemma that carry the action potential deep "
                 "into the fibre. In mammalian skeletal muscle they ring each myofibril at every A–I junction (two "
                 "per sarcomere), where voltage-sensing DHP (Cav1.1) receptors are coupled mechanically to "
                 "ryanodine receptors of the SR.",
    "sr": "Sarcoplasmic reticulum: a sleeve of smooth ER round each myofibril that stores Ca²⁺. Its terminal "
          "cisternae flank every T tubule, forming a triad; RyR1 releases Ca²⁺ to start contraction and SERCA pumps "
          "it back to relax. RyR1 mutations cause malignant hyperthermia with volatile anaesthetics and "
          "suxamethonium (treated with dantrolene).",
    "cap": "Endomysial capillaries: several around every fibre, running mostly along it with cross-links and loops. "
           "Slow oxidative (type I, red) fibres have the richest supply, and exercise training adds capillaries.",
    "arteriole": "Perimysial arterioles: branches of the muscle's artery running between fascicles in the "
                 "perimysium, feeding the endomysial capillary beds. Their smooth muscle relaxes within seconds of "
                 "contraction starting (exercise hyperaemia).",
    "venule": "Perimysial venules: collect the capillary blood between fascicles. Contraction squeezes the veins "
              "of the limb muscles, and with their valves this 'muscle pump' returns blood to the heart.",
    "nerve": "Intramuscular motor nerve branch: myelinated axons of α motor neurons running in the perimysium and "
             "branching to supply many fibres scattered through the muscle. One motor neuron and all the fibres it "
             "supplies form a motor unit - a handful in the extraocular muscles, over a thousand in gastrocnemius.",
    "nmj": "Neuromuscular junction (axon terminal): the motor axon loses its myelin and ends in a spray of terminal "
           "boutons lying in shallow gutters on the fibre, one junction per fibre near its middle. Each impulse "
           "releases acetylcholine onto nicotinic receptors. Botulinum toxin blocks release; antibodies to the "
           "receptor cause myasthenia gravis and to presynaptic P/Q Ca²⁺ channels Lambert–Eaton syndrome; "
           "rocuronium competes for the receptor.",
    "endplate": "Motor end plate (sole plate): the specialised patch of fibre under the terminal - a raised "
                "cushion of sarcoplasm with clustered sole-plate nuclei and junctional folds whose crests are "
                "packed with acetylcholine receptors, with acetylcholinesterase in the synaptic cleft.",
    "spindle": "Muscle spindle capsule: a fusiform connective-tissue capsule, continuous with perineurium, lying in "
               "the perimysium parallel to the ordinary (extrafusal) fibres, with a fluid-filled periaxial space "
               "round its equator. Spindles are densest in muscles for fine control (hand, neck, eye).",
    "intrafusal": "Intrafusal fibres: small modified muscle fibres inside the spindle - nuclear bag fibres (nuclei "
                  "crowded into a swollen equator) and thinner nuclear chain fibres (nuclei in a single row). Only "
                  "their striated polar ends contract, driven by γ motor neurons, which keeps the spindle taut and "
                  "sensitive while the muscle shortens (α–γ coactivation).",
    "intrafusal_nuclei": "Nuclei of the intrafusal fibres: clustered in the equatorial bag of nuclear bag fibres, "
                         "in a single file in nuclear chain fibres - the origin of their names.",
    "ia": "Primary (annulospiral, group Ia) sensory ending: the Ia afferent coils round the equator of each "
          "intrafusal fibre and fires when it is stretched, signalling muscle length and its rate of change. It "
          "synapses directly on α motor neurons of the same muscle - the monosynaptic stretch (tendon-jerk) reflex.",
}

M_R = 0.60              # muscle radius (inner surface of the epimysium)
M_X_EPI = 0.16          # epimysium and interfascicular perimysium stop here
M_HERO = 0.90           # the fibre that frays into myofibrils ends here
SARC = 0.030            # sarcomere length (enlarged: ~2.5 µm in life)
I_LEN, A_LEN, H_LEN = 0.010, 0.020, 0.0062
CAM = np.array([0.52, 0.85])        # (y, z) direction the default view looks from


def _fibre_map(by, bz, fw, c, phase, emerge=None, band=None):
    """Extrusion of one outline along the bent muscle axis, moving with its fascicle (`fw`).

    Inside the fascicle every fibre is a straight prism of its polygonal outline, so the endomysium between them can
    be built with exactly matching holes. With `emerge` = (x0, dir, dist, r) the fibre leaves the fascicle beyond
    x0: its outline rounds into a cylinder of radius r that swells and narrows a little, while it drifts `dist`
    along `dir`. `band` = (z0, amp) scallops the surface at every Z line, in register with the myofibrils."""
    cu, cv = float(c[0]), float(c[1])

    def f(U, V, T):
        fy, fz = fw(T)
        oy, oz = by(T) + fy, bz(T) + fz
        if emerge is None:
            return T, U + oy, V + oz
        x0, d, dist, rm = emerge
        du, dv = U - cu, V - cv
        rr = np.hypot(du, dv) + 1e-9
        b = _smooth01((T - x0) / 0.16)
        k = 1.0 + 0.03 * b * (np.sin(T * 3.3 + phase) + 0.6 * np.sin(T * 7.1 + phase * 1.7)) / 1.6
        if band is not None:
            k = k * (1.0 + band[1] * b * (1.0 - np.cos(2 * math.pi * (T - band[0]) / SARC)))
        du = (du * (1.0 - b) + du / rr * rm * b) * k
        dv = (dv * (1.0 - b) + dv / rr * rm * b) * k
        m = _smooth01((T - x0) / 0.26) * dist
        return (T, cu + du + d[0] * m + oy + 0.0012 * b * np.sin(T * 5.0 + phase),
                cv + dv + d[1] * m + oz + 0.0012 * b * np.cos(T * 4.0 + phase))
    return f


def _at(f, u, v, x):
    p = f(np.array([u], float), np.array([v], float), np.array([x], float))
    return np.array([float(np.ravel(q)[0]) for q in p])


def build_muscle():
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    parts = []
    rng = np.random.default_rng(6)
    R = M_R
    path = curved_path(2.0, bend=(0.065, -0.050), wobble=0.034, freq=1.0, seed=9)
    xs_ref = np.linspace(-1.0, 1.0, 400)
    oy = np.interp(xs_ref, path[:, 0], path[:, 1])
    oz = np.interp(xs_ref, path[:, 0], path[:, 2])

    def by(t):
        return np.interp(t, xs_ref, oy)

    def bz(t):
        return np.interp(t, xs_ref, oz)

    def world(x, rho, phi):
        x = np.asarray(x, float)
        return np.stack([x, by(x) + rho * np.cos(phi), bz(x) + rho * np.sin(phi)], -1)

    # ---------------------------------------------------------------- epimysium
    x_epi = M_X_EPI - 0.004
    trunk = _shear_sweep(np.linspace(-1.0, x_epi, 90), by, bz, 216)
    epi_in = rsum(R + 0.012, lobed(7, 0.014, 0.8), surf_noise(0.008, 3.0, 2.4, 2))
    epi_out = rsum(epi_in, 0.034, surf_noise(0.006, 6.0, 3.0, 3))
    parts.append(Part("Epimysium", "Connective tissue", "#e9dfc9", trunk.shell(epi_in, epi_out),
                      MUSCLE_DESC["epimysium"], category="fascia", clip=True, rank=2, detail=(0.10, 50.0, 0.12, 1)))
    felt = Mesh()
    for k, pitch in enumerate(((0.55, 0.95), (-0.95, -0.55))):
        felt.extend(collagen_felt(trunk, rsum(epi_out, -0.0040), rsum(epi_out, -0.0040), 64, seed=91 + k,
                                  r_range=(0.0055, 0.0090), pitch=pitch, waves=2.0, samples=40, segments=6))
    parts.append(mesh_part(felt, "Epimysial collagen bundles", "Connective tissue", "#d9c7a0",
                           MUSCLE_DESC["collagen"], "ligament", rank=2.2, detail=(0.10, 45.0, 0.12, 1)))

    # ---------------------------------------------------------------- fascicles
    R_f = R - 0.05
    region = Polygon(_circle_poly(R_f, 120))
    fas_pts = np.array([(0.0, 0.0)] + [(0.28 * math.cos(a), 0.28 * math.sin(a)) for a in
                                       np.linspace(0, 2 * math.pi, 7)[:-1] + 0.3] +
                       [(0.45 * math.cos(a), 0.45 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 10)[:-1] + 0.1])
    fas_pts += rng.uniform(-0.03, 0.03, fas_pts.shape)
    fcells = _cells_in(fas_pts, region, 0.0, 0.0)
    cents = np.array([[c.centroid.x, c.centroid.y] for c in fcells])
    outer = [i for i, c in enumerate(cents) if np.hypot(*c) > 0.36]
    hero_f = max(outer, key=lambda i: float(cents[i] @ CAM) / np.hypot(*cents[i]))

    perimysium, fibres, endo, nuclei, sats, caps = Mesh(), Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    fas_info = {}
    holes, hole_maps = [], []
    hero = None
    emerging = []
    for fi, fcell in enumerate(fcells):
        sheath = _rounded(fcell, 0.012, 0.026, 4)
        if sheath is None:
            continue
        rho_c = float(np.hypot(*cents[fi]))
        x_f = 0.66 - 0.22 * min(rho_c / 0.45, 1.0) + rng.uniform(-0.025, 0.025)
        if fi == hero_f:
            x_f = 0.47
        x_sl = x_f - rng.uniform(0.06, 0.085) - (0.04 if fi == hero_f else 0.0)
        fph = rng.uniform(0, 2 * math.pi)

        def fw(T, fph=fph):
            return 0.004 * np.sin(T * 2.3 + fph), 0.004 * np.cos(T * 1.9 + fph * 1.3)
        fmap = _fibre_map(by, bz, fw, (0.0, 0.0), 0.0)
        fas_info[fi] = (x_f, x_sl, fmap)
        inner = sheath.buffer(-0.010)
        if inner.is_empty or inner.geom_type != "Polygon":
            continue
        # perimysium: a sleeve round the fascicle (a ring, so it never caps over the fibres inside)
        ring = Polygon(_resample(sheath, 96), [_resample(inner, 96)[::-1]])
        n_t = int((x_sl + 1) / 0.08) + 2
        perimysium.extend(_extrude_region(ring, np.linspace(-1.0, x_sl, n_t), lambda k, fmap=fmap: fmap))
        holes.append(_resample(sheath.buffer(0.005), 48))
        hole_maps.append(fmap)

        # fibres: a Voronoi mosaic with rounded corners
        pts = [p for p in poisson_disk(inner.bounds[:2], inner.bounds[2:], 0.044, seed=200 + fi)
               if inner.buffer(-0.006).contains(Point(p))]
        if len(pts) < 3:
            continue
        pts = np.array(pts)
        cells = _cells_in(pts, inner.buffer(-0.001), 0.0035, 0.0065)
        shapes = [_resample(c, 14) for c in cells]
        hull = unary_union([Polygon(s).buffer(0.0045, join_style=2) for s in shapes]).buffer(-0.0055)
        hull = hull.simplify(0.0008)
        net = hull.difference(unary_union([Polygon(s).buffer(0.0005, join_style=2) for s in shapes]))
        n_t = int((x_f + 1) / 0.09) + 2
        for piece in _polys(net):
            endo.extend(_extrude_region(piece, np.linspace(-1.0, x_f, n_t), lambda k, fmap=fmap: fmap))

        # the fibres of the chosen fascicle on the side facing the viewer leave it and run on alone
        out_dir = cents[fi] / max(np.hypot(*cents[fi]), 1e-6)
        chosen = []
        if fi == hero_f:
            score = [float((np.array([c.centroid.x, c.centroid.y]) - cents[fi]) @ (out_dir + CAM)) for c in cells]
            order = np.argsort(score)[::-1]
            chosen = [int(i) for i in order[:7] if cells[int(i)].area > 0.0007]
        for ci, (cell, shape) in enumerate(zip(cells, shapes)):
            c = shape.mean(axis=0)
            rm = math.sqrt(cell.area / math.pi)
            phase = fi * 1.3 + ci * 0.7
            if ci in chosen:
                rank = chosen.index(ci)
                d = (c - cents[fi]) / max(np.hypot(*(c - cents[fi])), 1e-6) * 0.6 + out_dir * 0.8
                d /= np.hypot(*d)
                is_hero = rank == 1
                x_e = M_HERO if is_hero else x_f + rng.uniform(0.25, 0.38)
                r_e = 0.026 if is_hero else rm * 1.02
                x0, dist = x_f - 0.02, 0.012 + 0.008 * rank
                f = _fibre_map(by, bz, fw, c, phase, emerge=(x0, d, dist, r_e), band=(M_HERO + 0.004, 0.018))
                tv = np.concatenate([np.linspace(-1.0, x_f - 0.08, 20), np.arange(x_f - 0.07, x_e, 0.005), [x_e]])
                fibres.extend(_extrude_region(Polygon(shape), tv, lambda k, f=f: f))
                # its own endomysial sleeve, stopping short so the bare sarcolemma shows beyond
                x_s = x_f + rng.uniform(0.09, 0.14)
                sl = Polygon(_resample(Polygon(shape).buffer(0.0032), 22),
                             [_resample(Polygon(shape).buffer(0.0005, join_style=2), 22)[::-1]])
                maps = [_fibre_map(by, bz, fw, c, phase, emerge=(x0, d, dist, r_e + g)) for g in (0.0032, 0.0005)]
                endo.extend(_extrude_region(sl, np.linspace(x_f + 0.0003, x_s, 40), lambda k, maps=maps: maps[k]))
                emerging.append(dict(f=f, c=c, r=r_e, x0=x_f, x_s=x_s, x_e=x_e, d=d, hero=is_hero))
                if is_hero:
                    hero = emerging[-1]
                for x in np.arange(x_s + rng.uniform(0.01, 0.04), x_e - 0.02, 0.045):
                    phi = rng.uniform(0, 2 * math.pi)
                    cen = _at(f, c[0], c[1], x)
                    pos = cen + np.array([0.0, math.cos(phi), math.sin(phi)]) * (r_e - 0.0022)
                    nuclei.extend(_nucleus(pos, phi, (0.017, 0.0036, 0.0060), 6))
                phi = math.atan2(d[1], d[0]) + rng.uniform(-0.6, 0.6)
                cen = _at(f, c[0], c[1], rng.uniform(x_s + 0.02, x_e - 0.05))
                sats.extend(_nucleus(cen + np.array([0.0, math.cos(phi), math.sin(phi)]) * (r_e + 0.0012), phi,
                                     (0.014, 0.0036, 0.0062), 6))
                continue
            fibres.extend(_extrude_region(Polygon(shape), np.linspace(-1.0, x_f, n_t), lambda k: fmap))
            # myonuclei: pressed onto both end faces, along the exposed stretch, and where the cut opens the fibre
            spots = [(x_f, 1), (x_f, 1), (-1.0, -1)]
            spots += [(x, 0) for x in rng.uniform(x_sl, x_f - 0.02, 1)]
            spots += [(x, 0) for x in rng.uniform(0.0, 0.09, 1)]
            if abs(c[0]) < rm + 0.02:
                spots += [(x, 0) for x in np.arange(-0.95, 0.0, 0.10) + rng.uniform(0, 0.08)]
            for x, side in spots:
                j = int(rng.integers(len(shape)))
                u, v = c + (shape[j] - c) * 0.84
                phi = math.atan2(shape[j][1] - c[1], shape[j][0] - c[0])
                n = _nucleus(_at(fmap, u, v, x), phi, (0.016, 0.0035, 0.0058))
                nuclei.extend(_press(n, x, side) if side else n)
            if rng.random() < 0.16:
                j = int(rng.integers(len(shape)))
                u, v = c + (shape[j] - c) * 1.03
                phi = math.atan2(shape[j][1] - c[1], shape[j][0] - c[0])
                sats.extend(_press(_nucleus(_at(fmap, u, v, x_f), phi, (0.012, 0.0030, 0.0060)), x_f, 1))
        # capillaries in the corners where three fibres meet
        for u, v in _junctions(pts, inner.buffer(-0.004)):
            if rng.random() > 0.6:
                continue
            xs = np.linspace(-1.001, x_f + 0.002, n_t)
            caps.extend(tube(np.stack(fmap(np.full_like(xs, u), np.full_like(xs, v), xs), -1), 0.0032, 6))

    # interfascicular perimysium: the rest of the section, with a hole for every fascicle
    def ext_map(U, V, T):
        th = np.arctan2(V, U)
        r = epi_in(th, (T + 1.0) / (x_epi + 1.0)) - 0.002
        return T, r * np.cos(th) + by(T), r * np.sin(th) + bz(T)
    maps = [ext_map] + hole_maps
    filler = Polygon(_circle_poly(0.598, 180), [h[::-1] for h in holes])
    perimysium.extend(_extrude_region(filler, np.linspace(-1.0, M_X_EPI, 26), lambda k: maps[k]))

    # capillary loops along the fibres that have left their fascicle
    for a, b in zip(emerging[:-1], emerging[1:]):
        xa = min(a["x_e"], b["x_e"]) - 0.05
        xs = np.linspace(a["x0"] - 0.01, xa, 36)
        pa = np.array([_at(a["f"], a["c"][0], a["c"][1], x) for x in xs])
        pb = np.array([_at(b["f"], b["c"][0], b["c"][1], x) for x in xs])
        side = pb - pa
        side[:, 0] = 0.0
        side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-6)
        up = np.cross(side, np.array([1.0, 0.0, 0.0]))
        la = pa + side * (a["r"] + 0.0045) + up * (0.006 * np.sin(xs * 40))[:, None]
        lb = pb - side * (b["r"] + 0.0045) - up * (0.006 * np.sin(xs * 37))[:, None]
        turn = smooth_path(np.array([la[-2], la[-1] + np.array([0.02, 0, 0]), (la[-1] + lb[-1]) / 2 +
                                     np.array([0.03, 0, 0]), lb[-1] + np.array([0.02, 0, 0]), lb[-2]]), 12)
        caps.extend(tube(np.vstack([la[:-1], turn, lb[-2::-1]]), 0.0032, 6))

    # ---------------------------------------------------------------- perimysial vessels between fascicles
    art, ven = Mesh(), Mesh()
    for k, (u, v) in enumerate(_junctions(fas_pts, Polygon(_circle_poly(R_f - 0.03, 60)))):
        near = [int(i) for i in np.argsort(np.hypot(cents[:, 0] - u, cents[:, 1] - v))[:3] if int(i) in fas_info]
        x_end = min(fas_info[i][1] for i in near) - 0.04
        tgt = cents[near[0]]
        xs = np.linspace(-1.002, x_end, 40)
        dive = _smooth01((xs - (x_end - 0.12)) / 0.12)
        line = np.stack([xs, u + (tgt[0] - u) * 0.25 * dive + by(xs), v + (tgt[1] - v) * 0.25 * dive + bz(xs)], -1)
        if k % 2 == 0:
            art.extend(tube(line, np.linspace(0.0105, 0.008, 40), 12))
        else:
            ven.extend(tube(line, np.linspace(0.0140, 0.011, 40), 12))

    parts += [
        mesh_part(perimysium, "Perimysium", "Connective tissue", "#dcc49c", MUSCLE_DESC["perimysium"], "fascia",
                  bulk=True, rank=1.5, detail=(0.12, 55.0, 0.15, 1)),
        mesh_part(endo, "Endomysium", "Connective tissue", "#f2e6d8", MUSCLE_DESC["endomysium"], "fascia",
                  bulk=True, rank=1, detail=(0.08, 60.0, 0.12, 1)),
        mesh_part(fibres, "Muscle fibres", "Muscle fibres", "#b0463f", MUSCLE_DESC["fibres"], "muscle", rank=0.5,
                  detail=(0.06, 45.0, 0.0, 1)),
        mesh_part(nuclei, "Myonuclei", "Muscle fibres", "#3f3584", MUSCLE_DESC["nuclei"], "nucleus", rank=0.6,
                  detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(sats, "Satellite cells", "Muscle fibres", "#2f8c85", MUSCLE_DESC["satellite"], "nucleus",
                  rank=0.7, detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(caps, "Endomysial capillaries", "Nerves & vessels", "#d8433b", MUSCLE_DESC["cap"], "artery",
                  rank=0.6),
        mesh_part(art, "Perimysial arterioles", "Nerves & vessels", "#c3302b", MUSCLE_DESC["arteriole"], "artery",
                  rank=1.6),
        mesh_part(ven, "Perimysial venules", "Nerves & vessels", "#5a4fa3", MUSCLE_DESC["venule"], "vein",
                  rank=1.6),
    ]

    parts += _myofibrils(hero, rng)
    parts += _motor_nerve(emerging, cents[hero_f], by, bz, world, R_f, nuclei, rng)
    parts += _spindle(cents, hero_f, world, R_f, rng)
    return _finish(parts, 6, 0.004, 11.0, 2.0, 0.0022, 30.0)


def _myofibrils(hero, rng):
    """The hero fibre's myofibrils, running on past its cut end with every band a separate part."""
    f, c, r_f = hero["f"], hero["c"], hero["r"]
    x0 = M_HERO
    r_m = 0.0045

    def centre(x):
        return _at(f, c[0], c[1], min(x, x0)) + np.array([x - min(x, x0), 0.0, 0.0])
    pts = []
    sp = 2 * r_m + 0.0014
    for j in range(-4, 5):
        for i in range(-4, 5):
            p = np.array([i * sp + (j % 2) * sp / 2, j * sp * math.sqrt(3) / 2])
            if np.hypot(*p) < r_f - r_m * 1.15:
                pts.append(p)
    bands = {k: Mesh() for k in ("I", "Z", "A", "H", "M", "core", "T", "SR")}
    z0 = x0 + 0.004
    toward = hero["d"]
    sr_set = sorted(range(len(pts)), key=lambda i: -float(pts[i] @ np.array([-toward[1], toward[0]])))[:4]
    for i, o in enumerate(pts):
        n_sarc = int(rng.integers(3, 9))
        x_end = z0 + n_sarc * SARC + rng.choice([0.0, I_LEN / 2, I_LEN / 2 + A_LEN / 2])
        ph = rng.uniform(0, 2 * math.pi)

        def axis(x, o=o, ph=ph):
            spread = 1.0 + 1.3 * _smooth01((x - x0) / 0.12)
            droop = 0.02 * max(x - x0, 0.0) ** 2 / 0.09
            cc = centre(x)
            return cc + np.array([0.0, o[0] * spread + 0.0015 * math.sin(x * 60 + ph) - droop,
                                  o[1] * spread + 0.0015 * math.cos(x * 50 + ph)])

        def seg(key, a, b, r):
            if b - a < 1e-5:
                return
            bands[key].extend(tube(np.array([axis(a), axis(b)]), r, 12))
        core = np.array([axis(x) for x in np.linspace(x0 - 0.03, x_end + 0.005, 24)])
        bands["core"].extend(tube(core, np.r_[np.full(22, r_m * 0.9), r_m * 0.7, r_m * 0.3], 10))
        n = 0
        while True:
            z = z0 + n * SARC
            if z - I_LEN / 2 >= x_end:
                break
            seg("I", max(z - I_LEN / 2, x0 - 0.02), min(z + I_LEN / 2, x_end), r_m)
            if z <= x_end:
                seg("Z", z - 0.0007, z + 0.0007, r_m * 1.16)
            a0, m = z + I_LEN / 2, z + SARC / 2
            a1 = z + SARC - I_LEN / 2
            seg("A", a0, min(m - H_LEN / 2, x_end), r_m * 1.035)
            if m - H_LEN / 2 < x_end:
                seg("H", m - H_LEN / 2, min(m + H_LEN / 2, x_end), r_m * 1.03)
            if m < x_end:
                seg("M", m - 0.0006, m + 0.0006, r_m * 1.08)
            if m + H_LEN / 2 < x_end:
                seg("A", m + H_LEN / 2, min(a1, x_end), r_m * 1.035)
            if i in sr_set and 0 <= n <= 2 and a1 < x_end:
                # triads at both A-I junctions, longitudinal SR over the A band, a collar at the H zone
                for xj in (a0, a1):
                    bands["T"].extend(tube(_ring(axis, xj, r_m * 1.34), 0.0007, 5, caps=False))
                    for s in (-1, 1):
                        bands["SR"].extend(tube(_ring(axis, xj + s * 0.0021, r_m * 1.24), 0.0012, 6, caps=False))
                bands["SR"].extend(tube(_ring(axis, m, r_m * 1.2), 0.0009, 5, caps=False))
                for k in range(6):
                    a = k * math.pi / 3 + n
                    xs = np.linspace(a0 + 0.0035, a1 - 0.0035, 9)
                    wig = 0.25 * np.sin((xs - a0) * 500 + k)
                    ln = np.array([axis(x) for x in xs])
                    ln[:, 1] += r_m * 1.17 * np.cos(a + wig)
                    ln[:, 2] += r_m * 1.17 * np.sin(a + wig)
                    bands["SR"].extend(tube(ln, 0.0006, 5))
            n += 1
    g = "Sarcomere"
    return [
        mesh_part(bands["core"], "Myofibrils", "Muscle fibres", "#d98377", MUSCLE_DESC["myofibrils"], "muscle",
                  rank=0.4, detail=(0.04, 0.0, 0.0, 0)),
        mesh_part(bands["A"], "A band", g, "#8a2c3b", MUSCLE_DESC["a_band"], "muscle", rank=0.3,
                  detail=(0.04, 0.0, 0.0, 0)),
        mesh_part(bands["I"], "I band", g, "#f2c4ba", MUSCLE_DESC["i_band"], "muscle", rank=0.3,
                  detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(bands["H"], "H zone", g, "#c9676a", MUSCLE_DESC["h_zone"], "muscle", rank=0.3, label=False,
                  detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(bands["M"], "M line", g, "#4a1c34", MUSCLE_DESC["m_line"], "muscle", rank=0.3,
                  detail=(0.02, 0.0, 0.0, 0)),
        mesh_part(bands["Z"], "Z disc", g, "#2c2346", MUSCLE_DESC["z_disc"], "muscle", rank=0.3,
                  detail=(0.02, 0.0, 0.0, 0)),
        mesh_part(bands["T"], "T tubules", g, "#6fb6d8", MUSCLE_DESC["t_tubules"], "other", rank=0.35,
                  detail=(0.02, 0.0, 0.0, 0)),
        mesh_part(bands["SR"], "Sarcoplasmic reticulum", g, "#9fcf8a", MUSCLE_DESC["sr"], "other", rank=0.35,
                  detail=(0.02, 0.0, 0.0, 0)),
    ]


def _motor_nerve(emerging, c_fas, by, bz, world, R_f, nuclei, rng):
    """A motor branch leaves the perimysium and sends a terminal axon to an end plate on each of three fibres."""
    phi_n = math.atan2(c_fas[1], c_fas[0]) - 0.16
    x_b = emerging[0]["x0"] + 0.04
    trunk_pts = np.vstack([world(np.array([-0.55, -0.2, M_X_EPI - 0.05]), R_f + 0.024, phi_n),
                           world(np.array([M_X_EPI + 0.08, x_b - 0.06]), R_f + 0.004, phi_n),
                           world(np.array([x_b]), R_f + 0.03, phi_n)])
    trunk = smooth_path(trunk_pts, 56)
    nerve = Mesh().extend(tube(trunk, np.linspace(0.0115, 0.0085, len(trunk)), 12))
    targets = [e for e in emerging if not e["hero"]][:3]
    plates, terms = Mesh(), Mesh()
    for k, e in enumerate(targets):
        x = min(e["x_s"] + 0.04 + 0.02 * k, e["x_e"] - 0.05)
        cen = _at(e["f"], e["c"][0], e["c"][1], x)
        nrm = cen[1:] - np.array([float(by(x)), float(bz(x))])
        nrm = nrm / np.hypot(*nrm) * 0.5 + CAM * 0.5
        nrm /= np.hypot(*nrm)
        phi = math.atan2(nrm[1], nrm[0])
        n3 = np.array([0.0, nrm[0], nrm[1]])
        t3 = np.array([0.0, -nrm[1], nrm[0]])
        s = cen + n3 * (e["r"] - 0.0005)
        plates.extend(ellipsoid_mesh(s, (0.021, 0.0042, 0.011), 12, rotation=_rot_x(phi)))
        for j in range(3):
            a = j * 2.1 + 0.4
            p = s - n3 * 0.0035 + np.array([1, 0, 0]) * 0.016 * math.cos(a) + t3 * 0.010 * math.sin(a)
            nuclei.extend(_nucleus(p, phi, (0.0065, 0.0030, 0.0045), 6))
        top = s + n3 * 0.0045
        path = smooth_path(np.array([trunk[-1], trunk[-1] + (top - trunk[-1]) * 0.5 + n3 * 0.03 +
                                     np.array([0.01, 0, 0]), top + n3 * 0.012 - np.array([0.012, 0, 0]), top]), 24)
        nerve.extend(tube(path, np.linspace(0.0050, 0.0030, len(path)), 8))
        v = Volume(s - 0.035, s + 0.035, 0.0008)
        shapes = [round_cone(top, s + n3 * 0.0026, 0.0028, 0.0022)]
        hub = s + n3 * 0.0026
        for b in range(5):
            a = b * 2 * math.pi / 5 + rng.uniform(-0.3, 0.3)
            d = np.array([1, 0, 0]) * 0.015 * math.cos(a) + t3 * 0.0085 * math.sin(a)
            mid = hub + d * 0.55 + t3 * 0.003 * math.cos(a * 3)
            end = hub + d - n3 * 0.0006
            shapes += [round_cone(hub, mid, 0.0020, 0.0017), round_cone(mid, end, 0.0017, 0.0015),
                       sphere(end, 0.0030), sphere(mid, 0.0024)]
            tw = mid + (np.array([1, 0, 0]) * math.sin(a) - t3 * math.cos(a)) * 0.006
            shapes += [round_cone(mid, tw, 0.0014, 0.0012), sphere(tw, 0.0022)]
        v.add_all(shapes, "smooth", 0.0016)
        terms.extend(v.mesh(0.6))
    return [
        mesh_part(nerve, "Motor nerve branch", "Nerves & vessels", "#f0cf45", MUSCLE_DESC["nerve"], "nerve",
                  rank=2.5),
        mesh_part(terms, "Neuromuscular junction", "Nerves & vessels", "#f7dd6a", MUSCLE_DESC["nmj"], "nerve",
                  rank=2.6, detail=(0.04, 0.0, 0.0, 0)),
        mesh_part(plates, "Motor end plate", "Nerves & vessels", "#c77f9a", MUSCLE_DESC["endplate"], "muscle",
                  rank=2.55, detail=(0.04, 0.0, 0.0, 0)),
    ]


def _spindle(cents, hero_f, world, R_f, rng):
    """A muscle spindle lying in the perimysium on top of the fascicles, just past the end of the epimysium."""
    # in the groove between two outer fascicles, round the side from the hero fascicle
    ang = np.sort([math.atan2(c[1], c[0]) for c in cents if np.hypot(*c) > 0.36])
    mids = (ang + np.roll(ang, -1) + np.r_[np.zeros(len(ang) - 1), 2 * math.pi]) / 2
    want = math.atan2(cents[hero_f][1], cents[hero_f][0]) + 0.8
    phi_s = float(mids[np.argmin(np.abs(np.angle(np.exp(1j * (mids - want)))))])
    a0 = world(np.array([0.11]), R_f + 0.012, phi_s)[0]
    a1 = world(np.array([0.45]), R_f + 0.012, phi_s)[0]
    mid = (a0 + a1) / 2
    r_eq = 0.034
    cap = Volume(np.minimum(a0, a1) - 0.06, np.maximum(a0, a1) + 0.06, 0.0024)
    cap.add(round_cone(a0, mid, 0.009, r_eq), "smooth", 0.03)
    cap.add(round_cone(mid, a1, r_eq, 0.009), "smooth", 0.03)
    shell = cap.copy(np.maximum(cap.d, -(cap.d + 0.0034)))
    axis = (a1 - a0) / np.linalg.norm(a1 - a0)
    up = np.array([0.0, math.cos(phi_s), math.sin(phi_s)])
    side = np.cross(axis, up)

    def prof(t):
        return 0.30 + 0.70 * np.sin(np.clip(t, 0, 1) * math.pi) ** 0.8

    intra, inuc, ia = Mesh(), Mesh(), Mesh()
    fibres = [(0.0115 * math.cos(a), 0.0115 * math.sin(a), 0.0058, True) for a in (0.4, 0.4 + math.pi)]
    fibres += [(0.0125 * math.cos(a), 0.0125 * math.sin(a), 0.0040, False) for a in (1.5, 2.4, 4.5, 5.5)]
    fibres += [(0.0, 0.0, 0.0040, False)]
    for k, (ou, ov, r, bag) in enumerate(fibres):
        t = np.linspace(-0.05, 1.05, 60) if bag else np.linspace(0.08, 0.92, 50)
        off = (up * ou + side * ov)[None, :] * prof(t)[:, None]
        line = a0 + np.outer(t, a1 - a0) + off
        eq = np.exp(-((t - 0.5) / 0.07) ** 2)
        rad = r * (1.0 + (0.45 if bag else 0.0) * eq) * np.clip(np.minimum(t + 0.05, 1.05 - t) / 0.12, 0.35, 1.0)
        intra.extend(tube(line, rad, 10))
        centre_eq = mid + (up * ou + side * ov) * prof(0.5)
        if bag:
            for j in range(12):
                tt = 0.5 + rng.uniform(-0.05, 0.05)
                a = rng.uniform(0, 2 * math.pi)
                cc = a0 + (a1 - a0) * tt + (up * ou + side * ov) * prof(tt)
                d = up * math.cos(a) + side * math.sin(a)
                inuc.extend(ellipsoid_mesh(cc + d * r * 1.05, (0.0034, 0.0030, 0.0030), 6))
        else:
            for j in range(7):
                tt = 0.5 + (j - 3) * 0.024
                cc = a0 + (a1 - a0) * tt + (up * ou + side * ov) * prof(tt)
                d = (up * ou + side * ov)
                d = d / max(np.linalg.norm(d), 1e-6) if np.linalg.norm(d) > 1e-6 else up
                inuc.extend(ellipsoid_mesh(cc + d * r * 0.7, (0.0045, 0.0026, 0.0026), 6))
        # annulospiral ending coiled round the equator
        n_t = 5
        s = np.linspace(-0.045, 0.045, 90)
        ang = s / 0.09 * n_t * 2 * math.pi + k
        rr = r * (1.0 + (0.45 if bag else 0.0) * np.exp(-(s / (0.07 * 0.42)) ** 2)) + 0.0014
        base = centre_eq[None, :] + np.outer(s, axis)
        coil = base + (up[None, :] * np.cos(ang)[:, None] + side[None, :] * np.sin(ang)[:, None]) * rr[:, None]
        ia.extend(tube(coil, 0.0011, 5))
        root = mid + up * (r_eq + 0.012) - axis * 0.01
        ia.extend(tube(smooth_path(np.array([coil[45], (coil[45] + root) / 2 + up * 0.004, root]), 14), 0.0012, 5))
    aff = smooth_path(np.array([mid + up * (r_eq + 0.012) - axis * 0.01, mid + up * 0.05 - axis * 0.06,
                                world(np.array([0.19]), R_f + 0.06, phi_s)[0],
                                world(np.array([0.08]), R_f + 0.035, phi_s)[0]]), 30)
    ia.extend(tube(aff, 0.0042, 10))
    return [
        sdf_part(shell, "Muscle spindle capsule", "Muscle spindle", "#e6e2d6", MUSCLE_DESC["spindle"], "fascia",
                 smooth=0.6, rank=1.8, alpha=0.38, detail=(0.04, 0.0, 0.0, 0)),
        mesh_part(intra, "Intrafusal fibres", "Muscle spindle", "#d9807a", MUSCLE_DESC["intrafusal"], "muscle",
                  rank=1.8, detail=(0.05, 45.0, 0.0, 1)),
        mesh_part(inuc, "Nuclear bag & chain nuclei", "Muscle spindle", "#4a3b98", MUSCLE_DESC["intrafusal_nuclei"],
                  "nucleus", rank=1.85, label=False, detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(ia, "Annulospiral (Ia) sensory ending", "Muscle spindle", "#f2c230", MUSCLE_DESC["ia"], "nerve",
                  rank=1.9, detail=(0.03, 0.0, 0.0, 0)),
    ]


# ==================================================================================================== nerve
NERVE_DESC = {
    "epineurium": "Epineurium: the dense irregular connective tissue that binds the fascicles into a nerve - a tough "
                  "outer coat plus looser interfascicular epineurium between the fascicles, carrying fat and the "
                  "vasa nervorum. It can be half the cross-section of a large nerve, cushions the fascicles against "
                  "compression, and is the layer sutured in an epineurial nerve repair.",
    "collagen": "Collagen bundles of the outer epineurium: type I collagen running mostly along the nerve, gently "
                "crimped, so a nerve can lengthen a few per cent as a joint moves before its fascicles are loaded. "
                "Beyond roughly 8–10 % stretch the intraneural blood flow and conduction fail.",
    "fat": "Epineurial fat: lobules of adipocytes in the interfascicular epineurium that cushion the fascicles. "
           "Nerves with little fat and a superficial course (ulnar at the elbow, common fibular at the fibular neck) "
           "are the ones most prone to compression palsy.",
    "arteriole": "Vasa nervorum (arterioles): a longitudinal anastomosing plexus in the epineurium, fed segmentally "
                 "by nearby arteries, whose branches pierce the perineurium obliquely to supply the endoneurial "
                 "capillaries. Their occlusion in diabetes or vasculitis causes ischaemic mononeuropathy and "
                 "mononeuritis multiplex (e.g. a painful third-nerve palsy that spares the pupil).",
    "venule": "Vasa nervorum (venules): epineurial veins draining the endoneurial capillaries back through the "
              "perineurium. Their oblique course through it is easily pinched when endoneurial pressure rises - "
              "one reason compression neuropathies (carpal tunnel) become ischaemic.",
    "perineurium": "Perineurium: concentric lamellae of flattened perineurial cells (each layer with a basal lamina "
                   "on both sides, joined by tight junctions) with thin collagen between them. It wraps every "
                   "fascicle, gives it tensile strength, and with the endoneurial capillaries forms the blood–nerve "
                   "barrier. Fascicles divide and merge along a nerve, so their number changes from level to level; "
                   "a perineurial repair sutures fascicle to fascicle.",
    "endoneurium": "Endoneurium: loose connective tissue (fine collagen, fibroblasts, a few mast cells and "
                   "macrophages) between the individual nerve fibres inside a fascicle, bathed in endoneurial fluid. "
                   "After an axon is cut, its endoneurial tube with the Schwann cells inside (bands of Büngner) "
                   "guides regrowth at about 1–3 mm per day - which is why axonotmesis recovers and neurotmesis "
                   "needs repair.",
    "capillary": "Endoneurial capillaries: continuous, non-fenestrated capillaries whose tight junctions form the "
                 "vascular half of the blood–nerve barrier.",
    "myelin": "Myelin sheaths (internodes): each internode is the compacted spiral membrane of one Schwann cell - "
              "in the CNS one oligodendrocyte myelinates many axons. Myelin (P0, PMP22, MBP) insulates the axon so "
              "the impulse jumps from node to node. In life internodes are ~100 times the fibre diameter "
              "(0.2–1.5 mm); here they are drawn far shorter so several nodes fit in the block. In section each "
              "myelinated fibre is a pale ring round a central axon. Attacked in Guillain–Barré syndrome and CIDP; "
              "PMP22 duplication causes Charcot–Marie–Tooth disease type 1A.",
    "axon": "Myelinated axons: the conducting processes of motor neurons, large sensory neurons (Aα/Aβ) and Aδ pain "
            "and temperature fibres, 1–20 µm across; the axon is about 60–70 % of the fibre diameter (g-ratio). "
            "Conduction velocity rises with diameter, up to about 120 m/s. Cut axons degenerate distally "
            "(Wallerian degeneration).",
    "node": "Nodes of Ranvier: ~1 µm gaps between successive Schwann cells where the axon is bare and packed with "
            "voltage-gated Na⁺ channels (Nav1.6), with K⁺ channels hidden under the paranodal myelin. The action "
            "potential is regenerated only here - saltatory conduction. Antibodies to nodal gangliosides (GM1) "
            "cause the acute motor axonal form of Guillain–Barré.",
    "schwann": "Schwann cell nuclei: one elongated nucleus per internode, in the thin collar of cytoplasm outside "
               "the myelin; the Remak Schwann cells have their own. Schwann cells come from the neural crest and "
               "give rise to schwannomas (bilateral vestibular schwannomas in neurofibromatosis type 2).",
    "remak": "Remak (non-myelinating) Schwann cells: each holds a bundle of several thin axons, every one sunk in "
             "its own trough of Schwann cell cytoplasm with no myelin - a Remak bundle.",
    "c_fibres": "Unmyelinated axons (C fibres): 0.2–1.5 µm, conducting at 0.5–2 m/s - slow burning pain, "
                "temperature, itch and postganglionic sympathetic fibres. They outnumber the myelinated fibres in "
                "most cutaneous nerves and are lost early in small-fibre neuropathy (diabetes, amyloid).",
}

N_X_EPI = 0.14          # the epineurium stops here
N_TWIST = 0.35          # the fascicles spiral this far round the nerve over the block
N_RING = (0.122, 0.096, 0.128, 0.102, 0.114, 0.088)


def _nerve_layout():
    """Fascicles as (angle, distance from the axis, radius): a large central one inside a ring of six."""
    rho = 0.39
    w = [2 * math.asin((r + 0.045) / rho) for r in N_RING]
    gap = (2 * math.pi - sum(w)) / len(w)
    fas, gaps = [(0.0, 0.0, 0.155)], []
    a = 0.25
    for r, wi in zip(N_RING, w):
        a += wi / 2
        fas.append((a, rho, r))
        a += wi / 2 + gap
        gaps.append(a - gap / 2)
    return fas, gaps


def _surface_bundles(sw, r_fn, count, seed, pitch=0.3, crimp=0.012, r_range=(0.006, 0.010), depth=0.0045):
    """Collagen bundles lying in the surface of a sheath, mostly along it and finely crimped: low ridges, not a
    felt standing off the surface."""
    rng = np.random.default_rng(seed)
    m = Mesh()
    s = np.linspace(0.0, 1.0, 64)
    for _ in range(count):
        th0 = rng.uniform(0, 2 * math.pi)
        ph = rng.uniform(0, 2 * math.pi)
        a, b = sorted(rng.uniform(0, 1, 2))
        if b - a < 0.35:
            a, b = max(0.0, a - 0.2), min(1.0, b + 0.2)
        ss = a + (b - a) * s
        theta = th0 + rng.uniform(-pitch, pitch) * ss + crimp * np.sin(ss * rng.uniform(22, 30) + ph)
        r = r_fn(theta, ss) - depth
        taper = 0.35 + 0.65 * np.sin(np.linspace(0, math.pi, len(s))) ** 0.5
        m.extend(tube(sw.curve(ss, theta, r), rng.uniform(*r_range) * taper, 6))
    return m


def build_nerve():
    from shapely.geometry import Polygon
    parts = []
    rng = np.random.default_rng(21)
    path = curved_path(2.0, bend=(0.075, -0.055), wobble=0.038, freq=1.0, seed=5)
    xs_ref = np.linspace(-1.0, 1.0, 400)
    oy = np.interp(xs_ref, path[:, 0], path[:, 1])
    oz = np.interp(xs_ref, path[:, 0], path[:, 2])

    def by(t):
        return np.interp(t, xs_ref, oy)

    def bz(t):
        return np.interp(t, xs_ref, oz)

    def tw(t):
        return N_TWIST * (np.asarray(t, float) + 1.0) / 2.0

    fas, gaps = _nerve_layout()
    wob = [rng.uniform(0, 2 * math.pi, 2) for _ in fas]

    def place(k, U, V, T):
        """Reference-section coordinates (U, V) at station T to world: the whole section turns slowly (the
        fascicles spiral round the nerve), rides on the bent axis, and fascicle k wobbles a little on its own."""
        a = tw(T)
        c, s = np.cos(a), np.sin(a)
        wy = wz = 0.0
        if k is not None:
            wy = 0.004 * np.sin(T * 2.2 + wob[k][0])
            wz = 0.004 * np.cos(T * 1.8 + wob[k][1])
        return T, U * c - V * s + by(T) + wy, U * s + V * c + bz(T) + wz

    def ref_c(k):
        phi, rho, _ = fas[k]
        return np.array([rho * math.cos(phi), rho * math.sin(phi)])

    # ---------------------------------------------------------------- radius functions of (angle, x)
    def epi_r(th, x):
        S = (x + 1.0) / 2.0
        return 0.645 + lobed(6, 0.020, 0.7)(th, S) + surf_noise(0.014, 3.0, 2.4, 5)(th, S) + \
            surf_noise(0.004, 17.0, 9.0, 6)(th, S)

    def core_r(k, th, x):
        fr = fas[k][2]
        S = (x + 1.0) / 2.0
        return fr + lobed(5, fr * 0.02, 0.9)(th, S) + surf_noise(fr * 0.015, 3.4, 3.0, 30 + k)(th, S)

    LAM = [(0.0040, 0.0078), (0.0112, 0.0150), (0.0184, 0.0222)]      # perineurial lamellae: (inner, outer) offset
    hero_k = 1 + int(np.argmin([abs(math.remainder(f[0] + float(tw(0.5)) - math.atan2(0.85, 0.52), 2 * math.pi))
                                for f in fas[1:]]))
    x_f = [0.62] + [0.44 + 0.10 * rng.random() for _ in fas[1:]]
    x_f[hero_k] = 0.46

    # ---------------------------------------------------------------- epineurium, with a hole for each fascicle
    def ext_map(U, V, T):
        th = np.arctan2(V, U)
        r = epi_r(th, T)
        return place(None, r * np.cos(th), r * np.sin(th), T)

    def hole_map(k, pad):
        cu, cv = ref_c(k)

        def f(U, V, T):
            th = np.arctan2(V - cv, U - cu)
            r = core_r(k, th, T) + pad
            return place(k, cu + r * np.cos(th), cv + r * np.sin(th), T)
        return f

    holes = [ref_c(k) + _circle_poly(fas[k][2] + 0.03, 64) for k in range(len(fas))]
    maps = [ext_map] + [hole_map(k, LAM[-1][1] + 0.003) for k in range(len(fas))]
    epi = _extrude_region(Polygon(_circle_poly(0.64, 200), [h[::-1] for h in holes]),
                          np.linspace(-1.0, N_X_EPI, 34), lambda k: maps[k])
    parts.append(mesh_part(epi, "Epineurium", "Connective tissue", "#e8dcc0", NERVE_DESC["epineurium"], "fascia",
                           bulk=True, rank=0.2, detail=(0.10, 50.0, 0.15, 1)))
    trunk = _shear_sweep(np.linspace(-1.0, N_X_EPI, 90), by, bz, 8)

    def epi_world(T, S):
        x = -1.0 + S * (N_X_EPI + 1.0)
        return epi_r(T - tw(x), x)
    parts.append(mesh_part(_surface_bundles(trunk, epi_world, 90, 90), "Epineurial collagen bundles",
                           "Connective tissue", "#dcc79c", NERVE_DESC["collagen"], "ligament", rank=0.3,
                           detail=(0.10, 45.0, 0.12, 1)))

    # ---------------------------------------------------------------- fascicles
    peri, endo, myelin, axons, nodes, schwann, remak_s, remak_a, ecap = (Mesh() for _ in range(9))
    for k, (phi, rho, fr) in enumerate(fas):
        xf = x_f[k]
        cu, cv = ref_c(k)

        def centre(x, k=k):
            _, y, z = place(k, np.full_like(x, cu), np.full_like(x, cv), x)
            return y, z
        for j, (a, b) in enumerate(LAM):
            x_end = xf - 0.04 - 0.026 * j
            xs = np.linspace(-1.0, x_end, 20)
            sw = _shear_sweep(xs, lambda x: centre(x)[0], lambda x: centre(x)[1], 60)

            def rad(T, S, pad, x0=-1.0, x1=x_end, k=k):
                x = x0 + S * (x1 - x0)
                return core_r(k, T - tw(x), x) + pad
            peri.extend(sw.shell(lambda T, S, a=a: rad(T, S, a), lambda T, S, b=b: rad(T, S, b)))

        # fibres packed in the fascicle: myelinated fibres, Remak bundles and a few capillaries
        # fibres sit shoulder to shoulder, as in a section: a jittered hexagonal packing, each fibre as large as
        # its neighbours allow
        pts = hex_points((-fr, -fr), (fr, fr), 0.0262, jitter=0.16, seed=100 + k)
        pts = pts[np.hypot(pts[:, 0], pts[:, 1]) < fr - 0.021]
        from scipy.spatial import cKDTree
        nn = cKDTree(pts).query(pts, k=2)[0][:, 1]
        kinds = []
        for p in pts:
            u = rng.random()
            kinds.append("cap" if u < 0.03 and sum(q == "cap" for q in kinds) < 3 else
                         "remak" if u < 0.27 else "myelin")
        # the fibres of the hero fascicle nearest the viewer run on past its end
        chosen = {}
        if k == hero_k:
            a = -float(tw(xf))
            view = np.array([0.52 * math.cos(a) - 0.85 * math.sin(a), 0.52 * math.sin(a) + 0.85 * math.cos(a)])
            out = np.array([cu, cv]) / np.hypot(cu, cv)
            score = pts @ (view + out)
            order = [int(i) for i in np.argsort(score)[::-1] if kinds[int(i)] != "cap"]
            my = [i for i in order if kinds[i] == "myelin"][:5]
            rk = [i for i in order if kinds[i] == "remak"][:2]
            for n, i in enumerate(sorted(my + rk, key=lambda i: -score[i])):
                d = pts[i] / max(np.hypot(*pts[i]), 1e-6) * 0.5 + out
                chosen[i] = (d / np.hypot(*d), 0.010 + 0.009 * n, xf + 0.34 + rng.uniform(0.0, 0.17))

        fib_holes = []
        for i, (p, kind) in enumerate(zip(pts, kinds)):
            hero = chosen.get(i)
            x_hi = hero[2] if hero else xf
            # small parts are only made where they can be seen: along fibres the cut-away opens lengthwise, and
            # near the transverse cut, the end face and beyond
            y_cut = float(place(k, np.array([cu + p[0]]), np.array([cv + p[1]]), np.array([-0.5]))[1][0] - by(-0.5))
            x_vis = -1.0 if abs(y_cut) < 0.04 else -0.16

            def fpath(xs, p=p, hero=hero):
                q = np.broadcast_to(np.array([cu, cv]) + p, (len(xs), 2)).copy()
                if hero:
                    b = _smooth01((xs - xf + 0.01) / 0.22)[:, None]
                    q = q + p[None, :] * 0.7 * b + hero[0][None, :] * hero[1] * b
                return np.stack(place(k, q[:, 0], q[:, 1], xs), -1)
            if kind == "cap":
                xs = np.linspace(-1.002, xf + 0.003, 24)
                ecap.extend(tube(fpath(xs), 0.0042, 8))
                continue
            if kind == "remak":
                r_s = min(0.0098, nn[i] / 2 - 0.0012)
                fib_holes.append((np.array([cu, cv]) + p, r_s + 0.0008))
                xs = np.linspace(-1.0, x_hi, 16 if not hero else 50)
                ph = rng.uniform(0, 2 * math.pi)
                line = fpath(xs)
                remak_s.extend(tube(line, r_s * (1.0 + 0.05 * np.sin(xs * 23 + ph)), 9))
                n_ax = int(rng.integers(4, 7))
                for j in range(n_ax):
                    a = j * 2 * math.pi / n_ax + rng.uniform(-0.2, 0.2) + tw(xs)
                    off = np.stack([np.zeros_like(xs), 0.0074 * np.cos(a), 0.0074 * np.sin(a)], -1)
                    xa = np.r_[xs[:-1], x_hi + 0.004]
                    remak_a.extend(tube(fpath(xa) + off, rng.uniform(0.0020, 0.0026), 5))
                for x in np.arange(x_vis + rng.uniform(0, 0.3), x_hi, 0.32):
                    a = rng.uniform(0, 2 * math.pi)
                    c3 = fpath(np.array([x]))[0]
                    n = _nucleus(c3 + np.array([0, math.cos(a), math.sin(a)]) * (r_s + 0.0004), a,
                                 (0.022, 0.0028, 0.0060))
                    schwann.extend(_press(_press(n, x_hi, 1), -1.0, -1))
                continue
            # a mix of large (A alpha/beta) and small (A delta) myelinated fibres
            r_o = rng.uniform(0.0105, 0.0140) if rng.random() < 0.5 else rng.uniform(0.0068, 0.0092)
            r_o = min(r_o, nn[i] / 2 - 0.0012)
            if hero:
                r_o = max(r_o, 0.0115)
            r_a = r_o * rng.uniform(0.58, 0.68)
            fib_holes.append((np.array([cu, cv]) + p, r_o + 0.0008))
            xs = np.linspace(-1.003, x_hi + (0.014 if hero else 0.003), 18 if not hero else 70)
            axons.extend(tube(fpath(xs), r_a, 8))
            L = 20.0 * r_o
            gap = 0.008
            x_n = -1.0 - rng.uniform(0, L)
            if x_vis > -1.0:
                # where nothing can see it, one continuous sheath stands in for the internodes
                x_n = x_vis - rng.uniform(0, L)
                myelin.extend(tube(fpath(np.linspace(-1.0, x_n + gap / 2, 12)), r_o, 10))
            prof = np.array([0.0, 0.05, 0.15, 0.5, 0.85, 0.95, 1.0]) if not hero else \
                np.array([0.0, 0.025, 0.06, 0.12, 0.3, 0.5, 0.7, 0.88, 0.94, 0.975, 1.0])
            while x_n < x_hi:
                a, b = x_n + gap / 2, x_n + L - gap / 2
                lo, hi = max(a, -1.0), min(b, x_hi)
                if hi - lo > 0.02:
                    xs_i = lo + (hi - lo) * prof
                    tp = np.ones_like(xs_i)
                    if a >= -1.0:
                        tp *= _smooth01((xs_i - a) / (0.07 * L))
                    if b <= x_hi:
                        tp *= _smooth01((b - xs_i) / (0.07 * L))
                    r_out = r_a * 1.04 + (r_o - r_a * 1.04) * tp
                    # a solid sheath: the axon runs through it and stands a hair proud of every end face
                    myelin.extend(tube(fpath(xs_i), r_out, 10))
                    mid = (a + b) / 2
                    if lo < mid < hi and mid > x_vis:
                        ang = rng.uniform(0, 2 * math.pi)
                        c3 = fpath(np.array([mid]))[0]
                        schwann.extend(_nucleus(c3 + np.array([0, math.cos(ang), math.sin(ang)]) * (r_o + 0.0006),
                                                ang, (0.030, 0.0026, 0.0062)))
                if x_vis < b + gap / 2 < x_hi:
                    xn = np.array([b - 0.003, min(b + gap + 0.003, x_hi + 0.0015)])
                    nodes.extend(tube(fpath(xn), r_a * 1.22, 10))
                x_n += L

        # endoneurium: the fascicle core with a hole for every fibre
        ring = hole_map(k, 0.0)
        from shapely.ops import unary_union
        region = Polygon(np.array([cu, cv]) + _circle_poly(fr + 0.002, 72)).difference(
            unary_union([Polygon(c + _circle_poly((r + 0.0002) / 0.951, 10)) for c, r in fib_holes]))

        def fib_map(U, V, T, k=k):
            return place(k, U, V, T)
        for piece in _polys(region):
            endo.extend(_extrude_region(piece, np.linspace(-1.0, xf, 14), lambda j, ring=ring: ring if j == 0
                                        else fib_map))

    parts += [
        mesh_part(peri, "Perineurium", "Connective tissue", "#cf9f86", NERVE_DESC["perineurium"], "ligament",
                  rank=0.5, detail=(0.08, 120.0, 0.5, 4)),
        mesh_part(endo, "Endoneurium", "Connective tissue", "#d9aaa3", NERVE_DESC["endoneurium"], "fascia",
                  bulk=True, rank=0.4, detail=(0.08, 90.0, 0.2, 1)),
        mesh_part(myelin, "Myelin sheaths (internodes)", "Nerve fibres", "#f7f3ea", NERVE_DESC["myelin"],
                  "white_matter", rank=1, detail=(0.04, 0.0, 0.0, 1)),
        mesh_part(axons, "Axons", "Nerve fibres", "#e2a23e", NERVE_DESC["axon"], "nerve", rank=1,
                  detail=(0.05, 0.0, 0.0, 1)),
        mesh_part(nodes, "Nodes of Ranvier", "Nerve fibres", "#46a9d6", NERVE_DESC["node"], "nerve", rank=1.1,
                  detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(schwann, "Schwann cell nuclei", "Nerve fibres", "#4b56a8", NERVE_DESC["schwann"], "nucleus",
                  rank=1.1, detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(remak_s, "Remak Schwann cells", "Nerve fibres", "#c9b3d4", NERVE_DESC["remak"], "fascia",
                  rank=1, detail=(0.05, 80.0, 0.3, 1)),
        mesh_part(remak_a, "Unmyelinated axons (C fibres)", "Nerve fibres", "#d98a3c", NERVE_DESC["c_fibres"],
                  "nerve", rank=1.05, detail=(0.04, 0.0, 0.0, 1)),
        mesh_part(ecap, "Endoneurial capillaries", "Vessels", "#d8433b", NERVE_DESC["capillary"], "artery",
                  rank=0.6),
    ]

    # ---------------------------------------------------------------- vessels and fat of the epineurium
    art, ven, fat = Mesh(), Mesh(), Mesh()

    def free(q, r):
        if np.hypot(*q) + r > 0.615:
            return False
        return all(np.hypot(*(q - ref_c(k))) > fas[k][2] + 0.032 + r for k in range(len(fas)))
    for g, a in enumerate(gaps):
        # an arteriole and a venule side by side deep in each gap between ring fascicles, cut at the step
        for kind, (rho, da, r) in (("a", (0.335, -0.035, 0.013)), ("v", (0.37, 0.05, 0.017))):
            q = np.array([rho * math.cos(a + da), rho * math.sin(a + da)])
            if not free(q, r * 0.6):
                continue
            xs = np.linspace(-1.002, N_X_EPI + 0.002, 36)
            wig = 0.006 * np.sin(xs * 4 + g)
            line = np.stack(place(None, q[0] + wig, q[1] - wig, xs), -1)
            (art if kind == "a" else ven).extend(_press(_press(tube(line, r, 14), N_X_EPI, 1), -1.0, -1))
        # lobules of fat further out in the gap: adipocytes packed on a jittered lattice, trimmed to the space
        centres, radii = [], []
        for x0 in np.arange(-1.0 + rng.uniform(0, 0.2), N_X_EPI + 0.1, 0.5):
            half = rng.uniform(0.13, 0.19)
            for x in np.arange(x0 - half, x0 + half, 0.056):
                for rho in np.arange(0.43, 0.61, 0.05):
                    for da in np.arange(-0.21, 0.22, 0.06):
                        rr = rng.uniform(0.022, 0.030)
                        q = np.array([math.cos(a + da), math.sin(a + da)]) * rho + rng.normal(0, 0.006, 2)
                        xx = x + rng.normal(0, 0.008)
                        if free(q, rr * 0.9) and xx > -1.04:
                            centres.append((xx, q[0], q[1]))
                            radii.append(rr)
        if centres:
            cw = np.array([np.array(place(None, c[1], c[2], c[0]), float) for c in centres])
            v = Volume(cw.min(0) - 0.05, cw.max(0) + 0.05, 0.011)
            for c, rr in zip(cw, radii):
                v.add(ellipsoid(c, (rr * 1.25, rr, rr)), "smooth", 0.006)
            fat.extend(_press(_press(v.mesh(0.7), N_X_EPI, 1), -1.0, -1))
    # the surface plexus: longitudinal vessels half sunk in the outer epineurium, with branches round it
    for j, (th0, kind) in enumerate(((0.6, "a"), (0.75, "v"), (3.3, "a"), (3.45, "v"))):
        s = np.linspace(0.0, 1.0, 60)
        x = -1.0 + s * (N_X_EPI + 1.0)
        th = th0 + 0.12 * np.sin(s * 5 + j)
        r = epi_r(th, x) - 0.004
        rad = 0.011 if kind == "a" else 0.014
        mesh = tube(np.stack(place(None, r * np.cos(th), r * np.sin(th), x), -1), rad, 12)
        for b in range(3):
            i = int(rng.integers(6, 50))
            n = 18
            bt = th[i] + np.linspace(0, rng.choice([-1, 1]) * rng.uniform(0.5, 0.9), n)
            bx = x[i] + np.linspace(0, rng.uniform(0.08, 0.18), n)
            br = epi_r(bt, bx) - 0.003
            mesh.extend(tube(np.stack(place(None, br * np.cos(bt), br * np.sin(bt), bx), -1),
                             np.linspace(rad * 0.6, rad * 0.3, n), 8))
        (art if kind == "a" else ven).extend(_press(_press(mesh, N_X_EPI, 1), -1.0, -1))
    parts += [
        mesh_part(fat, "Epineurial fat", "Connective tissue", "#f2d77f", NERVE_DESC["fat"], "fat", rank=0.1,
                  detail=(0.05, 22.0, 0.08, 0)),
        mesh_part(art, "Vasa nervorum (arterioles)", "Vessels", "#cf3a31", NERVE_DESC["arteriole"], "artery",
                  rank=0.1),
        mesh_part(ven, "Vasa nervorum (venules)", "Vessels", "#4f5fae", NERVE_DESC["venule"], "vein", rank=0.1),
    ]
    return _finish(parts, 21, 0.004, 12.0, 2.5, 0.0022, 46.0)

