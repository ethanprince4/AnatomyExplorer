"""Stage B: for each exported part, Blender Collapse at 25%, then 15% if that passes or 50% if it fails; keep the
most reduced copy that is indistinguishable from the original (shape and shading against an unchanged surface).

Every piece is simplified and judged by the same check; a part made of many separate pieces (cells, nuclei) is
sampled at least PER_PIECE points per piece, so one damaged piece cannot hide in the part's average. MIN_PIECE_AREA
can keep pieces under that share of the model's surface untouched (0 = off).
usage: slim_decimate.py OUT [manifest lines start:end]"""
import json, math, os, sys, time
from pathlib import Path
import numpy as np
import bpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_eval as E
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
MIN_PIECE_AREA = 0.0             # of the model's total surface area (0: every piece goes through the check)
PER_PIECE = 10                   # sample points per separate piece, at least
DEBRIS_TRIANGLES = 100000        # a small piece with this many triangles is not a cell: listed for review
HEALTH = Path(os.environ.get("SLIM_HEALTH", ""))   # tri_health.py output; only used when MIN_PIECE_AREA > 0
out = Path(sys.argv[1])
rows = [json.loads(l) for l in open(out / "manifest.jsonl")]
a, b = (int(x) for x in sys.argv[2].split(":")) if len(sys.argv) > 2 else (0, len(rows))
bpy.ops.wm.read_factory_settings(use_empty=True)


def collapse(v, f, ratio):
    me = bpy.data.meshes.new("m")
    me.vertices.add(len(v)); me.vertices.foreach_set("co", v.astype(np.float32).ravel())
    me.loops.add(f.size); me.loops.foreach_set("vertex_index", f.astype(np.int32).ravel())
    me.polygons.add(len(f)); me.polygons.foreach_set("loop_start", np.arange(0, f.size, 3, dtype=np.int32))
    me.polygons.foreach_set("loop_total", np.full(len(f), 3, dtype=np.int32))
    me.update(); me.validate()
    ob = bpy.data.objects.new("o", me); bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("d", "DECIMATE"); mod.decimate_type = "COLLAPSE"; mod.ratio = ratio
    mod.use_collapse_triangulate = True
    ob.modifiers.new("t", "TRIANGULATE")
    em = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    co = np.empty(len(em.vertices) * 3, np.float32); em.vertices.foreach_get("co", co)
    em.calc_loop_triangles()
    tv = np.empty(len(em.loop_triangles) * 3, np.int32); em.loop_triangles.foreach_get("vertices", tv)
    bpy.data.objects.remove(ob); bpy.data.meshes.remove(me)
    return co.reshape(-1, 3).astype(np.float64), tv.reshape(-1, 3).astype(np.int64)


def pieces(v, f):
    """Connected component of every triangle, and each component's area."""
    k = len(v)
    a = np.concatenate([f[:, 0], f[:, 1]]); b = np.concatenate([f[:, 1], f[:, 2]])
    n, lab = connected_components(coo_matrix((np.ones(len(a), np.int8), (a, b)), shape=(k, k)), directed=False)
    fl = lab[f[:, 0]]
    area = 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)
    return fl, np.bincount(fl, weights=area, minlength=n), np.bincount(fl, minlength=n), float(area.sum())


def submesh(v, f):
    u = np.unique(f); r = np.full(len(v), -1); r[u] = np.arange(len(u))
    return v[u], r[f]


def score(ov, of, cv, cf, otree, on, floor, probes, dense):
    # the copy is sampled as densely as the original: a sparser sample on one side alone measures as error
    cp, cn = E.sample(cv, cf, dense)
    ctree = cKDTree(cp)
    p1, n1 = E.sample(ov, of, probes); d1, a1 = E.compare(p1, n1, ctree, cn)
    p2, n2 = E.sample(cv, cf, probes); d2, a2 = E.compare(p2, n2, otree, on)
    d, ang = np.concatenate([d1, d2]), np.concatenate([a1, a2])
    fd, fa, edge = floor
    s = {"triangles": int(len(cf)),
         "dist_excess_edges": round(max(float(np.percentile(d, 99) - np.percentile(fd, 99)), 0) / edge, 3),
         "angle_p99": round(float(np.percentile(ang, 99)), 2), "angle_p99_floor": round(float(np.percentile(fa, 99)), 2),
         "over5": round(100 * float((ang > 5).mean()), 3), "over5_floor": round(100 * float((fa > 5).mean()), 3)}
    s["pass"] = (s["angle_p99"] <= s["angle_p99_floor"] + 0.8 and s["over5"] <= s["over5_floor"] + 0.15
                 and s["dist_excess_edges"] <= 0.25)
    return s


