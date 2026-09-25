"""The cardiac cycle of the heart model: how the heart deforms and when its valves and conduction system act.

Built once with the model (heart.build_heart calls attach_motion) as four morph targets per vertex, in the heart
frame of heart.py and then turned into the body:

* 0 - ventricular systole: the atrioventricular (AV) plane descends towards the nearly stationary apex (long-axis
  shortening, ~12 mm), the ventricular walls thicken as the cavities empty - an incompressible thick-walled
  cylinder about the LV long axis, so the endocardium moves far more than the epicardium and the RV free wall
  moves in towards the septum like a bellows - and the LV wrings (apex anticlockwise, base clockwise seen from the
  apex). The atria and great-vessel roots are pulled down with the AV plane, fading with height;
* 1 - atrial systole: each atrium shrinks towards its centre;
* 2, 3 - a valve opening, as the linear and quadratic terms of a path through the half-open pose, so the cusps
  swing on their hinges instead of shrinking along a chord: AV cusps rotate about the annulus down into the
  ventricle, semilunar cusps fold back against the sinus wall; chordae follow their cusps and slacken.

Conduction-system vertices carry an activation phase (fraction of the cycle at which the impulse reaches them) for
the travelling glow: SA node -> internodal pathways and Bachmann's bundle -> AV node (the delay) -> bundle of His
-> bundle branches -> Purkinje fibres.

The timing (heart_animation) is one 1 s beat (60/min): P wave 0-80 ms, PR ~150 ms, QRS ~150-230 ms, AV valves close
at 220 ms (S1), ejection 270-550 ms, semilunar valves close at 550 ms (S2), AV valves reopen at ~650 ms."""
import math

import numpy as np
from scipy.spatial import cKDTree

from . import heart as H
from .anim import MODE_WAVE, Animation, Track, ramp, window

DELTA_AV = 0.20            # AV-plane descent in systole (units: 1 = 6 cm)
EPS_OUT = 0.05             # fractional shortening of the LV outer radius
LAMBDA = 0.88              # long-axis length ratio in systole
BELLOWS = 0.24             # fraction of its distance from the LV that the RV free wall moves in
TWIST_APEX, TWIST_BASE = math.radians(7.0), math.radians(-3.5)
ATRIAL_SHRINK = 0.14


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _rotate(v, axis, ang):
    """Rodrigues rotation of vectors v (n, 3) about unit axes (n, 3) or (3,) by angles (n,) or scalar."""
    axis = np.broadcast_to(axis, v.shape)
    ang = np.broadcast_to(np.asarray(ang, float), (len(v),))[:, None]
    c, s = np.cos(ang), np.sin(ang)
    return v * c + np.cross(axis, v) * s + axis * np.einsum("ij,ij->i", axis, v)[:, None] * (1 - c)


# ----------------------------------------------------------------------------------------------- chamber fields
def ventricular_systole(p):
    """Displacement of heart-frame points p (n, 3) at end-systole."""
    a = np.asarray(H.LV_O[0], float)
    b = np.asarray(H.LV_O[2], float)
    L = float(np.linalg.norm(b - a))
    u = (b - a) / L
    h = (p - a) @ u
    hc = np.maximum(h, 0.0)
    q = p - a - hc[:, None] * u
    r = np.linalg.norm(q, axis=1)
    e = q / np.maximum(r, 1e-9)[:, None]
    hn = np.clip(h / L, 0.0, 1.0)
    ro = H.LV_O[1] + (H.LV_O[3] - H.LV_O[1]) * hn           # outer LV radius at this level
    ro2 = ro * (1.0 - EPS_OUT)
    inner = ro2 ** 2 - (ro ** 2 - r ** 2) / LAMBDA
    r_in = np.sqrt(np.maximum(inner, (0.3 * r) ** 2))
    r_out = r - (ro - ro2) - BELLOWS * np.clip(r - ro, 0.0, 0.34)
    r_new = np.where(r <= ro, r_in, r_out)
    # the radial motion belongs to the ventricles: it fades out across the AV plane and at the very apex
    g_v = _smooth((L + 0.06 - h) / 0.14) * _smooth((h + 0.10) / 0.2)
    radial = (r_new - r) * g_v
    q_new = q + e * radial[:, None]
    twist = (TWIST_APEX * (1.0 - hn) + TWIST_BASE * hn) * g_v
    q_new = _rotate(q_new, u, twist)
    # long axis: the base descends towards the apex, the atria and vessel roots follow, fading with height
    f_long = np.where(h < L, hn, np.clip(1.0 - (h - L) / 0.6, 0.0, 1.0))
    f_long = _smooth(f_long) * 0.35 + f_long * 0.65
    return (q_new - q) - u * (DELTA_AV * f_long)[:, None]


