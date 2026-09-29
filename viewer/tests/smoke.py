"""Smoke test: load the rebuild GLB, check morphs move vertices, render one offscreen frame, time the load.

    .venv/Scripts/python.exe viewer/tests/smoke.py [viewer/models/rebuild.glb]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import moderngl  # noqa: E402
import numpy as np  # noqa: E402

from viewer.camera import OrbitCamera  # noqa: E402
from viewer.model import Model  # noqa: E402
from viewer.offscreen import setup_camera  # noqa: E402
from viewer.renderer import Renderer, Settings  # noqa: E402


def main():
    glb = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "viewer" / "models" / "rebuild.glb"
    if not glb.is_file():
        print(f"SKIP no model at {glb} (export it with viewer/tools/export_for_viewer.py)")
        return 2
    fails = []

    t0 = time.perf_counter()
    m = Model(glb)
    load_s = time.perf_counter() - t0
    print(f"load {load_s:.2f} s: {len(m.parts)} parts, {m.triangle_count:,} triangles, "
          f"{len(m.vertices):,} vertices, clip {m.clip.name if m.clip else None} {m.clip_range}, "
          f"states {list(m.states)}, cameras {m.camera_order}")
    if m.triangle_count <= 0:
        fails.append("no triangles")

    # morph: a weight of 1 moves vertices
    morphed = [p for p in m.parts if p.has_morph]
    if not morphed:
        fails.append("no morph targets")
    else:
        p = morphed[0]
        v = m.vertices[p.vertex_base:p.vertex_base + p.vertex_count]
        moved = np.linalg.norm(v[:, 6:9], axis=1)   # pos + 1.0 * delta - pos
        print(f"morph: {len(morphed)} parts; {p.name} max move at weight 1 = {moved.max():.4f} BU "
              f"({(moved > 1e-6).mean() * 100:.0f} % of vertices move)")
        if moved.max() <= 1e-6:
            fails.append("weight 1 does not move vertices")
    if m.clip is not None:
        peak = max(m.evaluate(t) for t in np.linspace(*m.clip_range, 97))
        print(f"clip peak weight {peak:.3f}")
        if peak < 0.5:
            fails.append("the clip never drives the morph weight up")

    # one offscreen frame, non-empty
    ctx = moderngl.create_standalone_context(require=410)
    r = Renderer(ctx)
    r.set_model(m)
    cam = OrbitCamera()
    w, h = 960, 540
    setup_camera(m, cam, "V1" if "V1" in m.cameras else None, w / h)
    m.evaluate(m.clip_range[0])
    fbo = ctx.framebuffer([ctx.renderbuffer((w, h), 4)])
    t1 = time.perf_counter()
    r.render(fbo, (w, h), cam, Settings())
    img = r.read_final(fbo, (w, h))
    render_s = time.perf_counter() - t1
    bg = img[2, 2].astype(int)
    fg = (np.abs(img.astype(int) - bg).sum(2) > 30).mean()
    print(f"render {render_s * 1000:.0f} ms first frame; foreground {fg * 100:.1f} % of pixels; {r.gl_info}")
    if fg < 0.05:
        fails.append("the rendered frame is empty")
    pid, point = r.pick(w // 2, h // 2)
    print(f"pick at centre: part id {pid}, point {None if point is None else np.round(point, 3)}")

    print("PASS" if not fails else "FAIL " + "; ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
