"""Shared mesh helpers for the decimation bench."""
import numpy as np


def clean(pos, tris, size):
    """Weld vertices closer than a millionth of the part's size, drop degenerate and repeated triangles."""
    used, inv = np.unique(tris, return_inverse=True)
    q = np.round(pos[used] / (size * 1e-6)).astype(np.int64)
    _u, first, weld = np.unique(q, axis=0, return_index=True, return_inverse=True)
    p = pos[used][first]
    t = weld.reshape(-1)[inv.reshape(-1)].reshape(-1, 3)
    v = p[t]
    a = 0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1)
    ok = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2]) & (a > (size * 1e-7) ** 2)
    t = t[ok]
    t = t[np.unique(np.sort(t, 1), axis=0, return_index=True)[1]]
    keep = np.unique(t)
    remap = np.full(len(p), -1); remap[keep] = np.arange(len(keep))
    return p[keep], remap[t]
