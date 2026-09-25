"""Blood vessel walls: muscular artery, elastic artery (aorta) and a vein with a valve.

Each model is a short segment of vessel swept round a gently curved centreline, opened by the standard tube cut
(the quadrant x < 0, y > 0 is taken away), so the wall is seen twice in section - across it at x = 0 and along it at
y = 0 - with the lumen and its blood exposed between. The wall is drawn in proportion to its lumen: thick in the
muscular artery (wall about two thirds of the lumen radius), thin in the aorta and the vein (about a quarter).

Every layer is its own closed shell between two radius functions r(theta, s), and the shells are sampled on grids
that are fine where a cut face shows them and coarse where they are buried. That is what lets the aortic media be
built as two dozen separate elastic lamellae with smooth muscle between them, each lamella wavy in section and
broken by fenestrations, inside a sane triangle budget.

Tubes that run inside the wall - vasa vasorum, nervi vasorum, the longitudinal muscle bundles of a vein - lie in
channels: every layer they pass through is deflected round them, the way lamellae part round a vessel in the outer
media. A section therefore shows each one as a clean round profile in the tissue instead of a tube seen through it.
"""
import math

import numpy as np

from .base import Part
from .cells import frame_from_normal, orient_outward
from .geometry import Mesh, tube
from .kit import Volume, ellipsoid, mesh_part, sdf_part
from .organic import Sweep, cells_on, curved_path, noise_field, surf_noise, warp_parts

GAP = 0.00015            # clearance between neighbouring shells, so no two surfaces ever coincide
SEAM = 0.00002           # between two shells of one part: a crack any wider shows what lies in it at grazing angles
ZONE_GAP = 0.0004        # a little more between neighbours sampled on different angular grids
CH_GAP = 0.0001          # clearance round a tube lying in a channel, on top of 2% of its radius
SEAT = 0.0003            # surfaces this close to a channel's centre are the two it lies between

# ------------------------------------------------------------------------------------------------ descriptions
_ENDO = ("Endothelium: a single layer of flat (simple squamous) cells, elongated in the direction of flow, on a "
         "basement membrane. It releases nitric oxide and prostacyclin (vasodilator, antiplatelet) and endothelin, "
         "stores von Willebrand factor in Weibel–Palade bodies, and controls permeability and which leukocytes "
         "stick. Endothelial dysfunction is the first step of atherosclerosis.")
_ENDO_VEIN = ("Endothelium of the vein: simple squamous cells, shorter and broader than in an artery, continuous "
              "with the endothelium covering both faces of the valve cusps.")
_SUBENDO_M = ("Subendothelial layer: a very thin layer of loose connective tissue (collagen, proteoglycans, the odd "
              "smooth muscle cell) between the endothelium and the internal elastic lamina. LDL retained here is "
              "the start of an atherosclerotic plaque.")
_SUBENDO_A = ("Subendothelial layer of the aortic intima: relatively thick in adults - loose connective tissue with "
              "collagen, elastic fibres, proteoglycans and scattered smooth muscle (myointimal) cells. It thickens "
              "with age, and it is where fatty streaks and atherosclerotic plaques form.")
_SUBENDO_V = ("Subendothelial layer: a thin sheet of connective tissue under the endothelium. Most veins have no "
              "distinct internal elastic lamina - only scattered elastic fibres - so intima and media blend.")
_IEL_M = ("Internal elastic lamina: a fenestrated sheet of elastin at the inner border of the media - the hallmark "
          "of a muscular artery. It is wavy (scalloped) in section because the artery contracts at death and "
          "fixation; the fenestrations let nutrients diffuse from the lumen to the inner media. It splits and "
          "reduplicates in atherosclerosis and hypertension.")
_IEL_A = ("Internal elastic lamina: in an elastic artery it is not distinct - it looks like the first of the "
          "medial lamellae, only a little thicker - unlike the prominent lamina of a muscular artery.")
_MEDIA_M = ("Tunica media: 10–40 layers of smooth muscle cells wound circumferentially (in a low helix) round the "
            "vessel, with fine elastic and reticular fibres and proteoglycans between them - all made by the muscle "
            "cells, since the media has no fibroblasts. Sympathetic tone on this muscle distributes blood between "
            "regions. Its cut faces show the long nuclei wrapped round the lumen.")
_EEL_M = ("External elastic lamina: a thinner, often fragmented elastic sheet at the border of media and adventitia, "
          "clear in larger muscular arteries.")
_ADV_M = ("Tunica adventitia: connective tissue of mainly longitudinal type I collagen and elastic fibres with "
          "fibroblasts - here a little thinner than the media. It anchors the vessel to its surroundings, carries "
          "the vasa vasorum, nervi vasorum and lymphatics, and blends outwards into loose connective tissue.")
_LAMELLAE = ("Elastic lamellae: concentric fenestrated sheets of elastin, 40–70 in the adult aorta, each 2–3 µm "
             "thick and about 15 µm apart, wavy in section. They stretch in systole and recoil in diastole, "
             "storing part of each stroke volume and keeping blood moving in diastole (Windkessel effect). The "
             "fenestrations (gaps in the lines) let nutrients and cells through. About two dozen are drawn here.")
_MEDIA_A = ("Smooth muscle of the aortic media: a layer of smooth muscle cells, collagen and proteoglycan between "
            "each pair of lamellae (lamella plus muscle = one lamellar unit). The muscle cells make all of the "
            "elastin, collagen and ground substance. When they fail - Marfan syndrome (fibrillin-1), cystic medial "
            "degeneration - the lamellae fragment and the wall dilates (aneurysm) or tears (dissection).")
_EEL_A = ("External elastic lamina: indistinct in an elastic artery - little more than the outermost lamella, at "
          "the border with the adventitia.")
_ADV_A = ("Tunica adventitia of the aorta: relatively thin - collagen with elastic fibres, fibroblasts, vasa and "
          "nervi vasorum and lymphatics. Its collagen sets the limit of distension, and it is the outer wall of the "
          "false lumen in an aortic dissection.")
_MEDIA_V = ("Tunica media of the vein: thin - a few layers of circular smooth muscle cells mixed with collagen and "
            "fibroblasts, far thinner than the media of an artery of the same size. So the vein is thin-walled and "
            "easily distended: veins hold about two thirds of the blood volume (capacitance vessels).")
_ADV_V = ("Tunica adventitia: the thickest coat of a vein - collagen and elastic fibres with fibroblasts, "
          "longitudinal smooth muscle bundles, vasa vasorum and nerves.")
_LONG_MUSCLE = ("Longitudinal smooth muscle bundles in the adventitia, cut across as round profiles. They are best "
                "developed in large veins - the inferior vena cava, portal, splenic and renal veins - where they "
                "resist lengthening and help set the vein's capacity.")
_VALVE = ("Venous valve: two semilunar cusps (bicuspid), each a fold of intima - a thin core of collagen and "
          "elastic fibres covered by endothelium on both faces. Their free edges point towards the heart: forward "
          "flow parts them, and backflow fills the pocket (sinus) behind each cusp and snaps them shut. The wall "
          "bulges at the sinuses. Stasis in the sinus pockets is where deep vein thrombi begin (Virchow triad); "
          "incompetent valves cause varicose veins and chronic venous insufficiency.")
_VASA_M = ("Vasa vasorum: small arteries, capillaries and venules supplying the outer wall. In a muscular artery "
           "they stay in the adventitia - some run in it (seen here cut across), others branch over its surface; "
           "the media is fed by diffusion from the lumen and from these vessels.")
_VASA_A = ("Vasa vasorum: the aortic wall is too thick to be fed from the lumen alone (beyond about 29 lamellar "
           "units), so small arteries from the adventitial plexus penetrate the outer media - cut across here "
           "between the outer lamellae, which part round them. The inner media and intima rely on diffusion from "
           "the lumen. Obliterative endarteritis of these vessels in syphilis causes aortitis and aneurysm.")
_VASA_V = ("Vasa vasorum: small vessels in the adventitia of the vein. Because venous blood carries little oxygen "
           "they reach deeper into a vein wall than into an artery wall of the same size.")
_VENULE = ("Venules of the vasa vasorum: thin-walled vessels beside the small arteries of the adventitia, draining "
           "the outer wall to neighbouring veins.")
_NERVI = ("Nervi vasorum: unmyelinated sympathetic (vasomotor) axons running in the adventitia. They do not enter "
          "the media: varicosities at the media–adventitia border release noradrenaline, which diffuses inwards and "
          "contracts the smooth muscle through α1 receptors.")
