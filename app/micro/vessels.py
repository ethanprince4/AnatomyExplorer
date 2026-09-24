"""Blood vessel walls: muscular artery, elastic artery (aorta) and a vein with a valve.

Nothing here is a cylinder. Every layer is swept around a curved centreline whose calibre varies along its length,
and the wall is thrown into the longitudinal folds a contracted vessel actually shows - so the lumen is star-shaped
in section, not round. On top of that each surface carries the relief of its own cells: endothelium as cobblestones
stretched along the flow, smooth muscle as spindles wrapped around the circumference, adventitia as a felt of
collagen bundles built from real geometry rather than a smooth sleeve.
"""
import math

import numpy as np

from .base import Part
from .cells import frame_from_normal, orient_outward
from .geometry import Mesh, tube
from .kit import Volume, ellipsoid, mesh_part, sdf_part
from .organic import Sweep, cells_on, curved_path, lobed, noise_field, surf_noise, taper, warp_parts
from .organs import VESSEL

N_THETA, N_S = 264, 116

_COLLAGEN_DESC = ("Wavy bundles of type I collagen with elastic fibres woven between them. They are slack at rest and "
                  "only tighten at high pressure, which is why the adventitia sets the limit of distension and why "
                  "it is the layer that holds a suture.")
_FAT_DESC = ("Adipocytes of the perivascular fat pad. It is not inert packing: perivascular adipose releases "
             "adipokines that relax healthy vessels, and in obesity becomes inflamed and pro-atherogenic.")
_VENULE_DESC = ("Venules of the vasa vasorum: thin-walled vessels running beside the small arteries of the adventitia, "
                "collecting blood from the capillaries of the outer wall and draining it to neighbouring veins.")


def red_cell(center, normal, radius=0.042, n_theta=22, n_r=10):
    """Biconcave erythrocyte (Evans–Fung profile) as a closed surface of revolution."""
    rho = np.sin(np.linspace(0, math.pi / 2, n_r))
    h = 0.5 * radius * np.sqrt(np.maximum(1 - rho ** 2, 0)) * (0.207 + 2.003 * rho ** 2 - 1.123 * rho ** 4)
    h = np.maximum(h, radius * 0.02)
    th = np.linspace(0, 2 * math.pi, n_theta, endpoint=False)
    prof_r = np.concatenate([rho, rho[::-1][1:]]) * radius
    prof_y = np.concatenate([h, -h[::-1][1:]])
    R, T = np.meshgrid(prof_r, th, indexing="ij")
    Y = np.broadcast_to(prof_y[:, None], R.shape)
    local = np.stack([R * np.cos(T), Y, R * np.sin(T)], -1).reshape(-1, 3)
    m = len(prof_r)
    a = np.arange(m * n_theta).reshape(m, n_theta)
    q0, q1 = a[:-1, :], np.roll(a, -1, axis=1)[:-1, :]
    q3, q2 = a[1:, :], np.roll(a, -1, axis=1)[1:, :]
    idx = np.vstack([np.stack([q0.ravel(), q1.ravel(), q2.ravel()], 1), np.stack([q0.ravel(), q2.ravel(), q3.ravel()], 1)])
    Rm = frame_from_normal(normal)
    return orient_outward(Mesh().add(local @ Rm.T + np.asarray(center), idx))


class Wall:
    """Radii of a vessel wall as fractions of its thickness, with the folds and roughness shared by every layer."""

    def __init__(self, r_lumen, r_outer, fold_lobes, fold_amp, seed, oval=0.0, oval_phase=0.0, damp=1.7,
                 calibre=(1.02, 0.96, 1.0, 1.05, 0.99)):
        self.r0, self.r1 = r_lumen, r_outer
        self.fold = lobed(fold_lobes, 1.0, 0.9)
        self.fold_amp = fold_amp
        self.damp = damp
        self.seed = seed
        self.oval, self.oval_phase = oval, oval_phase
        self.calibre = taper(calibre)

    def __call__(self, f, extra=None, fold_scale=1.0, rough=1.0):
        def g(T, S):
            r = (self.r0 + f * (self.r1 - self.r0)) * self.calibre(T, S)
            if self.oval:
                r = r * (1.0 + self.oval * np.cos(2.0 * T + self.oval_phase) * (1.0 - 0.55 * f))
            r = r + self.fold_amp * fold_scale * max(0.0, 1.0 - f) ** self.damp * self.fold(T, S)
            r = r + rough * (0.006 + 0.020 * f) * surf_noise(1.0, 2.6, 3.1, self.seed + 3)(T, S)
            r = r + rough * 0.0045 * surf_noise(1.0, 21.0, 13.0, self.seed + 9)(T, S)
            if extra is not None:
                r = r + extra(T, S)
            return r
        return g


def _lamellar(sw, wall, f_in, f_out, layers, inner_extra=None, outer_extra=None, gap=0.16):
    """A tunica media built as concentric muscle layers with a thin space of elastin between each pair, so the cut
    face shows the banding a real media has instead of one flat sheet of colour."""
    thin = Sweep(sw.path, 204, 92)
    m = Mesh()
    edges = np.linspace(f_in, f_out, layers + 1)
    band = (edges[1] - edges[0])
    for k in range(layers):
        lo = edges[k] + band * gap * 0.5
        hi = edges[k + 1] - band * gap * 0.5
        e_lo = inner_extra if k == 0 else None
        e_hi = outer_extra if k == layers - 1 else None
        m.extend(thin.shell(wall(lo, e_lo), wall(hi, e_hi)))
    return m


def _collagen(sw, wall, f_in, f_out, count, seed, r_range=(0.010, 0.030), pitch=(-2.4, 2.4), waves=3.0):
    """A felt of wavy collagen bundles wound round the vessel at mixed pitches - what adventitia really looks like."""
    rng = np.random.default_rng(seed)
    m = Mesh()
    n = 46
    s = np.linspace(0.0, 1.0, n)
    lo, hi = wall(f_in), wall(f_out)
    for _ in range(count):
        th0 = rng.uniform(0, 2 * math.pi)
        p = rng.uniform(*pitch)
        ph = rng.uniform(0, 2 * math.pi)
        theta = th0 + p * s + 0.22 * np.sin(waves * math.pi * s + ph)
        u = np.clip(rng.uniform(0.05, 0.95) + 0.16 * np.sin(2.3 * math.pi * s + ph * 1.7), 0.02, 0.98)
        r = lo(theta, s) + u * (hi(theta, s) - lo(theta, s))
        rad = rng.uniform(*r_range)
        prof = rad * (0.55 + 0.45 * np.sin(np.linspace(0, math.pi, n)) ** 0.35)
        m.extend(tube(sw.curve(s, theta, r), prof, 7))
    return m


def _vasa(sw, wall, f_in, f_out, count, seed, radius=0.014, branch=True):
    rng = np.random.default_rng(seed)
    m = Mesh()
    n = 54
    s = np.linspace(0.02, 0.98, n)
    lo, hi = wall(f_in), wall(f_out)
    for k in range(count):
        th0 = rng.uniform(0, 2 * math.pi)
        theta = th0 + rng.uniform(-1.1, 1.1) * s + 0.2 * np.sin(2.2 * math.pi * s + k)
        u = 0.55 + 0.3 * np.sin(1.7 * math.pi * s + k)
        r = lo(theta, s) + u * (hi(theta, s) - lo(theta, s))
        path = sw.curve(s, theta, r)
        m.extend(tube(path, radius * rng.uniform(0.8, 1.25), 10))
        if not branch:
            continue
        for _ in range(rng.integers(2, 4)):
            i = int(rng.integers(6, n - 8))
            bs = s[i] + np.linspace(0, 0.16, 10)
            bt = theta[i] + np.linspace(0, rng.uniform(-0.9, 0.9), 10)
            bu = u[i] + np.linspace(0, rng.uniform(-0.5, 0.45), 10)
            br = lo(bt, bs) + np.clip(bu, 0.02, 0.98) * (hi(bt, bs) - lo(bt, bs))
            m.extend(tube(sw.curve(np.clip(bs, 0, 1), bt, br), np.linspace(radius * 0.6, radius * 0.22, 10), 7))
    return m


