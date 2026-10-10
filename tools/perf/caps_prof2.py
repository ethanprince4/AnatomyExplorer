"""GPU time of the cut-face passes split by kind: cluster mask pass, parity passes, cap passes (summed over the items).
python caps_prof2.py <model> [section fraction of the box, default median]   (from the tree root, through the GPU lock)
Env: ANATOMY_CAPS_COMPACT=0 for the plain draws; CAPS_PROF_RECT=x0,y0,x1,y1 forces every item's scissor rectangle."""
import sys, os
import numpy as np
sys.path.insert(0, os.getcwd())
from tools.perf import perfkit as pk
pk.env_setup()
from tools.perf.viewer_session import ViewerSession, timed_prepare
from tools.perf.gpu.visbuf_check import calibrate_period_ns
from app.gpu.renderer import WgpuRenderer
from app.gpu import caps as capsmod
entry, m, load = timed_prepare(sys.argv[1])
sess = ViewerSession(entry, m, backend="wgpu", renderer_factory=lambda gpu: WgpuRenderer(gpu, profile=False))
r, w = sess.r, sess.w
period = calibrate_period_ns(sess.gpu)[0]
dev = r.device
C = capsmod.CapPasses
orig = C.encode_gather
S = {}


class Enc:
    """Command encoder proxy: a timestamp pair around every pass of the cap gather."""
    def __init__(self, enc, qs, kinds):
        self.e, self.qs, self.kinds = enc, qs, kinds

    def _tw(self, kind):
        i = len(self.kinds)
        self.kinds.append(kind)
        return {"timestamp_writes": {"query_set": self.qs, "beginning_of_pass_write_index": 2 * i,
                                     "end_of_pass_write_index": 2 * i + 1}}

    def begin_render_pass(self, **kw):
        kw.pop("timestamp_writes", None)
        return self.e.begin_render_pass(**kw, **self._tw("render"))

    def begin_compute_pass(self, **kw):
        kw.pop("timestamp_writes", None)
        return self.e.begin_compute_pass(**kw, **self._tw("mask"))

    def __getattr__(self, n):
        return getattr(self.e, n)


def prof(self, enc, plan, ts=None):
    if os.environ.get("CAPS_PROF_RECT"):
        for ci in plan.items:
            ci.rect = tuple(int(x) for x in os.environ["CAPS_PROF_RECT"].split(","))
    cap = 2 * (2 * len(plan.items) + 2)
    qs = dev.create_query_set(type="timestamp", count=cap)
    buf = dev.create_buffer(size=cap * 8, usage=capsmod.BU.QUERY_RESOLVE | capsmod.BU.COPY_SRC)
    kinds = []
    orig(self, Enc(enc, qs, kinds), plan)
    enc.resolve_query_set(qs, 0, 2 * len(kinds), buf, 0)
    S["buf"], S["kinds"], S["plan"] = buf, kinds, plan


C.encode_gather = prof
cl = [i for i in range(len(m.items)) if m.items[i].clip]
cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
pos = float(np.median(cx)) if len(sys.argv) < 3 else float(min(cx) + (max(cx) - min(cx)) * float(sys.argv[2]))
w.sections[0] = [pos, False]
sess.warm(4)
for _ in range(8):
    sess.paint()
acc = []
for _ in range(12):
    sess.paint()
    k = S["kinds"]
    ts = np.frombuffer(bytes(r.queue.read_buffer(S["buf"], 0, len(k) * 16)), dtype=np.uint64).astype(np.float64)
    dt = (ts[1::2] - ts[0::2]) * period * 1e-6
    row = {"mask": 0.0, "parity": 0.0, "cap": 0.0}
    seen = {}
    for i, kind in enumerate(k):
        if kind == "mask":
            row["mask"] += dt[i]
        else:
            n = seen.get("r", 0)
            seen["r"] = n + 1
            row["parity" if n % 2 == 0 else "cap"] += dt[i]
    acc.append(row)
med = {key: float(np.median([a[key] for a in acc])) for key in acc[0]}
plan = S["plan"]
mk = plan.mask
print("adapter", sess.gpu.info, "render", sess.render_size, "items", len(plan.items), "draws", sum(len(ci.draws) for ci in plan.items),
      "masked parts", 0 if mk is None else len(mk.table), "slots", 0 if mk is None else mk.slots, "classes", r.caps.last_classes, "density", [round(x, 2) for x in r.caps.last_density][:40])
print("counts (clusters, caplist, kept, straddle)", r.caps.mask_counts())
print("ms  mask %.2f  parity %.2f  cap %.2f  total %.2f" % (med["mask"], med["parity"], med["cap"], sum(med.values())))
sess.close()
