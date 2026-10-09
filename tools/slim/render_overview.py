"""Opening-view renders of models (cut-away as they open), for the triangle audit.  usage: render_overview.py OUT id ..."""
import gc, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_viewer import setup
import moderngl
from PySide6.QtGui import QGuiApplication
QGuiApplication.instance() or QGuiApplication([])
from PIL import Image
from app.viewer.camera import OrbitCamera
from app.viewer.renderer import Renderer, Settings
W, H = 900, 650
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
ctx = moderngl.create_standalone_context(require=410)
fbo = ctx.framebuffer([ctx.renderbuffer((W, H), 4)])
for mid in sys.argv[2:]:
    try:
        m, fs = setup(mid)
        s = Settings()
        for k, v in getattr(m, "look_defaults", {}).items():
            setattr(s, k, v)
        s.msaa, s.shadows = 4, False
        lo, hi = m.bounds_min, m.bounds_max
        cam = OrbitCamera(); cam.set_scene(lo, hi)
        cam.animate_to((lo + hi) / 2, cam.fit_distance(float(np.linalg.norm(hi - lo)) / 2 * 0.95, W / H),
                       math.radians(35), math.radians(24), 0.0)
        r = Renderer(ctx); r.set_model(m)
        r.render(fbo, (W, H), cam, s, fs); ctx.finish()
        img = np.frombuffer(fbo.read(components=3), dtype=np.uint8).reshape(H, W, 3)[::-1]
        Image.fromarray(img).save(out / f"{mid}.png")
        r.release(); print(mid, "ok", flush=True)
    except BaseException as e:
        print(mid, "failed", repr(e)[:200], flush=True)
    m = None; gc.collect()