def _adipocytes(sw, wall, f, count, seed, radius=0.052):
    """Lobules of fat tucked into the collagen: cells smooth-unioned so they press against each other into
    polyhedra with visible boundaries, the way adipocytes actually pack."""
    rng = np.random.default_rng(seed)
    m = Mesh()
    r_at = wall(f)
    for _ in range(count):
        s0 = rng.uniform(0.08, 0.92)
        t0 = rng.uniform(0, 2 * math.pi)
        base = float(r_at(np.array([t0]), np.array([s0]))[0])
        origin = sw.curve(np.array([s0]), np.array([t0]), np.array([base]))[0]
        n = int(rng.integers(10, 20))
        # cells packed shoulder to shoulder in world space, so they press into one another instead of floating apart
        spread = radius * 1.25
        centres = origin + rng.normal(0, spread, (n, 3)) * np.array([1.35, 1.0, 1.0])
        radii = list(radius * rng.uniform(0.72, 1.22, n))
        lo = centres.min(0) - max(radii) - 0.03
        hi = centres.max(0) + max(radii) + 0.03
        v = Volume(lo, hi, 0.0055)
        for c, rr in zip(centres, radii):
            v.add(ellipsoid(c, (rr, rr * rng.uniform(0.82, 1.18), rr * rng.uniform(0.82, 1.18))), "smooth", 0.016)
        v.displace(0.004, 26.0, 2, seed=int(rng.integers(1, 9999)))
        m.extend(v.mesh(0.7))
    return m


def _blood(sw, wall, parts, rng, n_rbc=110):
    """Erythrocytes tumbling down the (curved, folded) lumen, and one leukocyte rolling on the endothelium."""
    rbc = Mesh()
    r_lum = wall(0.0)
    placed = []
    for _ in range(n_rbc * 7):
        if len(placed) >= n_rbc:
            break
        s = np.array([rng.uniform(0.03, 0.97)])
        th = np.array([rng.uniform(0, 2 * math.pi)])
        wallr = float(r_lum(th, s)[0])
        r = np.array([wallr * math.sqrt(rng.uniform(0.0, 0.80))])
        c = sw.curve(s, th, r)[0]
        if placed and np.min(np.linalg.norm(np.array(placed) - c, axis=1)) < 0.072:
            continue
        placed.append(c)
        rbc.extend(red_cell(c, rng.normal(size=3), 0.042))
    parts.append(mesh_part(rbc, "Red blood cells", "Blood", "#c3302a", VESSEL["rbc"], "artery", rank=-1,
                           detail=(0.03, 0.0, 0.0, 0)))
    s = np.array([0.30])
    th = np.array([2.5])
    c = sw.curve(s, th, np.array([float(r_lum(th, s)[0]) - 0.062]))[0]
    lo = c - 0.16
    w = Volume(lo, c + 0.16, 0.0032)
    w.add(ellipsoid(c, (0.075, 0.062, 0.070)))
    for _ in range(46):
        d = rng.normal(size=3)
        d /= np.linalg.norm(d)
        w.add(ellipsoid(c + d * 0.064, (0.014, 0.014, 0.014)), "smooth", 0.011)
    parts.append(sdf_part(w, "Rolling leukocyte", "Blood", "#e9e4f2", VESSEL["wbc"], "lymph", smooth=0.75, rank=-1,
                          detail=(0.05, 60.0, 0.9, 0)))


# ------------------------------------------------------------------------------------------------------ models
def build_vessel(kind="muscular"):
    if kind == "elastic":
        return build_aorta()
    rng = np.random.default_rng({"muscular": 11, "elastic": 22, "vein": 33}[kind])
    parts = []
    if kind == "muscular":
        path = curved_path(2.0, bend=(0.090, -0.060), wobble=0.042, freq=1.1, seed=7)
        sw = Sweep(path, N_THETA, N_S)
        wall = Wall(0.30, 0.80, 9, 0.064, seed=7)
        endo_cells = cells_on(0.050, 0.0230, 41, aspect=2.0, groove=0.20, dome=0.62, r_typ=0.30, length=2.0)
        musc_in = cells_on(0.042, 0.0100, 43, aspect=0.24, groove=0.26, dome=0.55, r_typ=0.36, length=2.0)
        musc_out = cells_on(0.046, 0.0115, 44, aspect=0.22, groove=0.26, dome=0.55, r_typ=0.58, length=2.0)
        crinkle = surf_noise(0.010, 16.0, 7.0, 45)
        spec = [
            ("Endothelium", "Tunica intima", "#e6b3ad", wall(0.0, endo_cells), wall(0.022, endo_cells),
             VESSEL["endothelium"], "artery", 0, (0.06, 170.0, 0.9, 1)),
            ("Subendothelial layer", "Tunica intima", "#dcb9ab", wall(0.024, endo_cells), wall(0.048),
             VESSEL["subendo"], "fascia", 0, (0.1, 90.0, 0.2, 1)),
            ("Internal elastic lamina", "Tunica intima", "#f5e59e", wall(0.050, crinkle),
             wall(0.076, crinkle), VESSEL["iel"], "cartilage", 0.5, (0.03, 0.0, 0.0, 0)),
            ("External elastic lamina", "Tunica media", "#f5e59e", wall(0.566, surf_noise(0.007, 13.0, 6.0, 46)),
             wall(0.592, surf_noise(0.007, 13.0, 6.0, 46)), VESSEL["eel"], "cartilage", 1.5, (0.03, 0.0, 0.0, 0)),
            ("Tunica adventitia", "Tunica adventitia", "#e6c6a3", wall(0.598),
             wall(0.80, surf_noise(0.024, 9.0, 2.4, 47)), VESSEL["adventitia"], "fascia", 2, (0.14, 50.0, 0.18, 1)),
        ]
        # the media is not a slab of muscle: it is a stack of muscle layers with elastin between them, and a cut
        # face has to show those concentric bands
        media = _lamellar(sw, wall, 0.080, 0.560, 6, inner_extra=musc_in, outer_extra=musc_out)
        parts.append(mesh_part(media, "Tunica media (smooth muscle)", "Tunica media", "#b54a44",
                               VESSEL["media_musc"], "muscle", clip=True, rank=1, detail=(0.08, 85.0, 0.55, 4)))
        adv = (0.60, 1.04)
    else:
        path = curved_path(2.0, bend=(-0.085, 0.075), wobble=0.048, freq=1.3, seed=19)
        sw = Sweep(path, N_THETA, N_S)
        wall = Wall(0.42, 0.76, 7, 0.055, seed=19, oval=0.26, oval_phase=0.6, damp=1.2,
                    calibre=(0.98, 1.06, 1.12, 1.0, 0.95))
        endo_cells = cells_on(0.058, 0.0230, 61, aspect=2.2, groove=0.20, dome=0.62, r_typ=0.42, length=2.0)
        musc = cells_on(0.050, 0.0075, 63, aspect=0.25, groove=0.30, dome=0.5, r_typ=0.46, length=2.0)
        spec = [
            ("Endothelium", "Tunica intima", "#e7c3cf", wall(0.0, endo_cells), wall(0.030, endo_cells),
             VESSEL["endothelium"], "vein", 0, (0.06, 170.0, 0.9, 1)),
            ("Tunica adventitia", "Tunica adventitia", "#e2c7ab", wall(0.176),
             wall(0.46, surf_noise(0.020, 7.0, 2.0, 67)), VESSEL["vein_adv"], "fascia", 2, (0.14, 50.0, 0.18, 1)),
        ]
        media = _lamellar(sw, wall, 0.034, 0.170, 3, inner_extra=endo_cells, outer_extra=musc)
        parts.append(mesh_part(media, "Tunica media (smooth muscle)", "Tunica media", "#b86a6a",
                               VESSEL["vein_media"], "muscle", clip=True, rank=1, detail=(0.08, 85.0, 0.5, 4)))
        adv = (0.44, 1.10)
    for name, group, color, rin, rout, desc, cat, rank, detail in spec:
        parts.append(Part(name, group, color, sw.shell(rin, rout), desc, category=cat, clip=True,
                          bulk=group == "Tunica adventitia", rank=rank, detail=detail))

    coll = _collagen(sw, wall, adv[0] + 0.02, adv[1] - 0.06, 300 if kind != "vein" else 330, seed=80,
                     r_range=(0.009, 0.026))
    parts.append(mesh_part(coll, "Adventitial collagen bundles", "Tunica adventitia", "#dcc09a", _COLLAGEN_DESC,
                           "ligament", rank=2.2, detail=(0.12, 45.0, 0.12, 1)))
    parts.append(mesh_part(_vasa(sw, wall, adv[0], adv[1] - 0.10, 7, seed=81,
                                 radius=0.017), "Vasa vasorum", "Tunica adventitia", "#d23d34", VESSEL["vasa"],
                           "artery", rank=2.5))
    parts.append(mesh_part(_vasa(sw, wall, adv[0] + 0.10, adv[1] - 0.04, 4, seed=82, radius=0.008, branch=False),
                           "Nervi vasorum", "Tunica adventitia", "#f0cf45", VESSEL["nervi"], "nerve", rank=2.5))
    parts.append(mesh_part(_adipocytes(sw, wall, adv[1] - 0.20, 9 if kind != "vein" else 11, seed=83, radius=0.040),
                           "Perivascular fat", "Tunica adventitia", "#f0cf6d", _FAT_DESC, "fat", rank=3,
                           detail=(0.05, 22.0, 0.08, 0)))

    if kind == "vein":
        lm = Mesh()
        s = np.linspace(0.0, 1.0, 40)
        lo, hi = wall(0.30), wall(0.86)
        for k in range(22):
            th = np.full(40, k * 2 * math.pi / 22) + 0.10 * np.sin(2.2 * math.pi * s + k)
            u = 0.30 + 0.18 * (k % 3) + 0.08 * np.sin(1.6 * math.pi * s + k)
            r = lo(th, s) + u * (hi(th, s) - lo(th, s))
            lm.extend(tube(sw.curve(s, th, r), rng.uniform(0.018, 0.030), 12))
        parts.append(mesh_part(lm, "Longitudinal smooth muscle bundles", "Tunica adventitia", "#b86a6a",
                               VESSEL["long_muscle"], "muscle", rank=2, detail=(0.08, 85.0, 0.5, 1)))
        parts.append(_valve(sw, wall))
    _blood(sw, wall, parts, rng, 130 if kind != "vein" else 150)
    warp_parts(parts, noise_field((0.016, 0.016, 0.016), 1.15, 3, seed=int(rng.integers(1, 500))))
    return parts


