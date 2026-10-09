"""Per-frame cost of a model in the app's model-viewer renderer, split into what drives it.

    python bench_viewer.py <model_id> [...] [--size 1600x1000] [--frames 6]

For each model: draw calls and uniform uploads per frame, Python time per frame (renderer code only, measured at a
tiny resolution with geometry already cheap), and full-resolution frame time (software GL, so only relative).
"""
import argparse
import cProfile
import math
import pstats
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def setup(mid):
    from app.viewer.procedural import cutaway_planes
    from app.viewer.renderer import FrameState
    from render_model import find_entry
    entry = find_entry(mid)
    model = entry.load() if hasattr(entry, 'load') else entry.prepare_cpu(None)
    vis = np.ones(len(model.items), dtype=bool)
    fs = FrameState(visible=vis)
    cut = getattr(model, "cutaway", None)
    if cut is not None and cut["on"]:
        fs.clip_planes, fs.clip_on, fs.clip_mode = tuple(cutaway_planes(cut)), (True, True, False), 1
    model.evaluate(model.clip_range[0], None, 1.0)
    return model, fs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--size", default="1600x1000")
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--msaa", type=int, default=8)
    ap.add_argument("--profile", action="store_true")
    a = ap.parse_args()
    import moderngl
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    from app.viewer.camera import OrbitCamera
    from app.viewer.renderer import Renderer, Settings
    W, H = (int(v) for v in a.size.split("x"))
    ctx = moderngl.create_standalone_context(require=410)
    print(f"GL: {ctx.info.get('GL_RENDERER')}  max_samples={ctx.max_samples}", flush=True)
    for mid in a.models:
        t_load = time.perf_counter()
        model, fs = setup(mid)
        r = Renderer(ctx)
        r.set_model(model)
        s = Settings()
        for k, v in getattr(model, "look_defaults", {}).items():
            setattr(s, k, v)
        s.msaa = a.msaa
        cam = OrbitCamera()
        cam.set_scene(model.bounds_min, model.bounds_max)
        lo, hi = model.bounds_min, model.bounds_max
        cam.yaw, cam.pitch = math.radians(35), math.radians(24)
        cam.animate_to((lo + hi) / 2, cam.fit_distance(float(np.linalg.norm(hi - lo)) / 2 * 0.95, W / H),
                       cam.yaw, cam.pitch, 0.0)
        load_s = time.perf_counter() - t_load
        # count draws and uniform writes
        counts = {"draw": 0, "uniform": 0, "fbo_use": 0}
        real_render = moderngl.VertexArray.render
        from app.viewer import renderer as R
        real_call = R._U.__call__

        def counted(self, *aa, **kw):
            counts["draw"] += 1
            return real_render(self, *aa, **kw)

        def counted_u(self, name, value):
            counts["uniform"] += 1
            return real_call(self, name, value)

        def frame(size, n):
            fbo = ctx.framebuffer([ctx.renderbuffer(size, 4)])
            r.render(fbo, size, cam, s, fs)
            ctx.finish()
            times = []
            for i in range(n):
                cam.yaw += 0.03                 # rotating: the camera-relative lights re-render the shadows
                t0 = time.perf_counter()
                r.render(fbo, size, cam, s, fs)
                t1 = time.perf_counter()
                ctx.finish()
                times.append((t1 - t0, time.perf_counter() - t0))
            fbo.release()
            return np.median([t[0] for t in times]), np.median([t[1] for t in times])

        moderngl.VertexArray.render = counted
        R._U.__call__ = counted_u
        try:
            cam.yaw += 0.03
            fbo = ctx.framebuffer([ctx.renderbuffer((64, 40), 4)])
            r.render(fbo, (64, 40), cam, s, fs)
            fbo.release()
        finally:
            moderngl.VertexArray.render = real_render
            R._U.__call__ = real_call
        cut_items = None
        tiny_submit, tiny_total = frame((64, 40), a.frames)
        full_submit, full_total = frame((W, H), max(2, a.frames // 2))
        print(f"{mid:22s} tris={model.triangle_count:>11,d} parts={len(model.parts):>4d} items={len(model.items):>4d} "
              f"draws/frame={counts['draw']:>5d} uniforms/frame={counts['uniform']:>6d} | "
              f"tiny: submit {tiny_submit*1000:6.1f} ms total {tiny_total*1000:7.1f} ms | "
              f"{W}x{H}: total {full_total*1000:8.1f} ms | load {load_s:.1f}s", flush=True)
        if a.profile:
            pr = cProfile.Profile()
            fbo = ctx.framebuffer([ctx.renderbuffer((64, 40), 4)])
            pr.enable()
            for _ in range(3):
                cam.yaw += 0.03
                r.render(fbo, (64, 40), cam, s, fs)
            ctx.finish()
            pr.disable()
            fbo.release()
            pstats.Stats(pr).sort_stats("tottime").print_stats(12)
        r.release()
        del model


if __name__ == "__main__":
    main()
