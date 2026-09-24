"""Small helpers shared by the liver lobule and lung acinus models (voxel-slab evaluation, cell mosaics, stellate
cells)."""
import numpy as np

from .organic import cell_profile
from .sdf import Volume, ellipsoid, round_cone


def chunked(vol, fn, step=48):
    """Evaluate fn(x, y, z) over the volume in slabs along x, keeping peak memory low."""
    out = np.empty(vol.shape, np.float32)
    for i in range(0, vol.shape[0], step):
        j = min(i + step, vol.shape[0])
        x, y, z = vol.axes((i, 0, 0), (j, vol.shape[1], vol.shape[2]))
        out[i:j] = np.broadcast_to(fn(x, y, z), (j - i,) + vol.shape[1:])
    return out


def band_cells(vol, d, size, amp, seed, band=0.012, dome=0.35):
    """Stamp a polygonal cell mosaic onto a surface, evaluating the Worley field only near it."""
    ii = np.nonzero(np.abs(d) < band)
    p = np.stack(ii, -1) * vol.voxel + vol.lo
    prof = cell_profile(p, size, seed, groove=0.22, dome=dome)
    d[ii] += ((0.55 - prof) * amp).astype(np.float32)
    return d


def star_cell(c, body, arms, length, rng, sub_vox=0.0025, flat=None, extra=()):
    """A cell body with tapering processes (macrophages, Kupffer and stellate cells)."""
    c = np.asarray(c, float)
    sub = Volume(c - length - max(body), c + length + max(body), sub_vox)
    shapes = [ellipsoid(c, body)] + list(extra)
    for _ in range(arms):
        dvec = rng.normal(size=3)
        if flat is not None:
            dvec -= flat * np.dot(dvec, flat)
        dvec /= np.linalg.norm(dvec) + 1e-9
        shapes.append(round_cone(c, c + dvec * length * rng.uniform(0.7, 1.1), min(body) * 0.45, 0.0018))
    sub.add_all(shapes, "smooth", 0.004)
    return sub.mesh(0.6)