def _valve(sw, wall):
    """Two pocket-shaped cusps whose free edges face downstream, built in the swept frame so they sit in the lumen."""
    lo = sw.path.min(axis=0) - 0.6
    hi = sw.path.max(axis=0) + 0.6
    v = Volume(lo, hi, 0.0055)
    x, y, z = v.axes()
    r_lum = wall(0.0)
    field = np.full(v.shape, 1e3, np.float32)
    for sgn in (1.0, -1.0):
        s_c = 0.66
        i = int(s_c * (sw.n_s - 1))
        c = sw.path[i]
        axis = sw.t[i]
        up = sw.nrm[i] * sgn
        side = sw.bi[i]
        px, py, pz = x - c[0], y - c[1], z - c[2]
        ax = px * axis[0] + py * axis[1] + pz * axis[2]
        uy = px * up[0] + py * up[1] + pz * up[2]
        sz = px * side[0] + py * side[1] + pz * side[2]
        shell = np.sqrt((ax / 0.40) ** 2 + ((uy - 0.34) / 0.33) ** 2 + (sz / 0.48) ** 2) - 1.0
        d = np.abs(shell) * 0.32 - 0.008
        d = np.maximum(d, ax - 0.30)              # free edge, downstream
        d = np.maximum(d, -uy + 0.012)            # one half of the lumen each
        rr = np.sqrt(uy ** 2 + sz ** 2)
        d = np.maximum(d, rr - 0.45)
        field = np.minimum(field, d)
    v.d = field.astype(np.float32)
    return sdf_part(v, "Venous valve cusps", "Tunica intima", "#efd5de", VESSEL["valve"], "serosa", smooth=0.7,
                    rank=0, detail=(0.05, 90.0, 0.2, 0))



# ================================================================================ elastic artery (aortic wall)
# The wall, lumen outwards, as (layer, thickness) in model units. It is drawn far thicker for its lumen than in life
# (about 2 mm of wall round a 25 mm lumen) so the layers can be read, but the lumen is still kept wide - an elastic
# artery is a big, relatively thin-walled conduit with a wall about half its lumen radius here, where a muscular
# artery's wall is nearly as thick as its lumen is wide - and the layers keep their true proportions to one another:
# a thin intima, a media that is most of the wall, and an adventitia under half the media. The internal elastic
# lamina is only a little thicker than a medial lamella: in an elastic artery it is hardly distinct from the first of
# them, unlike the prominent lamina of a muscular artery.
AORTA_LUMEN = 0.62
AORTA_LAYERS = (("endo", 0.008), ("subendo", 0.024), ("iel", 0.008), ("media", 0.182), ("eel", 0.009),
                ("adv", 0.080))
# Telescoped cutaway: where each layer begins, in model units from the open (-x) end. The innermost layer runs
# furthest and every layer outside it is cut back a step more, so each shows its own outer surface; at the +x end
# the whole wall stops in one clean cross-section. The media gets the longest step, since its ridged surface is what
# makes the vessel elastic; the external elastic lamina - in an elastic artery the less distinct of the two laminae,
# little more than the last and slightly thicker lamella - shows a narrow band, but one wide enough to find from
# outside; and the adventitia still covers over half the length with its vessels, nerves and fat.
AORTA_STEPS = {"endo": 0.0, "subendo": 0.14, "iel": 0.30, "media": 0.46, "eel": 0.98, "adv": 1.12}
AORTA_LAMELLAE = 14      # modelled lamellae standing in for the 40-70 of a real aortic media
_GAP = 0.0010            # clearance between neighbouring shells, so no two surfaces ever coincide


def _grid(nt, ns, flip):
    a = np.arange(nt * ns).reshape(nt, ns)
    i0, i1 = a[:, :-1], np.roll(a, -1, axis=0)[:, :-1]
    j0, j1 = a[:, 1:], np.roll(a, -1, axis=0)[:, 1:]
    tri = np.vstack([np.stack([i0.ravel(), i1.ravel(), j0.ravel()], 1),
                     np.stack([i1.ravel(), j1.ravel(), j0.ravel()], 1)])
    return tri[:, ::-1] if flip else tri


def _stations(sw, s0, coarse, fine=None, lip=0.0, s1=1.0):
    """Stations (0..1 along the vessel) for a layer that runs from s0 to s1.

    `coarse` is the spacing, in model units, of a grid every layer shares, so neighbouring shells are sampled at the
    same places; `fine` = (from, to, spacing) packs samples into the stretch of surface that is on show; and the
    rounded shoulder at the near end (length `lip`) gets samples spaced evenly round its curve."""
    L = sw.length
    s = [np.arange(0.0, 1.0, coarse / L)]
    if fine:
        lo, hi, sp = fine
        s.append(np.arange(lo, hi, sp / L))
    s = np.concatenate(s)
    s = s[(s > s0 + max(lip, 0.004) / L) & (s < s1 - 3e-4)]
    head = s0 + lip * (1.0 - np.cos(np.linspace(0.0, math.pi / 2, 8))) / L if lip else np.array([s0])
    s = np.unique(np.concatenate([head, s, [s1]]))
    return s[np.concatenate([[True], np.diff(s) > 2e-4])]


