"""Mesh health per part of each model: triangles, surface area, density against the model's average, duplicated
vertices (same position stored more than once), degenerate triangles (no area), slivers (longest edge over 20x the
shortest), and the count left after welding duplicates and dropping degenerate and repeated triangles.

usage: tri_health.py OUT_DIR model_id ..."""
import json, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_viewer import setup
from PySide6.QtGui import QGuiApplication
QGuiApplication.instance() or QGuiApplication([])

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
for mid in sys.argv[2:]:
    t0 = time.perf_counter()
    try:
        m, _fs = setup(mid)
    except BaseException as e:
        print(mid, "skipped", type(e).__name__, flush=True); continue
    pos = m.vertices[:, :3].astype(np.float64)
    diag = float(np.linalg.norm(np.asarray(m.bounds_max) - np.asarray(m.bounds_min))) or 1.0
    rows = []
    for p in m.parts:
        n = p.count // 3
        if n == 0:
            continue
        tris = m.indices[p.first:p.first + p.count].reshape(-1, 3).astype(np.int64)
        used = np.unique(tris)
        lo, hi = pos[used].min(0), pos[used].max(0)
        size = float(np.linalg.norm(hi - lo)) or diag
        q = np.round(pos[used] / (size * 1e-6)).astype(np.int64)
        _u, inv = np.unique(q, axis=0, return_inverse=True)
        weld = np.empty(len(pos), dtype=np.int64); weld[used] = inv.reshape(-1)
        wt = weld[tris]
        v = pos[tris]
        e = np.stack([np.linalg.norm(v[:, 1] - v[:, 0], axis=1), np.linalg.norm(v[:, 2] - v[:, 1], axis=1),
                      np.linalg.norm(v[:, 0] - v[:, 2], axis=1)], 1)
        a = 0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1)
        degenerate = (a < (size * 1e-6) ** 2) | (wt[:, 0] == wt[:, 1]) | (wt[:, 1] == wt[:, 2]) | (wt[:, 0] == wt[:, 2])
        sliver = (e.max(1) > 20 * np.maximum(e.min(1), 1e-30)) & ~degenerate
        good = wt[~degenerate]
        key = np.sort(good, axis=1)
        distinct_tris = len(np.unique(key, axis=0)) if len(key) else 0
        rows.append({
            "part": p.name, "item": m.items[p.item].name if p.item < len(m.items) else "", "triangles": n,
            "area": float(a.sum()), "size": round(size, 4),
            "vertices": int(len(used)), "distinct_positions": int(len(_u)),
            "degenerate_pct": round(100 * float(degenerate.mean()), 1),
            "sliver_pct": round(100 * float(sliver.mean()), 1),
            "after_cleanup": int(distinct_tris),
            "median_edge_vs_size": float(np.median(e) / size),
        })
    total_area = sum(r["area"] for r in rows) or 1.0
    total = sum(r["triangles"] for r in rows)
    for r in rows:
        r["density_vs_model"] = round((r["triangles"] / max(r["area"], 1e-30)) / (total / total_area), 2)
        r["area_pct"] = round(100 * r["area"] / total_area, 2)
        r["triangles_pct"] = round(100 * r["triangles"] / max(total, 1), 2)
        del r["area"]
        r["median_edge_vs_size"] = float(f'{r["median_edge_vs_size"]:.2e}')
    rows.sort(key=lambda r: -r["triangles"])
    summary = {"model": mid, "parts": len(rows), "triangles": total,
               "after_cleanup": sum(r["after_cleanup"] for r in rows), "seconds": round(time.perf_counter() - t0, 1)}
    (out / f"{mid}.json").write_text(json.dumps({"summary": summary, "parts": rows}, indent=1))
    print(mid, f"{total:,} tris, {summary['after_cleanup']:,} after cleanup ({summary['seconds']} s)", flush=True)
    del m