def atrial_systole(p):
    """Each atrium contracts towards its centre; the right/left split follows the interatrial septum."""
    from .sdf import ellipsoid
    p0, n = H.septal_plane()
    sp = (p - p0) @ n
    w_left = _smooth(sp / 0.12 + 0.5)
    out = np.zeros_like(p)
    for (c, radii), w_side in ((H.RA_C, 1.0 - w_left), (H.LA_C, w_left)):
        local = (p - c) @ H.ROT_B
        k = np.linalg.norm(local / radii, axis=1)
        w = 1.0 - _smooth((k - 1.25) / 0.7)
        out += -(p - c) * (ATRIAL_SHRINK * w * w_side)[:, None]
    above = _smooth((p[:, 1] - (H.Y_AV - 0.04)) / 0.12)
    return out * above[:, None]


# ----------------------------------------------------------------------------------------------- valves
def _quad_terms(p, open_fn):
    """Linear and quadratic morph terms of a path through the half-open and open poses."""
    mid = open_fn(p, 0.5) - p
    full = open_fn(p, 1.0) - p
    return 4 * mid - full, 2 * full - 4 * mid


def av_open(C, R, axis, swing=math.radians(64.0)):
    """AV cusps swing about the annulus (the hinge) down into the ventricle."""
    a = H.unit(axis)

    def fn(p, f):
        rel = p - C
        h = rel @ a
        rv = rel - h[:, None] * a
        rho = np.linalg.norm(rv, axis=1)
        e = rv / np.maximum(rho, 1e-9)[:, None]
        hinge = C + e * R
        s = p - hinge
        t = np.cross(a, e)             # rotating about a x e turns -e (inwards) towards +a (into the ventricle)
        t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
        return hinge + _rotate(s, t, swing * f)
    return fn


def semilunar_open(C, R, axis, cusps):
    """Semilunar cusps fold back against their sinuses: each cusp (one sub-mesh) moves out along its own
    direction, the free edge most, the attachment not at all."""
    A, U, V = H.valve_frame(axis)

    def for_mesh(p):
        rel = p - C
        c = rel.mean(axis=0)
        ang = math.degrees(math.atan2(c @ V, c @ U))
        mid = min((m for _, m in cusps), key=lambda m: abs((ang - m + 180) % 360 - 180))
        e = H._dir(U, V, mid)

        def fn(q, f):
            rq = q - C
            h = rq @ A
            k = np.clip((h + 0.62 * R) / (0.95 * R), 0.0, 1.0) ** 0.8
            rho = rq @ e
            return q + e * ((0.80 * R - rho) * k * f)[:, None] + A * (0.12 * R * k * f)[:, None]
        return fn
    return for_mesh


# ----------------------------------------------------------------------------------------------- attach
def _body(v):
    return H.to_body(v)


def _sub_meshes(part):
    return [pos.astype(np.float64) for pos, _, _ in part.mesh.parts]