def _span_shell(sw, r_in, r_out, s0, stations, n_theta, lip=0.0):
    """A closed layer of the wall between two radius functions, running from station s0 to the +x end.

    It is laid out on the parent sweep's own frames, so layers cut back to different stations stay in register. At
    s0 the outer edge rolls over a quarter circle of radius `lip` - a cut sleeve of tissue, not a machined step - and
    the +x end is a clean flat section. End faces get their own vertices so they shade flat."""
    nt, ns = n_theta, len(stations)
    th = np.linspace(0.0, 2 * math.pi, nt, endpoint=False)
    T, S = np.meshgrid(th, stations, indexing="ij")
    ri = np.broadcast_to(np.asarray(r_in(T, S), np.float64), T.shape)
    ro = np.array(np.broadcast_to(np.asarray(r_out(T, S), np.float64), T.shape))
    if lip:
        x = np.clip(1.0 - (S - s0) * sw.length / lip, 0.0, 1.0)
        ro -= np.minimum(lip * (1.0 - np.sqrt(1.0 - x * x)), 0.8 * (ro - ri))
    po = sw.curve(S.ravel(), T.ravel(), ro.ravel())
    pi = sw.curve(S.ravel(), T.ravel(), ri.ravel())
    n = nt * ns
    a = np.arange(n).reshape(nt, ns)
    ring, nxt = np.arange(nt), np.roll(np.arange(nt), -1)
    pos, idx = [po, pi], [_grid(nt, ns, False), _grid(nt, ns, True) + n]
    base = 2 * n
    for col, flip in ((0, True), (ns - 1, False)):
        pos += [po[a[:, col]], pi[a[:, col]]]
        o0, o1 = base + ring, base + nxt
        i0, i1 = o0 + nt, o1 + nt
        tri = np.vstack([np.stack([o0, o1, i1], 1), np.stack([o0, i1, i0], 1)])
        idx.append(tri[:, ::-1] if flip else tri)
        base += 2 * nt
    return orient_outward(Mesh().add(np.vstack(pos), np.vstack(idx)))


class _AortaWall:
    """Radius of any depth in the aortic wall as a function of (theta, s).

    Every layer shares the same calibre and the same slow swelling, so they stay concentric however they are cut;
    the lumen is thrown into shallow longitudinal folds that die away within the intima, and the internal elastic
    lamina carries a fine crinkle of its own."""

    def __init__(self, seed):
        self.calibre = taper((1.012, 0.99, 0.998, 1.016, 1.0))
        self.fold = lobed(15, 1.0, 0.7, harmonics=((2, 0.12),))
        self.swell = surf_noise(0.010, 1.7, 2.3, seed)
        self.crinkle = lobed(38, 0.0024, 1.3, harmonics=((2, 0.3),))

    def __call__(self, r, *extras):
        def g(T, S):
            v = r * self.calibre(T, S) + self.swell(T, S)
            v = v + 0.014 * math.exp(-(r - AORTA_LUMEN) / 0.030) * self.fold(T, S)
            for e in extras:
                v = v + e(T, S)
            return v
        return g


def _circular_grooves(L, depth, period, s_lo, s_hi, fade, seed, wobble=0.45):
    """Relief of the media's outer surface: rounded circumferential bands of smooth muscle and elastin with shallow
    grooves between them. The bands meander so they never read as machined rings, and the relief only cuts inward
    and only where the surface is on show, so the layer outside it can never be pierced."""
    wob = surf_noise(1.0, 1.6, 2.5, seed)
    var = surf_noise(1.0, 3.0, 4.0, seed + 1)

    def f(T, S):
        a = S * L / period + wobble * wob(T, S)
        h = np.abs(np.sin(math.pi * a)) ** 0.45
        env = np.clip((S - s_lo) * L / 0.02, 0.0, 1.0) * np.clip(1.0 - (S - s_hi) * L / fade, 0.0, 1.0)
        return -depth * (1.0 - h) * (0.75 + 0.5 * var(T, S)) * env
    return f


AORTA_HELIX = 13.0       # degrees off the axis of the helix the adventitial collagen runs in


def _grain(amp, seed, L, R, fine=True):
    """Relief of the adventitial surface: a directional grain of collagen fibres running in the shallow helix of the
    bundles that lie on it. Noise packed tightly across the fibres and stretched far along them gives fine ridges
    that run a long way and then merge or peter out, over a broad swell of fibre bundles, and the lanes wander a
    little so the grain is not ruled. With fine=False only the broad swell is returned: the surface that vessels,
    nerves and bundles are laid on, so they do not jolt over every ridge they cross."""
    shear = math.tan(math.radians(AORTA_HELIX)) * L / R      # angle turned per unit s along one fibre
    ridges = surf_noise(1.0, 46.0, 7.0, seed, octaves=1)
    ridges2 = surf_noise(1.0, 30.0, 4.5, seed + 3, octaves=1)
    broad = surf_noise(1.0, 12.0, 3.0, seed + 1, octaves=2)
    wander = surf_noise(1.0, 2.5, 1.6, seed + 2, octaves=2)

    def f(T, S):
        th = T + shear * S + 0.05 * wander(T, S)
        v = 0.30 * broad(th, S)
        if fine:
            r1 = np.clip(1.0 - np.abs(ridges(th, S)) * 3.2, 0.0, 1.0) ** 1.5
            r2 = np.clip(1.0 - np.abs(ridges2(th, S)) * 3.2, 0.0, 1.0) ** 1.5
            v = v + 0.55 * r1 + 0.30 * r2 - 0.28
        return amp * v
    return f


def _theta_toward(sw, s, direction):
    """Angle of the sweep that points (roughly) along a world direction at station s."""
    i = int(np.clip(round(s * (sw.n_s - 1)), 0, sw.n_s - 1))
    d = np.asarray(direction, np.float64)
    return math.atan2(float(d @ sw.bi[i]), float(d @ sw.nrm[i]))


def _surface_tube(sw, outer, s, theta, rad, sink, segments=8):
    """A strand lying on (and partly sunk into) the outer surface: its centre sits `sink` x its radius below it."""
    s = np.asarray(s, np.float64)
    theta = np.broadcast_to(np.asarray(theta, np.float64), s.shape)
    rad = np.broadcast_to(np.asarray(rad, np.float64), s.shape)
    r = outer(theta, s) - rad * sink
    return tube(sw.curve(s, theta, r), rad, segments)


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _dive(u, length, rad, sink, settle=0.10, sunk=0.55, thin=0.85, plunge=2.5, deep=1.6, start=True, end=True):
    """Radius and sink (in radii below the surface) along a vessel or nerve lying half sunk in the adventitia that
    goes down into it at its ends. Over the last `settle` model units of its `length` it narrows a little, to `thin`
    of its radius, and settles gradually deeper, to `sunk` radii; then within `plunge` radii of its end it dives
    steeply to `deep` radii, wholly under the surface. A strand sinking slowly all the way would leave a long sliver
    drawn out to a point on the surface - a thorn - where this leaves a rounded dip into the collagen."""
    u = np.asarray(u, np.float64)
    rad = np.broadcast_to(np.asarray(rad, np.float64), u.shape)
    es, ep = np.ones_like(u), np.ones_like(u)
    for on, d, tip in ((start, u, rad[0]), (end, 1.0 - u, rad[-1])):
        if on:
            es = es * _smoothstep(d * length / settle)
            ep = ep * _smoothstep(d * length / (plunge * thin * tip))
    return rad * (thin + (1.0 - thin) * es), sink + (sunk - sink) * (1.0 - es) + (deep - sunk) * (1.0 - ep)


def _dense(u, *arrays, ends=0.05, length=1.0, n=24):
    """Resample a strand parameterised by u (0..1, `length` model units long) more closely over the last `ends` model
    units at each end, where it dives, so the dive is drawn smoothly rather than in two or three straight steps."""
    e = min(ends / length, 0.5)
    uu = np.unique(np.concatenate([u, np.linspace(0.0, e, n), np.linspace(1.0 - e, 1.0, n)]))
    return (uu,) + tuple(np.interp(uu, u, np.asarray(a, np.float64)) for a in arrays)


def _path_length(s, th, L, R):
    return float(np.sum(np.hypot(np.diff(s) * L, np.diff(th) * R)))


def _beside(s, th, L, R, dist):
    """A path running beside (s, th) at `dist` model units, measured square to the path on the unrolled surface, so
    a companion vessel or nerve keeps its distance however the path it follows turns."""
    x, y = s * L, th * R
    dx, dy = np.gradient(x), np.gradient(y)
    n = np.hypot(dx, dy) + 1e-12
    return (x - dy / n * dist) / L, (y + dx / n * dist) / R


