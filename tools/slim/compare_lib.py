"""Side-by-side renderer for an original mesh and its simplified copy (shared by the review tools)."""
import math
import numpy as np
import moderngl
from PIL import Image, ImageDraw

VS = """#version 410
in vec3 p; in vec3 n; uniform mat4 mvp; out vec3 vn; out vec3 vp;
void main(){ gl_Position = mvp * vec4(p,1); vn = n; vp = p; }"""
FS = """#version 410
in vec3 vn; in vec3 vp; uniform vec3 eye; out vec4 c;
void main(){ vec3 N = normalize(vn); vec3 V = normalize(eye - vp); if (dot(N,V) < 0.0) N = -N;
 vec3 L = normalize(V + vec3(0.3,0.5,0.2)); float d = max(dot(N, L), 0.0);
 float s = pow(max(dot(N, normalize(V + L)), 0.0), 40.0);
 c = vec4(vec3(0.16) + vec3(0.78,0.74,0.70) * d + vec3(0.25) * s, 1); }"""


def normals(v, t):
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, t[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-20)


def look(eye, target):
    f = target - eye; f /= np.linalg.norm(f)
    up = np.array([0, 1.0, 0]) if abs(f[1]) < 0.95 else np.array([0, 0, 1.0])
    r = np.cross(f, up); r /= np.linalg.norm(r); u = np.cross(r, f)
    m = np.eye(4); m[0, :3], m[1, :3], m[2, :3] = r, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def persp(fov, aspect, near, far):
    f = 1 / math.tan(math.radians(fov) / 2)
    return np.array([[f / aspect, 0, 0, 0], [0, f, 0, 0], [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]])


class Sheet:
    def __init__(self, w=520, h=420):
        self.W, self.H = w, h
        self.ctx = moderngl.create_standalone_context(require=410)
        self.prog = self.ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.fbo = self.ctx.framebuffer([self.ctx.renderbuffer((w, h), 4, samples=4)], self.ctx.depth_renderbuffer((w, h), samples=4))
        self.res = self.ctx.framebuffer([self.ctx.renderbuffer((w, h), 4)])

    def _vao(self, v, t):
        v = np.ascontiguousarray(v, np.float64); t = np.ascontiguousarray(t, np.int64)
        data = np.hstack([v, normals(v, t)]).astype(np.float32)
        return self.ctx.vertex_array(self.prog, [(self.ctx.buffer(data), "3f 3f", "p", "n")], self.ctx.buffer(t.astype(np.int32)))

    def render(self, ov, ot, sv, st, title, dst):
        ov = np.asarray(ov, np.float64); W, H = self.W, self.H
        va, vb = self._vao(ov, ot), self._vao(sv, st)
        lo, hi = ov.min(0), ov.max(0); c = (lo + hi) / 2; R = float(np.linalg.norm(hi - lo)) / 2
        centre_pt = ov[np.argmin(np.linalg.norm(ov - c, axis=1))]
        d = np.array([0.55, 0.45, 0.7]); d /= np.linalg.norm(d)
        views = [("whole part", c, c + d * R * 2.6, R * 6), ("close-up x6", centre_pt, centre_pt + d * R * 0.43, R * 2),
                 ("close-up x25", centre_pt, centre_pt + d * R * 0.1, R * 1)]
        sheet = Image.new("RGB", (W * 2 + 12, (H + 26) * 3 + 30), (255, 255, 255))
        dr = ImageDraw.Draw(sheet); dr.text((8, 6), title, fill=(0, 0, 0))
        for i, (name, target, eye, far) in enumerate(views):
            y = 30 + i * (H + 26)
            dr.text((8, y + 4), f"{name} - original", fill=(0, 0, 0)); dr.text((W + 20, y + 4), f"{name} - simplified copy", fill=(0, 0, 0))
            for j, vao in enumerate((va, vb)):
                mvp = persp(35, W / H, max(far * 1e-4, 1e-6), far) @ look(eye, target)
                self.prog["mvp"].write(mvp.T.astype("f4").tobytes()); self.prog["eye"].value = tuple(eye)
                self.fbo.use(); self.ctx.enable(moderngl.DEPTH_TEST); self.ctx.clear(0.08, 0.09, 0.11, depth=1.0)
                vao.render(moderngl.TRIANGLES)
                self.ctx.copy_framebuffer(self.res, self.fbo)
                img = Image.frombytes("RGBA", (W, H), self.res.read(components=4)).transpose(Image.FLIP_TOP_BOTTOM).convert("RGB")
                sheet.paste(img, (j * (W + 12), y + 22))
        sheet.save(dst, quality=88)
        va.release(); vb.release()
