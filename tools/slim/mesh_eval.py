"""How much a simplified mesh differs from the original: surface distance and surface direction (what shading shows),
both above what sampling alone measures on an unchanged surface.

usage: mesh_eval.py original.npz candidate.npz [...]   (prints one JSON line per candidate)"""
import json, sys
import numpy as np
from scipy.spatial import cKDTree
rng = np.random.default_rng(1)


def load(p):
    z = np.load(p)
    return z["vertices"].astype(np.float64), z["triangles"].astype(np.int64)


def face_normals(v, f):
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    a = np.linalg.norm(n, axis=1)
    return n / np.maximum(a[:, None], 1e-30), 0.5 * a


def sample(v, f, n):
    nrm, area = face_normals(v, f)
    pick = rng.choice(len(f), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    w = np.stack([1 - s, s * (1 - r2), s * r2], 1)
    return (v[f[pick]] * w[:, :, None]).sum(1), nrm[pick]


def compare(a_pts, a_nrm, tree, b_nrm):
    d, i = tree.query(a_pts)
    ang = np.degrees(np.arccos(np.clip(np.abs((a_nrm * b_nrm[i]).sum(1)), 0, 1)))
    return d, ang


def main():
    ov, of = load(sys.argv[1])
    edge = float(np.median(np.linalg.norm(ov[of[:, 0]] - ov[of[:, 1]], axis=1)))
    dense = int(min(max(600000, 3 * len(of)), 12000000))
    op, on = sample(ov, of, dense)
    otree = cKDTree(op)
    fp, fn = sample(ov, of, 80000)
    fd, fa = compare(fp, fn, otree, on)                       # floor: an unchanged surface against itself
    for cand in sys.argv[2:]:
        cv, cf = load(cand)
        cp, cn = sample(cv, cf, dense)
        ctree = cKDTree(cp)
        p1, n1 = sample(ov, of, 80000)
        d1, a1 = compare(p1, n1, ctree, cn)                   # original -> candidate
        p2, n2 = sample(cv, cf, 80000)
        d2, a2 = compare(p2, n2, otree, on)                   # candidate -> original
        d, a = np.concatenate([d1, d2]), np.concatenate([a1, a2])
        print(json.dumps({
            "candidate": cand.split("/")[-1], "triangles": int(len(cf)), "of_original": round(len(cf) / len(of), 3),
            "dist_p99_excess_edges": round(max(np.percentile(d, 99) - np.percentile(fd, 99), 0) / edge, 3),
            "dist_max_edges": round(float(d.max()) / edge, 2),
            "angle_p99_deg": round(float(np.percentile(a, 99)), 1), "angle_p99_floor_deg": round(float(np.percentile(fa, 99)), 1),
            "over_5deg_pct": round(100 * float((a > 5).mean()), 2), "over_5deg_floor_pct": round(100 * float((fa > 5).mean()), 2),
            "over_15deg_pct": round(100 * float((a > 15).mean()), 2), "over_15deg_floor_pct": round(100 * float((fa > 15).mean()), 2),
        }), flush=True)


if __name__ == "__main__":
    main()