def _fade_ends(f, L, s0, width):
    """Relief term f faded out within `width` model units of both open ends of a layer (s0 and s = 1), so every cut
    edge of the layer is a clean, smooth contour however rough the surface is in between."""
    def g(T, S):
        env = _smoothstep((S - s0) * L / width) * _smoothstep((1.0 - S) * L / width)
        return f(T, S) * env
    return g


def _flush_at_end(sw, mesh, proud=0.0008):
    """Section a strand flush with the +x cross-section: every vertex beyond the end plane is pressed back onto it
    (a hair proud of it, so it wins the depth test), which leaves a vessel cut across as a flat round profile and one
    cut along its length as a flat strip lying in the face - sectioned tissue, not pins standing out of it."""
    o, t = sw.path[-1].astype(np.float64), sw.t[-1].astype(np.float64)
    out = Mesh()
    for p, n, i in mesh.parts:
        q = p.astype(np.float64)
        h = (q - o) @ t
        over = h > proud
        if over.any():
            q[over] -= np.outer(h[over] - proud, t)
            out.add(q, i)
        else:
            out.parts.append((p, n, i))
    return out


def _aorta_bundles(sw, outer, s_lo, count, seed, R, s_hi=0.975, under=()):
    """Collagen bundles on the adventitia. Aortic adventitial collagen runs mainly along the vessel in a shallow helix,
    so every bundle follows that helix give or take a dozen degrees. They are scattered over the surface - each one
    placed as far from the others as a few tries allow, and never within a set clearance of one, so no two cross -
    rather than ruled into lanes. Each is a single flat ribbon: two or three strands pressed together side by side
    and crimped in step, as the fibres of one fascicle are. A bundle is long, and it rises only a little out of the
    fibrous surface along its middle and sinks back into it over a long stretch at each end (and short of either edge
    of the adventitia where it runs past one), so it grows out of the grain and fades back into it instead of
    stopping. R is the radius of the surface they lie on, which turns arc lengths into angles. Where a bundle meets
    one of the vessels or nerves in `under` (paths as (s, theta, radius)) it dips beneath it, so the vessels lie on
    top of the collagen instead of being chopped into dashes by it."""
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    L = sw.length
    m = Mesh()
    circ = 2 * math.pi * R
    tree, vrad = None, None
    if len(under):
        ux = np.concatenate([np.asarray(a, np.float64) * L for a, _, _ in under])
        uy = np.concatenate([np.asarray(b, np.float64) * R for _, b, _ in under]) % circ
        vrad = np.concatenate([np.broadcast_to(np.asarray(c, np.float64), np.shape(a)) for a, _, c in under])
        tree = cKDTree(np.stack([ux, uy], 1), boxsize=[100.0 * L, circ])
    span = (s_hi - s_lo) * L
    pitch = -math.tan(math.radians(AORTA_HELIX))       # the helix of the grain under them
    step, clear, edge = 0.0075, 0.06, 0.12

    def candidate():
        length = rng.uniform(1.0, 1.8)
        n = int(length / step) + 1
        u = np.linspace(0.0, 1.0, n)
        # the bundle may run past either edge of the adventitia; it is drawn only where it lies on it
        x = rng.uniform(-0.40 * length, span - 0.60 * length) + u * length
        slope = pitch + math.tan(math.radians(rng.uniform(-12.0, 12.0)))
        ph = rng.uniform(0, 2 * math.pi)
        xm = x - x.mean()
        y = (rng.uniform(0.0, circ) + slope * xm + rng.uniform(-0.05, 0.05) * np.sin(math.pi * u)
             + 0.010 * np.sin(math.pi * u * rng.uniform(0.8, 1.8) + ph))
        # long fades: the ribbon surfaces over the first and last third or so of its length, and dives again
        # before it reaches an edge of the adventitia
        env = (_smoothstep(u / 0.30) * _smoothstep((1.0 - u) / 0.30)
               * _smoothstep(x / edge) * _smoothstep((span - x) / edge))
        keep = env > 0.01
        if keep.sum() * step < 0.45:
            return None
        return x[keep], y[keep], env[keep], ph

    plan, taken = [], None
    for _ in range(count):
        best, best_d = None, -1.0
        for _try in range(10):
            c = candidate()
            if c is None:
                continue
            x, y, env, _ = c
            pts = np.stack([x, y % circ], 1)[env > 0.1]
            if not len(pts):
                continue
            d = float(taken.query(pts)[0].min()) if taken is not None else 1e9
            if d > clear and d > best_d:
                best, best_d = c, d
        if best is None:
            continue
        plan.append(best)
        allp = np.vstack([np.stack([p[0], p[1] % circ], 1)[p[2] > 0.1] for p in plan])
        taken = cKDTree(allp, boxsize=[100.0 * L, circ])
    for x, y, env, ph in plan:
        s = s_lo + x / L
        strands = 2 if rng.random() < 0.3 else 3
        raised = rng.random() < 0.2                   # a few bundles stand out a little more than the rest
        rad0 = rng.uniform(0.0115, 0.0135) * (1.2 if raised else 1.0)
        spacing = rad0 * 0.85                         # strands overlapping: one ribbon, not a row of worms
        # the strands draw together where the ribbon fades, so it tapers into the grain as one band
        gather = 0.25 + 0.75 * env ** 0.7
        # resting collagen is crimped, the whole fascicle in register: a fine regular wave of the ribbon
        crimp = 0.0012 * np.sin(2 * math.pi * x / rng.uniform(0.045, 0.060) + ph)
        for k in range(strands):
            base = (k - 0.5 * (strands - 1)) * spacing
            weave = 0.08 * spacing * np.sin(2 * math.pi * x / rng.uniform(0.40, 0.70) + ph + 1.9 * k)
            off = ((base + weave) * gather + crimp) / R
            # the ribbon is highest along its middle and rounds off to its edges, so it reads as one soft band
            edge_k = strands == 3 and k != 1
            prof = (0.82 if edge_k else 1.0) if strands == 3 else 0.92
            # the edge strands of a three-strand ribbon surface later and go under sooner than the middle one, so
            # the ribbon narrows to a single tapering strand at each end instead of splitting into three hairs
            e_k = env ** 1.8 if edge_k else env
            rad = rad0 * prof * rng.uniform(0.94, 1.06) * (0.45 + 0.55 * e_k)
            # it sinks in step with the fade, so it emerges gradually over the whole of it instead of popping up
            # near its end
            sink0 = (0.40 if raised else 0.60) + 0.08 * rng.uniform(-1.0, 1.0)
            sink = sink0 + (1.05 - sink0) * (1.0 - e_k)
            th = y / R + off
            if tree is not None:
                d, idx = tree.query(np.stack([s * L, (th * R) % circ], 1))
                dip = 1.0 - _smoothstep((d - (vrad[idx] + rad + 0.004)) / 0.02)
                # widen and soften each dip, so no scrap of strand is left showing between two nearby vessels
                w = max(3, int(round(0.05 / step)))
                dip = uniform_filter1d(maximum_filter1d(dip, w, mode="nearest"), w, mode="nearest")
                sink = sink + 1.5 * dip
            m.extend(_surface_tube(sw, outer, s, th, rad, sink, 7))
    return m