def attach_motion(parts):
    """Give every part its morph targets (and the conduction parts their activation phases). Parts are in the
    body frame (after build_heart's final turn)."""
    by = {p.name: p for p in parts}
    fixed = {"Fibrous pericardium", "Parietal layer of serous pericardium", "Pericardial cavity"}
    valve_terms = {}
    # valves first: their open poses, per sub-mesh (one per cusp)
    specs = {"Tricuspid valve": ("av", H.TV_C, H.TV_R * 0.98, H.TV_AX, None),
             "Mitral (bicuspid) valve": ("av", H.MV_C, H.MV_R * 0.98, H.MV_AX, None),
             "Aortic valve": ("sl", H.AO_C, H.AO_R * 0.97, H.AO_AX, H.AO_CUSPS),
             "Pulmonary valve": ("sl", H.PV_C, H.PV_R * 0.97, H.PV_AX, H.PV_CUSPS)}
    for name, (kind, C, R, ax, cusps) in specs.items():
        part = by.get(name)
        if part is None:
            continue
        lin, quad = [], []
        for pos in _sub_meshes(part):
            ph = H.to_heart(pos)
            fn = av_open(C, R, ax) if kind == "av" else semilunar_open(C, R, ax, cusps)(ph)
            l_, q_ = _quad_terms(ph, fn)
            lin.append(l_)
            quad.append(q_)
        valve_terms[name] = (np.vstack(lin), np.vstack(quad))
    # chordae follow the nearest cusp in proportion to how far along the cord they are from the papillary muscle
    ch = by.get("Chordae tendineae")
    if ch is not None:
        vp = np.vstack([H.to_heart(by[n].mesh.arrays()[0]) for n in ("Tricuspid valve", "Mitral (bicuspid) valve")])
        vl = np.vstack([valve_terms[n][0] for n in ("Tricuspid valve", "Mitral (bicuspid) valve")])
        vq = np.vstack([valve_terms[n][1] for n in ("Tricuspid valve", "Mitral (bicuspid) valve")])
        pp = np.vstack([H.to_heart(by[n].mesh.arrays()[0]) for n in ("Papillary muscles (left ventricle)",
                                                                     "Papillary muscles (right ventricle)")])
        cp = H.to_heart(ch.mesh.arrays()[0])
        dv, jv = cKDTree(vp).query(cp)
        dp, _ = cKDTree(pp).query(cp)
        s = (dp / np.maximum(dp + dv, 1e-9))[:, None]
        valve_terms["Chordae tendineae"] = (vl[jv] * s, vq[jv] * s)

    for p in parts:
        pos = p.mesh.arrays()[0].astype(np.float64)
        n = len(pos)
        if not n:
            continue
        morph = np.zeros((n, 4, 3), np.float32)
        if p.name not in fixed:
            ph = H.to_heart(pos)
            morph[:, 0] = _body(ventricular_systole(ph))
            morph[:, 1] = _body(atrial_systole(ph))
            if p.name in valve_terms:
                lin, quad = valve_terms[p.name]
                morph[:, 2] = _body(lin)
                morph[:, 3] = _body(quad)
        p.anim = {"morph": morph, "phase": np.zeros(n, np.float32)}
    _conduction_phases(by)
    return parts


# ----------------------------------------------------------------------------------------------- conduction timing
T_SA = 0.0
V_ATRIAL = 12.0            # units per cycle-second: ~0.7 m/s through atrial muscle
T_AV_IN, T_AV_OUT = 0.045, 0.135
V_HIS = 34.0               # ~2 m/s
V_PURKINJE = 60.0          # ~3.5 m/s


def _pos(by, name):
    return by[name].mesh.arrays()[0].astype(np.float64)


def _set_phase(by, name, phase):
    if name in by and getattr(by[name], "anim", None):
        by[name].anim["phase"] = np.asarray(phase, np.float32) % 1.0


