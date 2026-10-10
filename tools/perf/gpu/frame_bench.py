"""wgpu model-viewer frame timing, the wgpu counterpart of bench_models.py's orbit section: the real WgpuModelViewport at
2560x1600 physical pixels (device pixel ratio 2, 4x MSAA by the default settings), 120 orbit frames of 3 degrees with a
mouse button "held", each frame = widget _paint_frame + wait for the GPU. GPU time per pass from timestamp queries.

    python <scratch>/tools/gpu_lock.py <repo>/.venv/Scripts/python.exe tools/perf/gpu/frame_bench.py <out_dir> model [model ...]
    (ANATOMY_WGPU_ADAPTER=UHD selects the Intel adapter)

Writes <out_dir>/<adapter tag>/<model>.json.
"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import numpy as np                                                    # noqa: E402

PASSES = ("backdrop_ms", "vis_ms", "geom_ms", "ssao_ms", "shade_ms", "composite_ms", "final_ms", "caps_ms", "total_ms")


def stats(v):
    v = sorted(v)
    return {"median": round(statistics.median(v), 3), "p95": round(v[min(len(v) - 1, int(0.95 * len(v)))], 3),
            "max": round(v[-1], 3), "mean": round(sum(v) / len(v), 3)}


def run(model_id, out, frames=120):
    from tools.perf import perfkit as pk
    pk.env_setup()
    from tools.perf.viewer_session import ViewerSession, timed_prepare
    from tools.perf.gpu.visbuf_check import calibrate_period_ns
    from app.gpu.renderer import WgpuRenderer
    entry, model, load = timed_prepare(model_id)
    sess = ViewerSession(entry, model, backend="wgpu", renderer_factory=lambda gpu: WgpuRenderer(gpu, profile=True))
    if sess.error:
        raise RuntimeError(sess.error)
    r = sess.r
    r.ts_period_ns = calibrate_period_ns(sess.gpu)[0]
    sess.warm(4)
    settled = [sess.paint()["wall_ms"] for _ in range(20)]
    rows, walls = [], []
    for row in sess.orbit_run(frames=frames, step_deg=3.0):
        walls.append(row["wall_ms"])
        rows.append(dict(r.timings))
    res = {"model": model_id, "backend": "wgpu", "adapter": str(sess.gpu.info), "ts_period_ns": r.ts_period_ns,
           "triangles": int(model.triangle_count), "render_size": list(sess.render_size), "samples": int(sess.w.rsettings.msaa),
           "frames": frames, "load": load, "upload_s": round(sess.upload.get("upload_s", 0.0), 3),
           "gpu_bytes": int(r.geom.stats.get("gpu_bytes", 0)),
           "settled_wall_ms": stats(settled), "orbit_wall_ms": stats(walls),
           "orbit_gpu_ms": {k: stats([x[k] for x in rows if k in x]) for k in PASSES if rows and k in rows[0]},
           "draw_slots": len(r.last_draws)}
    tag = "uhd" if "intel" in str(sess.gpu.info).lower() else "rtx3080" if "3080" in str(sess.gpu.info) else "gpu"
    d = Path(out) / tag
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{model_id}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{model_id} [{tag}] orbit wall median {res['orbit_wall_ms']['median']} p95 {res['orbit_wall_ms']['p95']} ms; gpu total "
          f"{res['orbit_gpu_ms']['total_ms']['median']} ms; " + " ".join(f"{k[:-3]}={res['orbit_gpu_ms'][k]['median']}" for k in PASSES[:-1]),
          flush=True)
    sess.close()


if __name__ == "__main__":
    out = sys.argv[1]
    for m in sys.argv[2:]:
        run(m, out)