def _aorta_vasa(sw, outer, s_lo, seed, R, trunks=4, venules=3, s_hi=0.965):
    """Vasa vasorum on the adventitia: a few small arteries running along it with branches curling round it, and
    beside some of them the thinner-walled venules that drain the wall. Every vessel lies half sunk in the collagen
    and dives into it at its ends: it keeps a rounded end of about half its radius and sinks well below the surface
    over the last stretch, so no tip is left standing proud of the collagen as a thorn. Returns (arteries, venules,
    trunk paths, every strand as (s, theta, radius))."""
    rng = np.random.default_rng(seed)
    L = sw.length
    art, ven = Mesh(), Mesh()
    paths, strands = [], []
    for k in range(trunks):
        n = 90
        u = np.linspace(0.0, 1.0, n)
        s0 = s_lo + rng.uniform(0.02, 0.10)
        s1 = rng.uniform(0.90, s_hi)
        s = s0 + u * (s1 - s0)
        th0 = 2 * math.pi * k / trunks + rng.uniform(-0.4, 0.4)
        th = th0 + 0.22 * np.sin(1.7 * math.pi * u + k) + 0.08 * np.sin(5.3 * math.pi * u + 2 * k)
        rad = rng.uniform(0.013, 0.016) * (0.8 + 0.2 * np.sin(math.pi * u) ** 0.3)
        tlen = _path_length(s, th, L, R)
        uu, ss, tt, rr = _dense(u, s, th, rad, length=tlen)
        art.extend(_surface_tube(sw, outer, ss, tt, *_dive(uu, tlen, rr, 0.25, settle=0.14), 10))
        paths.append((s, th))
        strands.append((s, th, rad))
        # trunk direction on the unrolled surface, for starting branches off it at an angle
        heading = np.arctan2(np.gradient(th * R), np.gradient(s * L))
        for _ in range(int(rng.integers(3, 5))):
            i = int(rng.integers(12, n - 12))
            nb = 28
            v = np.linspace(0.0, 1.0, nb)
            bl = rng.uniform(0.16, 0.30)
            # a branch leaves at 40-70 degrees and bends gently as it goes, the way small arteries wander over the
            # wall, then dives into the collagen
            phi = (heading[i] + rng.choice([-1.0, 1.0]) * math.radians(rng.uniform(40.0, 70.0))
                   + rng.choice([-1.0, 1.0]) * rng.uniform(0.3, 0.8) * v ** 1.3)
            step = bl / (nb - 1)
            bx = s[i] * L + np.concatenate([[0.0], np.cumsum(np.cos(phi[:-1]) * step)])
            by = th[i] * R + np.concatenate([[0.0], np.cumsum(np.sin(phi[:-1]) * step)])
            bs, bt = bx / L, by / R
            # a branch that would run off the adventitia simply stops short of its edge
            ok = (bs > s_lo + 0.012) & (bs < s_hi + 0.01)
            stop = int(np.argmin(ok)) if not ok.all() else nb
            if stop < 8:
                continue
            bs, bt, w = bs[:stop], bt[:stop], np.linspace(0.0, 1.0, stop)
            blen = _path_length(bs, bt, L, R)
            w, bs, bt = _dense(np.linspace(0.0, 1.0, stop), bs, bt, length=blen, ends=0.04, n=20)
            # the branch narrows only a little, to about 0.45 of the trunk, settles deeper into the collagen over
            # its last third and then dives under it
            brad, bsink = _dive(w, blen, rad[i] * (0.62 - 0.12 * w), 0.25, settle=0.33 * blen, sunk=0.6, thin=0.9)
            art.extend(_surface_tube(sw, outer, bs, bt, brad, bsink, 8))
            strands.append((bs, bt, brad))
        if k < venules:
            # the companion venule: on the other side of the artery from its nerve, a little wider apart
            side = -1.0 if k % 2 else 1.0
            a, b = rng.uniform(0.04, 0.12), rng.uniform(0.88, 0.97)
            j = (u >= a) & (u <= b)
            w = np.linspace(0.0, 1.0, int(j.sum()))
            vr = rng.uniform(0.009, 0.011)
            gap = rad[j] + vr + 0.006 + 0.004 * np.sin(3.1 * math.pi * w + k)
            vs, vt = _beside(s[j], th[j], L, R, side * gap)
            vlen = _path_length(vs, vt, L, R)
            w, vs, vt = _dense(w, vs, vt, length=vlen)
            vrad, vsink = _dive(w, vlen, vr, 0.25, settle=0.12)
            ven.extend(_surface_tube(sw, outer, vs, vt, vrad, vsink, 8))
            strands.append((vs, vt, vrad))
    return art, ven, paths, strands


