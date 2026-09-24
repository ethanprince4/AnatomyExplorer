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


class SectionIndex:
    def __init__(self, ds):
        self.ds = ds
        self.points = None
        self.owner = None
        self._thread = None
        self._lock = threading.Lock()
        self._allowed = np.array([s["system"] not in SKIP_SYSTEMS for s in ds.structures], dtype=bool)

    @property
    def ready(self):
        return self.points is not None

    def start(self):
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._load, daemon=True)
                self._thread.start()

    def _load(self):
        try:
            points, offsets = sample_points(self.ds)
            owner = np.repeat(np.arange(len(offsets) - 1, dtype=np.int32), np.diff(offsets))
            self.owner = owner
            self.points = points
        except Exception:
            self.points = None

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
