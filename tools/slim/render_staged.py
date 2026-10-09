"""In-app renders of a model before and after its staged simplified copy: the opening view and a close-up on its
largest simplified part, same camera and light for both.  usage: render_staged.py SLIM_DIR OUT_DIR model ..."""
import gc, json, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_viewer import setup
import moderngl
from PySide6.QtGui import QGuiApplication
QGuiApplication.instance() or QGuiApplication([])
from PIL import Image
from app.variants import local_runtime
from app.viewer.camera import OrbitCamera
from app.viewer.renderer import Renderer, Settings

W, H = 960, 680
slim, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
staged = {s["model"]: s for s in json.loads((slim / "staged" / "summary.json").read_text())}
res = [json.loads(l) for l in open(slim / "results.jsonl")]
ctx = moderngl.create_standalone_context(require=410)
fbo = ctx.framebuffer([ctx.renderbuffer((W, H), 4)])
original_decode = local_runtime.decode_local_npz
swap = {}


def decode(path, *a, **k):
    return original_decode(swap.get(str(Path(path).resolve()), path), *a, **k)


local_runtime.decode_local_npz = decode


def views(m, focus):
    lo, hi = m.bounds_min, m.bounds_max
    yield "open", (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 0.95
    if focus is not None:
        p = next((p for p in m.parts if p.name == focus), None)
        if p is not None:
            idx = np.unique(m.indices[p.first:p.first + p.count])
            pts = m.vertices[idx, :3]
            plo, phi = pts.min(0), pts.max(0)
            r = float(np.linalg.norm(phi - plo)) / 2
            yield "close", (plo + phi) / 2, max(r * 0.35, float(np.linalg.norm(hi - lo)) * 0.03)


def render(m, fs, name, centre, radius):
    s = Settings()
    for k, v in getattr(m, "look_defaults", {}).items():
        setattr(s, k, v)
    s.msaa, s.shadows = 4, False
    cam = OrbitCamera(); cam.set_scene(m.bounds_min, m.bounds_max)
    cam.animate_to(centre, cam.fit_distance(radius, W / H), math.radians(35), math.radians(24), 0.0)
    r = Renderer(ctx); r.set_model(m)
    r.render(fbo, (W, H), cam, s, fs); ctx.finish()
    img = np.frombuffer(fbo.read(components=3), dtype=np.uint8).reshape(H, W, 3)[::-1]
    Image.fromarray(img).save(out / name, quality=88)
    r.release()


for mid in sys.argv[3:]:
    st = staged[mid]
    parts = sorted((r for r in res if r["model"] == mid and r.get("accepted")), key=lambda r: -r["triangles"])
    focus = parts[0]["part"] if parts else None
    try:
        for tag, target in (("before", None), ("after", st["file"])):
            swap.clear()
            if target:
                swap[str(Path(st["source"]).resolve())] = target
            m, fs = setup(mid)
            tri = int(len(m.indices) // 3)
            for view, centre, radius in views(m, focus):
                render(m, fs, f"{mid}__{view}__{tag}.jpg", centre, radius)
            print(mid, tag, f"{tri:,} triangles", flush=True)
            with open(out / "counts.jsonl", "a") as fh:
                fh.write(json.dumps({"model": mid, "tag": tag, "triangles": tri, "focus": focus}) + "\n")
            m = None; gc.collect()
    except BaseException as e:
        print(mid, "failed", repr(e)[:300], flush=True)