for r in rows[a:b]:
    t0 = time.perf_counter()
    z = np.load(r["file"]); pv, pf = z["vertices"].astype(np.float64), z["triangles"].astype(np.int64)
    # the model's whole surface, from the audit's share for this part
    health = HEALTH / f"{r['model']}.json" if str(HEALTH) else None
    hp = (next((p for p in json.loads(health.read_text())["parts"] if p["part"] == r["part"]), None)
          if health and health.exists() else None)
    fl, carea, ccount, part_area = pieces(pv, pf)
    model_area = part_area * 100.0 / hp["area_pct"] if hp and hp["area_pct"] > 0 else part_area
    big = carea >= MIN_PIECE_AREA * model_area
    debris = [int(c) for c in ccount[(~big) & (ccount >= DEBRIS_TRIANGLES)]]
    info = {"pieces": int(len(carea)), "big_pieces": int(big.sum()),
            "big_piece_triangles": int(ccount[big].sum()), "small_kept_triangles": int(ccount[~big].sum()),
            "small_debris_pieces": debris}
    if not big.any():
        res = dict(r, **info, skipped="every piece is under 1% of the model's surface", seconds=round(time.perf_counter() - t0, 1))
        with open(out / "results.jsonl", "a") as fh:
            fh.write(json.dumps(res) + "\n")
        print(r["model"], r["part"][:36], "skipped: all", info["pieces"], "pieces small", ("debris " + str(debris)) if debris else "", flush=True)
        continue
    keep_f = pf[~big[fl]]                                 # small pieces: kept exactly
    ov, of = submesh(pv, pf[big[fl]])                     # big pieces: the ones simplified and scored
    edge = float(np.median(np.linalg.norm(ov[of[:, 0]] - ov[of[:, 1]], axis=1)))
    dense = int(min(max(600000, 3 * len(of)), 6000000))
    op, on = E.sample(ov, of, dense); otree = cKDTree(op)
    probes = int(min(max(60000, PER_PIECE * int(big.sum())), 1000000))
    fp, fn = E.sample(ov, of, probes); fd, fa = E.compare(fp, fn, otree, on)
    floor = (fd, fa, edge)
    tried, best = [], None
    plan = [0.25]
    while plan:
        ratio = plan.pop(0)
        cv, cf = collapse(ov, of, ratio)
        s = score(ov, of, cv, cf, otree, on, floor, probes, dense); s["ratio"] = ratio
        tried.append(s)
        if s["pass"]:
            if best is None or s["triangles"] < best[0]["triangles"]:
                best = (s, cv, cf)
            if ratio == 0.25: plan.append(0.15)
            elif ratio == 0.15: plan.append(0.08)
        elif ratio == 0.25:
            plan.append(0.5)
    res = dict(r, **info, tried=tried, seconds=round(time.perf_counter() - t0, 1))
    if best:
        s, cv, cf = best
        kv, kf = submesh(pv, keep_f) if len(keep_f) else (np.zeros((0, 3)), np.zeros((0, 3), np.int64))
        allv = np.vstack([cv, kv]); allf = np.vstack([cf, kf + len(cv)])
        path = r["file"].replace(".npz", f"__slim{int(s['ratio'] * 100)}.npz")
        np.savez_compressed(path, vertices=allv.astype(np.float32), triangles=allf.astype(np.int32))
        res.update(accepted=dict(s, part_triangles=int(len(allf))), slim_file=path)
    with open(out / "results.jsonl", "a") as fh:
        fh.write(json.dumps(res) + "\n")
    print(r["model"], r["part"][:36], r["cleaned"], f"(big pieces {info['big_piece_triangles']})", "->", (best[0]["triangles"] if best else "no pass"),
          [(t["ratio"], t["angle_p99"], t["pass"]) for t in tried], f"{res['seconds']} s", flush=True)
