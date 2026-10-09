"""Where the caps wall time goes: wall median with parts of the caps encode disabled (monkeypatch). python cut_prof.py <model>"""
import sys, time, os
import numpy as np
sys.path.insert(0, os.getcwd())
from tools.perf import perfkit as pk
pk.env_setup()
from tools.perf.viewer_session import ViewerSession, timed_prepare
from app.gpu.renderer import WgpuRenderer
from app.gpu import caps as capsmod
entry, model, load = timed_prepare(sys.argv[1])
sess = ViewerSession(entry, model, backend="wgpu", renderer_factory=lambda gpu: WgpuRenderer(gpu, profile=True))
r, w, m = sess.r, sess.w, model
cl = [i for i in range(len(m.items)) if m.items[i].clip]
cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
C = capsmod.CapPasses
orig = {n: getattr(C, n) for n in ("plan", "encode_gather", "encode_lay_in", "encode_colour", "encode_depth")}
T = []
def timed(self, *a, **k):
    t = time.perf_counter(); out = orig["plan"](self, *a, **k); T.append((time.perf_counter() - t) * 1e3); return out
def run(name, sect, off=()):
    for n in orig: setattr(C, n, orig[n])
    C.plan = timed
    for n in off: setattr(C, n, lambda self, *a, **k: None)
    if "plan" in off: C.plan = lambda self, *a, **k: None
    w.sections[0] = sect
    sess.warm(4)
    for _ in range(6): sess.paint()
    T.clear(); walls = []
    for row in sess.orbit_run(frames=40, step_deg=3.0):
        walls.append(row["wall_ms"])
    print(name, "wall", round(float(np.median(walls)), 1), "plan", round(float(np.median(T)), 2) if T else "-", flush=True)
run("nocut", None)
cut = [float(np.median(cx)), False]
run("cut_full", cut)
run("cut_no_gather", cut, ("encode_gather",))
run("cut_no_lay", cut, ("encode_lay_in",))
run("cut_no_colour", cut, ("encode_colour",))
run("cut_no_depth", cut, ("encode_depth",))
run("cut_no_caps", cut, ("encode_gather", "encode_lay_in", "encode_colour", "encode_depth"))
run("cut_no_plan", cut, ("plan",))
sess.close()
