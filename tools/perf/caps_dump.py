"""Cut-view pixels and cap targets of one model, to compare two trees byte for byte.
python caps_dump.py <model> <out.npz> [section positions as fractions of the model box]   (from the tree root, through the GPU lock)
Scenario (env CAPS_DUMP_SCEN): x (default; one section on x, the flip alternates), multi (sections on x, z and y with their flips),
corner (the cut-away: two planes, mode 1, flips alternate).
Stores per position <tag>_frame, _albedo, _normal, _id, _zp and, when the cap passes used cluster masks, <tag>_mask =
(clusters, cap list, KEPT, STRADDLE clusters) read back from the indirect arguments."""
import sys, os
import numpy as np
sys.path.insert(0, os.getcwd())
from tools.perf import perfkit as pk
pk.env_setup()
from tools.perf.viewer_session import ViewerSession, timed_prepare
from app.gpu.renderer import WgpuRenderer
entry, m, load = timed_prepare(sys.argv[1])
sess = ViewerSession(entry, m, backend="wgpu", renderer_factory=lambda gpu: WgpuRenderer(gpu, profile=False))
r, w = sess.r, sess.w
scen = os.environ.get("CAPS_DUMP_SCEN", "x")
cl = [i for i in range(len(m.items)) if m.items[i].clip]
cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
out = {}
fr = [float(x) for x in sys.argv[3:]] or [0.5]
lo, hi = float(np.min(cx)), float(np.max(cx))
bmin, bmax = np.asarray(m.bounds_min, np.float64), np.asarray(m.bounds_max, np.float64)
from app.gpu.post import read_texture


def read_mask():
    c = r.caps.mask_counts()
    return np.zeros(4, np.int64) if c is None else np.array(c, np.int64)


def grab(tag):
    sess.warm(3)
    out[tag + "_frame"] = np.asarray(sess.grab_array())
    caps = r.caps
    for n, dt, c in (("albedo", np.float16, 4), ("normal", np.float16, 4), ("id", np.float32, 2), ("zp", np.float32, 1)):
        if n in caps.t:
            out[tag + "_" + n] = np.asarray(read_texture(r.device, caps.t[n], dt, c))
    if getattr(caps, "last_mask", None) is not None:
        out[tag + "_mask"] = read_mask()
        print(tag, "lists: clusters, cap, kept, straddle =", out[tag + "_mask"].tolist(), flush=True)


for i, f in enumerate(fr):
    flip = bool(i % 2)
    if scen == "x":
        w.sections[0] = [lo + (hi - lo) * f, flip]
    elif scen == "multi":
        w.sections[0] = [lo + (hi - lo) * f, flip]
        w.sections[1] = [float(bmin[2] + (bmax[2] - bmin[2]) * (0.3 + 0.4 * f)), not flip]       # axis 1 is z
        w.sections[2] = [float(bmin[1] + (bmax[1] - bmin[1]) * (0.7 - 0.4 * f)), flip] if i % 3 else None   # axis 2 is y
    elif scen == "corner":
        w.sections = [None, None, None]
        xf = lo + (hi - lo) * f
        yc = float((bmin[1] + bmax[1]) / 2)
        s = -1.0 if flip else 1.0
        w.cut_on = True
        w.cut_planes = ((-s, 0.0, 0.0, s * xf), (0.0, -s, 0.0, s * yc), (0.0, 0.0, 0.0, 0.0))
    grab("s%d" % i)
np.savez_compressed(sys.argv[2], **{k: v for k, v in out.items() if v is not None})
print("saved", sorted(out))
sess.close()
