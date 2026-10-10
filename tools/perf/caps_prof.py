"""Per-item GPU time of the caps gather passes (parity + cap), one timestamp pair per item, and the part classes.
python caps_prof.py <model> [out.json]   (run from the tree root, through the GPU lock)"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.getcwd())
from tools.perf import perfkit as pk
pk.env_setup()
from tools.perf.viewer_session import ViewerSession, timed_prepare
from tools.perf.gpu.visbuf_check import calibrate_period_ns
from app.gpu.renderer import WgpuRenderer
from app.gpu import caps as capsmod
entry, m, load = timed_prepare(sys.argv[1])
sess = ViewerSession(entry, m, backend="wgpu", renderer_factory=lambda gpu: WgpuRenderer(gpu, profile=True))
r, w = sess.r, sess.w
period = calibrate_period_ns(sess.gpu)[0]
dev = r.device
C = capsmod.CapPasses
orig = C.encode_gather
S = {}
def prof(self, enc, plan, ts=None):
    n = len(plan.items)
    qs = dev.create_query_set(type="timestamp", count=n * 2)
    buf = dev.create_buffer(size=n * 2 * 8, usage=capsmod.BU.QUERY_RESOLVE | capsmod.BU.COPY_SRC)
    for i, ci in enumerate(plan.items):
        if os.environ.get("CAPS_PROF_RECT"):
            ci.rect = tuple(int(x) for x in os.environ["CAPS_PROF_RECT"].split(","))
        sub = capsmod.CapPlan([ci], plan.n_draws, plan.size, plan.pages, plan.records)
        orig(self, enc, sub, (qs, 2 * i, 2 * i + 1))
    enc.resolve_query_set(qs, 0, n * 2, buf, 0)
    S["buf"], S["plan"], S["n"] = buf, plan, n
C.encode_gather = prof
if os.environ.get("CAPS_PROF_SHADER"):         # timing only: "old=>new" text replacement in caps_gather.wgsl
    _o, _n = os.environ["CAPS_PROF_SHADER"].split("=>")
    _t = capsmod._text
    capsmod._text = lambda name: _t(name).replace(_o, _n) if name == "caps_gather.wgsl" else _t(name)
if os.environ.get("CAPS_PROF_CLASS"):          # timing only: force every part to one class (0 kept, 1 straddle)
    C._classes = lambda self, model, parts, *a, **k: {p.id: int(os.environ["CAPS_PROF_CLASS"]) for p in parts}
cl = [i for i in range(len(m.items)) if m.items[i].clip]
cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
w.sections[0] = [float(np.median(cx)), False]
sess.warm(4)
for _ in range(8): sess.paint()
acc = []
for _ in range(10):
    sess.paint()
    ts = np.frombuffer(bytes(r.queue.read_buffer(S["buf"], 0, S["n"] * 16)), dtype=np.uint64).astype(np.float64)
    acc.append((ts[1::2] - ts[0::2]) * period * 1e-6)
acc = np.median(np.array(acc), 0)
plan = S["plan"]
rows = []
for i, ci in enumerate(plan.items):
    x0, y0, x1, y1 = ci.rect
    rows.append({"item": ci.item, "rect_px": (x1 - x0) * (y1 - y0), "draws": len(ci.draws),
                 "tris_clip": sum(d[3] for d in ci.draws if d[4]) // 3, "tris_kept": sum(d[3] for d in ci.draws if not d[4]) // 3,
                 "ms": float(acc[i])})
print("adapter", sess.gpu.info, "render", sess.render_size, "items", len(rows), "classes kept/straddle/removed", r.caps.last_classes)
print("total ms %.2f tris_clip %d tris_kept %d draws %d" % (sum(x["ms"] for x in rows), sum(x["tris_clip"] for x in rows), sum(x["tris_kept"] for x in rows), sum(x["draws"] for x in rows)))
rows.sort(key=lambda x: -x["ms"])
for x in rows[:8]: print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in x.items()})
if len(sys.argv) > 2: json.dump(rows, open(sys.argv[2], "w"), indent=1)
sess.close()
