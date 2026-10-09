"""Shared pieces of the renderer benchmark harness (tools/perf).

Nothing here changes the app: GL counters and per-pass GPU timers are installed by patching moderngl classes and a few
renderer methods at run time, and removed again afterwards.

    env_setup()      Retina-like Qt setup (device pixel ratio 2, 2560x1600 physical pixels), repo on sys.path
    memory           peak working set / commit of this process, total RAM (ctypes, no psutil)
    GlProbe          draw calls, triangles submitted, readbacks, copies and GPU ms per pass for one frame
    gpu_used_mib()   nvidia-smi memory.used
"""
from __future__ import annotations

import ctypes
import json
import os
import statistics
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHYS_W, PHYS_H, DPR = 2560, 1600, 2


def env_setup():
    """Call before importing Qt widgets. Returns the QApplication."""
    os.environ["QT_SCREEN_SCALE_FACTORS"] = str(DPR)     # replaces the platform scale: exactly 2.0
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["perf"])


# --------------------------------------------------------------------------------------------- memory
class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


class _MSE(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    """{'rss_mb', 'peak_rss_mb', 'commit_mb', 'peak_commit_mb'} of this process."""
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    c = _PMC()
    c.cb = ctypes.sizeof(c)
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    mb = 1 / (1024 * 1024)
    return {"rss_mb": round(c.WorkingSetSize * mb, 1), "peak_rss_mb": round(c.PeakWorkingSetSize * mb, 1),
            "commit_mb": round(c.PagefileUsage * mb, 1), "peak_commit_mb": round(c.PeakPagefileUsage * mb, 1)}


def total_ram_mb():
    s = _MSE()
    s.dwLength = ctypes.sizeof(s)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return round(s.ullTotalPhys / (1024 * 1024)), round(s.ullAvailPhys / (1024 * 1024))


def gpu_used_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
        used, total = (int(v) for v in out.split(","))
        return used, total
    except Exception:
        return None, None


# --------------------------------------------------------------------------------------------- stats
def med(xs):
    xs = [x for x in xs if x is not None]
    return float(statistics.median(xs)) if xs else None


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return float(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))])


def summarize(series):
    """{'median','p95','max','mean'} of a list of numbers."""
    xs = [x for x in series if x is not None]
    if not xs:
        return None
    return {"median": round(med(xs), 3), "p95": round(pct(xs, 0.95), 3), "max": round(max(xs), 3),
            "mean": round(sum(xs) / len(xs), 3)}


def dump(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, default=_json_default), encoding="utf-8")


def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(o)


# --------------------------------------------------------------------------------------------- GL probe
def _find_framebuffers(obj, name, out, depth=0):
    import moderngl
    if isinstance(obj, moderngl.Framebuffer):
        out.setdefault(id(obj), name)
    elif depth < 3 and isinstance(obj, dict):
        for k, v in obj.items():
            _find_framebuffers(v, f"{name}.{k}" if name else str(k), out, depth + 1)
    elif depth < 3 and isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _find_framebuffers(v, f"{name}[{i}]", out, depth + 1)


def _find_vaos(obj, name, out, depth=0):
    import moderngl
    if isinstance(obj, moderngl.VertexArray):
        out.setdefault(id(obj), name)
    elif depth < 3 and isinstance(obj, dict):
        for k, v in obj.items():
            _find_vaos(v, f"{name}.{k}" if name else str(k), out, depth + 1)
    elif depth < 3 and isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _find_vaos(v, f"{name}[{i}]", out, depth + 1)


