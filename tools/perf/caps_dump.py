"""Cut-view pixels and cap targets of one model, to compare two trees byte for byte.
python caps_dump.py <model> <out.npz> [sections: x position fraction list]   (from the tree root, through the GPU lock)"""
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
cl = [i for i in range(len(m.items)) if m.items[i].clip]
cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
out = {}
fr = [float(x) for x in sys.argv[3:]] or [0.5]
lo, hi = float(np.min(cx)), float(np.max(cx))
from app.gpu.post import read_texture
def grab(tag):
    sess.warm(3)
    out[tag + "_frame"] = np.asarray(sess.grab_array())
    caps = r.caps
    for n, dt, c in (("albedo", np.float16, 4), ("normal", np.float16, 4), ("id", np.float32, 2), ("zp", np.float32, 1)):
        if n in caps.t:
            out[tag + "_" + n] = np.asarray(read_texture(r.device, caps.t[n], dt, c))
for i, f in enumerate(fr):
    w.sections[0] = [lo + (hi - lo) * f, bool(i % 2)]
    grab("s%d" % i)
np.savez_compressed(sys.argv[2], **{k: v for k, v in out.items() if v is not None})
print("saved", sorted(out))
sess.close()
