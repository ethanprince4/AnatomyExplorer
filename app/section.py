"""What a cross-section actually cuts through - the data behind the labelled section plate.

Testing every triangle against the plane would be exact but far too slow to follow a slider. Instead the surface
samples already kept for the relations index are reused: the points lying within a few millimetres of the plane
tell you which structures the cut passes through, roughly how much of each it exposes, and where on the cut face
to hang its label.
"""
import threading

import numpy as np

from .relations import sample_points

SKIP_SYSTEMS = {"attachments", "reference"}
SLAB = 0.007          # half-thickness of the band of samples counted as "cut", in metres


def plane_bounds(ds, vertices, indices, visible, plane):
    """Exact surface/plane intersection bounds, excluding off-plane mesh extents.

    This runs when framing a section, not while dragging its position slider.
    AABB admission avoids scanning unrelated meshes; chunking bounds scratch RAM.
    """
    dtype = np.dtype([("pos", "<f4", 3), ("nrm", "<f4", 3),
                      ("obj", "<u2"), ("mat", "<u2")])
    positions = np.frombuffer(vertices, dtype=dtype)["pos"]
    triangles = np.frombuffer(indices, dtype="<u4")
    normal = np.asarray(plane[:3], dtype=np.float64)
    offset = float(plane[3])
    length = np.linalg.norm(normal)
    if length == 0:
        return None
    normal, offset = normal / length, offset / length
    center = (ds.bbox_min + ds.bbox_max) * .5
    radius = ((ds.bbox_max - ds.bbox_min) * .5) @ np.abs(normal)
    admitted = np.asarray(visible, dtype=bool).copy()
    admitted &= np.abs(center @ normal + offset) <= radius + 1e-7
    admitted &= ~getattr(ds, "noclip_mask", np.zeros(len(admitted), dtype=bool))
    low = np.full(3, np.inf)
    high = np.full(3, -np.inf)
    contributors = []
    for sid in np.flatnonzero(admitted):
        part = ds.structures[sid]
        start, count = part["i_start"], part["i_count"]
        contributed = False
        for first in range(start, start + count, 3 * 16384):
            ids = triangles[first:min(first + 3 * 16384, start + count)].reshape(-1, 3)
            points = positions[ids].astype(np.float64)
            distance = points @ normal + offset
            crossing = (distance.min(axis=1) <= 0) & (distance.max(axis=1) >= 0)
            points, distance = points[crossing], distance[crossing]
            for a, b in ((0, 1), (1, 2), (2, 0)):
                da, db = distance[:, a], distance[:, b]
                on = da == 0
                if on.any():
                    cut = points[on, a]
                    low, high = np.minimum(low, cut.min(axis=0)), np.maximum(high, cut.max(axis=0))
                    contributed = True
                crosses = ((da < 0) & (db > 0)) | ((da > 0) & (db < 0))
                if crosses.any():
                    t = da[crosses] / (da[crosses] - db[crosses])
                    cut = points[crosses, a] + t[:, None] * (points[crosses, b] - points[crosses, a])
                    low, high = np.minimum(low, cut.min(axis=0)), np.maximum(high, cut.max(axis=0))
                    contributed = True
        if contributed:
            contributors.append(int(sid))
    return None if not contributors else (low, high, contributors)


class SectionIndex:
    def __init__(self, ds):
        self.ds = ds
        self.points = None
        self.owner = None
        self._thread = None
        self.failed = False
        self._lock = threading.Lock()
        self._allowed = np.array([s["system"] not in SKIP_SYSTEMS for s in ds.structures], dtype=bool)

    @property
    def ready(self):
        return self.points is not None

    def start(self, retry=False):
        with self._lock:
            if self.ready or (self._thread is not None and self._thread.is_alive()):
                return
            if self.failed and not retry:
                return
            self.failed = False
            self._thread = threading.Thread(target=self._load, daemon=True)
            self._thread.start()

    def _load(self):
        try:
            points, offsets = sample_points(self.ds)
            owner = np.repeat(np.arange(len(offsets) - 1, dtype=np.int32), np.diff(offsets))
            self.owner = owner
            self.points = points
        except Exception:
            self.points, self.owner = None, None
            self.failed = True

    def cut(self, axis, value, visible, limit=26, slab=SLAB):
        """Structures the plane passes through, biggest first.

        Returns [(sid, anchor_xyz, weight)] where the anchor lies on the cut face itself."""
        if not self.ready:
            return []
        pts, owner = self.points, self.owner
        near = np.abs(pts[:, axis] - value) < slab
        if not near.any():
            return []
        keep = near & self._allowed[owner] & visible[owner]
        if not keep.any():
            return []
        own = owner[keep]
        sel = pts[keep]
        n = self.ds.n
        counts = np.bincount(own, minlength=n)
        hit = np.flatnonzero(counts > 1)
        if not len(hit):
            return []
        sums = np.stack([np.bincount(own, weights=sel[:, k].astype(np.float64), minlength=n) for k in range(3)], -1)
        order = hit[np.argsort(-counts[hit])][:limit]
        out = []
        for sid in order:
            anchor = sums[sid] / counts[sid]
            anchor[axis] = value
            out.append((int(sid), anchor, int(counts[sid])))
        return out
