"""Orbit camera of the model viewer (Y up, glTF space).

It moves exactly like the atlas camera (app/camera.py), so the mouse, trackpad and keyboard controls - which drive
it through orbit(), pan(), dolly() and animate_to() - behave the same in both views: orbit in degrees per pixel,
pan by pixels, zoom by a factor toward a point, and eased moves that last Settings -> camera animation speed.

On top of that it keeps what the model files need. Its field of view follows Blender's sensor fit AUTO (the angle,
or the orthographic width, applies to the larger image dimension), so a view stored in a model's sidecar frames
the model as its author saw it; it has an orthographic mode; and a move between two named views that differ a lot
in scale (the kidney's views run from the whole organ down to a podocyte) goes along a scale-aware path instead of
a straight ease, so the viewer can see where it is going.
"""
from __future__ import annotations

import math
import time

import numpy as np

PITCH_LIMIT = math.radians(89.5)


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


def ease(t):
    return t * t * (3 - 2 * t) if t < 1 else 1.0


class OrbitCamera:
    """Turntable camera around a target: yaw 0 puts the camera on +Z looking toward -Z (an anterior view of a model
    that faces +Z, as the atlas does)."""

    PATH_KEEP = 5.6          # a target this many times closer than the camera distance sits well inside the frame

    def __init__(self, fov=39.597753):
        self.target = np.zeros(3)
        self.distance = 3.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.fov = float(fov)            # degrees, on the larger image dimension (Blender's sensor fit AUTO)
        self.ortho = False
        self.ortho_width = 2.0           # orthographic extent on the larger image dimension
        self.scene_centre = np.zeros(3)
        self.scene_radius = 1.0
        self.aspect = 1.6                # of the viewport, kept up to date by it (pan() needs it)
        self._anim = None

    # ------------------------------------------------------------------ limits
    @property
    def min_distance(self):
        # the kidney reaches 0.05 units (0.5 um) at its closest; a two-unit tissue block goes about as close as the
        # old microanatomy view did
        return min(0.05, self.scene_radius * 0.003)

    @property
    def max_distance(self):
        return max(self.scene_radius * 40.0, 1.0)

    def set_scene(self, lo, hi):
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        self.scene_centre = (lo + hi) / 2
        self.scene_radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3)

    # ------------------------------------------------------------------ derived
    def forward_dir(self):
        """Unit vector from the target to the camera."""
        cp = math.cos(self.pitch)
        return np.array([cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)])

    def eye(self):
        return self.target + self.distance * self.forward_dir()

    position = eye

    def basis(self):
        """(right, up, back) in world space, as the atlas camera gives them."""
        back = self.forward_dir()
        right = np.cross(np.array([0.0, 1.0, 0.0]), back)
        n = np.linalg.norm(right)
        right = right / n if n > 1e-6 else np.array([math.cos(self.yaw), 0.0, -math.sin(self.yaw)])
        up = np.cross(back, right)
        return right, up, back

    def view(self):
        _right, up, _back = self.basis()
        return look_at(self.eye(), self.target, up)

    view_matrix = view

    def half_tans(self, aspect):
        t = math.tan(math.radians(self.fov) / 2.0)
        return (t, t / aspect) if aspect >= 1.0 else (t * aspect, t)

    def ortho_halves(self, aspect):
        h = self.ortho_width / 2.0
        return (h, h / aspect) if aspect >= 1.0 else (h * aspect, h)

    def near_far(self):
        d = float(np.linalg.norm(self.eye() - self.scene_centre))
        r = self.scene_radius
        far = d + r * 1.6 + 1.0
        near = max(d - r * 1.6, far * 1e-4, 0.002)
        if not self.ortho:
            near = max(min(near, self.distance * 0.2), min(0.002, self.distance * 0.05))
        return near, far

    def proj(self, aspect):
        near, far = self.near_far()
        if self.ortho:
            hx, hy = self.ortho_halves(aspect)
            return orthographic(hx, hy, near, far)
        tx, ty = self.half_tans(aspect)
        return perspective(tx, ty, near, far)

    proj_matrix = proj

    def world_per_pixel(self, height_px, aspect):
        if self.ortho:
            _hx, hy = self.ortho_halves(aspect)
            return 2.0 * hy / max(height_px, 1)
        _tx, ty = self.half_tans(aspect)
        return 2.0 * ty * self.distance / max(height_px, 1)

    def ray(self, x_ndc, y_ndc, aspect):
        """World ray (origin, direction) through normalised device coordinates."""
        right, up, back = self.basis()
        fwd = -back
        if self.ortho:
            hx, hy = self.ortho_halves(aspect)
            return self.eye() + right * x_ndc * hx + up * y_ndc * hy, fwd
        tx, ty = self.half_tans(aspect)
        d = fwd + right * x_ndc * tx + up * y_ndc * ty
        return self.eye(), d / np.linalg.norm(d)

    # ------------------------------------------------------------------ interaction (the atlas's)
    def orbit(self, dx_deg, dy_deg):
        self._anim = None
        self.yaw -= math.radians(dx_deg)
        self.pitch = max(-PITCH_LIMIT, min(PITCH_LIMIT, self.pitch + math.radians(dy_deg)))

    def pan(self, dx_px, dy_px, viewport_h, aspect=None):
        self._anim = None
        right, up, _ = self.basis()
        scale = self.world_per_pixel(viewport_h, aspect or self.aspect)
        self.target = self.target - right * dx_px * scale + up * dy_px * scale

    def dolly(self, factor, toward=None):
        self._anim = None
        new_d = max(self.min_distance, min(self.max_distance, self.distance * factor))
        f = new_d / self.distance
        if toward is not None:
            toward = np.asarray(toward, float)
            self.target = toward + (self.target - toward) * f
        self.distance = new_d
        self.ortho_width = max(self.ortho_width * f, self.min_distance)

    def fit_distance(self, radius, aspect):
        tx, ty = self.half_tans(aspect)
        return radius / math.sin(math.atan(min(tx, ty))) * 1.05

    def frame_bounds(self, bmin, bmax, aspect, yaw=None, pitch=None, duration=0.55, min_radius=None):
        center = (np.asarray(bmin, float) + np.asarray(bmax, float)) / 2
        floor = self.min_distance * 0.5 if min_radius is None else min_radius
        radius = max(float(np.linalg.norm(np.asarray(bmax) - np.asarray(bmin))) / 2, floor)
        self.animate_to(center, self.fit_distance(radius, aspect), self.yaw if yaw is None else yaw,
                        self.pitch if pitch is None else pitch, duration, ortho_width=radius * 2.2)

    def animate_to(self, target, distance, yaw, pitch, duration=0.55, ortho_width=None):
        dyaw = (yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi          # the short way round
        distance = max(self.min_distance, min(self.max_distance, float(distance)))
        if ortho_width is None:
            ortho_width = 2.0 * distance * math.tan(math.radians(self.fov) / 2.0)
        self._anim = {
            "kind": "ease", "t0": time.perf_counter(), "dur": max(float(duration), 1e-3),
            "from": (self.target.copy(), self.distance, self.yaw, self.pitch, self.ortho_width),
            "to": (np.asarray(target, dtype=np.float64), distance, self.yaw + dyaw,
                   max(-PITCH_LIMIT, min(PITCH_LIMIT, float(pitch))), float(ortho_width)),
        }
        if duration <= 1e-3:
            self._finish()

    def snap(self):
        if self._anim is not None:
            self._finish()

    def _finish(self):
        a = self._anim
        self._anim = None
        if a is None:
            return
        self.target, self.distance, self.yaw, self.pitch, self.ortho_width = \
            (a["to"][0].copy(), a["to"][1], a["to"][2], a["to"][3], a["to"][4])

    @property
    def animating(self):
        return self._anim is not None

    def update(self):
        """Advance a running move; True while still moving."""
        a = self._anim
        if a is None:
            return False
        t = (time.perf_counter() - a["t0"]) / a["dur"]
        if t >= 1.0:
            self._finish()
            return False
        k = ease(t)
        if a["kind"] == "path":
            self._path_state(a, k)
            return True
        (t0, d0, y0, p0, o0), (t1, d1, y1, p1, o1) = a["from"], a["to"]
        self.target = t0 + (t1 - t0) * k
        self.distance = math.exp(math.log(d0) + (math.log(d1) - math.log(d0)) * k)
        self.ortho_width = math.exp(math.log(o0) + (math.log(o1) - math.log(o0)) * k)
        self.yaw = y0 + (y1 - y0) * k
        self.pitch = p0 + (p1 - p0) * k
        return True

    # ------------------------------------------------------------------ stored views
    @staticmethod
    def record_pose(rec, fov):
        """(target, distance, yaw, pitch, ortho, ortho width, fov) of a sidecar camera record."""
        pos, tgt = np.asarray(rec["position"], float), np.asarray(rec["target"], float)
        d = pos - tgt
        dist = float(np.linalg.norm(d))
        d /= max(dist, 1e-12)
        yaw = math.atan2(d[0], d[2])
        pitch = math.asin(float(np.clip(d[1], -1.0, 1.0)))
        if rec.get("type") == "ORTHO":
            ow = float(rec["ortho_width"])
            return tgt, ow / (2.0 * math.tan(math.radians(fov) / 2.0)), yaw, pitch, True, ow, fov
        fov = float(rec.get("fov_deg", fov))
        return tgt, dist, yaw, pitch, False, 2.0 * dist * math.tan(math.radians(fov) / 2.0), fov

    def set_record(self, rec, duration=0.55, zoom_path=False, fit=None):
        """Go to a camera record from a model's sidecar (position, target, type, fov or orthographic width).
        zoom_path (perspective only): take the scale-aware path rather than a straight ease.
        fit (bounds min, bounds max, aspect): a perspective record aimed at the middle of those bounds from far enough
        away that they fill little of the frame (the exporter's turntable cameras, composed for a wide render) keeps
        its direction but is brought in to frame them, as F does."""
        tgt, dist, yaw, pitch, ortho, ow, fov = self.record_pose(rec, self.fov)
        self.fov = fov
        if fit is not None and not ortho:
            lo, hi, aspect = fit
            centre = (np.asarray(lo, float) + np.asarray(hi, float)) / 2
            radius = float(np.linalg.norm(np.asarray(hi, float) - np.asarray(lo, float))) / 2
            tx, ty = self.half_tans(aspect)
            if radius > 0 and np.linalg.norm(tgt - centre) < 0.1 * radius and radius / (min(tx, ty) * dist) < 0.75:
                tgt, dist = centre, self.fit_distance(radius * 0.95, aspect)
                ow = 2.0 * dist * math.tan(math.radians(fov) / 2.0)
        if ortho != self.ortho:
            self.ortho = ortho
            self._anim = None
            duration = 0.0                       # no sensible blend between the two projections
        if zoom_path and not ortho and duration > 0:
            self._start_path(tgt, dist, yaw, pitch, ow)
        else:
            self.animate_to(tgt, dist, yaw, pitch, duration, ortho_width=ow)

    def toggle_ortho(self):
        self.snap()
        if self.ortho:
            self.ortho = False
            self.distance = self.ortho_width / (2.0 * math.tan(math.radians(self.fov) / 2.0))
        else:
            self.ortho = True
            self.ortho_width = 2.0 * self.distance * math.tan(math.radians(self.fov) / 2.0)
        return self.ortho

    # ------------------------------------------------------------------ scale-aware move between views
    def _start_path(self, tgt, dist, yaw, pitch, ortho_width):
        """Move so that a change of scale reads as a zoom: the distance changes in log space and the target moves
        in step with it, so the start's target stays inside the frame while zooming out and the goal's target while
        zooming in; when neither view holds the other's target, the move goes out, across and in (a simple form of
        van Wijk and Nuij's smooth zooming and panning)."""
        c0 = (self.target.copy(), max(self.distance, 1e-9), self.yaw, self.pitch)
        d0, d1 = c0[1], max(float(dist), 1e-9)
        tgt = np.asarray(tgt, float)
        u = float(np.linalg.norm(tgt - c0[0]))
        k = self.PATH_KEEP
        if u * k <= d0 and d1 <= d0:
            dm, tm = d0, c0[0].copy()                      # the goal is inside the start view: zoom in toward it
        elif u * k <= d1 and d1 >= d0:
            dm, tm = d1, tgt.copy()                        # the start is inside the goal view: zoom out from it
        else:
            dm, tm = max(d0, d1, 0.5 * k * u), 0.5 * (c0[0] + tgt)
        l0, l1, lm = math.log(d0), math.log(d1), math.log(dm)
        span = (lm - l0) + (lm - l1)
        yaw = self.yaw + ((yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi)
        turn = abs(yaw - self.yaw) + abs(pitch - self.pitch)
        dur = float(np.clip(0.45 + 0.30 * span + 0.25 * turn, 0.45, 3.2))
        self._anim = {"kind": "path", "t0": time.perf_counter(), "dur": dur,
                      "from": (c0[0], d0, c0[2], c0[3], self.ortho_width),
                      "to": (tgt, d1, yaw, float(pitch), float(ortho_width)),
                      "dm": dm, "tm": tm, "l0": l0, "l1": l1, "lm": lm, "span": span}

    def _path_state(self, P, x):
        t0, d0, y0, p0, _o0 = P["from"]
        t1, d1, y1, p1, _o1 = P["to"]
        self.yaw = y0 + (y1 - y0) * x
        self.pitch = p0 + (p1 - p0) * x
        if P["span"] < 1e-6:
            self.distance = d0 + (d1 - d0) * x
            self.target = t0 + (t1 - t0) * x
        else:
            lam = x * P["span"]
            up = P["lm"] - P["l0"]
            if lam <= up:
                d = math.exp(P["l0"] + lam)
                f = (d - d0) / (P["dm"] - d0) if P["dm"] > d0 else 1.0
                self.target = t0 + (P["tm"] - t0) * f
            else:
                d = math.exp(P["lm"] - (lam - up))
                f = (d - d1) / (P["dm"] - d1) if P["dm"] > d1 else 0.0
                self.target = t1 + (P["tm"] - t1) * f
            self.distance = d
        self.ortho_width = 2.0 * self.distance * math.tan(math.radians(self.fov) / 2.0)