def _conduction_phases(by):
    need = ["Sinoatrial (SA) node", "Atrioventricular (AV) node", "Internodal pathways & Bachmann's bundle",
            "Atrioventricular bundle (bundle of His)", "Right bundle branch", "Left bundle branch", "Purkinje fibres"]
    if not all(n in by for n in need):
        return
    sa = _pos(by, need[0])
    sa_c = sa.mean(axis=0)
    _set_phase(by, need[0], T_SA + np.linalg.norm(sa - sa_c, axis=1) / V_ATRIAL * 0.3)
    inter = _pos(by, need[2])
    _set_phase(by, need[2], T_SA + np.linalg.norm(inter - sa_c, axis=1) / V_ATRIAL)
    av = _pos(by, need[1])
    his = _pos(by, need[3])
    av_c = av.mean(axis=0)
    # the node conducts slowly from its atrial end to where the bundle of His leaves it
    his_start = his[np.argmin(np.linalg.norm(his - av_c, axis=1))]
    d = H.unit(his_start - av_c)
    s = (av - av_c) @ d
    s = (s - s.min()) / max(np.ptp(s), 1e-9)
    _set_phase(by, need[1], T_AV_IN + (T_AV_OUT - T_AV_IN) * s)
    dh = np.linalg.norm(his - his_start, axis=1)
    _set_phase(by, need[3], T_AV_OUT + dh / V_HIS)
    his_end = his[np.argmax(dh)]
    t_his_end = T_AV_OUT + dh.max() / V_HIS
    bb_pts = []
    for name in need[4:6]:
        q = _pos(by, name)
        _set_phase(by, name, t_his_end + np.linalg.norm(q - his_end, axis=1) / V_HIS)
        bb_pts.append((q, t_his_end + np.linalg.norm(q - his_end, axis=1) / V_HIS))
    bq = np.vstack([q for q, _ in bb_pts])
    bt = np.concatenate([t for _, t in bb_pts])
    pk = _pos(by, need[6])
    dist, j = cKDTree(bq).query(pk)
    _set_phase(by, need[6], bt[j] + dist / V_PURKINJE)


# ----------------------------------------------------------------------------------------------- timing
def v_sys(t):
    return window(t, 0.22, 0.44, 0.52, 0.72)


def a_sys(t):
    return window(t, 0.07, 0.16, 0.21, 0.33)


def av_open_w(t):
    w = window(t, 0.635, 0.685, 1.205, 1.232)
    return w * (1.0 - 0.3 * window(t, 0.84, 0.93, 0.995, 1.07))       # the cusps drift up in diastasis


def sl_open_w(t):
    return window(t, 0.262, 0.292, 0.528, 0.556)


def _w(extra=None):
    if extra is None:
        return lambda t: (v_sys(t), a_sys(t), 0.0, 0.0)
    return lambda t: (v_sys(t), a_sys(t), extra(t), extra(t) ** 2)


PHASES = [(0.00, 0.08, "SA node fires · atria depolarise (P wave)"),
          (0.08, 0.15, "AV node delays the impulse · atria contract"),
          (0.15, 0.22, "His–Purkinje · ventricles depolarise (QRS)"),
          (0.22, 0.27, "Isovolumetric contraction · AV valves close (S1)"),
          (0.27, 0.55, "Ejection · aortic & pulmonary valves open"),
          (0.55, 0.64, "Isovolumetric relaxation · semilunar valves close (S2)"),
          (0.64, 1.00, "Ventricular filling · AV valves open")]


def heart_animation():
    wave = lambda decay: Track(_w(), glow=1.4, mode=MODE_WAVE, decay=decay)   # noqa: E731
    tracks = {
        "Tricuspid valve": Track(_w(av_open_w)),
        "Mitral (bicuspid) valve": Track(_w(av_open_w)),
        "Chordae tendineae": Track(_w(av_open_w)),
        "Aortic valve": Track(_w(sl_open_w)),
        "Pulmonary valve": Track(_w(sl_open_w)),
        "Sinoatrial (SA) node": wave(0.10),
        "Internodal pathways & Bachmann's bundle": wave(0.05),
        "Atrioventricular (AV) node": wave(0.07),
        "Atrioventricular bundle (bundle of His)": wave(0.05),
        "Right bundle branch": wave(0.05),
        "Left bundle branch": wave(0.05),
        "Purkinje fibres": wave(0.05),
    }
    return Animation(1.0, tracks, default=Track(_w()), phases=PHASES, title="Cardiac cycle",
                     speeds=(1.0, 0.5, 0.25, 0.1))


__all__ = ["attach_motion", "heart_animation", "ramp"]