class GlProbe:
    """Counts GL work and times each pass on the GPU while installed.

    A pass is the stretch between two framebuffer switches (or a framebuffer copy). Scope wrappers around renderer
    methods (shadows, cut faces) give their passes a prefix. GPU time uses GL_TIME_ELAPSED queries, one per pass,
    read after ctx.finish(); queries are not nested.

    renderer: the object whose attributes hold the framebuffers and vertex arrays (the app's Renderer).
    model_vaos: names (as found on the renderer) of vertex arrays that draw model geometry; other vertex arrays
        (full-screen triangles) are counted as draws but not as geometry or triangles.
    scopes: {method name: scope label} of renderer methods to wrap.
    """

    def __init__(self, ctx, renderer, model_vao_prefixes, scopes, default_fbo_name="target"):
        self.ctx, self.r = ctx, renderer
        self.prefixes = tuple(model_vao_prefixes)
        self.scopes = dict(scopes)
        self.default_fbo_name = default_fbo_name
        self.fbo_names, self.vao_names = {}, {}
        self.timing = True
        self.active = False
        self.installed = False
        self._pool, self._used = [], 0
        self.reset()

    # -------------------------------------------------------------- install / remove
    def refresh_names(self):
        self.fbo_names.clear()
        self.vao_names.clear()
        for k, v in vars(self.r).items():
            _find_framebuffers(v, k, self.fbo_names)
            _find_vaos(v, k, self.vao_names)

    def install(self):
        import moderngl
        self.refresh_names()
        P = self
        self._orig = {}

        def patch(cls, attr, fn):
            self._orig[(cls, attr)] = getattr(cls, attr)
            setattr(cls, attr, fn)

        o_use = moderngl.Framebuffer.use
        o_render = moderngl.VertexArray.render
        o_copy = moderngl.Context.copy_framebuffer

        def use(fb):
            if P.active:
                P._on_use(fb)
            return o_use(fb)

        def render(vao, mode=None, vertices=-1, first=0, instances=-1):
            if P.active:
                P._on_draw(vao, vertices, instances)
            return o_render(vao, mode, vertices, first, instances)

        def copy_framebuffer(ctx, dst, src):
            if P.active:
                P._enter("resolve")
                P.copies += 1
            return o_copy(ctx, dst, src)

        patch(moderngl.Framebuffer, "use", use)
        patch(moderngl.VertexArray, "render", render)
        patch(moderngl.Context, "copy_framebuffer", copy_framebuffer)
        for cls, attr, kind in ((moderngl.Framebuffer, "read", "fbo"), (moderngl.Framebuffer, "read_into", "fbo"),
                                (moderngl.Texture, "read", "tex"), (moderngl.Texture, "read_into", "tex"),
                                (moderngl.Buffer, "read", "buf"), (moderngl.Buffer, "read_into", "buf")):
            patch(cls, attr, self._wrap_read(getattr(cls, attr), kind, attr))
        for name, scope in self.scopes.items():
            if hasattr(self.r, name):
                self._wrap_scope(name, scope)
        self.installed = True

    def uninstall(self):
        for (cls, attr), fn in self._orig.items():
            setattr(cls, attr, fn)
        self._orig = {}
        for name in self.scopes:
            self.r.__dict__.pop(name, None)           # drop the instance-level wrapper
        self.installed = False
        self._close()

    def _wrap_read(self, orig, kind, attr):
        P = self

        def wrapper(obj, *a, **kw):
            if not P.active:
                return orig(obj, *a, **kw)
            t0 = time.perf_counter()
            try:
                return orig(obj, *a, **kw)
            finally:
                P.readbacks += 1
                P.readback_ms += (time.perf_counter() - t0) * 1000.0
                P.readback_labels[P.label] = P.readback_labels.get(P.label, 0) + 1
                try:
                    if kind == "buf":
                        P.readback_bytes += int(kw.get("size", a[0] if a and isinstance(a[0], int) else obj.size))
                    else:
                        vp = kw.get("viewport", a[0] if a and isinstance(a[0], tuple) else None)
                        w, h = (vp[-2], vp[-1]) if vp else obj.size[:2]
                        comp = kw.get("components", 4)
                        P.readback_bytes += int(w) * int(h) * int(comp) * 4
                except Exception:
                    pass
        wrapper.__name__ = attr
        return wrapper

    def _wrap_scope(self, name, scope):
        P = self
        orig = getattr(self.r, name)

        def wrapper(*a, **kw):
            if not P.active:
                return orig(*a, **kw)
            prev = P.scope
            P.scope = scope
            P._enter(None)
            try:
                return orig(*a, **kw)
            finally:
                P.scope = prev
                P._enter(None)
        setattr(self.r, name, wrapper)

    # -------------------------------------------------------------- per-frame state
    def reset(self):
        self.scope = ""
        self.fbo_name = "start"
        self.label = "start"
        self.draws = {}
        self.model_draws = {}
        self.tris = {}
        self.readbacks = 0
        self.readback_ms = 0.0
        self.readback_bytes = 0
        self.readback_labels = {}
        self.copies = 0
        self._segments = []
        self._open = None
        self._used = 0

    def begin_frame(self):
        self.reset()
        self.active = True
        self._enter("start")

    def end_frame(self):
        """Close the last pass. Call ctx.finish() afterwards, then frame_result()."""
        self._close()
        self.active = False

    def _label(self, fbo_name):
        return f"{self.scope}:{fbo_name}" if self.scope else fbo_name

    def _on_use(self, fb):
        name = self.fbo_names.get(id(fb))
        if name is None:
            name = self.default_fbo_name if getattr(fb, "glo", -1) in (0, None) or fb is self.ctx.screen \
                else f"fbo{getattr(fb, 'glo', '?')}"
            self.fbo_names[id(fb)] = name
        self._enter(name)

    def _enter(self, fbo_name):
        if fbo_name == "resolve":
            label = "resolve"
        else:
            if fbo_name is not None:
                self.fbo_name = fbo_name
            label = self._label(self.fbo_name)
        if label == self.label and self._open is not None:
            return
        self.label = label
        if not self.timing:
            return
        self._close()
        if self._used == len(self._pool):
            self._pool.append(self.ctx.query(time=True))
        q = self._pool[self._used]
        self._used += 1
        q.__enter__()
        self._open = (label, q)

    def _close(self):
        if self._open is not None:
            label, q = self._open
            q.__exit__(None, None, None)
            self._segments.append((label, q))
            self._open = None

    def _on_draw(self, vao, vertices, instances):
        name = self.vao_names.get(id(vao), "?")
        lab = self.label
        self.draws[lab] = self.draws.get(lab, 0) + 1
        if name.startswith(self.prefixes):
            self.model_draws[lab] = self.model_draws.get(lab, 0) + 1
            n = vao.vertices if vertices is None or vertices < 0 else vertices
            inst = max(1, vao.instances if instances is None or instances < 0 else instances)
            self.tris[lab] = self.tris.get(lab, 0) + (n // 3) * inst

    def frame_result(self):
        gpu = {}
        for label, q in self._segments:
            gpu[label] = gpu.get(label, 0.0) + q.elapsed / 1e6
        md = self.model_draws
        return {
            "gpu_ms": {k: round(v, 3) for k, v in gpu.items()},
            "gpu_total_ms": round(sum(gpu.values()), 3),
            "draws_total": sum(self.draws.values()),
            "draws_by_pass": dict(self.draws),
            "model_draws": sum(md.values()),
            "model_draws_by_pass": dict(md),
            "tris_submitted": sum(self.tris.values()),
            "tris_by_pass": dict(self.tris),
            "geometry_passes": len(md),
            "readbacks": self.readbacks,
            "readback_ms": round(self.readback_ms, 3),
            "readback_bytes": self.readback_bytes,
            "readbacks_by_pass": dict(self.readback_labels),
            "framebuffer_copies": self.copies,
            "shadow_rerendered": any(k.startswith("shadow") for k in md),
        }


def aggregate(frames):
    """Median over frames for every numeric field; dict fields get a median per key."""
    out = {}
    if not frames:
        return out
    for k in frames[0]:
        vals = [f.get(k) for f in frames]
        if isinstance(vals[0], bool):
            out[k] = sum(1 for v in vals if v)               # frames in which it happened
        elif isinstance(vals[0], (int, float)):
            out[k] = round(med(vals), 3)
        elif isinstance(vals[0], dict):
            keys = sorted({kk for v in vals for kk in v})
            out[k] = {kk: round(med([v.get(kk, 0) for v in vals]), 3) for kk in keys}
    return out