_NERVI_V = ("Nervi vasorum: sympathetic axons in the adventitia. Venoconstriction moves blood from the venous "
            "reservoir back to the heart - a large part of the early compensation for haemorrhage.")
_COLLAGEN = ("Adventitial collagen bundles: wavy bundles of type I collagen, mostly running along the vessel in a "
             "shallow helix, with elastic fibres between. Slack at rest, they only tighten at high pressure, so "
             "they set the limit of distension - and they are what holds a suture.")
_FAT = ("Perivascular fat: adipocytes of the fat round the vessel. It is not inert packing: perivascular adipose "
        "tissue releases adipokines that relax healthy vessels, and in obesity becomes inflamed and pro-atherogenic.")
_RBC = ("Red blood cells: biconcave, anucleate discs about 7.5 µm across and 2 µm thick - a shape that gives a large "
        "surface for gas exchange and lets them fold through 3 µm capillaries. Drawn many times enlarged: at true "
        "scale this lumen would hold millions.")
_WBC = ("Leukocyte (neutrophil) rolling on the endothelium: selectins make it tether and roll, then integrins make "
        "it stop and squeeze between endothelial cells into the tissue (diapedesis) - mostly in postcapillary "
        "venules, but it also happens in inflamed arteries.")


# ------------------------------------------------------------------------------------------------ small helpers
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


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _theta_toward(sw, s, direction):
    """Angle of the sweep that points (roughly) along a world direction at station s."""
    i = int(np.clip(round(s * (sw.n_s - 1)), 0, sw.n_s - 1))
    d = np.asarray(direction, np.float64)
    return math.atan2(float(d @ sw.bi[i]), float(d @ sw.nrm[i]))


def _vessel_sweep(length, bend, wobble, seed, n=241):
    """A gently curved centreline, centred on the x axis (the shader wraps the media's fibre texture round it). The
    path is sampled at exactly the sweep's resolution, so Sweep never resplines it."""
    path = curved_path(length, bend=bend, wobble=wobble, freq=0.8, seed=seed, n=n)
    path[:, 1:] -= path[:, 1:].mean(axis=0)
    return Sweep(path, 16, n)


def _theta_grid(sw, fine, coarse, span=math.radians(250), clusters=()):
    """Angles round the vessel: spaced `fine` over the `span` centred on +y (the half the default cut opens, with a
    margin past the y = 0 plane on both sides), `coarse` over the buried underside, plus a tight cluster round every
    channel so the layers can wrap the tube lying in it."""
    up = _theta_toward(sw, 0.5, (0.0, 1.0, 0.0))
    n_f = max(int(round(span / fine)), 8)
    parts = [up - span / 2 + np.arange(n_f + 1) * (span / n_f)]
    rest = 2 * math.pi - span
    n_c = max(int(round(rest / coarse)), 4)
    parts.append(up + span / 2 + np.arange(1, n_c) * (rest / n_c))
    for c, half, n, *even in clusters:
        u = np.linspace(-1.0, 1.0, n)
        parts.append(c + half * (u if even else np.sin(u * math.pi / 2)))
    th = np.sort(np.mod(np.concatenate(parts), 2 * math.pi))
    th = th[np.concatenate([[True], np.diff(th) > 2e-5])]
    if th[0] + 2 * math.pi - th[-1] < 2e-5:
        th = th[:-1]
    return th


def _grid(nt, ns, flip):
    a = np.arange(nt * ns).reshape(nt, ns)
    i0, i1 = a[:, :-1], np.roll(a, -1, axis=0)[:, :-1]
    j0, j1 = a[:, 1:], np.roll(a, -1, axis=0)[:, 1:]
    tri = np.vstack([np.stack([i0.ravel(), i1.ravel(), j0.ravel()], 1),
                     np.stack([i1.ravel(), j1.ravel(), j0.ravel()], 1)])
    return tri[:, ::-1] if flip else tri


def _shell(sw, r_in, r_out, th, st):
    """A closed layer of the wall between two radius functions, on the angles `th` and stations `st` (0..1 along the
    vessel). Every layer is laid out on the same sweep frames, so layers sampled differently stay in register. The
    end faces get their own vertices so they shade flat."""
    nt, ns = len(th), len(st)
    T, S = np.meshgrid(th, st, indexing="ij")
    ri = np.broadcast_to(np.asarray(r_in(T, S), np.float64), T.shape)
    ro = np.maximum(np.broadcast_to(np.asarray(r_out(T, S), np.float64), T.shape), ri + 2e-5)
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


