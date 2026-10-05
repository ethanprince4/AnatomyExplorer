"""Spatial neighbours: which structures lie against or near the selection.

Each structure is represented by random surface samples (more for larger meshes) taken from the GPU buffers once
and cached in data/anatomy/samples.npz. A query compares the selection's samples with those of structures whose
bounding boxes come close, and ranks them by the smallest sample distance."""
import threading
from zipfile import BadZipFile

import numpy as np

from .config import FROZEN, cache_candidates
from .cache_io import format_matches, save_npz

EXCLUDED_SYSTEMS = {"attachments", "regions", "reference", "fascia"}
STRIDE = 28
# Source runs notice editable file times; installed runs use the packaged content
# identity, independent of installer mtimes and source byte lengths.
STAMP_MTIME = not FROZEN
SAMPLE_FORMAT = 1


def geometry_stamp(ds):
    from .dataset_identity import installed_stamp, read_manifest, source_stamp
    if STAMP_MTIME:
        return np.array(source_stamp(ds), dtype=np.int64)
    content_id = getattr(ds, "_dataset_content_id", None)
    if content_id is None:
        content_id = read_manifest(ds.dir)["content_id"]
    return np.array(installed_stamp(ds, content_id), dtype=np.int64)



def sample_points(ds):
    """Random surface samples per structure, cached in data/anatomy/samples.npz.

    Returns (points, offsets) where structure `sid` owns points[offsets[sid]:offsets[sid + 1]]."""
    vpath, ipath = ds.dir / "vertices.bin", ds.dir / "indices.bin"
    reads, cache = cache_candidates(ds.dir / "samples.npz")
    stamp = geometry_stamp(ds)
    for path in reads:
        if not path.exists():
            continue
        try:
            with path.open("rb") as stream, np.load(stream) as z:
                if (not np.array_equal(z["stamp"], stamp)
                        or not format_matches(z["format"], SAMPLE_FORMAT)):
                    continue
                points, offsets = z["points"], z["offsets"]
                if (points.ndim == 2 and points.shape[1] == 3 and points.dtype.kind == "f"
                        and np.isfinite(points).all() and offsets.shape == (ds.n + 1,)
                        and offsets.dtype.kind in "iu" and offsets[0] == 0 and offsets[-1] == len(points)
                        and np.all(offsets[1:] >= offsets[:-1])):
                    return points, offsets
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            pass
    indices = np.memmap(ipath, dtype="<u4", mode="r")
    verts = np.memmap(vpath, dtype=np.uint8, mode="r").reshape(-1, STRIDE)
    # findings live past the end of the two files, in memory; sample them from there
    base_i, base_v = len(indices), len(verts)
    f_idx = f_verts = None
    if getattr(ds, "findings", None) is not None:
        vbytes, ibytes = ds.findings.geometry()
        f_idx = np.frombuffer(ibytes, dtype="<u4")
        f_verts = np.frombuffer(vbytes, dtype=np.uint8).reshape(-1, STRIDE)
    rng = np.random.default_rng(0)
    chunks, offsets = [], [0]
    for s in ds.structures:
        n_idx = s["i_count"]
        k = int(np.clip(n_idx / 3 * 0.08, 32, 1500)) if n_idx else 0
        if k:
            far = s["i_start"] >= base_i
            src_i, src_v = (f_idx, f_verts) if far else (indices, verts)
            off_i, off_v = (base_i, base_v) if far else (0, 0)
            pick = (s["i_start"] - off_i) + rng.integers(0, n_idx, size=k)
            vid = np.unique(np.asarray(src_i[np.sort(pick)])) - off_v
            pts = np.ascontiguousarray(src_v[vid, :12]).view("<f4").reshape(-1, 3)
        else:
            pts = np.zeros((0, 3), np.float32)
        chunks.append(pts)
        offsets.append(offsets[-1] + len(pts))
    points = np.concatenate(chunks).astype(np.float32)
    offsets = np.array(offsets, dtype=np.int64)
    try:
        save_npz(cache, points=points, offsets=offsets, stamp=stamp, format=np.int32(SAMPLE_FORMAT))
    except OSError:
        pass
    return points, offsets


class RelationsIndex:
    def __init__(self, ds):
        self.ds = ds
        self.points = None
        self.offsets = None
        self._lock = threading.Lock()
        self._thread = None
        self.failed = False

    @property
    def ready(self):
        return self.points is not None

    def start(self, retry=False):
        """Start once; a completed failure requires an explicit retry."""
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
            self.offsets = offsets
            self.points = points  # publish readiness only after its companion data
        except Exception:  # this optional study aid must not escape its worker
            self.points, self.offsets = None, None
            self.failed = True

    def neighbours(self, sids, limit=24, margin=0.02):
        """Return [(base, [sids], distance_m, system_key)] sorted by distance.

        Distances use float64 Euclidean arithmetic on the stored samples. Exact
        computed ties retain structure-index encounter order; no epsilon or
        rounding is added to the caller's distance cutoff.
        """
        if not self.ready:
            return None
        ds = self.ds
        sids = [s for s in sids if self.offsets[s + 1] > self.offsets[s]]
        if not sids:
            return []
        sel_bases = {ds.structures[s]["base"] for s in sids}
        lo = ds.bbox_min[sids] - margin
        hi = ds.bbox_max[sids] + margin
        overlap = np.zeros(ds.n, dtype=bool)
        for a, b in zip(lo, hi):
            overlap |= np.all((ds.bbox_max >= a) & (ds.bbox_min <= b), axis=1)
        cands = [c for c in np.flatnonzero(overlap)
                 if ds.structures[c]["system"] not in EXCLUDED_SYSTEMS and not ds.structures[c].get("role")
                 and ds.structures[c]["base"] not in sel_bases and self.offsets[c + 1] > self.offsets[c]]
        if not cands:
            return []
        sel_pts = np.concatenate([self.points[self.offsets[s]:self.offsets[s + 1]] for s in sids])
        if len(sel_pts) > 3000:
            sel_pts = sel_pts[np.random.default_rng(1).choice(len(sel_pts), 3000, replace=False)]
        from scipy.spatial import cKDTree
        tree = cKDTree(sel_pts)
        best = {}
        batch, owners = [], []

        def flush():
            if not batch:
                return
            pts = np.concatenate(batch)
            own = np.concatenate(owners)
            # Avoid a batch-by-selection distance matrix and float32
            # cancellation for near-touching structures far from the origin.
            dmin = tree.query(pts, k=1, eps=0.0, p=2, workers=1)[0]
            order = np.argsort(own, kind="stable")
            own_sorted, d_sorted = own[order], dmin[order]
            starts = np.flatnonzero(np.r_[True, own_sorted[1:] != own_sorted[:-1]])
            mins = np.minimum.reduceat(d_sorted, starts)
            for c, d in zip(own_sorted[starts], mins):
                best[int(c)] = float(d)
            batch.clear()
            owners.clear()

        count = 0
        for c in cands:
            pts = self.points[self.offsets[c]:self.offsets[c + 1]]
            batch.append(pts)
            owners.append(np.full(len(pts), c, dtype=np.int64))
            count += len(pts)
            if count > 6000:
                flush()
                count = 0
        flush()
        by_base = {}
        for c, d in best.items():
            s = ds.structures[c]
            key = s["base"]
            if key not in by_base:
                by_base[key] = [key, [], d, s["system"]]
            entry = by_base[key]
            entry[1].append(c)
            entry[2] = min(entry[2], d)
        out = sorted(by_base.values(), key=lambda e: e[2])
        return [tuple(e) for e in out[:limit]]
