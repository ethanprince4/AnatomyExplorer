"""Lumen courses for the shipped axillary teaching specimen.

These are the accepted specimen's authored rail/branch paths, not a new vascular
layout. Radii are schematic model units; the bore leaves a visible vessel wall.
"""
import numpy as np
from .geometry import Mesh, tube
from .kit import smooth_path, at
from . import skin
from .base import Part
from .organic import settle


def lumen_cutters():
    xs = np.linspace(-.92, -.08, 85)
    ra = np.stack([xs, .755 + .008 * np.cos(xs * 3), .20 + .035 * np.sin(xs * 4)], 1)
    rv = ra + [0, -.025, .055]
    dx = np.r_[np.linspace(-1.04, -.92, 13)[:-1], xs, np.linspace(-.08, .24, 33)[1:]]
    da = np.stack([dx, .34 + .018 * np.sin(dx * 3), np.full_like(dx, .13)], 1)
    dv = da + [0, -.028, .060]
    courses = [(da, .019), (dv, .024), (ra, .009), (rv, .012)]
    for k in [15, 44, 69]:
        j = int(np.argmin(abs(da[:, 0] - ra[k, 0])))
        a0, a1, v0, v1 = da[j], ra[k], dv[j], rv[k]
        courses.extend([
            (smooth_path([a0, (a0 + a1) / 2 + [-.024, 0, -.018], a1], 45), .011),
            (smooth_path([v0, (v0 + v1) / 2 + [.022, 0, .025], v1], 45), .014),
        ])
    cfg = skin.CONFIG['axilla']
    fols = skin._follicle_specs('axilla', cfg)
    dej = skin._hairy_geometry('axilla', cfg, fols)['dej']
    for k in [10, 25, 39, 55, 72]:
        a, b = ra[k], rv[k]
        mid = (a + b) * .5
        peak = np.array([mid[0], at(dej, mid[0], mid[2]) - .020, mid[2]])
        controls = [a, a + [0, .040, 0], peak + [0, -.020, -.014], peak,
                    peak + [0, -.020, .014], b + [0, .04, 0], b]
        courses.append((smooth_path(controls, 50), .005))
    cutters = []
    for path, radius in courses:
        # Extend bores past the terminal rims. The receiving parent bore clears
        # branch endpoints; extension also opens the exposed specimen ports.
        path = np.vstack([path[0] - (path[1] - path[0]), path,
                          path[-1] + (path[-1] - path[-2])])
        cutters.append(Part('Vascular lumen cutter', 'Construction', '#ffffff',
                            tube(path, radius * .70, 20), '', clip=True))
    settle(cutters, seed=104, amp_xz=.030, amp_y=.070, freq=1.7)
    return [part.mesh for part in cutters]