class _Wall:
    """Radius at any depth d (model units from the lumen) of a vessel wall, as a function of (theta, s).

    Every depth shares one calibre, one flattening and one slow swelling, so the layers stay concentric however
    they are cut; tubes registered as channels push every surface they overlap aside (see `push`)."""

    def __init__(self, r_lumen, seed, calibre=0.025, oval=0.0, oval_dir=0.0, swell=0.005, swell_s=1.0, bulge=None):
        rng = np.random.default_rng(seed)
        p1, p2 = rng.uniform(0, 2 * math.pi, 2)
        self.r0 = r_lumen
        self.cal = lambda S: 1.0 + calibre * (np.sin(math.pi * 1.1 * S + p1) + 0.45 * np.sin(math.pi * 2.3 * S + p2))
        self.oval, self.oval_dir = oval, oval_dir
        self.swell = surf_noise(swell, 1.6, swell_s, seed + 5, octaves=2)
        self.bulge = bulge
        self.channels = []
        self.knots = None

    def base(self, d):
        def g(T, S):
            v = (self.r0 + d) * self.cal(S)
            if self.oval:
                v = v * (1.0 + self.oval * np.cos(2.0 * (T - self.oval_dir)))
            if self.bulge is not None:
                v = v * (1.0 + self.bulge(T, S))
            return v + self.swell(T, S)
        return g

    def channel(self, theta, depth, rad, spread=0.8):
        """Register a tube running along the vessel at angle `theta` and depth `depth`, lying between two layers.
        `spread` (in tube radii) is how far the layers beyond those two are eased aside round it."""
        # the radius the channel's angular samples are laid out for (see `clusters`)
        ss = np.linspace(0.0, 1.0, 41)
        r_ref = float(np.mean(self.base(depth)(np.full(41, float(theta)), ss)))
        rp = rad * 1.02 + CH_GAP
        self.channels.append((float(theta), float(depth), rp, float(spread), r_ref))

    def tube_in(self, sw, theta, depth, rad, spread=0.8, segments=18):
        """Register a channel and return the tube lying in it. `depth` must fall strictly between the two surfaces
        the tube is to lie between (for two shells of one part: their interface + SEAM / 2)."""
        self.channel(theta, depth, rad, spread)
        return _channel_tube(sw, self, theta, depth, rad, segments=segments)

    def push(self, T, S, v, d):
        """Deflect a surface of radius v round every channel near it: a surface inside the tube's centre is pushed
        inwards, one outside it outwards. The two surfaces the tube lies between wrap it exactly; the layers beyond
        are eased aside by an amount that dies away with their distance from it, so they bow round the tube the
        way lamellae part round a vessel. The displacement never decreases towards the tube, so the order of the
        layers is never broken."""
        out = v
        for th, c, rp, spread, r_ref in self.channels:
            # the tube's centre, and in polar coordinates round the vessel axis the nearest point of the ray at
            # angle T to it (rc cos phi) and that point's distance from it (a): exact for a circle in the section
            T, S = np.broadcast_arrays(np.asarray(T, np.float64), np.asarray(S, np.float64))
            r_c = self.base(c)(np.full(T.shape, th), S)
            phi = np.clip(np.abs(_wrap(T - th)), 0.0, math.pi / 2)
            rc = r_c * np.cos(phi)
            a = r_c * np.sin(phi)
            circ = np.sqrt(np.maximum(rp * rp - a * a, 0.0))
            side = 1.0 if d > c else -1.0            # a layer deeper than the tube passes outside it
            dist = side * (v - rc)
            new = np.where(circ > 0.0, np.maximum(dist, circ), dist)
            if spread > 0 and abs(d - c) > SEAT:
                ad = np.abs(dist)
                soft = np.maximum(circ, rp * (1.0 - _smoothstep(a / (2.4 * rp))))
                lam = spread * rp
                eased = ad + soft * np.exp(-ad / lam) * (1.0 - _smoothstep(ad / (2.8 * lam)))
                new = np.maximum(eased * np.sign(dist + 1e-12), new)
            out = out + side * (new - dist)
        return out

    def clusters(self, n=17, only=None):
        """Dense-angle clusters for `_theta_grid`, one per channel (optionally only those with depth in `only`)."""
        out = []
        for th, c, rp, spread, r_ref in self.channels:
            if only and not (only[0] <= c <= only[1]):
                continue
            # evenly round the circle the layers wrap, with a sample on each side exactly at its equator, so the
            # wrapped surfaces hug the tube with no wedge of empty space along its flanks
            out.append((th, rp / r_ref, n))
            out.append((th, 1.08 * rp / r_ref, 2, "even"))
            if spread > 0:
                out.append((th, 2.5 * rp / r_ref, n // 2, "even"))
        return out

    def __call__(self, d, *extras, push=True, fine=None):
        """Radius function of the surface at depth d plus `extras`, deflected round the channels. If the wall has
        `knots` (stations along it) the surface is made piecewise linear between them, so shells sampled at any
        superset of the knots meet their neighbours exactly however the wall swells; `fine` relief (the cells of
        the endothelium, the grain of the adventitia) is added on top at full resolution."""
        base = self.base(d)

        def g(T, S):
            v = base(T, S)
            for e in extras:
                v = v + (e(T, S) if callable(e) else e)
            return self.push(T, S, v, d) if (push and self.channels) else v

        knots = self.knots
        if knots is None and fine is None:
            return g

        def h(T, S):
            T, S = np.broadcast_arrays(np.asarray(T, np.float64), np.asarray(S, np.float64))
            if knots is None:
                v = g(T, S)
            else:
                j = np.clip(np.searchsorted(knots, S, side="right") - 1, 0, len(knots) - 2)
                s0, s1 = knots[j], knots[j + 1]
                w = (S - s0) / (s1 - s0)
                v = (1.0 - w) * g(T, s0) + w * g(T, s1)
            return v if fine is None else v + fine(T, S)
        return h


def _channel_tube(sw, W, theta, depth, rad, n=90, segments=18, seed=0):
    """The tube lying in a channel: a vessel, nerve or muscle bundle running the length of the segment, cut flush
    with both ends. The channel is only a hair wider than the tube (see `_Wall.channel`): any clearance is a slit
    through which the tube shows at grazing angles beyond the section."""
    s = np.linspace(0.0, 1.0, n)
    r = W(depth, push=False)(np.full(n, theta), s)
    return tube(sw.curve(s, np.full(n, theta), r), rad, segments)


def _wave(amp, n, seed, warp=2.2, s_freq=1.0, step=0.22, envelope=None):
    """Undulation of a wall surface round the circumference - the crenation of an elastic lamina fixed in a
    contracted vessel. n waves round the vessel, their phase wandering with position so they never look ruled,
    and their height varying from wave to wave. Returns f(T, S, k), k shifting the phase by `step` for the next
    lamella out so neighbours undulate nearly, but not exactly, in step. `envelope(T)` scales it (to fade it out
    where the angular grid is too coarse to carry it)."""
    wander = surf_noise(1.0, 2.6, s_freq, seed, octaves=2)
    height = surf_noise(1.0, 6.0, 1.4 * s_freq, seed + 1, octaves=2)

    def f(T, S, k=0.0):
        ph = n * T + warp * wander(T, S) + step * k
        v = np.sin(ph) + 0.22 * np.sin(2.0 * ph + 1.3)
        v = amp * v * np.clip(0.75 + 1.1 * height(T, S), 0.25, 1.4)
        return v if envelope is None else v * envelope(T)
    return f


def _knotted(field, xs):
    """A warp made piecewise linear in x between the planes x = xs. Shells sampled at different stations along a
    straight vessel stay in register under it as long as every station set contains those planes: a warp that
    curved between the stations of a coarsely sampled shell would carry its finely sampled neighbours through it."""
    xs = np.asarray(xs, np.float64)

    def f(p):
        x = np.clip(p[:, 0], xs[0], xs[-1])
        j = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, len(xs) - 2)
        w = ((x - xs[j]) / (xs[j + 1] - xs[j]))[:, None]
        q0, q1 = p.copy(), p.copy()
        q0[:, 0], q1[:, 0] = xs[j], xs[j + 1]
        return (1.0 - w) * field(q0) + w * field(q1)
    return f


def _fine_envelope(sw, span=math.radians(250), fade=math.radians(12)):
    """1 over the finely sampled span of `_theta_grid`, fading to 0 just inside its edges."""
    up = _theta_toward(sw, 0.5, (0.0, 1.0, 0.0))

    def f(T):
        return _smoothstep((span / 2 - np.abs(_wrap(T - up))) / fade)
    return f


# ------------------------------------------------------------------------------ adventitial surface furnishings
def _grain(amp, seed, L, R, helix=13.0, fine=True):
    """Relief of the adventitial surface: a directional grain of collagen fibres running in a shallow helix. Noise
    packed tightly across the fibres and stretched far along them gives fine ridges that run a long way and then
    merge or peter out, over a broad swell of fibre bundles. With fine=False only the broad swell is returned: the
    surface that vessels, nerves and bundles are laid on, so they do not jolt over every ridge they cross."""
    shear = math.tan(math.radians(helix)) * L / R
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


REST = -1.03             # strands on the adventitia rest on it: see _surface_tube


def _surface_tube(sw, outer, s, theta, rad, segments=8):
    """A strand resting on the outer surface of the adventitia, its centre a little over one radius above it. It is
    not sunk into the surface: a cut face is drawn at the depth where the view ray leaves the tissue, so anything
    bedded in the surface shows through the cut wherever the ray leaves beneath it."""
    s = np.asarray(s, np.float64)
    theta = np.broadcast_to(np.asarray(theta, np.float64), s.shape)
    rad = np.broadcast_to(np.asarray(rad, np.float64), s.shape)
    r = outer(theta, s) - rad * REST
    return tube(sw.curve(s, theta, r), rad, segments)


def _taper(u, length, rad, settle=0.10, thin=0.3):
    """Radius along a vessel or nerve lying on the adventitia that thins to `thin` of its calibre over the last
    `settle` model units at each end, where it would turn into the wall, and ends there in a rounded tip."""
    u = np.asarray(u, np.float64)
    rad = np.broadcast_to(np.asarray(rad, np.float64), u.shape)
    es = _smoothstep(u * length / settle) * _smoothstep((1.0 - u) * length / settle)
    return rad * (thin + (1.0 - thin) * es)


def _dense(u, *arrays, ends=0.05, length=1.0, n=24):
    """Resample a strand more closely over the last `ends` model units at each end, where it tapers."""
    e = min(ends / length, 0.5)
    uu = np.unique(np.concatenate([u, np.linspace(0.0, e, n), np.linspace(1.0 - e, 1.0, n)]))
    return (uu,) + tuple(np.interp(uu, u, np.asarray(a, np.float64)) for a in arrays)


def _path_length(s, th, L, R):
    return float(np.sum(np.hypot(np.diff(s) * L, np.diff(th) * R)))


def _beside(s, th, L, R, dist):
    """A path running beside (s, th) at `dist` model units, measured square to it on the unrolled surface."""
    x, y = s * L, th * R
    dx, dy = np.gradient(x), np.gradient(y)
    n = np.hypot(dx, dy) + 1e-12
    return (x - dy / n * dist) / L, (y + dx / n * dist) / R


def _bundles(sw, outer, count, seed, R, helix=13.0, spread=12.0, length=(1.0, 1.8), rad=(0.0115, 0.0135),
             clear=0.06, s_lo=0.0, s_hi=1.0, under=()):
    """Collagen bundles lying on the adventitia, following the helix of its grain give or take `spread` degrees.
    They are scattered - each placed as far from the others as a few tries allow, never within `clear` of one, so no
    two cross. Each is a flat ribbon of two or three strands crimped in step, resting on the surface, that thins away
    over a long stretch at each end, so it grows out of the grain and fades back into it. Where it meets a vessel or
    nerve in `under` (paths as (s, theta, radius)) it thins away beneath it, so the vessels lie on top of the
    collagen instead of being chopped into dashes by it."""
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
    pitch = -math.tan(math.radians(helix))
    step, edge = 0.0075, 0.06

    def candidate():
        ln = rng.uniform(*length)
        n = int(ln / step) + 1
        u = np.linspace(0.0, 1.0, n)
        x = rng.uniform(-0.40 * ln, span - 0.60 * ln) + u * ln
        slope = pitch + math.tan(math.radians(rng.uniform(-spread, spread)))
        ph = rng.uniform(0, 2 * math.pi)
        xm = x - x.mean()
        y = (rng.uniform(0.0, circ) + slope * xm + rng.uniform(-0.05, 0.05) * np.sin(math.pi * u)
             + 0.010 * np.sin(math.pi * u * rng.uniform(0.8, 1.8) + ph))
        env = (_smoothstep(u / 0.30) * _smoothstep((1.0 - u) / 0.30)
               * _smoothstep(x / edge) * _smoothstep((span - x) / edge))
        keep = env > 0.01
        if keep.sum() * step < 0.35:
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
        raised = rng.random() < 0.2
        rad0 = rng.uniform(*rad) * (1.2 if raised else 1.0)
        spacing = rad0 * 0.85
        gather = 0.25 + 0.75 * env ** 0.7
        crimp = 0.0012 * np.sin(2 * math.pi * x / rng.uniform(0.045, 0.060) + ph)
        for k in range(strands):
            base = (k - 0.5 * (strands - 1)) * spacing
            weave = 0.08 * spacing * np.sin(2 * math.pi * x / rng.uniform(0.40, 0.70) + ph + 1.9 * k)
            off = ((base + weave) * gather + crimp) / R
            edge_k = strands == 3 and k != 1
            prof = (0.82 if edge_k else 1.0) if strands == 3 else 0.92
            e_k = env ** 1.8 if edge_k else env
            r_k = rad0 * prof * rng.uniform(0.94, 1.06) * np.maximum(e_k, 0.02) ** 0.6
            th = y / R + off
            if tree is not None:
                d, idx = tree.query(np.stack([s * L, (th * R) % circ], 1))
                dip = 1.0 - _smoothstep((d - (vrad[idx] + r_k + 0.004)) / 0.02)
                w = max(3, int(round(0.05 / step)))
                dip = uniform_filter1d(maximum_filter1d(dip, w, mode="nearest"), w, mode="nearest")
                r_k = r_k * np.maximum(1.0 - dip, 0.02)
            m.extend(_surface_tube(sw, outer, s, th, r_k, 7))
    return m


def _surface_vasa(sw, outer, seed, R, trunks=4, venules=3, s_lo=0.0, s_hi=0.975, rad=(0.013, 0.016), avoid=()):
    """Vasa vasorum on the adventitia: a few small arteries running along it with branches curling round it, and
    beside some of them the thinner venules that drain the wall. Every vessel rests on the collagen and thins to a
    rounded tip at its ends, where it would turn into the wall. Trunks start at angles away from
    `avoid` (angles the caller keeps clear). Returns (arteries, venules, trunk paths, every strand as
    (s, theta, radius))."""
    rng = np.random.default_rng(seed)
    L = sw.length
    art, ven = Mesh(), Mesh()
    paths, strands = [], []
    for k in range(trunks):
        n = 90
        u = np.linspace(0.0, 1.0, n)
        s0 = s_lo + rng.uniform(0.02, 0.10)
        s1 = rng.uniform(0.88, s_hi)
        s = s0 + u * (s1 - s0)
        th0 = 2 * math.pi * k / trunks + rng.uniform(-0.4, 0.4)
        for a in avoid:
            if abs(_wrap(th0 - a)) < 0.35:
                th0 = a + math.copysign(0.35, _wrap(th0 - a) or 1.0)
        th = th0 + 0.22 * np.sin(1.7 * math.pi * u + k) + 0.08 * np.sin(5.3 * math.pi * u + 2 * k)
        r_t = rng.uniform(*rad) * (0.8 + 0.2 * np.sin(math.pi * u) ** 0.3)
        tlen = _path_length(s, th, L, R)
        uu, ss, tt, rr = _dense(u, s, th, r_t, length=tlen)
        art.extend(_surface_tube(sw, outer, ss, tt, _taper(uu, tlen, rr, settle=0.14), 10))
        paths.append((s, th))
        strands.append((s, th, r_t))
        heading = np.arctan2(np.gradient(th * R), np.gradient(s * L))
        for _ in range(int(rng.integers(3, 5))):
            i = int(rng.integers(12, n - 12))
            nb = 28
            v = np.linspace(0.0, 1.0, nb)
            bl = rng.uniform(0.16, 0.30)
            phi = (heading[i] + rng.choice([-1.0, 1.0]) * math.radians(rng.uniform(40.0, 70.0))
                   + rng.choice([-1.0, 1.0]) * rng.uniform(0.3, 0.8) * v ** 1.3)
            step = bl / (nb - 1)
            bx = s[i] * L + np.concatenate([[0.0], np.cumsum(np.cos(phi[:-1]) * step)])
            by = th[i] * R + np.concatenate([[0.0], np.cumsum(np.sin(phi[:-1]) * step)])
            bs, bt = bx / L, by / R
            ok = (bs > s_lo + 0.012) & (bs < s_hi + 0.01)
            stop = int(np.argmin(ok)) if not ok.all() else nb
            if stop < 8:
                continue
            bs, bt = bs[:stop], bt[:stop]
            blen = _path_length(bs, bt, L, R)
            w, bs, bt = _dense(np.linspace(0.0, 1.0, stop), bs, bt, length=blen, ends=0.04, n=20)
            brad = _taper(w, blen, r_t[i] * (0.62 - 0.12 * w), settle=0.33 * blen, thin=0.35)
            art.extend(_surface_tube(sw, outer, bs, bt, brad, 8))
            strands.append((bs, bt, brad))
        if k < venules:
            side = -1.0 if k % 2 else 1.0
            a, b = rng.uniform(0.04, 0.12), rng.uniform(0.88, 0.97)
            j = (u >= a) & (u <= b)
            w = np.linspace(0.0, 1.0, int(j.sum()))
            vr = rad[0] * rng.uniform(0.66, 0.8)
            gap = r_t[j] + vr + 0.006 + 0.004 * np.sin(3.1 * math.pi * w + k)
            vs, vt = _beside(s[j], th[j], L, R, side * gap)
            vlen = _path_length(vs, vt, L, R)
            w, vs, vt = _dense(w, vs, vt, length=vlen)
            vrad = _taper(w, vlen, vr, settle=0.12)
            ven.extend(_surface_tube(sw, outer, vs, vt, vrad, 8))
            strands.append((vs, vt, vrad))
    return art, ven, paths, strands


def _surface_nerves(sw, lay, trunks, R, rad=0.0042, count=3):
    """Nervi vasorum: thin nerves each keeping to one side of a vasa trunk on the adventitial surface."""
    L = sw.length
    nerves, strands = Mesh(), []
    for k, (s, th) in enumerate(trunks[:count]):
        off = (1 if k % 2 else -1) * (0.034 + 0.008 * np.sin(4.0 * math.pi * s + k))
        ns, nt = _beside(s, th, L, R, off)
        nlen = _path_length(ns, nt, L, R)
        w, ns, nt = _dense(np.linspace(0.0, 1.0, len(s)), ns, nt, length=nlen, ends=0.03)
        nrad = _taper(w, nlen, rad, settle=0.10)
        nerves.extend(_surface_tube(sw, lay, ns, nt, nrad, 7))
        strands.append((ns, nt, nrad))
    return nerves, strands


def _fat_pads(sw, outer, pads, seed, recess=0.0015):
    """Perivascular fat: broad, flat pads of adipocytes resting on the surface of the adventitia, smooth-unioned so
    the cells press softly into one another, and gathered into a few low lobules with shallow clefts (septa)
    between them. Each pad is (s, theta, cells, cell radius, spread along, spread round). A pad may run past the +x
    end, where it is cut off in the plane of the section."""
    rng = np.random.default_rng(seed)
    L = sw.length
    o_end, t_end = sw.path[-1].astype(np.float64), sw.t[-1].astype(np.float64)
    m = Mesh()

    def frame(s, th):
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
        pitch = rad * 1.55
        g = np.array([(i + 0.5 * (j % 2), j * 0.87) for i in range(-10, 11) for j in range(-10, 11)], float) * pitch
        g = g[np.argsort(np.hypot(g[:, 0] / along, g[:, 1] / round_))][:count]
        g += rng.normal(0.0, rad * 0.15, g.shape)
        n_lob = max(2, count // 18)
        seeds = g[rng.choice(len(g), n_lob, replace=False)]
        for _ in range(3):
            lab = np.argmin(np.linalg.norm(g[:, None, :] - seeds[None], axis=2), axis=1)
            seeds = np.array([g[lab == q].mean(axis=0) if np.any(lab == q) else seeds[q] for q in range(n_lob)])
        lab = np.argmin(np.linalg.norm(g[:, None, :] - seeds[None], axis=2), axis=1)
        to_c = seeds[lab] - g
        g = g + 0.10 * to_c
        dl = np.linalg.norm(to_c, axis=1)
        lob_r = np.array([max(float(dl[lab == q].max()), rad) if np.any(lab == q) else rad for q in range(n_lob)])
        dome = np.clip(1.0 - (dl / lob_r[lab]) ** 2, 0.0, 1.0)
        cs = np.clip(s0 + g[:, 0] / L, 0.02, None)
        ct = th0 + g[:, 1] / R
        radii = rad * rng.uniform(0.88, 1.12, count)
        flat = 0.60 + 0.18 * dome
        # resting on the adventitia, clear of it by the growth of the smooth union and the displacement
        lift = radii * (flat + 0.12 * dome) + 0.004
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
            v.add(sh, "smooth", rad * 0.26)
        v.displace(0.0012, 30.0, 2, seed=int(rng.integers(1, 9999)))
        x, y, z = v.axes()
        cut = (x - o_end[0]) * t_end[0] + (y - o_end[1]) * t_end[1] + (z - o_end[2]) * t_end[2] + recess
        np.maximum(v.d, cut.astype(np.float32), out=v.d)
        m.extend(v.mesh(0.7))
    return m


# ------------------------------------------------------------------------------------------------------ blood
def _leukocyte(c, radius, bumps, bump_r, rng, voxel=0.0030):
    v = Volume(c - radius * 1.6, c + radius * 1.6, voxel)
    v.add(ellipsoid(c, (radius, radius * 0.88, radius * 0.95)))
    for _ in range(bumps):
        d = rng.normal(size=3)
        d /= np.linalg.norm(d)
        v.add(ellipsoid(c + d * radius * 0.86, (bump_r, bump_r, bump_r)), "smooth", bump_r * 0.8)
    return v


def _blood(sw, lumen, parts, rng, n_rbc, rbc_r=0.032, wbc=(0.62, 0.045), keep_out=None, extra=()):
    """A sparse scatter of red cells down the lumen - enough to say 'blood' without filling it - and one leukocyte
    rolling on the endothelium. `keep_out(points)` -> distances to anything in the lumen the cells must clear (the
    valve cusps); `extra` are extra cell centres (the red cells caught in a valve sinus)."""
    rbc = Mesh()
    placed = [np.asarray(c, np.float64) for c in extra]
    for c in extra:
        rbc.extend(red_cell(c, rng.normal(size=3), rbc_r))
    tries = 0
    while len(placed) < n_rbc + len(extra) and tries < n_rbc * 30:
        tries += 1
        s = np.array([rng.uniform(0.04, 0.96)])
        th = np.array([rng.uniform(0, 2 * math.pi)])
        r = np.array([(float(lumen(th, s)[0]) - rbc_r * 1.6) * math.sqrt(rng.uniform(0.0, 0.92))])
        c = sw.curve(s, th, r)[0]
        if placed and np.min(np.linalg.norm(np.array(placed) - c, axis=1)) < rbc_r * 3.6:
            continue
        if keep_out is not None and keep_out(c[None])[0] < rbc_r * 1.5:
            continue
        placed.append(c)
        rbc.extend(red_cell(c, rng.normal(size=3), rbc_r))
    parts.append(mesh_part(rbc, "Red blood cells", "Blood", "#c3302a", _RBC, "artery", rank=-1,
                           detail=(0.03, 0.0, 0.0, 0)))
    s_w, rad = wbc
    s = np.array([s_w])
    th = np.array([_theta_toward(sw, s_w, (0.0, -0.55, -0.83))])
    c = sw.curve(s, th, np.array([float(lumen(th, s)[0]) - rad * 0.92]))[0]
    parts.append(sdf_part(_leukocyte(c, rad, 40, rad * 0.24, rng), "Rolling leukocyte", "Blood", "#e9e4f2",
                          _WBC, "lymph", smooth=0.75, rank=-1, detail=(0.05, 60.0, 0.9, 0)))


def _part(parts, name, group, color, mesh, desc, cat, rank, detail, bulk=False):
    parts.append(Part(name, group, color, mesh, desc, category=cat, clip=True, bulk=bulk, rank=rank, detail=detail))


def _adventitia_outside(sw, W, d_out, seed, R, *, bundles, trunks, venules, nerves, pads, vasa_rad=(0.013, 0.016),
                        bundle_rad=(0.0115, 0.0135), grain=0.003, avoid=()):
    """The outer surface of the adventitia and what lies on it: the grained collagen surface itself (returned as the
    radius function for the outer shell), collagen bundles, vasa vasorum with their venules, nervi vasorum and
    perivascular fat."""
    L = sw.length
    outer = W(d_out, fine=_grain(grain, seed, L, R))
    lay = W(d_out, fine=_grain(grain, seed, L, R, fine=False))
    vasa, ven, paths, on_top = _surface_vasa(sw, lay, seed + 1, R, trunks=trunks, venules=venules, rad=vasa_rad,
                                             avoid=avoid)
    nv, n_strands = _surface_nerves(sw, lay, paths, R, count=nerves)
    on_top += n_strands
    coll = _bundles(sw, lay, bundles, seed + 2, R, rad=bundle_rad, under=on_top)
    fat = _fat_pads(sw, lay, pads, seed + 3) if pads else Mesh()
    return outer, dict(collagen=coll, vasa=vasa, venules=ven, nerves=nv, fat=fat)


def _finish_adventitia(parts, furn, deep_vasa, deep_nerves, vasa_desc, nervi_desc, venule=True):
    parts.append(mesh_part(furn["collagen"], "Adventitial collagen bundles", "Tunica adventitia", "#d9b882", _COLLAGEN,
                           "fascia", rank=2.2, detail=(0.05, 45.0, 0.10, 1)))
    vasa = Mesh().extend(furn["vasa"]).extend(deep_vasa)
    parts.append(mesh_part(vasa, "Vasa vasorum", "Tunica adventitia", "#b8242a", vasa_desc, "artery", rank=2.5,
                           detail=(0.05, 110.0, 0.5, 1)))
    if venule and furn["venules"].parts:
        parts.append(mesh_part(furn["venules"], "Vasa vasorum venules", "Tunica adventitia", "#6e2440", _VENULE,
                               "vein", rank=2.5))
    nerves = Mesh().extend(furn["nerves"]).extend(deep_nerves)
    parts.append(mesh_part(nerves, "Nervi vasorum", "Tunica adventitia", "#ece6a8", nervi_desc, "nerve", rank=2.5,
                           detail=(0.05, 160.0, 0.3, 1)))
    if furn["fat"].parts:
        parts.append(mesh_part(furn["fat"], "Perivascular fat", "Tunica adventitia", "#f3d272", _FAT, "fat", rank=3,
                               detail=(0.04, 22.0, 0.08, 0)))


def _pads(sw, spec):
    """Fat pads as (distance back from the +x end, world direction, cells, cell radius, along, round)."""
    out = []
    for back, direction, count, cell, along, round_ in spec:
        s_p = 1.0 - back / sw.length
        out.append((s_p, _theta_toward(sw, s_p, direction), count, cell, along, round_))
    return out


# ================================================================================================ muscular artery
# Depths from the lumen, model units. Lumen radius 0.42 and wall 0.28: a muscular artery's wall is about two thirds
# of its lumen radius (radial artery: ~1 mm of wall round a ~3 mm lumen), with the media over half of it and the
# adventitia a little thinner than the media. The elastic laminae are drawn much thicker than their 1-2 µm so they
# can be seen at all.
MA_LUMEN = 0.42
MA = dict(endo=0.0048, subendo=0.0095, iel=0.0200, media=0.1640, eel=0.1700, adv_mid=0.2150, adv=0.2800)


def build_muscular():
    rng = np.random.default_rng(11)
    sw = _vessel_sweep(2.0, bend=(0.06, -0.04), wobble=0.012, seed=7)
    L = sw.length
    W = _Wall(MA_LUMEN, 7, calibre=0.02, oval=0.03, oval_dir=0.7, swell=0.004)
    W.knots = st = np.linspace(0.0, 1.0, 33)
    d = MA
    R_out = MA_LUMEN + d["adv"]
    # channels: small vasa vasorum and nerves in the adventitia, cut across by the section
    up = _theta_toward(sw, 0.5, (0.0, 1.0, 0.0))
    deep_vasa, deep_nerves = Mesh(), Mesh()
    for k, (off, rad, kind) in enumerate(((-0.95, 0.011, "v"), (-0.55, 0.0065, "n"), (-0.05, 0.009, "v"),
                                          (0.42, 0.012, "v"), (0.70, 0.006, "n"), (1.05, 0.008, "v"),
                                          (2.4, 0.010, "v"), (3.6, 0.009, "v"))):
        (deep_vasa if kind == "v" else deep_nerves).extend(W.tube_in(sw, up + off, d["adv_mid"] + SEAM / 2, rad))

    # IEL crenation: every surface of the intima follows it, and the media fills it in within a short depth
    cren = _wave(0.0085, 34, 71, warp=2.6)
    eelw = _wave(0.0022, 52, 72, warp=2.0)

    def fold(depth):
        a = 1.0 if depth <= d["iel"] else math.exp(-(depth - d["iel"]) / 0.018)
        b = math.exp(-abs(depth - d["eel"]) / 0.010)
        return lambda T, S: a * cren(T, S) + b * eelw(T, S)

    th_fine = _theta_grid(sw, math.radians(0.55), math.radians(1.4))
    th_adv = _theta_grid(sw, math.radians(0.55), math.radians(1.4), clusters=W.clusters())
    st_fine = np.union1d(st, np.linspace(0.0, 1.0, 96))
    endo_cells = cells_on(0.046, 1.0, 41, aspect=2.2, groove=0.22, dome=0.6, r_typ=MA_LUMEN, length=L)
    parts = []

    def lay(depth, fine=None):
        return W(depth, fold(depth), fine=fine)

    _part(parts, "Endothelium", "Tunica intima", "#e7a2ab",
          _shell(sw, lay(0.0, lambda T, S: -0.0032 * endo_cells(T, S) - 0.0016), lay(d["endo"]), th_fine, st_fine),
          _ENDO, "fascia", 0, (0.05, 170.0, 0.9, 1))
    _part(parts, "Subendothelial layer", "Tunica intima", "#efd6cb",
          _shell(sw, lay(d["endo"] + GAP), lay(d["subendo"]), th_fine, st), _SUBENDO_M, "fascia", 0,
          (0.06, 120.0, 0.3, 1))
    _part(parts, "Internal elastic lamina", "Tunica intima", "#f1cf5e",
          _shell(sw, lay(d["subendo"] + GAP), lay(d["iel"]), th_fine, st), _IEL_M, "cartilage", 0.5,
          (0.02, 0.0, 0.0, 0))
    _part(parts, "Tunica media (smooth muscle)", "Tunica media", "#b4524c",
          _shell(sw, lay(d["iel"] + GAP), lay(d["media"]), th_fine, st), _MEDIA_M, "muscle", 1,
          (0.07, 135.0, 0.62, 4))
    _part(parts, "External elastic lamina", "Tunica media", "#ecd27e",
          _shell(sw, lay(d["media"] + GAP), lay(d["eel"]), th_fine, st), _EEL_M, "cartilage", 1.5,
          (0.02, 0.0, 0.0, 0))

    pads = _pads(sw, ((0.20, (0.0, -0.8, -0.6), 44, 0.030, 3.0, 1.3), (0.62, (0.0, 0.45, -0.89), 40, 0.028, 2.6,
                                                                         1.4)))
    outer, furn = _adventitia_outside(sw, W, d["adv"], 91, R_out, bundles=26, trunks=3, venules=2, nerves=2,
                                      pads=pads, vasa_rad=(0.011, 0.013),
                                      bundle_rad=(0.009, 0.011))
    adv = Mesh()
    adv.extend(_shell(sw, lay(d["eel"] + ZONE_GAP), W(d["adv_mid"]), th_adv, st))
    adv.extend(_shell(sw, W(d["adv_mid"] + SEAM), outer, th_adv, st_fine))
    _part(parts, "Tunica adventitia", "Tunica adventitia", "#d7b27f", adv, _ADV_M, "fascia", 2,
          (0.10, 70.0, 0.22, 1), bulk=True)
    _finish_adventitia(parts, furn, deep_vasa, deep_nerves, _VASA_M, _NERVI)
    _blood(sw, lay(0.0), parts, rng, 22, rbc_r=0.030, wbc=(0.70, 0.040))
    warp_parts(parts, noise_field((0.008, 0.008, 0.008), 1.0, 3, seed=int(rng.integers(1, 500))))
    return parts


# ================================================================================================= elastic artery
# Lumen radius 0.70 and wall 0.165: the aorta is a wide, relatively thin-walled conduit (about 2 mm of wall round a
# 25 mm lumen). The wall is drawn a little thicker than in life so the lamellae can be told apart, but still under a
# quarter of the lumen radius, against two thirds for the muscular artery. A thin intima (a tenth of the wall), a
# media that is most of it, and an adventitia under half the media.
EA_LUMEN = 0.70
EA = dict(endo=0.0040, subendo=0.0130, media_in=0.0130, media_out=0.1180, adv_mid=0.1350, adv=0.1650)
EA_LAMELLAE = 24         # counting the internal and external laminae: standing in for the 40-70 of an adult aorta


def build_aorta():
    """Elastic artery (aortic wall). The media is a stack of separate shells: the internal elastic lamina, then
    muscle and lamella alternating out to the external elastic lamina. Each lamella undulates round the vessel,
    nearly in step with its neighbours, and is broken here and there by a fenestration where the muscle on either
    side meets through it; the outer lamellae part round the vasa vasorum that penetrate the outer media.

    The segment is built straight and of constant calibre, so its layers need only a handful of stations along it
    and every sample can go into the angle, where the undulation of the lamellae needs it; the shared warp at the
    end bends and swells the whole wall together."""
    rng = np.random.default_rng(22)
    sw = _vessel_sweep(2.0, bend=(0.0, 0.0), wobble=0.0, seed=13)
    L = sw.length
    W = _Wall(EA_LUMEN, 13, calibre=0.0, swell=0.005, swell_s=0.0)
    d = EA
    R_out = EA_LUMEN + d["adv"]
    up = _theta_toward(sw, 0.5, (0.0, 1.0, 0.0))
    n = EA_LAMELLAE
    t_lam, t_iel, t_eel = 0.0017, 0.0024, 0.0020
    c0, c1 = d["media_in"] + t_iel / 2, d["media_out"] - t_eel / 2
    centres = c0 + np.arange(n) * (c1 - c0) / (n - 1)

    # vasa in the outer media, each lying on the outer face of a lamella in the outer third, and vessels and nerves
    # in the adventitia; all run along the vessel and are cut across by the section
    deep_vasa, deep_nerves = Mesh(), Mesh()
    media_ch = []
    for k, (off, lam, rad) in enumerate(((-0.80, n - 4, 0.0070), (-0.30, n - 7, 0.0060), (0.35, n - 5, 0.0075),
                                         (0.95, n - 6, 0.0065), (2.9, n - 4, 0.0070))):
        th = up + off
        deep_vasa.extend(W.tube_in(sw, th, centres[lam] + t_lam / 2 + GAP / 2, rad, spread=1.3, segments=16))
        media_ch.append((th, rad))
    for k, (off, rad, kind) in enumerate(((-1.10, 0.0090, "v"), (-0.62, 0.0050, "n"), (0.05, 0.0080, "v"),
                                          (0.60, 0.0048, "n"), (1.20, 0.0085, "v"), (3.4, 0.0080, "v"))):
        (deep_vasa if kind == "v" else deep_nerves).extend(W.tube_in(sw, up + off, d["adv_mid"] + SEAM / 2, rad))

    # ~9 lamellar spacings to a wave, neighbours a little out of step; only where the angular grid can carry it
    wave = _wave(0.0013, 120, 301, warp=2.6, s_freq=0.0, step=0.45, envelope=_fine_envelope(sw))
    holes = surf_noise(1.0, 60.0, 2.5, 303, octaves=2)

    def far(T, near=2.5, ramp=2.0):
        """0 close to a vessel in the media, where the lamellae must stay whole and smooth to part round it, else 1."""
        v = np.ones_like(T)
        for th, rad in media_ch:
            v = v * _smoothstep((np.abs(_wrap(T - th)) * 0.8 - near * rad) / (ramp * rad))
        return v

    def wav(k):
        # the undulation is strongest mid-media and a little flatter at either lamina; it dies away beside a vessel,
        # so the vessel lies between two lamellae instead of inside a wave of one
        f = 0.6 + 0.4 * math.sin(math.pi * k / (n - 1))
        return lambda T, S: f * wave(T, S, k) * far(T, 1.2, 3.0)

    def half(k, sign, t):
        """Radius term of one face of lamella k: its half-thickness, pinched almost to nothing at fenestrations."""
        if k in (0, n - 1):
            return lambda T, S: sign * 0.5 * t

        def g(T, S):
            h = holes(T + 0.7 * k, S + 0.37 * k)
            pinch = 1.0 - 0.94 * _smoothstep((h - 0.40) / 0.05) * far(T)
            return sign * 0.5 * t * pinch
        return g

    th_media = _theta_grid(sw, math.radians(0.45), math.radians(2.4), clusters=W.clusters(only=(0.0, d["media_out"])))
    th_adv = _theta_grid(sw, math.radians(0.55), math.radians(1.5), clusters=W.clusters(only=(d["media_out"], 1.0)))
    st_fine = np.linspace(0.0, 1.0, 46)
    st_media = np.linspace(0.0, 1.0, 6)
    parts = []

    endo_cells = cells_on(0.046, 1.0, 51, aspect=2.6, groove=0.22, dome=0.6, r_typ=EA_LUMEN, length=L)
    iel_w = wav(0)
    _part(parts, "Endothelium", "Tunica intima", "#e7a2ab",
          _shell(sw, W(0.0, lambda T, S: -0.003 * endo_cells(T, S) - 0.0015, lambda T, S: 0.5 * iel_w(T, S)),
                 W(d["endo"], lambda T, S: 0.5 * iel_w(T, S)), th_media, st_fine), _ENDO, "fascia", 0,
          (0.05, 170.0, 0.9, 1))
    _part(parts, "Subendothelial layer", "Tunica intima", "#efd6cb",
          _shell(sw, W(d["endo"] + GAP, lambda T, S: 0.5 * iel_w(T, S)),
                 W(centres[0], iel_w, half(0, -1, t_iel), -GAP), th_media, st_media), _SUBENDO_A, "fascia", 0,
          (0.07, 150.0, 0.35, 0))

    lam, muscle = Mesh(), Mesh()
    iel = eel = None
    for k in range(n):
        t = t_iel if k == 0 else (t_eel if k == n - 1 else t_lam)
        w = wav(k)
        shell = _shell(sw, W(centres[k], w, half(k, -1, t)), W(centres[k], w, half(k, 1, t)), th_media, st_media)
        if k == 0:
            iel = shell
        elif k == n - 1:
            eel = shell
        else:
            lam.extend(shell)
        if k < n - 1:
            w2 = wav(k + 1)
            t2 = t_eel if k + 1 == n - 1 else t_lam
            muscle.extend(_shell(sw, W(centres[k], w, half(k, 1, t), GAP),
                                 W(centres[k + 1], w2, half(k + 1, -1, t2), -GAP), th_media, st_media))
    _part(parts, "Internal elastic lamina", "Tunica intima", "#efc760", iel, _IEL_A, "cartilage", 0.5,
          (0.02, 0.0, 0.0, 0))
    _part(parts, "Tunica media (smooth muscle)", "Tunica media", "#b0554e", muscle, _MEDIA_A, "muscle", 1,
          (0.06, 230.0, 0.55, 4))
    _part(parts, "Elastic lamellae", "Tunica media", "#f2da8c", lam, _LAMELLAE, "cartilage", 1, (0.02, 0.0, 0.0, 0))
    _part(parts, "External elastic lamina", "Tunica media", "#ead08a", eel, _EEL_A, "cartilage", 1.5,
          (0.02, 0.0, 0.0, 0))

    pads = _pads(sw, ((0.14, (0.0, 0.35, 0.94), 46, 0.032, 3.0, 1.4), (0.10, (0.0, -0.75, -0.66), 38, 0.030, 3.0, 1.3),
                      (0.55, (0.0, 0.94, -0.34), 34, 0.028, 3.0, 1.5)))
    outer, furn = _adventitia_outside(sw, W, d["adv"], 91, R_out, bundles=22, trunks=5, venules=3, nerves=3,
                                      pads=pads)
    adv = Mesh()
    adv.extend(_shell(sw, W(centres[-1], wav(n - 1), half(n - 1, 1, t_eel), ZONE_GAP), W(d["adv_mid"]), th_adv,
                      st_media))
    adv.extend(_shell(sw, W(d["adv_mid"] + SEAM), outer, th_adv, st_fine))
    _part(parts, "Tunica adventitia", "Tunica adventitia", "#d2aa74", adv, _ADV_A, "fascia", 2,
          (0.10, 70.0, 0.22, 1), bulk=True)
    _finish_adventitia(parts, furn, deep_vasa, deep_nerves, _VASA_A, _NERVI)
    _blood(sw, W(0.0), parts, rng, 30, rbc_r=0.032, wbc=(0.62, 0.046))
    # the segment gets its bend and swelling from the warp, kept linear between the stations of the media
    bend = noise_field((0.035, 0.035, 0.035), 0.45, 2, seed=int(rng.integers(1, 500)))
    fine = noise_field((0.008, 0.008, 0.008), 1.0, 3, seed=int(rng.integers(1, 500)))
    xs = sw.curve(st_media, np.zeros(len(st_media)), np.zeros(len(st_media)))[:, 0]
    warp_parts(parts, _knotted(lambda p: bend(p) + fine(p), xs))
    return parts


# ============================================================================================================ vein
# Lumen radius about 0.56 (wider and flatter than the artery's, and irregular), wall 0.15: a vein's wall is about a
# quarter of its lumen radius, and most of it is adventitia - the media is a thin band of muscle.
VN_LUMEN = 0.56
VN = dict(endo=0.0045, subendo=0.0120, media=0.0440, adv_a=0.0820, adv_b=0.1190, adv=0.1500)
# The valve, as stations along the vessel (0 at the -x end). Blood flows towards -x, where the heart is: each cusp is
# attached along a U-shaped line whose deepest (most upstream) point is at VALVE_BASE, and whose commissures reach
# VALVE_H further towards the heart, and its free edge points the same way. It sits in the opened half, so the
# default cut shows both cusps in section, and their sinus pockets open towards the default viewpoint.
VALVE_BASE, VALVE_H, VALVE_DIR = 0.47, 0.27, -1.0


def _sinus(theta_c):
    """The wall bulges at the valve sinuses, most over the middle of each cusp."""
    s_c, w = VALVE_BASE + VALVE_DIR * 0.6 * VALVE_H, 0.55 * VALVE_H

    def g(T, S):
        return 0.14 * np.exp(-((S - s_c) / w) ** 2) * (0.30 + 0.70 * np.cos(T - theta_c) ** 2)
    return g


def _closed_sheet(P, t):
    """A closed sheet of thickness t (per sample) round the mid-surface grid P (nu x nv x 3): two offset faces and
    a rounded rim stitched round the whole boundary."""
    du = np.gradient(P, axis=0)
    dv = np.gradient(P, axis=1)
    N = np.cross(du, dv)
    N /= np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-12)
    top = P + N * (t[..., None] / 2)
    bot = P - N * (t[..., None] / 2)
    nu, nv = P.shape[:2]
    a = np.arange(nu * nv).reshape(nu, nv)
    q0, q1, q2, q3 = a[:-1, :-1].ravel(), a[1:, :-1].ravel(), a[1:, 1:].ravel(), a[:-1, 1:].ravel()
    grid = np.vstack([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
    off = nu * nv
    ring = ([a[i, 0] for i in range(nu)] + [a[nu - 1, j] for j in range(1, nv)]
            + [a[i, nv - 1] for i in range(nu - 2, -1, -1)] + [a[0, j] for j in range(nv - 2, 0, -1)])
    ring = np.array(ring)
    r0, r1 = ring, np.roll(ring, -1)
    rim = np.vstack([np.stack([r0, r1 + off, r1], 1), np.stack([r0, r0 + off, r1 + off], 1)])
    idx = np.vstack([grid, grid[:, ::-1] + off, rim])
    return orient_outward(Mesh().add(np.vstack([top.reshape(-1, 3), bot.reshape(-1, 3)]), idx))


def _valve(sw, lumen, theta_side, gap=0.012):
    """Two cusps, each a pocket of intima. Cusp k is centred on angle theta_side + k*pi: it is attached to the wall
    along a U-shaped line (lowest, i.e. most upstream, over its middle, rising to the two commissures), leaves the
    wall heading inwards and curves downstream to a free edge that lies just short of the plane through both
    commissures - so the two free edges meet across the lumen with a narrow slit between them, and behind each cusp
    a sinus opens downstream. Returns the mesh and a distance function to it."""
    from scipy.spatial import cKDTree
    m = Mesh()
    s0, h = VALVE_BASE, VALVE_DIR * VALVE_H
    n_phi, n_v = 57, 30
    phi = np.linspace(-math.pi / 2, math.pi / 2, n_phi)
    v = np.linspace(0.0, 1.0, n_v)
    pockets = []
    for k in range(2):
        tc = theta_side + k * math.pi
        th_a = tc + phi
        s_a = s0 + h * (1.0 - np.cos(phi))
        r_a = lumen(th_a, s_a) - 0.004
        r_c = float(np.mean(lumen(np.array([tc + math.pi / 2, tc - math.pi / 2]), np.array([s0 + h] * 2)))) - 0.004
        ua, wa = r_a * np.cos(phi), r_a * np.sin(phi)
        uf, wf = np.full(n_phi, gap), r_c * np.sin(phi)
        s_f = s0 + h - 0.10 * h * np.cos(phi)
        # the belly: from the wall the cusp heads inwards first, then turns downstream to its free edge
        uc, wc = 0.42 * ua + 0.58 * uf, 0.5 * (wa + wf)
        s_c = s_a + 0.12 * (s_f - s_a)
        V = v[None, :]
        b0, b1, b2 = (1 - V) ** 2, 2 * V * (1 - V), V ** 2
        U = b0 * ua[:, None] + b1 * uc[:, None] + b2 * uf[:, None]
        Wl = b0 * wa[:, None] + b1 * wc[:, None] + b2 * wf[:, None]
        S = b0 * s_a[:, None] + b1 * s_c[:, None] + b2 * s_f[:, None]
        T = tc + np.arctan2(Wl, U)
        Rr = np.hypot(U, Wl)
        P = sw.curve(S.ravel(), T.ravel(), Rr.ravel()).reshape(n_phi, n_v, 3)
        # thickest at the root, thin over the belly, with a slightly thickened free margin
        t = 0.010 * (1.0 - v) + 0.0055 * v + 0.004 * _smoothstep((v - 0.85) / 0.15)
        t = np.broadcast_to(t[None, :], (n_phi, n_v)) * (0.55 + 0.45 * np.cos(phi)[:, None] ** 0.5)
        m.extend(_closed_sheet(P, np.ascontiguousarray(t)))
        pockets.append((tc, S, Rr, T))
    pos = np.vstack([p for p, _, _ in m.parts])
    tree = cKDTree(pos)
    return m, (lambda q: tree.query(q)[0]), pockets


def build_vein():
    rng = np.random.default_rng(33)
    sw = _vessel_sweep(2.0, bend=(-0.06, 0.05), wobble=0.014, seed=19)
    L = sw.length
    side = _theta_toward(sw, 0.3, (0.0, 0.0, 1.0))
    # flattened (a vein partly collapses) with its long axis along the cusps, bulging at the valve sinuses
    W = _Wall(VN_LUMEN, 19, calibre=0.03, oval=0.10, oval_dir=side, swell=0.006, bulge=_sinus(side))
    W.knots = st = np.linspace(0.0, 1.0, 41)
    d = VN
    irregular = surf_noise(0.020, 2.2, 1.2, 23, octaves=2)
    up = _theta_toward(sw, 0.5, (0.0, 1.0, 0.0))

    def irr(depth):
        f = math.exp(-depth / 0.12)
        return lambda T, S: f * irregular(T, S)

    # longitudinal smooth muscle bundles in two staggered rows in the adventitia, with vasa and nerves among them
    deep_vasa, deep_nerves, bundles = Mesh(), Mesh(), Mesh()
    n_b = 22
    for k in range(n_b):
        th = up + 2 * math.pi * (k + rng.uniform(-0.18, 0.18)) / n_b
        depth, rad = (d["adv_a"], rng.uniform(0.015, 0.021)) if k % 2 == 0 else (d["adv_b"], rng.uniform(0.012, 0.017))
        bundles.extend(W.tube_in(sw, th, depth + SEAM / 2, rad, spread=0.0, segments=22))
    # vasa and nerves in the gaps between bundles (offsets in bundle spacings)
    for k, (off, rad, kind) in enumerate(((0.5, 0.0085, "v"), (-4.5, 0.009, "v"), (-2.5, 0.0055, "n"),
                                          (3.5, 0.008, "v"), (6.5, 0.005, "n"))):
        depth = d["adv_a"] if k % 2 else d["adv_b"]
        (deep_vasa if kind == "v" else deep_nerves).extend(
            W.tube_in(sw, up + off * 2 * math.pi / n_b, depth + SEAM / 2, rad, spread=0.0))

    th_in = _theta_grid(sw, math.radians(0.6), math.radians(1.5))
    # each shell of the adventitia needs dense angles only round the channels on its own two surfaces
    th_a = _theta_grid(sw, math.radians(0.6), math.radians(1.5), clusters=W.clusters(13, (0.0, d["adv_a"] + SEAM)))
    th_ab = _theta_grid(sw, math.radians(0.6), math.radians(1.5), clusters=W.clusters(13))
    th_b = _theta_grid(sw, math.radians(0.6), math.radians(1.5), clusters=W.clusters(13, (d["adv_b"], 1.0)))
    st_fine = np.union1d(st, np.linspace(0.0, 1.0, 61))
    endo_cells = cells_on(0.05, 1.0, 61, aspect=1.9, groove=0.22, dome=0.6, r_typ=VN_LUMEN, length=L)
    parts = []

    def lay(depth, fine=None):
        return W(depth, irr(depth), fine=fine)

    lumen = lay(0.0)
    _part(parts, "Endothelium", "Tunica intima", "#e3aab8",
          _shell(sw, lay(0.0, lambda T, S: -0.003 * endo_cells(T, S) - 0.0015), lay(d["endo"]), th_in, st_fine),
          _ENDO_VEIN, "fascia", 0, (0.05, 170.0, 0.9, 1))
    _part(parts, "Subendothelial layer", "Tunica intima", "#efd9d2",
          _shell(sw, lay(d["endo"] + GAP), lay(d["subendo"]), th_in, st), _SUBENDO_V, "fascia", 0,
          (0.06, 120.0, 0.3, 1))
    valve, valve_dist, pockets = _valve(sw, lumen, side)
    parts.append(mesh_part(valve, "Venous valve cusps", "Tunica intima", "#f2c4cf", _VALVE, "fascia", rank=0,
                           detail=(0.05, 150.0, 0.45, 0)))
    _part(parts, "Tunica media (smooth muscle)", "Tunica media", "#b7615f",
          _shell(sw, lay(d["subendo"] + GAP), lay(d["media"]), th_in, st),
          _MEDIA_V, "muscle", 1, (0.08, 140.0, 0.5, 4))

    pads = _pads(sw, ((0.20, (0.0, -0.7, -0.7), 50, 0.032, 3.0, 1.3), (0.55, (0.0, 0.5, 0.86), 46, 0.030, 2.8, 1.4)))
    R_out = VN_LUMEN + d["adv"]
    outer, furn = _adventitia_outside(sw, W, d["adv"], 97, R_out, bundles=24, trunks=4, venules=0, nerves=2,
                                      pads=pads, vasa_rad=(0.011, 0.014),
                                      bundle_rad=(0.010, 0.012))
    adv = Mesh()
    adv.extend(_shell(sw, lay(d["media"] + ZONE_GAP), W(d["adv_a"]), th_a, st))
    adv.extend(_shell(sw, W(d["adv_a"] + SEAM), W(d["adv_b"]), th_ab, st))
    adv.extend(_shell(sw, W(d["adv_b"] + SEAM), outer, th_b, st_fine))
    _part(parts, "Tunica adventitia", "Tunica adventitia", "#d9b98c", adv, _ADV_V, "fascia", 2,
          (0.10, 70.0, 0.22, 1), bulk=True)
    parts.append(mesh_part(bundles, "Longitudinal smooth muscle bundles", "Tunica adventitia", "#b7615f",
                           _LONG_MUSCLE, "muscle", rank=2, detail=(0.07, 140.0, 0.55, 1)))
    _finish_adventitia(parts, furn, deep_vasa, deep_nerves, _VASA_V, _NERVI_V, venule=False)

    # a few red cells caught in the sinus pocket behind each cusp - where stasis starts a thrombus
    extra = []
    for tc, S, Rr, T in pockets:
        for _ in range(3):
            for _try in range(40):
                s = VALVE_BASE + VALVE_DIR * VALVE_H * rng.uniform(0.35, 0.8)
                th = tc + rng.uniform(-0.5, 0.5)
                r = float(lumen(np.array([th]), np.array([s]))[0]) * rng.uniform(0.62, 0.82)
                c = sw.curve(np.array([s]), np.array([th]), np.array([r]))[0]
                if valve_dist(c[None])[0] > 0.05 and all(np.linalg.norm(c - e) > 0.1 for e in extra):
                    extra.append(c)
                    break
    _blood(sw, lumen, parts, rng, 30, rbc_r=0.032, wbc=(0.78, 0.045), keep_out=valve_dist, extra=extra)
    warp_parts(parts, noise_field((0.008, 0.008, 0.008), 1.0, 3, seed=int(rng.integers(1, 500))))
    return parts


def build_vessel(kind="muscular"):
    return {"muscular": build_muscular, "elastic": build_aorta, "vein": build_vein}[kind]()
