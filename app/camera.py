import math
import time

import numpy as np


def normalize(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def look_at(eye, target, up):
    f = normalize(target - eye)
    s = normalize(np.cross(f, up))
    u = np.cross(s, f)
    m = np.identity(4)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def ease(t):
    return t * t * (3 - 2 * t) if t < 1 else 1.0


class OrbitCamera:
    """Turntable camera around a target. Y is up, the body faces +Z (anterior)."""

    def __init__(self, fov=32.0):
        self.target = np.array([0.0, 0.9, 0.0])
        self.distance = 3.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.fov = fov
        self._anim = None

    # --------------------------------------------------------------- derived
    def forward_dir(self):
        cp = math.cos(self.pitch)
        return np.array([cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)])

    def eye(self):
        return self.target + self.distance * self.forward_dir()

    def basis(self):
        back = self.forward_dir()
        right = normalize(np.cross(np.array([0.0, 1.0, 0.0]), back))
        if np.linalg.norm(right) < 1e-6:
            right = np.array([math.cos(self.yaw), 0.0, -math.sin(self.yaw)])
        up = np.cross(back, right)
        return right, up, back

    def view(self):
        right, up, back = self.basis()
        return look_at(self.eye(), self.target, up)

    def near_far(self, scene_radius=1.2):
        near = max(self.distance * 0.01, 0.0005)
        far = self.distance + scene_radius * 2.5 + 1.0
        return near, far

    def proj(self, aspect):
        near, far = self.near_far()
        return perspective(self.fov, aspect, near, far)

    # --------------------------------------------------------------- interaction
    def orbit(self, dx_deg, dy_deg):
        self._anim = None
        self.yaw -= math.radians(dx_deg)
        self.pitch = max(-math.radians(89.5), min(math.radians(89.5), self.pitch + math.radians(dy_deg)))

    def pan(self, dx_px, dy_px, viewport_h):
        self._anim = None
        right, up, _ = self.basis()
        scale = 2 * self.distance * math.tan(math.radians(self.fov) / 2) / max(viewport_h, 1)
        self.target = self.target - right * dx_px * scale + up * dy_px * scale

    def dolly(self, factor, toward=None):
        self._anim = None
        new_d = max(0.005, min(12.0, self.distance * factor))
        f = new_d / self.distance
        if toward is not None:
            self.target = toward + (self.target - toward) * f
        self.distance = new_d

    def fit_distance(self, radius, aspect):
        half = math.radians(self.fov) / 2
        half_h = math.atan(math.tan(half) * min(aspect, 1.0))
        return radius / math.sin(min(half, half_h)) * 1.05

    def frame_bounds(self, bmin, bmax, aspect, yaw=None, pitch=None, duration=0.55, min_radius=0.015):
        center = (np.asarray(bmin) + np.asarray(bmax)) / 2
        radius = max(np.linalg.norm(np.asarray(bmax) - np.asarray(bmin)) / 2, min_radius)
        self.animate_to(center, self.fit_distance(radius, aspect),
                        self.yaw if yaw is None else yaw, self.pitch if pitch is None else pitch, duration)

    def animate_to(self, target, distance, yaw, pitch, duration=0.55):
        # shortest yaw path
        dyaw = (yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi
        self._anim = {
            "t0": time.perf_counter(), "dur": max(duration, 1e-3),
            "from": (self.target.copy(), self.distance, self.yaw, self.pitch),
            "to": (np.asarray(target, dtype=np.float64), distance, self.yaw + dyaw, pitch),
        }

    def update(self):
        a = self._anim
        if a is None:
            return False
        t = (time.perf_counter() - a["t0"]) / a["dur"]
        k = ease(min(t, 1.0))
        (t0, d0, y0, p0), (t1, d1, y1, p1) = a["from"], a["to"]
        self.target = t0 + (t1 - t0) * k
        self.distance = math.exp(math.log(d0) + (math.log(d1) - math.log(d0)) * k)
        self.yaw = y0 + (y1 - y0) * k
        self.pitch = p0 + (p1 - p0) * k
        if t >= 1.0:
            self._anim = None
            return False
        return True

    @property
    def animating(self):
        return self._anim is not None