def _deep_vasa(sw, W, bands, s_lo, count, seed, radius=(0.010, 0.012), segments=12, twigs=3):
    """Vasa vasorum inside the wall. The aortic wall is too thick to be fed from its lumen alone, so small vessels
    from the adventitial plexus run in the adventitia and dive into the outer third of the media. They reach the +x
    section and are cut flush with it, each showing as a round red profile, alternating between the radial `bands`
    (pairs of radii) so about half of them lie in the outer media; and a few `twigs` are cut along their length
    where they plunge radially from the adventitia into the media, so the section shows how the media is supplied."""
    rng = np.random.default_rng(seed)
    m = Mesh()
    t_end = sw.t[-1]
    ends = []
    for k in range(count):
        n = 60
        u = np.linspace(0.0, 1.0, n)
        start = s_lo + rng.uniform(0.0, 0.25)
        s = start + u * (1.0 - start)
        th0 = 2 * math.pi * (k + rng.uniform(0.2, 0.8)) / count
        th = th0 + 0.10 * np.sin(2.1 * math.pi * u + k)
        band = k % len(bands)
        lo, hi = bands[band]
        depth = rng.uniform(lo, hi)
        r = W(depth)(th, s) + 0.006 * np.sin(1.3 * math.pi * u + 2 * k)
        p = sw.curve(s, th, r)
        p = np.vstack([p, p[-1] + t_end * 0.02])        # carried through the section, then cut flush with it
        rad = rng.uniform(*radius)
        m.extend(tube(p, rad, segments))
        ends.append((band, float(th[-1]), depth, rad))
    # penetrating twigs lying in the plane of the section, each leaving one of the outermost vessels and running
    # radially inward, tapering, until it ends in the outer third of the media
    r_in = min(lo for lo, _ in bands)
    outermost = [e for e in ends if e[0] == len(bands) - 1]
    for k in range(min(twigs, len(outermost))):
        _, th, depth, rad = outermost[(k * len(outermost)) // twigs]
        n = 24
        v = np.linspace(0.0, 1.0, n)
        tt = np.full(n, th) + 0.05 * (1.0 if k % 2 else -1.0) * v ** 2        # a slight sweep, not a straight rule
        rr = W(depth)(tt, np.ones(n)) * (1.0 - v) + W(r_in)(tt, np.ones(n)) * v
        p = sw.curve(np.ones(n), tt, rr)
        m.extend(tube(p, rad * (0.72 - 0.34 * v), 10))
    return _flush_at_end(sw, m)


def _aorta_fat(sw, outer, pads, seed, s_min=0.0, recess=0.0015):
    """Perivascular fat: broad, flat pads of adipocytes bedded in the surface of the adventitia, smooth-unioned
    with a generous blend so the cells press softly into one another the way packed fat cells do, and gathered into
    a few low lobules with shallow clefts between them. Each pad is (s, theta, cells, cell radius, spread along,
    spread round). A pad may run past the +x end, where it is cut off in the plane of the section (`recess` short of
    it), so the cross-section shows the fat as a thin layer outside the adventitia."""
    rng = np.random.default_rng(seed)
    L = sw.length
    o_end, t_end = sw.path[-1].astype(np.float64), sw.t[-1].astype(np.float64)
    m = Mesh()

    def frame(s, th):
        """Surface point and (along, round, out) unit vectors of the outer surface at (s, theta). Past the end of the
        vessel the surface is carried straight on along its last tangent."""
        sc = min(float(s), 1.0)
        s1, t1 = np.array([sc]), np.array([th])
        r = outer(t1, s1)
        p = sw.curve(s1, t1, r)[0]
        out = sw.curve(s1, t1, r + 0.01)[0] - p
        rnd = sw.curve(s1, t1 + 0.01, outer(t1 + 0.01, s1))[0] - p
        out /= np.linalg.norm(out)
        rnd -= out * (rnd @ out)
        rnd /= np.linalg.norm(rnd)
        return p + t_end * (float(s) - sc) * L, np.cross(rnd, out), rnd, out

    for s0, th0, count, rad, along, round_ in pads:
        R = float(outer(np.array([th0]), np.array([min(s0, 1.0)]))[0])
        # cells packed in a staggered lattice over an oval footprint, then jostled, so they fill it without gaps
        # and without strays; the footprint is filled from its middle outwards
        pitch = rad * 1.55
        g = np.array([(i + 0.5 * (j % 2), j * 0.87) for i in range(-10, 11) for j in range(-10, 11)], float) * pitch
        g = g[np.argsort(np.hypot(g[:, 0] / along, g[:, 1] / round_))][:count]
        g += rng.normal(0.0, rad * 0.15, g.shape)
        # a few lobules: every cell is drawn a little towards the middle of its own lobule, which opens shallow
        # clefts (the septa) between neighbouring lobules, and each lobule domes up on its own
        n_lob = max(2, count // 18)
        seeds = g[rng.choice(len(g), n_lob, replace=False)]
        for _ in range(3):                                   # a couple of rounds of Lloyd relaxation
            lab = np.argmin(np.linalg.norm(g[:, None, :] - seeds[None], axis=2), axis=1)
            seeds = np.array([g[lab == q].mean(axis=0) if np.any(lab == q) else seeds[q] for q in range(n_lob)])
        lab = np.argmin(np.linalg.norm(g[:, None, :] - seeds[None], axis=2), axis=1)
        to_c = seeds[lab] - g
        g = g + 0.10 * to_c
        dl = np.linalg.norm(to_c, axis=1)
        lob_r = np.array([max(float(dl[lab == q].max()), rad) if np.any(lab == q) else rad for q in range(n_lob)])
        dome = np.clip(1.0 - (dl / lob_r[lab]) ** 2, 0.0, 1.0)
        cs = np.maximum(s0 + g[:, 0] / L, s_min)
        ct = th0 + g[:, 1] / R
        radii = rad * rng.uniform(0.88, 1.12, count)
        # a flat pad hugging the vessel, not a heap stuck on it: the cells are flattened against the adventitia and
        # more than half bedded in it, and only the middle of each lobule rides a little higher
        flat = 0.60 + 0.18 * dome
        lift = radii * (-0.12 + 0.22 * dome)
        shapes = []
        for k in range(count):
            base, a, r_, o = frame(cs[k], ct[k])
            rot = np.stack([a, r_, o], axis=1)
            rr = radii[k]
            shapes.append(ellipsoid(base + o * lift[k],
                                    (rr * rng.uniform(1.0, 1.2), rr * rng.uniform(0.9, 1.1), rr * flat[k]), rot=rot))
        lo = np.min([sh[1] for sh in shapes], axis=0) - 0.02
        hi = np.max([sh[2] for sh in shapes], axis=0) + 0.02
        v = Volume(lo, hi, 0.0034)
        for sh in shapes:
            v.add(sh, "smooth", rad * 0.26)      # enough blend to pack the cells, little enough that each one still shows
        v.displace(0.0012, 30.0, 2, seed=int(rng.integers(1, 9999)))
        x, y, z = v.axes()
        cut = (x - o_end[0]) * t_end[0] + (y - o_end[1]) * t_end[1] + (z - o_end[2]) * t_end[2] + recess
        np.maximum(v.d, cut.astype(np.float32), out=v.d)
        m.extend(v.mesh(0.7))
    return m


def _leukocyte(c, radius, bumps, bump_r, rng, voxel=0.0034):
    v = Volume(c - radius * 1.6, c + radius * 1.6, voxel)
    v.add(ellipsoid(c, (radius, radius * 0.88, radius * 0.95)))
    for _ in range(bumps):
        d = rng.normal(size=3)
        d /= np.linalg.norm(d)
        v.add(ellipsoid(c + d * radius * 0.86, (bump_r, bump_r, bump_r)), "smooth", bump_r * 0.8)
    return v


def _aorta_blood(sw, lumen, parts, rng, n_rbc=56):
    """A modest scatter of red cells down the lumen, one leukocyte rolling on the endothelium and two more in the
    stream - enough to say 'blood' without filling the vessel."""
    rbc = Mesh()
    placed = []
    for _ in range(n_rbc * 14):
        if len(placed) >= n_rbc:
            break
        s = np.array([rng.uniform(0.03, 0.97)])
        th = np.array([rng.uniform(0, 2 * math.pi)])
        r = np.array([(float(lumen(th, s)[0]) - 0.065) * math.sqrt(rng.uniform(0.0, 0.94))])
        c = sw.curve(s, th, r)[0]
        if placed and np.min(np.linalg.norm(np.array(placed) - c, axis=1)) < 0.11:
            continue
        placed.append(c)
        rbc.extend(red_cell(c, rng.normal(size=3), 0.040))
    parts.append(mesh_part(rbc, "Red blood cells", "Blood", "#c3302a", VESSEL["rbc"], "artery", rank=-1,
                           detail=(0.03, 0.0, 0.0, 0)))
    s = np.array([0.56])
    th = np.array([_theta_toward(sw, 0.56, (0.0, -0.6, -0.8))])
    c = sw.curve(s, th, np.array([float(lumen(th, s)[0]) - 0.050]))[0]
    parts.append(sdf_part(_leukocyte(c, 0.056, 44, 0.013, rng, 0.0032), "Rolling leukocyte", "Blood", "#e9e4f2",
                          VESSEL["wbc"], "lymph", smooth=0.75, rank=-1, detail=(0.05, 60.0, 0.9, 0)))
    free = Mesh()
    for s_c, r_c, rad, bumps, br in ((0.30, 0.13, 0.050, 36, 0.012), (0.78, 0.17, 0.040, 14, 0.008)):
        th = np.array([rng.uniform(0, 2 * math.pi)])
        c = sw.curve(np.array([s_c]), th, np.array([r_c]))[0]
        free.extend(_leukocyte(c, rad, bumps, br, rng).mesh(0.75))
    parts.append(mesh_part(free, "White blood cells", "Blood", "#dcd6ec",
                           "White cells carried in the stream: a neutrophil with its ruffled surface and a smaller, "
                           "smoother lymphocyte. Together they are well under 1% of the cells in blood.", "lymph",
                           rank=-1, detail=(0.05, 60.0, 0.9, 0)))


def build_aorta():
    """Elastic artery (aortic wall) as a telescoped cutaway.

    Every layer is its own closed sleeve, cut back a step further than the one inside it, so the model reads at once
    as a wide, relatively thin-walled tube: pink intima running furthest, then the crinkled gold internal elastic
    lamina, the thick rose-brown media with its circumferential banding, a narrow pale-gold band of external elastic
    lamina, and the straw-coloured, fibre-grained adventitia with its vessels, nerves and fat. The media is not one
    slab: it is a stack of smooth-muscle layers with a thin pale elastic lamella between each pair, so every cut face
    shows the fine concentric banding that defines an elastic artery."""
    rng = np.random.default_rng(22)
    # the centreline is sampled at exactly the sweep's resolution: handed a coarser path, Sweep would respline it and
    # pad the end with repeated points, collapsing the last stretch of every layer onto its own end face
    path = curved_path(2.4, bend=(0.05, -0.035), wobble=0.016, freq=0.8, seed=13, n=481)
    path[:, 1:] -= path[:, 1:].mean(axis=0)
    sw = Sweep(path, 16, len(path))
    L = sw.length
    W = _AortaWall(13)
    rad = {}
    acc = AORTA_LUMEN
    for name, t in AORTA_LAYERS:
        rad[name] = (acc, acc + t)
        acc += t
    st = {k: v / L for k, v in AORTA_STEPS.items()}
    crinkle = W.crinkle
    parts = []

    def layer(name, group, color, mesh, desc, cat, rank, detail, bulk=False):
        parts.append(Part(name, group, color, mesh, desc, category=cat, clip=True, bulk=bulk, rank=rank,
                          detail=detail))

    # ---- tunica intima: endothelium on a thin subendothelial layer, both thrown into shallow longitudinal folds.
    # The cobblestone relief of the endothelial cells dies away at both cut ends, so the rim of the intima at the
    # open end and its ring in the +x section are clean contours that follow only the folds.
    cells = _fade_ends(cells_on(0.046, -0.004, 51, aspect=2.6, groove=0.22, dome=0.6, r_typ=AORTA_LUMEN, length=L),
                       L, st["endo"], 0.03)
    # shaded as a soft, matte sheet (the "fascia" material, not the glossy "artery" one): with a strong highlight the
    # folds of the lumen catch bright streaks that look like plastic and drown the blood cells
    r0, r1 = rad["endo"]
    layer("Endothelium", "Tunica intima", "#e79aa8",
          _span_shell(sw, W(r0, cells), W(r1), st["endo"], _stations(sw, st["endo"], 0.02, lip=0.0035), 320,
                      lip=0.0035),
          VESSEL["endothelium"], "fascia", 0, (0.04, 170.0, 0.9, 1))
    r0, r1 = rad["subendo"]
    layer("Subendothelial layer", "Tunica intima", "#f2dccd",
          _span_shell(sw, W(r0 + _GAP), W(r1, crinkle), st["subendo"],
                      _stations(sw, st["subendo"], 0.03, (st["subendo"], st["iel"] + 0.01, 0.01), lip=0.009), 320,
                      lip=0.009),
          VESSEL["subendo"], "fascia", 0, (0.05, 90.0, 0.2, 1))
    r0, r1 = rad["iel"]
    layer("Internal elastic lamina", "Tunica intima", "#ecc257",
          _span_shell(sw, W(r0 + _GAP, crinkle), W(r1, crinkle), st["iel"],
                      _stations(sw, st["iel"], 0.03, (st["iel"], st["media"] + 0.01, 0.006), lip=0.004), 288,
                      lip=0.004),
          VESSEL["iel"], "cartilage", 0.5, (0.02, 0.0, 0.0, 0))

    # ---- tunica media: smooth-muscle layers alternating with elastic lamellae. A lamella is a thin sheet (a few
    # micrometres) between much wider interlamellar units of muscle and matrix, so the pale bands are drawn about a
    # third as thick as the muscle between them, and each undulates gently on its own.
    m0, m1 = rad["media"]
    n = AORTA_LAMELLAE
    rc = m0 + (np.arange(n) + 1) * (m1 - m0) / (n + 1)
    tl = 0.0034
    wob = [surf_noise(0.0025, 6.0 + 0.8 * k, 2.6 + 0.35 * k, 300 + k) for k in range(n)]
    grooves = _circular_grooves(L, 0.004, 0.05, st["media"], st["eel"], 0.05, 77, wobble=0.45)
    coarse = _stations(sw, st["media"], 0.045)
    muscle, lamellae = Mesh(), Mesh()
    for k in range(n + 1):
        lo = W(m0 + _GAP, crinkle) if k == 0 else W(rc[k - 1] + tl / 2 + _GAP, wob[k - 1])
        if k == n:
            stn = _stations(sw, st["media"], 0.045, (st["media"], st["eel"] + 0.06, 0.0045), lip=0.007)
            muscle.extend(_span_shell(sw, lo, W(m1, grooves), st["media"], stn, 288, lip=0.007))
        else:
            hi = W(rc[k] - tl / 2 - _GAP, wob[k])
            muscle.extend(_span_shell(sw, lo, hi, st["media"], coarse, 288 if k == 0 else 128))
            lamellae.extend(_span_shell(sw, W(rc[k] - tl / 2, wob[k]), W(rc[k] + tl / 2, wob[k]), st["media"],
                                        coarse, 128))
    layer("Tunica media (smooth muscle)", "Tunica media", "#b05852", muscle, VESSEL["media_elastic"], "muscle", 1,
          (0.05, 120.0, 0.55, 1))
    layer("Elastic lamellae", "Tunica media", "#f1dc9e", lamellae, VESSEL["lamellae"], "cartilage", 1,
          (0.02, 0.0, 0.0, 0))
    # the external elastic lamina is a pale gold close to the lamellae - in an elastic artery it is hard to tell from
    # the outermost of them - and warm enough to read as elastin, not as the ivory subendothelial layer
    r0, r1 = rad["eel"]
    layer("External elastic lamina", "Tunica media", "#ecd79a",
          _span_shell(sw, W(r0 + _GAP), W(r1), st["eel"],
                      _stations(sw, st["eel"], 0.045, (st["eel"], st["adv"] + 0.01, 0.006), lip=0.0025), 288,
                      lip=0.0025),
          VESSEL["eel"], "cartilage", 1.5, (0.02, 0.0, 0.0, 0))

    # ---- tunica adventitia: collagen with a helical grain, vasa and nervi vasorum, perivascular fat on its surface.
    # The grain is fine across the fibres, so the shell is sampled more closely round the vessel than the others;
    # everything lying on it is laid on its broad swell only (`lay`)
    r0, r1 = rad["adv"]
    outer = W(r1, _grain(0.003, 91, L, r1))
    lay = W(r1, _grain(0.003, 91, L, r1, fine=False))
    layer("Tunica adventitia", "Tunica adventitia", "#caa06c",
          _span_shell(sw, W(r0 + _GAP), outer, st["adv"], _stations(sw, st["adv"], 0.012, lip=0.022), 560,
                      lip=0.022),
          VESSEL["adventitia"], "fascia", 2, (0.05, 50.0, 0.12, 0), bulk=True)
    vasa, venules, trunks, on_top = _aorta_vasa(sw, lay, st["adv"], 81, r1, trunks=5, venules=3)
    nerves = Mesh()
    for k, (s, th) in enumerate(trunks[:3]):
        # each nerve keeps to one side of its artery (the venule, where there is one, runs on the other)
        off = (1 if k % 2 else -1) * (0.034 + 0.008 * np.sin(4.0 * math.pi * s + k))
        ns, nt = _beside(s, th, L, r1, off)
        nlen = _path_length(ns, nt, L, r1)
        w, ns, nt = _dense(np.linspace(0.0, 1.0, len(s)), ns, nt, length=nlen, ends=0.03)
        nrad, nsink = _dive(w, nlen, 0.0042, 0.2, settle=0.10, sunk=0.5, thin=0.8, deep=1.8)
        nerves.extend(_surface_tube(sw, lay, ns, nt, nrad, nsink, 7))
        on_top.append((ns, nt, nrad))
    # the collagen bundles pass under the vessels and nerves lying on the adventitia
    parts.append(mesh_part(_aorta_bundles(sw, lay, st["adv"] + 0.03, 20, 80, r1, under=on_top),
                           "Adventitial collagen bundles", "Tunica adventitia", "#d9b882", _COLLAGEN_DESC, "fascia",
                           rank=2.2, detail=(0.05, 45.0, 0.10, 1)))
    # deep vasa alternate between the outer third of the media and the adventitia, so half of them supply the media
    vasa.extend(_deep_vasa(sw, W, ((m1 - 0.07, m1 - 0.02), (r0 + 0.018, r1 - 0.022)), st["adv"] + 0.04, 12, 84))
    parts.append(mesh_part(vasa, "Vasa vasorum", "Tunica adventitia", "#b01e28", VESSEL["vasa"], "artery", rank=2.5))
    parts.append(mesh_part(venules, "Vasa vasorum venules", "Tunica adventitia", "#6e2440", _VENULE_DESC, "vein",
                           rank=2.5))
    parts.append(mesh_part(nerves, "Nervi vasorum", "Tunica adventitia", "#e8e6b8", VESSEL["nervi"], "nerve",
                           rank=2.5))
    # perivascular fat: three broad, flat pads bedded in the adventitia, each drawn out along the vessel. Two run out
    # through the section at the +x end, so the cut face shows fat outside the adventitia; the third lies further
    # back on the upper flank, where it stands in the outline of the default oblique view and reads as tissue round
    # the vessel rather than an object on it
    pads = []
    for back, direction, count, cell, along, round_ in ((0.13, (0.0, 0.35, 0.94), 70, 0.034, 3.0, 1.4),
                                                        (0.09, (0.0, -0.75, -0.66), 56, 0.032, 3.0, 1.3),
                                                        (0.55, (0.0, 0.94, -0.34), 54, 0.030, 3.0, 1.5)):
        s_p = 1.0 - back / L
        pads.append((s_p, _theta_toward(sw, s_p, direction), count, cell, along, round_))
    parts.append(mesh_part(_aorta_fat(sw, lay, pads, 83, s_min=st["adv"] + 0.07 / L), "Perivascular fat",
                           "Tunica adventitia", "#f3d272", _FAT_DESC, "fat", rank=3, detail=(0.04, 22.0, 0.08, 0)))

    _aorta_blood(sw, W(AORTA_LUMEN, cells), parts, rng, n_rbc=46)
    warp_parts(parts, noise_field((0.010, 0.010, 0.010), 1.0, 3, seed=int(rng.integers(1, 500))))
    return parts
