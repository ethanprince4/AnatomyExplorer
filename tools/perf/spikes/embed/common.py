"""Shared pieces of the wgpu-in-Qt embedding spike: mesh loading and a lambert renderer for a rendercanvas draw callback.

Read-only use of the model library; nothing is written next to the model."""
import logging
import os
import math
import struct
import time
from pathlib import Path

import numpy as np
import wgpu

ROOT = Path(__file__).resolve().parents[4]
MODEL = ROOT / "data/local_model_library/models/tooth/v4/model.npz"

WGSL = """
struct U { vp: mat4x4<f32>, rot: mat4x4<f32>, clear: vec4<f32> };
@group(0) @binding(0) var<uniform> u: U;
struct VO { @builtin(position) pos: vec4<f32>, @location(0) n: vec3<f32> };
@vertex fn vs(@location(0) p: vec3<f32>, @location(1) n: vec3<f32>) -> VO {
    var o: VO;
    o.pos = u.vp * u.rot * vec4<f32>(p, 1.0);
    o.n = (u.rot * vec4<f32>(n, 0.0)).xyz;
    return o;
}
@fragment fn fs(i: VO) -> @location(0) vec4<f32> {
    let l = normalize(vec3<f32>(0.4, 0.7, 0.6));
    let d = max(dot(normalize(i.n), l), 0.0) * 0.8 + 0.2;
    return vec4<f32>(0.9 * d, 0.85 * d, 0.2 * d, 1.0);   // warm yellow-grey: never the magenta clear colour
}
"""


def load_mesh():
    """All parts of the tooth model concatenated: (N,6) float32 interleaved position+normal, uint32 indices."""
    d = np.load(MODEL, allow_pickle=False)
    parts = sorted(int(k[1:]) for k in d.files if k.startswith("p") and k[1:].isdigit())
    verts, idx, base = [], [], 0
    for k in parts:
        p, n, i = d[f"p{k}"], d[f"n{k}"], d[f"i{k}"]
        verts.append(np.hstack([p, n]).astype(np.float32))
        idx.append(i.astype(np.uint32) + base)
        base += len(p)
    v = np.ascontiguousarray(np.vstack(verts))
    i = np.ascontiguousarray(np.concatenate(idx))
    c = (v[:, :3].min(0) + v[:, :3].max(0)) / 2
    r = np.linalg.norm(v[:, :3] - c, axis=1).max()
    v[:, :3] = (v[:, :3] - c) / r          # unit sphere
    return v, i, len(parts)


def perspective(fov, aspect, near, far):
    f = 1 / math.tan(fov / 2)
    m = np.zeros((4, 4), np.float32)
    m[0, 0] = f / aspect; m[1, 1] = f
    m[2, 2] = far / (near - far); m[2, 3] = far * near / (near - far); m[3, 2] = -1
    return m


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], np.float32)


class Renderer:
    """Draws the rotating mesh into a rendercanvas canvas. The clear colour is (255, frame%128, 255) so every grabbed
    frame carries its own frame number in the green channel of the background."""
    FORMAT = "rgba8unorm"

    def __init__(self, canvas, device=None, mesh_scale=1.0):
        self.canvas = canvas
        self.log = logging.getLogger("spike")
        if device is None:
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
            self.adapter_info = dict(adapter.info)
            device = adapter.request_device_sync()
        self.device = device
        self.mesh_scale = mesh_scale
        v, i, nparts = load_mesh()
        self.tris, self.nparts, self.nverts = len(i) // 3, nparts, len(v)
        self.vbuf = device.create_buffer_with_data(data=v, usage="VERTEX")
        self.ibuf = device.create_buffer_with_data(data=i, usage="INDEX")
        self.ubuf = device.create_buffer(size=64 * 2 + 16, usage="UNIFORM|COPY_DST")
        self.ctx = canvas.get_context("wgpu")
        self.ctx.configure(device=device, format=self.FORMAT)
        sm = device.create_shader_module(code=WGSL)
        bgl = device.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": "VERTEX", "buffer": {"type": "uniform"}}])
        self.bind = device.create_bind_group(layout=bgl, entries=[
            {"binding": 0, "resource": {"buffer": self.ubuf, "offset": 0, "size": self.ubuf.size}}])
        self.pipe = device.create_render_pipeline(
            layout=device.create_pipeline_layout(bind_group_layouts=[bgl]),
            vertex={"module": sm, "entry_point": "vs", "buffers": [{
                "array_stride": 24, "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 0},
                    {"format": "float32x3", "offset": 12, "shader_location": 1}]}]},
            fragment={"module": sm, "entry_point": "fs", "targets": [{"format": self.FORMAT}]},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            depth_stencil={"format": "depth24plus", "depth_write_enabled": True, "depth_compare": "less"},
        )
        self.depth = None
        self.frame = 0
        self.stamps = []              # perf_counter at the start of every draw callback
        self.acq_ms = []
        self.draw_ms = []             # time spent inside the callback itself
        self.size_mismatch = 0        # frames where swapchain texture size != canvas physical size
        self.last_tex_size = None
        self.sizes_seen = set()
        self.angle = 0.0

    def draw(self):
        t0 = time.perf_counter()
        self.stamps.append(t0)
        tex = self.ctx.get_current_texture()
        self.acq_ms.append((time.perf_counter() - t0) * 1000)
        w, h = tex.size[0], tex.size[1]
        self.last_tex_size = (w, h)
        self.sizes_seen.add((w, h))
        if tuple(self.canvas.get_physical_size()) != (w, h):
            self.size_mismatch += 1
        if self.depth is None or (self.depth.size[0], self.depth.size[1]) != (w, h):
            self.depth = self.device.create_texture(size=(w, h, 1), format="depth24plus", usage="RENDER_ATTACHMENT")
        self.angle += 0.02
        view = np.eye(4, dtype=np.float32); view[2, 3] = -3.0 / self.mesh_scale
        vp = perspective(0.8, w / max(h, 1), 0.1, 20.0) @ view
        # numpy is row-major, WGSL expects column-major: upload the transpose
        data = np.concatenate([vp.T.ravel(), rot_y(self.angle).T.ravel(), np.zeros(4, np.float32)]).astype(np.float32)
        self.device.queue.write_buffer(self.ubuf, 0, data)
        g = (self.frame % 128) / 255.0
        enc = self.device.create_command_encoder()
        rp = enc.begin_render_pass(
            color_attachments=[{"view": tex.create_view(), "clear_value": (1.0, g, 1.0, 1.0),
                                "load_op": "clear", "store_op": "store"}],
            depth_stencil_attachment={"view": self.depth.create_view(), "depth_clear_value": 1.0,
                                      "depth_load_op": "clear", "depth_store_op": "store"})
        rp.set_pipeline(self.pipe)
        rp.set_bind_group(0, self.bind)
        rp.set_vertex_buffer(0, self.vbuf)
        rp.set_index_buffer(self.ibuf, "uint32")
        if not os.environ.get("SPIKE_NODRAW"):
            rp.draw_indexed(self.tris * 3)
        rp.end()
        self.device.queue.submit([enc.finish()])
        self.frame += 1
        self.draw_ms.append((time.perf_counter() - t0) * 1000)


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else float("nan")
