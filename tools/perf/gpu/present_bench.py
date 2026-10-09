"""Presenter benchmark: sync vs async present of app/gpu/host.py at 2560x1600 physical pixels.

    python <scratch>/tools/gpu_lock.py <repo>/.venv/Scripts/python.exe tools/perf/gpu/present_bench.py \
        --adapter 3080 --out <scratch>/gpu_port/host/present_3080.json [--modes sync,async] [--work-ms 0,8] [--frames 400]

A stand-in renderer with the WgpuRenderer API (set_model / render / pick / read_final ...) only clears the target or
runs a full-screen fragment shader whose cost is set by a loop count (calibrated per adapter to a wanted GPU time).
It is hosted in the real WgpuModelViewport with a real model, in a shown window sized like tools/perf/viewer_session.py
(logical 1280x800 at device pixel ratio 2), driven the way the app drives a moving camera (auto-rotate: every frame
asks for the next one). Reported per case: frame interval (the time between frames, so fps is 1000/mean), CPU time per
paint, and its parts (render callback, copy, wait for the GPU/map, QPainter.drawImage); idle renders per second.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

WGSL = """
struct U { clear: vec4<f32>, zero: f32, iters: u32, pad0: u32, pad1: u32 };
@group(0) @binding(0) var<uniform> u: U;
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}
@fragment fn fs(@builtin(position) pos: vec4<f32>) -> @location(0) vec4<f32> {
    var acc = 0.0;
    var x = pos.x * 0.001 + pos.y * 0.0007;
    for (var k = 0u; k < u.iters; k = k + 1u) {
        x = fract(sin(x * 12.9898 + f32(k)) * 43758.5453);
        acc = acc + x;
    }
    if (u.pad0 == 1u) {      // test pattern: red = x mod 251, green = y mod 241, blue 77
        return vec4<f32>(f32(u32(pos.x) % 251u) / 255.0, f32(u32(pos.y) % 241u) / 255.0, 77.0 / 255.0, 1.0);
    }
    // u.zero is 0.0 at run time, so the loop cannot be dropped but the colour is exactly the clear colour
    return vec4<f32>(u.clear.rgb + vec3<f32>(u.zero * acc), u.clear.a);
}
"""


class StandInRenderer:
    """Stands in for app.gpu.renderer.WgpuRenderer: same public API, draws one flat colour (optionally after busy work)."""
    FORMAT = "rgba8unorm"

    def __init__(self, gpu, colour=(64, 128, 192, 255), iters=0, pattern=False, cpu_ms=0.0):
        self.gpu = gpu
        self.device = gpu.device
        self.colour = tuple(colour)
        self.iters = int(iters)
        self.pattern = bool(pattern)
        self.cpu_ms = float(cpu_ms)           # busy CPU work at the start of every render (stands in for per-frame scene preparation)
        self.frames = 0
        self.frame_ok = False
        self.size = None
        self.last_vp = np.eye(4, dtype=np.float32)
        self.samples = 1
        self.gl_info = gpu.info
        self.model = None
        self.released = False
        d = self.device
        self.ubuf = d.create_buffer(size=32, usage="UNIFORM|COPY_DST")
        sm = d.create_shader_module(code=WGSL)
        bgl = d.create_bind_group_layout(entries=[{"binding": 0, "visibility": "FRAGMENT", "buffer": {"type": "uniform"}}])
        self.bind = d.create_bind_group(layout=bgl, entries=[{"binding": 0, "resource": {
            "buffer": self.ubuf, "offset": 0, "size": 32}}])
        self.pipe = d.create_render_pipeline(
            layout=d.create_pipeline_layout(bind_group_layouts=[bgl]),
            vertex={"module": sm, "entry_point": "vs"},
            fragment={"module": sm, "entry_point": "fs", "targets": [{"format": self.FORMAT}]},
            primitive={"topology": "triangle-list"})

    # lifecycle
    def set_model(self, model):
        self.model = model
        self.frame_ok = False

    def release(self):
        self.released = True
        self.frame_ok = False

    # frame
    def render(self, target, size, camera, s, fs=None, out_size=None):
        if self.cpu_ms:
            end = time.perf_counter() + self.cpu_ms / 1000.0
            while time.perf_counter() < end:
                pass
        w, h = target.size[0], target.size[1]
        data = np.zeros(8, np.float32)
        data[:4] = [c / 255.0 for c in self.colour]
        buf = bytearray(data.tobytes())
        buf[20:24] = int(self.iters).to_bytes(4, "little")
        buf[24:28] = (1 if self.pattern else 0).to_bytes(4, "little")
        self.gpu.queue.write_buffer(self.ubuf, 0, bytes(buf))
        enc = self.device.create_command_encoder()
        rp = enc.begin_render_pass(color_attachments=[{
            "view": target.create_view(), "clear_value": (0, 0, 0, 1), "load_op": "clear", "store_op": "store"}])
        rp.set_pipeline(self.pipe)
        rp.set_bind_group(0, self.bind)
        rp.draw(3)
        rp.end()
        self.gpu.queue.submit([enc.finish()])
        self.size = tuple(size)
        self.frames += 1
        self.frame_ok = True

    # picking and readback: nothing is drawn but a flat colour, so nothing is picked
    def pick(self, x, y):
        return -1, None, False

    def read_ids(self):
        return None, None

    def read_depth(self):
        return None

    def read_label_samples(self, step):
        return None

    def ids_at(self, points):
        return [-1 for _ in points]

    def world_from_pixel(self, x, y, d):
        return None

    def read_final(self, target, size):
        w, h = target.size[0], target.size[1]
        stride = (w * 4 + 255) & ~255
        buf = self.device.create_buffer(size=stride * h, usage="MAP_READ|COPY_DST")
        enc = self.device.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": target, "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": buf, "offset": 0, "bytes_per_row": stride, "rows_per_image": h}, (w, h, 1))
        self.gpu.queue.submit([enc.finish()])
        buf.map_sync("READ")
        raw = np.frombuffer(buf.read_mapped(copy=True), dtype=np.uint8).reshape(h, stride)
        buf.unmap()
        buf.destroy()
        return raw[:, :w * 4].reshape(h, w, 4)[:, :, :3].copy()


from app.gpu.device import wait_idle  # noqa: E402


def calibrate(gpu, want_ms, w=2560, h=1600):
    """Loop count at which one full-screen pass of w x h takes about ``want_ms`` of GPU time (wall clock of submit + wait)."""
    r = StandInRenderer(gpu)
    tex = gpu.device.create_texture(size=(w, h, 1), format="rgba8unorm", usage="RENDER_ATTACHMENT|COPY_SRC|TEXTURE_BINDING")

    def ms(iters, n=8):
        r.iters = iters
        for _ in range(3):
            r.render(tex, (w, h), None, None)
        wait_idle(gpu)
        t0 = time.perf_counter()
        for _ in range(n):
            r.render(tex, (w, h), None, None)
            wait_idle(gpu)
        return (time.perf_counter() - t0) * 1000.0 / n

    base = ms(0)
    n = 64
    t = ms(n)
    while t < 1.5 * max(base, 0.5) + 1.0 and n < 2 ** 20:
        n *= 4
        t = ms(n)
    per = (t - base) / n
    iters = max(int((want_ms - base) / per), 1) if want_ms > 0 else 0
    got = ms(iters) if iters else base
    tex.destroy()
    return {"iters": iters, "base_ms": round(base, 3), "per_iter_ms": per, "got_ms": round(got, 3)}


def prepare_model():
    from tools.perf import viewer_session as vs
    entry, model, _ = vs.timed_prepare("eyeball")
    return entry, model


def run_case(app, entry, model, gpu, mode, iters, frames, warm=60, cap_hz=0, cpu_ms=0.0):
    from PySide6.QtCore import QEventLoop
    from app.config import DEFAULT_SETTINGS
    from app.gpu.viewport import WgpuModelViewport
    from app.state import SceneState
    from app.viewer.dataset import ModelDataset

    settings = dict(DEFAULT_SETTINGS)
    state = SceneState(ModelDataset(model), settings)
    state.opaque_materials = False
    created = []

    def factory(g):
        r = StandInRenderer(g, iters=iters, cpu_ms=cpu_ms)
        created.append(r)
        return r

    vp = WgpuModelViewport(model, state, settings, entry, renderer_factory=factory, present_mode=mode, gpu=gpu)
    vp.frame_cap_hz = cap_hz                             # 0: uncapped: measure what the presenter costs, not the refresh rate
    from tools.perf.viewer_session import LOGICAL_H, LOGICAL_W
    vp.resize(LOGICAL_W, LOGICAL_H)
    vp.show()
    stamps = []
    orig = vp.render_callback

    def timed(tex, w, h):
        stamps.append(time.perf_counter())
        return orig(tex, w, h)

    vp.render_callback = timed
    vp.auto_rotate = True
    vp.update()

    def spin(n_frames):
        start = len(stamps)
        t_end = time.perf_counter() + 120
        while len(stamps) - start < n_frames and time.perf_counter() < t_end:
            app.processEvents(QEventLoop.AllEvents)

    spin(warm)
    for k in vp.stats:
        vp.stats[k] = 0.0
    i0 = len(stamps)
    spin(frames)
    st = dict(vp.stats)
    iv = np.diff(np.array(stamps[i0:])) * 1000.0
    n = max(st["paints"], 1)
    out = {
        "mode": mode, "iters": iters, "physical": list(vp._physical_size()), "frames": int(len(iv)),
        "interval_ms_mean": round(float(iv.mean()), 3), "interval_ms_median": round(float(np.median(iv)), 3),
        "interval_ms_p95": round(float(np.percentile(iv, 95)), 3), "interval_ms_max": round(float(iv.max()), 3),
        "fps": round(1000.0 / float(iv.mean()), 1),
        "cpu_per_paint_ms": round(st["paint_ms"] / n, 3), "render_cb_ms": round(st["render_ms"] / n, 3),
        "copy_submit_ms": round(st["copy_ms"] / n, 3), "wait_ms": round(st["wait_ms"] / n, 3),
        "drawImage_ms": round(st["draw_ms"] / n, 3), "paints": int(st["paints"]), "renders": int(st["renders"]),
    }
    # idle: stop asking for frames, let the last one land, then count renders over one second
    vp.auto_rotate = False
    t_end = time.perf_counter() + 0.5
    while time.perf_counter() < t_end:
        app.processEvents(QEventLoop.AllEvents)
    r0 = vp.stats["renders"]
    shown = vp._shown_frame, vp._frame - 1
    t_end = time.perf_counter() + 1.0
    while time.perf_counter() < t_end:
        app.processEvents(QEventLoop.AllEvents)
    out["idle_renders_per_s"] = int(vp.stats["renders"] - r0)
    out["last_frame_shown"] = bool(vp._shown_frame == vp._frame - 1)
    vp.hide()
    vp.release_gl()
    vp.deleteLater()
    app.processEvents()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="", help="substring for ANATOMY_WGPU_ADAPTER (empty: default adapter)")
    ap.add_argument("--modes", default="sync,async")
    ap.add_argument("--work-ms", default="0,8", help="GPU time of the stand-in pass, comma separated")
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--cpu-ms", type=float, default=0.0, help="busy CPU time per frame inside the stand-in renderer")
    ap.add_argument("--cap-hz", type=float, default=0, help="frame cap in Hz (0 = uncapped, the default for measuring; -1 = the screen refresh rate, as the app runs)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.adapter:
        os.environ["ANATOMY_WGPU_ADAPTER"] = a.adapter
    from tools.perf import perfkit as pk
    app = pk.env_setup()                                  # device pixel ratio 2: logical 1280x800 = 2560x1600 physical
    sys.path.insert(0, str(ROOT))
    from app.gpu.device import get_gpu
    gpu = get_gpu()
    print("adapter:", gpu.info, flush=True)
    entry, model = prepare_model()
    results = {"adapter": gpu.info, "cases": []}
    for want in [float(x) for x in a.work_ms.split(",")]:
        cal = calibrate(gpu, want)
        print(f"calibrated {want} ms -> {cal}", flush=True)
        for mode in a.modes.split(","):
            r = run_case(app, entry, model, gpu, mode, cal["iters"], a.frames, cap_hz=(None if a.cap_hz < 0 else a.cap_hz), cpu_ms=a.cpu_ms)
            r["gpu_ms_wanted"], r["gpu_ms_measured"] = want, cal["got_ms"]
            results["cases"].append(r)
            print(json.dumps(r), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
