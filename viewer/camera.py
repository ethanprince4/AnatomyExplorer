"""Orbit camera with smooth damping (Y up, glTF space) and Blender-compatible framing.

The field of view follows Blender's sensor fit AUTO: the angle (or orthographic width) applies to the larger
image dimension, so a harness view renders with the same framing as the Cycles stills at 16:9.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    f = np.asarray(target, float) - np.asarray(eye, float)
    f /= max(np.linalg.norm(f), 1e-12)
    u = np.asarray(up, float)
    s = np.cross(f, u)
    if np.linalg.norm(s) < 1e-9:
        s = np.cross(f, np.array([0.0, 0.0, 1.0]))
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ np.asarray(eye, float)
    return m


def perspective(tx, ty, near, far):
    m = np.zeros((4, 4))
    m[0, 0] = 1.0 / tx
    m[1, 1] = 1.0 / ty
    m[2, 2] = -(far + near) / (far - near)
    m[2, 3] = -2.0 * far * near / (far - near)
    m[3, 2] = -1.0
    return m


def orthographic(hx, hy, near, far):
    m = np.eye(4)
    m[0, 0] = 1.0 / hx
    m[1, 1] = 1.0 / hy
    m[2, 2] = -2.0 / (far - near)
    m[2, 3] = -(far + near) / (far - near)
    return m


@dataclass
class CamState:
    target: np.ndarray
    yaw: float          # radians, about +Y; 0 = camera on +Z looking toward -Z
    pitch: float        # radians above the XZ plane
    distance: float
    ortho_width: float  # orthographic extent on the larger image dimension

    def copy(self):
        return CamState(self.target.copy(), self.yaw, self.pitch, self.distance, self.ortho_width)


class OrbitCamera:
    def __init__(self):
        self.fov_deg = 39.597753          # 50 mm on a 36 mm sensor (the harness lens)
        self.ortho = False
        # default direction = the harness V1 (azimuth 35, elevation 28 in Blender) in glTF space
        self.cur = CamState(np.zeros(3), math.radians(145.0), math.radians(28.0), 30.0, 20.0)
        self.goal = self.cur.copy()
        self.scene_radius = 15.0
        self.scene_centre = np.zeros(3)
        self.damping = 14.0
        self._path = None                 # a running scale-aware view move (start_path), or None

    # ------------------------------------------------------------------ derived
    def position(self, st=None):
        st = st or self.cur
        cp = math.cos(st.pitch)
        d = np.array([cp * math.sin(st.yaw), math.sin(st.pitch), cp * math.cos(st.yaw)])
        return st.target + d * st.distance

    def basis(self):
        V = self.view_matrix()
        return V[0, :3].copy(), V[1, :3].copy(), -V[2, :3].copy()   # right, up, forward

    def view_matrix(self):
        return look_at(self.position(), self.cur.target)

    def half_tans(self, aspect):
        t = math.tan(math.radians(self.fov_deg) / 2.0)
        return (t, t / aspect) if aspect >= 1.0 else (t * aspect, t)

    def ortho_halves(self, aspect):
        h = self.cur.ortho_width / 2.0
        return (h, h / aspect) if aspect >= 1.0 else (h * aspect, h)

    def near_far(self):
        d = float(np.linalg.norm(self.position() - self.scene_centre))
        r = self.scene_radius
        far = d + r * 1.6 + 1.0
        near = max(d - r * 1.6, far * 1e-4, 0.002)
        if not self.ortho:
            near = max(min(near, self.cur.distance * 0.2), 0.002)
        return near, far

    def proj_matrix(self, aspect):
        near, far = self.near_far()
        if self.ortho:
            hx, hy = self.ortho_halves(aspect)
            return orthographic(hx, hy, near, far)
        tx, ty = self.half_tans(aspect)
        return perspective(tx, ty, near, far)

    def world_per_pixel(self, height_px, aspect):
        if self.ortho:
            _, hy = self.ortho_halves(aspect)
            return 2.0 * hy / max(height_px, 1)
        _, ty = self.half_tans(aspect)
        return 2.0 * ty * self.cur.distance / max(height_px, 1)

    # ------------------------------------------------------------------ interaction (goal state)
    def orbit(self, dx_px, dy_px):
        self._break_path()
        self.goal.yaw -= dx_px * 0.006
        self.goal.pitch = float(np.clip(self.goal.pitch + dy_px * 0.006, -1.55, 1.55))

    def pan(self, dx_px, dy_px, height_px, aspect):
        self._break_path()
        right, up, _ = self.basis()
        k = self.world_per_pixel(height_px, aspect)
        self.goal.target = self.goal.target + (-dx_px * right + dy_px * up) * k

    def zoom(self, steps, toward=None):
        self._break_path()
        f = 0.85 ** steps
        old = self.goal.distance
        self.goal.distance = float(np.clip(old * f, 0.05, self.scene_radius * 40.0))
        self.goal.ortho_width = float(np.clip(self.goal.ortho_width * f, 0.05, self.scene_radius * 20.0))
        if toward is not None:
            k = 1.0 - (self.goal.distance / old if not self.ortho else f)
            self.goal.target = self.goal.target + (np.asarray(toward) - self.goal.target) * k

    def update(self, dt):
        """Advance toward the goal; returns True while still moving."""
        if self._path is not None:
            return self._advance_path(dt)
        a = 1.0 - math.exp(-self.damping * max(dt, 0.0))
        c, g = self.cur, self.goal
        dyaw = (g.yaw - c.yaw + math.pi) % (2 * math.pi) - math.pi
        c.yaw += dyaw * a
        c.pitch += (g.pitch - c.pitch) * a
        c.distance *= (g.distance / c.distance) ** a
        c.ortho_width *= (g.ortho_width / c.ortho_width) ** a
        c.target = c.target + (g.target - c.target) * a
        moving = (abs(dyaw) > 1e-5 or abs(g.pitch - c.pitch) > 1e-5
                  or abs(math.log(g.distance / c.distance)) > 1e-5
                  or abs(math.log(g.ortho_width / c.ortho_width)) > 1e-5
                  or float(np.linalg.norm(g.target - c.target)) > 1e-5 * max(c.distance, 1.0))
        if not moving:
            self.cur = g.copy()
            self.goal = g.copy()
        return moving

    def snap(self):
        self.cur = self.goal.copy()

    # ------------------------------------------------------------------ framing
    def fit(self, lo, hi, aspect, animate=True, margin=0.06):
        """Frame the box: the harness rule (bisect the distance until every corner sits inside the frame)."""
        self._break_path()
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        c = (lo + hi) / 2
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        tx, ty = self.half_tans(aspect)
        st = self.goal.copy()
        st.target = c
        cp = math.cos(st.pitch)
        d = np.array([cp * math.sin(st.yaw), math.sin(st.pitch), cp * math.cos(st.yaw)])
        V = look_at(c + d, c)
        rel = (V[:3, :3] @ (corners - c).T).T          # camera-space offsets at distance 0
        limit = 1.0 - margin

        def fits(dist):
            z = dist - rel[:, 2]
            if np.any(z <= 1e-6):
                return False
            return bool(np.all(np.abs(rel[:, 0] / z / tx) <= limit) and np.all(np.abs(rel[:, 1] / z / ty) <= limit))

        lo_d, hi_d = 0.0, max(float(np.linalg.norm(hi - lo)), 1e-3)
        while not fits(hi_d):
            hi_d *= 2.0
        for _ in range(30):
            mid = 0.5 * (lo_d + hi_d)
            lo_d, hi_d = (lo_d, mid) if fits(mid) else (mid, hi_d)
        self.goal.target = c
        self.goal.distance = hi_d
        w = np.ptp(rel[:, 0]) / limit
        h = np.ptp(rel[:, 1]) / limit
        self.goal.ortho_width = max(w, h * aspect) if aspect >= 1.0 else max(h, w / aspect)
        if not animate:
            self.snap()

    def focus(self, point, radius, aspect):
        self._break_path()
        tx, ty = self.half_tans(aspect)
        t = min(tx, ty)
        self.goal.target = np.asarray(point, float)
        self.goal.distance = max(radius, 0.05) / math.sin(math.atan(t)) * 1.3
        self.goal.ortho_width = max(radius, 0.05) * 2.6 * (max(tx, ty) / t)

    def set_view(self, rec, animate=True, zoom_path=False):
        """Place the camera from a sidecar camera record (position, target, type, fov or ortho width).
        zoom_path (opt-in, perspective only): move there along start_path() instead of the damped glide."""
        self._break_path()
        pos, tgt = np.asarray(rec["position"], float), np.asarray(rec["target"], float)
        d = pos - tgt
        dist = float(np.linalg.norm(d))
        d /= max(dist, 1e-12)
        self.goal.yaw = math.atan2(d[0], d[2])
        self.goal.pitch = math.asin(float(np.clip(d[1], -1.0, 1.0)))
        self.goal.target = tgt
        if rec.get("type") == "ORTHO":
            self.ortho = True
            self.goal.ortho_width = float(rec["ortho_width"])
            # keep a modest orbit distance so switching back to perspective lands near the same framing
            self.goal.distance = self.goal.ortho_width / (2.0 * math.tan(math.radians(self.fov_deg) / 2.0))
        else:
            self.ortho = False
            self.fov_deg = float(rec.get("fov_deg", self.fov_deg))
            self.goal.distance = dist
            self.goal.ortho_width = 2.0 * dist * math.tan(math.radians(self.fov_deg) / 2.0)
        # unwrap yaw so the damping takes the short way
        self.goal.yaw = self.cur.yaw + ((self.goal.yaw - self.cur.yaw + math.pi) % (2 * math.pi) - math.pi)
        if not animate:
            self.snap()
        elif zoom_path and not self.ortho:
            self.start_path(self.goal)

    # ------------------------------------------------------------------ scale-aware move between views (opt-in)
    PATH_KEEP = 5.6          # a target this many times closer than the camera distance sits well inside the frame

    def _break_path(self):
        """User input takes over from a running view move where it is."""
        if self._path is not None:
            self._path = None
            self.goal = self.cur.copy()

    def start_path(self, goal):
        """Move from the current state to `goal` so that a change of scale reads as a zoom: the distance changes in
        log space and the target moves in step with it, so the start's target stays inside the frame while zooming
        out and the goal's target while zooming in; when neither view holds the other's target, the move goes out,
        across and in (a simple form of van Wijk and Nuij's smooth zooming and panning)."""
        c0, g = self.cur.copy(), goal.copy()
        d0, d1 = max(c0.distance, 1e-9), max(g.distance, 1e-9)
        u = float(np.linalg.norm(g.target - c0.target))
        k = self.PATH_KEEP
        if u * k <= d0 and d1 <= d0:
            dm, tm = d0, c0.target.copy()                  # the goal is inside the start view: zoom in toward it
        elif u * k <= d1 and d1 >= d0:
            dm, tm = d1, g.target.copy()                   # the start is inside the goal view: zoom out from it
        else:
            dm, tm = max(d0, d1, 0.5 * k * u), 0.5 * (c0.target + g.target)
        l0, l1, lm = math.log(d0), math.log(d1), math.log(dm)
        span = (lm - l0) + (lm - l1)
        turn = abs((g.yaw - c0.yaw + math.pi) % (2 * math.pi) - math.pi) + abs(g.pitch - c0.pitch)
        dur = float(np.clip(0.45 + 0.30 * span + 0.25 * turn, 0.45, 3.2))
        self._path = {"c0": c0, "g": g, "d0": d0, "d1": d1, "dm": dm, "tm": tm, "l0": l0, "l1": l1, "lm": lm,
                      "span": span, "t": 0.0, "dur": dur}

    def path_state(self, x):
        """The camera state at eased progress x (0..1) of the active move."""
        P = self._path
        c0, g = P["c0"], P["g"]
        st = g.copy()
        dyaw = (g.yaw - c0.yaw + math.pi) % (2 * math.pi) - math.pi
        st.yaw = c0.yaw + dyaw * x
        st.pitch = c0.pitch + (g.pitch - c0.pitch) * x
        if P["span"] < 1e-6:
            st.distance = P["d0"] + (P["d1"] - P["d0"]) * x
            st.target = c0.target + (g.target - c0.target) * x
        else:
            lam = x * P["span"]
            up = P["lm"] - P["l0"]
            if lam <= up:
                d = math.exp(P["l0"] + lam)
                f = (d - P["d0"]) / (P["dm"] - P["d0"]) if P["dm"] > P["d0"] else 1.0
                st.target = c0.target + (P["tm"] - c0.target) * f
            else:
                d = math.exp(P["lm"] - (lam - up))
                f = (d - P["d1"]) / (P["dm"] - P["d1"]) if P["dm"] > P["d1"] else 0.0
                st.target = g.target + (P["tm"] - g.target) * f
            st.distance = d
        st.ortho_width = 2.0 * st.distance * math.tan(math.radians(self.fov_deg) / 2.0)
        return st

    def _advance_path(self, dt):
        P = self._path
        P["t"] += max(dt, 0.0)
        if P["t"] >= P["dur"]:
            self.cur = P["g"].copy()
            self.goal = P["g"].copy()
            self._path = None
            return False
        x = P["t"] / P["dur"]
        self.cur = self.path_state(x * x * (3.0 - 2.0 * x))
        return True

    def toggle_ortho(self):
        if self.ortho:
            self.ortho = False
            self.goal.distance = self.cur.ortho_width / (2.0 * math.tan(math.radians(self.fov_deg) / 2.0))
            self.cur.distance = self.goal.distance
        else:
            self.ortho = True
            self.cur.ortho_width = 2.0 * self.cur.distance * math.tan(math.radians(self.fov_deg) / 2.0)
            self.goal.ortho_width = 2.0 * self.goal.distance * math.tan(math.radians(self.fov_deg) / 2.0)

    def ray(self, x_ndc, y_ndc, aspect):
        """World ray (origin, direction) through normalised device coordinates."""
        right, up, fwd = self.basis()
        if self.ortho:
            hx, hy = self.ortho_halves(aspect)
            o = self.position() + right * x_ndc * hx + up * y_ndc * hy
            return o, fwd
        tx, ty = self.half_tans(aspect)
        d = fwd + right * x_ndc * tx + up * y_ndc * ty
        return self.position(), d / np.linalg.norm(d)
