"""How deep each structure lies beneath the skin - the basis of the dissection slider.

Every structure is given a depth between 0 (on the surface) and 1 (as deep as the body gets at that point).
Absolute depth alone would be useless for a whole-body peel: a finger bone sits 2 mm down and a femur 40 mm, so a
millimetre slider would strip the entire hand before it touched the thigh. Instead each structure's distance from
the skin is divided by the local thickness of the body there, which is estimated from the deepest tissue found in
the same neighbourhood. Peeling then advances evenly everywhere, the way a dissection does.
"""
import threading

import numpy as np

from .relations import geometry_stamp, sample_points

SURFACE_SYSTEM = "regions"      # the body-surface patches of the atlas
VOXEL = 0.02                    # 2 cm grid for the local-thickness estimate
FORMAT = 1


class DepthIndex:
    """Relative and absolute depth per structure, computed once in the background and cached on disk."""

    def __init__(self, ds):
        self.ds = ds
        self.depth = None        # float32[n], 0..~1, -1 where a structure has no surface samples
        self.absolute = None     # float32[n], metres below the skin
        self._thread = None
        self._lock = threading.Lock()
        self.failed = False

    @property
    def ready(self):
        return self.depth is not None

    def start(self):
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self):
        try:
            self.depth, self.absolute = self._load()
        except Exception:                                  # never take the app down over a study aid
            self.depth, self.absolute = None, None
            self.failed = True

    def _load(self):
        ds = self.ds
        cache = ds.dir / "depth.npz"
        stamp = geometry_stamp(ds)
        if cache.exists():
            try:
                z = np.load(cache)
                if (np.array_equal(z["stamp"], stamp) and len(z["depth"]) == ds.n
                        and int(z["format"]) == FORMAT):
                    return z["depth"], z["absolute"]
            except (OSError, ValueError, KeyError):
                pass
        depth, absolute = compute(ds)
        try:
            np.savez(cache, depth=depth, absolute=absolute, stamp=stamp, format=np.int32(FORMAT))
        except OSError:
            pass
        return depth, absolute


def compute(ds):
    from scipy import ndimage
    from scipy.spatial import cKDTree

    points, offsets = sample_points(ds)
    skin = [s["id"] for s in ds.structures if s["system"] == SURFACE_SYSTEM and offsets[s["id"] + 1] > offsets[s["id"]]]
    n = ds.n
    if not skin or not len(points):
        return np.full(n, -1.0, np.float32), np.full(n, -1.0, np.float32)
    surface = np.concatenate([points[offsets[i]:offsets[i + 1]] for i in skin])
    dist = cKDTree(surface).query(points, workers=-1)[0].astype(np.float32)

    # local half-thickness of the body: the deepest sample in the same 2 cm neighbourhood
    lo = points.min(axis=0) - VOXEL
    hi = points.max(axis=0) + VOXEL
    shape = tuple(int(np.ceil((hi[i] - lo[i]) / VOXEL)) + 1 for i in range(3))
    cell = np.ravel_multi_index(((points - lo) / VOXEL).astype(int).T, shape)
    grid = np.zeros(int(np.prod(shape)), np.float32)
    np.maximum.at(grid, cell, dist)
    grid = ndimage.uniform_filter(ndimage.maximum_filter(grid.reshape(shape), size=5), size=5)
    thickness = np.maximum(grid.ravel()[cell], 0.004)

    rel = np.clip(dist / thickness, 0.0, 1.2)
    depth = np.full(n, -1.0, np.float32)
    absolute = np.full(n, -1.0, np.float32)
    for sid in range(n):
        a, b = offsets[sid], offsets[sid + 1]
        if b > a:
            depth[sid] = np.percentile(rel[a:b], 50)
            absolute[sid] = np.percentile(dist[a:b], 50)
    return depth, absolute
