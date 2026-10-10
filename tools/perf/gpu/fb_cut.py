"""frame_bench with and without the sagittal cut plane of make_reference (same session).
    python tools/perf/gpu/fb_cut.py <out.json> <model>   (ANATOMY_WGPU_ADAPTER=UHD selects the Intel adapter)"""
import json, sys, statistics
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.perf import perfkit as pk
pk.env_setup()
from tools.perf.viewer_session import ViewerSession, timed_prepare
from tools.perf.gpu.visbuf_check import calibrate_period_ns
from tools.perf.gpu.frame_bench import stats, PASSES
from app.gpu.renderer import WgpuRenderer
model_id = sys.argv[2]
entry, model, load = timed_prepare(model_id)
sess = ViewerSession(entry, model, backend="wgpu", renderer_factory=lambda gpu: WgpuRenderer(gpu, profile=True))
r = sess.r; w = sess.w; m = model
r.ts_period_ns = calibrate_period_ns(sess.gpu)[0]
out = {"adapter": str(sess.gpu.info)}
cl = [i for i in range(len(m.items)) if m.items[i].clip]
cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
pos = float(np.median(cx))
for name in ("nocut", "cut", "nocut2", "cut2"):
    w.sections[0] = [pos, False] if name.startswith("cut") else None
    sess.warm(4)
    for _ in range(10): sess.paint()
    walls, rows = [], []
    for row in sess.orbit_run(frames=120, step_deg=3.0):
        walls.append(row["wall_ms"]); rows.append(dict(r.timings))
    out[name] = {"wall": stats(walls), "gpu": {k: stats([x[k] for x in rows]) for k in PASSES if k in rows[0]}}
    print(name, out[name]["wall"]["median"], out[name]["gpu"]["total_ms"]["median"], flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
sess.close()
