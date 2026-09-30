"""Isolated real-atlas GPU/input checks for source and --pick-diagnostics.

Only reads the bundled atlas, without saved settings, study data or caches.
"""
import argparse
import ctypes
import hashlib
import platform
import struct
import json
import math
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import numpy as np


# These are encoded attachment values, not zero-based structure IDs. They are
# fixed before any GPU read, so a buffer stuck at 1 cannot satisfy the oracle.
SENTINELS = (2, 257, 3922)
GL = {
    "READ_FRAMEBUFFER": 0x8CA8, "DRAW_FRAMEBUFFER_BINDING": 0x8CA6,
    "READ_FRAMEBUFFER_BINDING": 0x8CAA, "READ_BUFFER": 0x0C02,
    "COLOR_ATTACHMENT2": 0x8CE2, "FRAMEBUFFER_COMPLETE": 0x8CD5,
    "FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE": 0x8CD0,
    "FRAMEBUFFER_ATTACHMENT_OBJECT_NAME": 0x8CD1,
    "FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE": 0x8211,
    "FRAMEBUFFER_ATTACHMENT_RED_SIZE": 0x8212,
    "TEXTURE_2D": 0x0DE1, "TEXTURE_BINDING_2D": 0x8069,
    "TEXTURE_INTERNAL_FORMAT": 0x1003, "TEXTURE_RED_TYPE": 0x8C10,
    "CLAMP_READ_COLOR": 0x891C, "FIXED_ONLY": 0x891D,
    "FLOAT": 0x1406, "R32F": 0x822E, "RGBA": 0x1908,
    "PIXEL_PACK_BUFFER": 0x88EB, "PIXEL_PACK_BUFFER_BINDING": 0x88ED,
    "PACK_ALIGNMENT": 0x0D05, "PACK_ROW_LENGTH": 0x0D02,
    "PACK_SKIP_ROWS": 0x0D03, "PACK_SKIP_PIXELS": 0x0D04,
}


def json_safe(value):
    """Keep interrupted/failed read observations valid JSON (null = nonfinite)."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class NativeGL:
    """Resolve typed core GL calls from the *current* Qt context only.

    No process-wide hooks or guessed native-library addresses. Keep this object
    on the GUI thread and never invoke it after doneCurrent/context destruction.
    """
    def __init__(self):
        from PySide6.QtGui import QOpenGLContext
        self.qt = QOpenGLContext.currentContext()
        if self.qt is None:
            raise RuntimeError("A current Qt OpenGL context is required")
        self.functions = {}

    def call(self, name, result, argtypes, *args):
        from PySide6.QtGui import QOpenGLContext
        if QOpenGLContext.currentContext() != self.qt:
            raise RuntimeError("Diagnostic GL context is no longer current")
        if name not in self.functions:
            address = int(self.qt.getProcAddress(name) or 0)
            if not address:
                raise RuntimeError("Unavailable OpenGL function: " + name)
            factory = ctypes.WINFUNCTYPE if sys.platform == "win32" else ctypes.CFUNCTYPE
            self.functions[name] = factory(result, *argtypes)(address)
        return self.functions[name](*args)

    def integer(self, enum):
        value = ctypes.c_int()
        self.call("glGetIntegerv", None, (ctypes.c_uint, ctypes.POINTER(ctypes.c_int)),
                  enum, ctypes.byref(value))
        return value.value

    def errors(self):
        errors = []
        for _ in range(32):
            error = self.call("glGetError", ctypes.c_uint, ())
            if error == 0:
                break
            errors.append(hex(error))
        return errors

    def bind_read(self, fbo):
        self.call("glBindFramebuffer", None, (ctypes.c_uint, ctypes.c_uint), GL["READ_FRAMEBUFFER"], fbo)

    def state(self):
        keys = ("DRAW_FRAMEBUFFER_BINDING", "READ_FRAMEBUFFER_BINDING", "READ_BUFFER",
                "CLAMP_READ_COLOR", "PIXEL_PACK_BUFFER_BINDING", "PACK_ALIGNMENT",
                "PACK_ROW_LENGTH", "PACK_SKIP_ROWS", "PACK_SKIP_PIXELS")
        return {key: self.integer(GL[key]) for key in keys}

    def attachment(self, renderer):
        before = self.state()
        texture = self.integer(GL["TEXTURE_BINDING_2D"])
        try:
            self.bind_read(renderer.gbuffer.glo)
            result = {"bound_state": self.state(), "expected_fbo": renderer.gbuffer.glo,
                      "expected_texture": renderer.id_tex.glo}
            result["completeness"] = self.call("glCheckFramebufferStatus", ctypes.c_uint,
                                                (ctypes.c_uint,), GL["READ_FRAMEBUFFER"])
            for key in ("FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE", "FRAMEBUFFER_ATTACHMENT_OBJECT_NAME",
                        "FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE", "FRAMEBUFFER_ATTACHMENT_RED_SIZE"):
                value = ctypes.c_int()
                self.call("glGetFramebufferAttachmentParameteriv", None,
                          (ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)),
                          GL["READ_FRAMEBUFFER"], GL["COLOR_ATTACHMENT2"], GL[key], ctypes.byref(value))
                result[key] = value.value
            self.call("glBindTexture", None, (ctypes.c_uint, ctypes.c_uint), GL["TEXTURE_2D"], renderer.id_tex.glo)
            for key in ("TEXTURE_INTERNAL_FORMAT", "TEXTURE_RED_TYPE"):
                value = ctypes.c_int()
                self.call("glGetTexLevelParameteriv", None,
                          (ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)),
                          GL["TEXTURE_2D"], 0, GL[key], ctypes.byref(value))
                result[key] = value.value
            result["errors"] = self.errors()
            return result
        finally:
            self.call("glBindTexture", None, (ctypes.c_uint, ctypes.c_uint), GL["TEXTURE_2D"], texture)
            self.bind_read(before["READ_FRAMEBUFFER_BINDING"])

    def reference_read(self, renderer, x, y, clamp):
        """Native comparison, with pack/read state restored; never a product fix."""
        before = self.state()
        destination = (ctypes.c_float * 4)(*[float("nan")] * 4)
        old_gbuffer_read = None
        try:
            self.bind_read(renderer.gbuffer.glo)
            old_gbuffer_read = self.integer(GL["READ_BUFFER"])
            self.call("glReadBuffer", None, (ctypes.c_uint,), GL["COLOR_ATTACHMENT2"])
            self.call("glClampColor", None, (ctypes.c_uint, ctypes.c_uint), GL["CLAMP_READ_COLOR"], clamp)
            self.call("glBindBuffer", None, (ctypes.c_uint, ctypes.c_uint), GL["PIXEL_PACK_BUFFER"], 0)
            for key, value in (("PACK_ALIGNMENT", 1), ("PACK_ROW_LENGTH", 0),
                               ("PACK_SKIP_ROWS", 0), ("PACK_SKIP_PIXELS", 0)):
                self.call("glPixelStorei", None, (ctypes.c_uint, ctypes.c_int), GL[key], value)
            during = self.state()
            self.call("glReadPixels", None,
                      (ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p),
                      x, y, 1, 1, GL["RGBA"], GL["FLOAT"], ctypes.cast(destination, ctypes.c_void_p))
            return {"rgba": list(destination), "bound_state": during, "errors": self.errors()}
        finally:
            if old_gbuffer_read is not None:
                self.call("glReadBuffer", None, (ctypes.c_uint,), old_gbuffer_read)
            self.call("glClampColor", None, (ctypes.c_uint, ctypes.c_uint),
                      GL["CLAMP_READ_COLOR"], before["CLAMP_READ_COLOR"])
            self.call("glBindBuffer", None, (ctypes.c_uint, ctypes.c_uint),
                      GL["PIXEL_PACK_BUFFER"], before["PIXEL_PACK_BUFFER_BINDING"])
            for key in ("PACK_ALIGNMENT", "PACK_ROW_LENGTH", "PACK_SKIP_ROWS", "PACK_SKIP_PIXELS"):
                self.call("glPixelStorei", None, (ctypes.c_uint, ctypes.c_int), GL[key], before[key])
            self.bind_read(before["READ_FRAMEBUFFER_BINDING"])


def environment_report(ctx, qt_context):
    import PySide6
    import moderngl
    from PySide6.QtCore import QLibraryInfo, qVersion
    fmt = qt_context.format()
    from .config import ROOT
    version_path = ROOT / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else "source (no embedded VERSION)"
    screen = qt_context.screen()
    return {"platform": sys.platform, "os": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(), "app_version": version,
            "frozen": bool(getattr(sys, "frozen", False)),
            "pyside_version": PySide6.__version__, "qt_runtime_version": qVersion(),
            "qt_library_version": QLibraryInfo.version().toString(), "moderngl_version": moderngl.__version__,
            "context_screen_dpr": screen.devicePixelRatio() if screen is not None else None,
            "context_screen_dpr_scope": "QScreen scale; offscreen controls have no widget logical input mapping",
            "gl": {key: ctx.info.get(key) for key in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION", "GL_SHADING_LANGUAGE_VERSION")},
            "qt_context_format": {"major": fmt.majorVersion(), "minor": fmt.minorVersion(),
                                  "profile": fmt.profile().name, "samples": fmt.samples()},
            "macos_gpu_run": sys.platform == "darwin", "physical_trackpad_verified": False}


def dataset_identity(ds):
    path = ds.dir / "anatomy.json"
    return {"anatomy_json_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "count": ds.n,
            "id_names": [{"id": sid, "name": ds.structures[sid]["name"],
                          "side": ds.structures[sid].get("side", "")}
                         for sid in sorted({0, 1, *(value - 1 for value in SENTINELS)}) if sid < ds.n]}


def dataset_metadata_identity(path):
    """Read metadata only, without geometry, caches, Dataset helpers or models."""
    path = Path(path)
    if not path.is_file():
        return {"available": False, "geometry_loaded": False}
    data = path.read_bytes()
    structures = json.loads(data)["structures"]
    return {"available": True, "geometry_loaded": False,
            "anatomy_json_sha256": hashlib.sha256(data).hexdigest(), "count": len(structures),
            "id_names": [{"id": sid, "name": structures[sid]["name"], "side": structures[sid].get("side", "")}
                         for sid in sorted({0, 1, *(value - 1 for value in SENTINELS)}) if sid < len(structures)]}


def sentinel_vertex_bytes(encoded, material=73):
    # Deliberately use every input: wrong stride/offset/type affects geometry or
    # the auxiliary outputs. All 3 vertices carry the same integer object ID.
    return b"".join(struct.pack("<6f2H", x, y, 0.0, 0.0, 0.0, 1.0, encoded - 1, material)
                    for x, y in ((-0.75, -0.75), (0.75, -0.75), (0.0, 0.75)))


def control_localization(uniform, attribute, production=None):
    if not uniform:
        return "uniform_failed: target/readback/draw-state; attribute inference withheld"
    if not attribute:
        return "uniform_passed_attribute_failed: integer VAO layout/upload/shader path"
    if production is False:
        return "basic_controls_passed_production_failed: production shader/VAO/state/render path"
    if production is True:
        return "all_three_passed: inspect actual mesh IDs, frame freshness and input mapping on this device"
    return "both_passed: inspect actual mesh IDs, frame freshness and input mapping on this device"


def sample_id_pixel(renderer, gl, x, y):
    import moderngl
    before = gl.state()
    before_viewport = tuple(renderer.ctx.viewport)
    rgba = np.full(4, np.nan, np.float32)
    read_exception = None
    try:
        renderer.gbuffer.read_into(rgba, viewport=(x, y, 1, 1), components=4, attachment=2, dtype="f4")
    except moderngl.Error as error:
        read_exception = str(error)
    raw_errors = gl.errors()
    raw_after = gl.state()
    value = renderer._read_float(x, y, 2)
    scalar_errors = gl.errors()
    after_scalar = gl.state()
    scalar_viewport = tuple(renderer.ctx.viewport)
    picked = renderer.pick(x, y)
    after_pick = gl.state()
    pick_viewport = tuple(renderer.ctx.viewport)
    bindings = ("DRAW_FRAMEBUFFER_BINDING", "READ_FRAMEBUFFER_BINDING")
    restored = (all(after_scalar[key] == before[key] and after_pick[key] == before[key]
                    for key in bindings)
                and scalar_viewport == before_viewport and pick_viewport == before_viewport)
    return {"pixel": [x, y], "raw_rgba": rgba.tolist(), "production_scalar": value,
            "production_pick": picked, "errors": raw_errors + scalar_errors + gl.errors(),
            "production_state_restored": restored,
            "after_production_scalar": after_scalar, "after_production_pick": after_pick,
            "viewport_before": before_viewport, "viewport_after_scalar": scalar_viewport,
            "viewport_after_pick": pick_viewport,
            "read_exception": read_exception, "before_read": before, "after_raw_read": raw_after,
            "native_fixed_only": gl.reference_read(renderer, x, y, GL["FIXED_ONLY"]),
            "native_unclamped": gl.reference_read(renderer, x, y, 0)}


def production_gpu_controls(renderer):
    """Independent CPU triangle through actual Renderer.render/opaque VAO.

    The instance was constructed with synthetic vertices/materials. Never call
    this on the real atlas renderer: its vertex buffer is intentionally rewritten.
    """
    from .config import DEFAULT_SETTINGS
    from .state import F_VISIBLE, STATE_TEX_WIDTH
    from . import shaders
    gl = NativeGL()
    ctx = renderer.ctx
    report = {"expected_source": "fixed CPU triangle, identity view/projection, known state/material",
              "same_renderer_attachment": renderer.gbuffer.glo, "rows": [],
              "path": "Renderer.__init__/resize/update_state/render/vao_opaque/_read_float/pick",
              "readback_interpretation": "raw_rgba is the deliberately unbound comparison; production_scalar/pick use the repaired binding path, checked against fixed CPU IDs and native unclamped readback.",
              "geometry_vs_sha256": hashlib.sha256(shaders.GEOMETRY_VS.encode("utf-8")).hexdigest(),
              "opaque_fs_sha256": hashlib.sha256(shaders.OPAQUE_FS.encode("utf-8")).hexdigest(),
              "vao_format": renderer._format_for(renderer.p_opaque),
              "errors_on_entry": gl.errors()}
    state = np.zeros((2, STATE_TEX_WIDTH, 4), np.float32)
    for encoded in SENTINELS:
        state[0, encoded - 1, 3] = F_VISIBLE
        state[1, encoded - 1, 0] = 1  # opaque alpha multiplier
    renderer.update_state(state)
    camera = SimpleNamespace(view=lambda: np.identity(4), proj=lambda aspect: np.identity(4),
                             eye=lambda: np.array([0.0, 0.0, 3.0]),
                             basis=lambda: tuple(np.array(vector, dtype=float)
                                                 for vector in ((1, 0, 0), (0, 1, 0), (0, 0, 1))))
    settings = dict(DEFAULT_SETTINGS, ssao=False, fxaa=False)
    clip = (np.zeros((3, 4)), (False, False, False), 0)
    w, h = renderer.size
    renderer.gbuffer.viewport = (0, 0, w, h)
    color = ctx.texture((w, h), 4, dtype="f1")
    target = ctx.framebuffer([color])
    old_viewport, old_scissor, old_fbo = ctx.viewport, ctx.scissor, ctx.fbo
    try:
        ctx.scissor = None
        for encoded in SENTINELS:
            renderer.vbo.write(sentinel_vertex_bytes(encoded, material=0))
            renderer.render(target, camera, settings, clip)
            render_errors = gl.errors()
            occupied = sample_id_pixel(renderer, gl, w // 2, h // 2)
            background = sample_id_pixel(renderer, gl, 0, h - 1)
            depth = renderer._read_float(w // 2, h // 2, -1)
            depth_errors = gl.errors()
            passed = (renderer.frame_ok and not render_errors and not depth_errors
                      and not occupied["errors"] and not background["errors"]
                      and occupied["production_state_restored"] and background["production_state_restored"]
                      and occupied["native_unclamped"]["rgba"][0] == encoded
                      and not occupied["native_unclamped"]["errors"]
                      and occupied["production_scalar"] == encoded
                      and occupied["production_pick"] == encoded - 1
                      and background["raw_rgba"][0] == 0 and background["production_pick"] == -1
                      and depth is not None and abs(depth - 0.5) < 0.00001
                      and np.array_equal(renderer.last_vp, np.identity(4)))
            report["rows"].append({"expected_encoded": encoded, "expected_id": encoded - 1,
                                   "passed": passed, "occupied": occupied, "background": background,
                                   "expected_depth": 0.5, "raw_depth": depth,
                                   "render_errors": render_errors, "depth_errors": depth_errors})
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if old_fbo is not None:
            old_fbo.use()
        ctx.viewport, ctx.scissor = old_viewport, old_scissor
        target.release()
        color.release()
    report["passed"] = len(report["rows"]) == len(SENTINELS) and all(row["passed"] for row in report["rows"])
    return report


def independent_gpu_controls(renderer):
    """Destructive only to the isolated diagnostic frame; redraw before reuse."""
    import moderngl
    from .renderer import VERTEX_ATTRS, VERTEX_FORMAT
    ctx = renderer.ctx
    gl = NativeGL()
    report = {"sentinels": list(SENTINELS), "expected_source": "fixed CPU constants",
              "same_renderer_attachment": renderer.gbuffer.glo, "same_readback": "Renderer._read_float/pick",
              "errors_on_entry": gl.errors(), "state_on_entry": gl.state(),
              "attachment": gl.attachment(renderer), "uniform": [], "integer_attribute": []}
    resources = []
    old_frame_ok, old_viewport, old_scissor = renderer.frame_ok, ctx.viewport, ctx.scissor
    old_fbo, old_gbuffer_viewport = ctx.fbo, renderer.gbuffer.viewport
    uniform_vs = """#version 410 core
    void main() { vec2 p[3] = vec2[3](vec2(-0.75,-0.75),vec2(0.75,-0.75),vec2(0.0,0.75));
                  gl_Position = vec4(p[gl_VertexID],0.0,1.0); }"""
    uniform_fs = """#version 410 core
    uniform float u_id; layout(location=0) out vec4 c; layout(location=1) out vec4 n;
    layout(location=2) out float object_id;
    void main() { c=vec4(0.2,0.3,0.4,1.0); n=vec4(0.0,0.0,1.0,1.0); object_id=u_id; }"""
    attribute_vs = """#version 410 core
    in vec3 in_pos; in vec3 in_nrm; in uint in_obj; in uint in_mat;
    flat out uint v_obj; flat out uint v_mat; out vec3 v_nrm;
    void main() { gl_Position=vec4(in_pos,1.0); v_obj=in_obj; v_mat=in_mat; v_nrm=in_nrm; }"""
    attribute_fs = """#version 410 core
    flat in uint v_obj; flat in uint v_mat; in vec3 v_nrm;
    layout(location=0) out vec4 c; layout(location=1) out vec4 n; layout(location=2) out float object_id;
    void main() { c=vec4(float(v_mat),0.0,0.0,1.0); n=vec4(v_nrm,1.0); object_id=float(v_obj)+1.0; }"""

    def sample(x, y):
        return sample_id_pixel(renderer, gl, x, y)

    try:
        up = ctx.program(vertex_shader=uniform_vs, fragment_shader=uniform_fs)
        resources.append(up)
        uv = ctx.vertex_array(up, [])
        resources.append(uv)
        ap = ctx.program(vertex_shader=attribute_vs, fragment_shader=attribute_fs)
        resources.append(ap)
        index = ctx.buffer(struct.pack("<3I", 0, 1, 2))
        resources.append(index)
        w, h = renderer.size
        for kind in ("uniform", "integer_attribute"):
            for encoded in SENTINELS:
                renderer.gbuffer.use()
                ctx.viewport = (0, 0, w, h)
                ctx.scissor = None
                ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
                renderer.gbuffer.clear(0, 0, 0, 0, depth=1)
                if kind == "uniform":
                    up["u_id"].value = encoded
                    uv.render(moderngl.TRIANGLES, vertices=3)
                else:
                    vbo = ctx.buffer(sentinel_vertex_bytes(encoded))
                    resources.append(vbo)
                    vao = ctx.vertex_array(ap, [(vbo, VERTEX_FORMAT, *VERTEX_ATTRS)],
                                           index_buffer=index, index_element_size=4)
                    resources.append(vao)
                    vao.render(moderngl.TRIANGLES)
                draw_errors = gl.errors()
                renderer.frame_ok = True
                occupied, background = sample(w // 2, h // 2), sample(0, h - 1)
                auxiliary = {}
                if kind == "integer_attribute":
                    auxiliary = {"material_raw": renderer._read_float(w // 2, h // 2, 0),
                                 "normal_z_expected": 1.0}
                    normal = np.full(4, np.nan, np.float32)
                    renderer.gbuffer.read_into(normal, viewport=(w // 2, h // 2, 1, 1), components=4,
                                               attachment=1, dtype="f4")
                    auxiliary["normal_raw_rgba"] = normal.tolist()
                    auxiliary["errors"] = gl.errors()
                passed = (not draw_errors and not occupied["errors"] and not background["errors"]
                          and occupied["production_scalar"] == encoded
                          and occupied["raw_rgba"][0] == encoded
                          and occupied["production_pick"] == encoded - 1
                          and background["production_scalar"] == 0
                          and background["production_pick"] == -1
                          and (kind != "integer_attribute" or (auxiliary["material_raw"] == 73
                               and auxiliary["normal_raw_rgba"][2] == 1 and not auxiliary["errors"])))
                report[kind].append({"expected_encoded": encoded, "expected_id": encoded - 1,
                                     "passed": passed, "draw_errors": draw_errors,
                                     "occupied": occupied, "background": background, **auxiliary})
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        for resource in reversed(resources):
            resource.release()
        renderer.frame_ok = old_frame_ok
        renderer.gbuffer.viewport = old_gbuffer_viewport
        if old_fbo is not None:
            old_fbo.use()
        ctx.viewport, ctx.scissor = old_viewport, old_scissor
    uniform = len(report["uniform"]) == len(SENTINELS) and all(row["passed"] for row in report["uniform"])
    attribute = len(report["integer_attribute"]) == len(SENTINELS) and all(row["passed"] for row in report["integer_attribute"])
    report.update(passed=uniform and attribute, localization=control_localization(uniform, attribute),
                  state_on_exit=gl.state(), errors_on_exit=gl.errors())
    return report


def model_viewer_readback_controls(ctx):
    """Known CPU pre-pass data through real model-viewer float query methods."""
    from .viewer.renderer import Renderer as ModelRenderer
    gl = NativeGL()
    old_fbo, old_viewport = ctx.fbo, ctx.viewport
    report = {"expected_source": "CPU pre-pass: encoded ID257, cut flag2, linear depth3.5",
              "path": "model Renderer.pick/read_ids/read_depth/ids_at",
              "passed": False, "checks": [], "errors_on_entry": gl.errors()}
    resources = []
    try:
        if old_fbo is None:
            raise RuntimeError("Model readback control needs a restorable target")
        nd = np.zeros((4, 4, 4), np.float32)
        nd[..., 2], nd[..., 3] = 1.0, 3.5
        ids = np.empty((4, 4, 2), np.float32)
        ids[..., 0], ids[..., 1] = 257, 2
        normal_depth = ctx.texture((4, 4), 4, nd.tobytes(), dtype="f4")
        resources.append(normal_depth)
        identifiers = ctx.texture((4, 4), 2, ids.tobytes(), dtype="f4")
        resources.append(identifiers)
        prepass = ctx.framebuffer([normal_depth, identifiers])
        resources.append(prepass)
        color = ctx.texture((4, 4), 4, dtype="f1")
        resources.append(color)
        output = ctx.framebuffer([color])
        resources.append(output)
        output.use()
        ctx.viewport = (1, 1, 2, 2)
        before, viewport = gl.state(), tuple(ctx.viewport)
        viewer = object.__new__(ModelRenderer)
        viewer.ctx, viewer.t = ctx, {"fbo_pre": prepass}
        viewer.size, viewer.frame_ok = (4, 4), True
        viewer.last_camera = (np.eye(4), np.eye(4), 1.0, True, (1.0, 1.0), (4, 4))
        item, point, cut = viewer.pick(1, 1)
        decoded_ids, flags = viewer.read_ids()
        depths = viewer.read_depth()
        sparse = viewer.ids_at([(0, 0), (3, 3), (-1, 0), (4, 1)])
        after = gl.state()
        checks = [
            ("model item ID", item == 256),
            ("model cut-face flag", cut is True),
            ("model world depth", point is not None and np.allclose(point, [-0.25, 0.25, -3.5])),
            ("model bulk IDs and flags", decoded_ids is not None and flags is not None
             and np.array_equal(decoded_ids, np.full((4, 4), 256))
             and np.array_equal(flags, np.full((4, 4), 2))),
            ("model linear depth", depths is not None and np.array_equal(depths, np.full((4, 4), 3.5))),
            ("model sparse queries", sparse == [256, 256, -1, -1]),
            ("model readback state restoration", tuple(ctx.viewport) == viewport
             and all(after[key] == before[key] for key in
                     ("DRAW_FRAMEBUFFER_BINDING", "READ_FRAMEBUFFER_BINDING"))),
        ]
        report["checks"] = [{"name": name, "passed": bool(passed)} for name, passed in checks]
        report["observed"] = {"item": item, "cut": bool(cut),
                              "point": point.tolist() if point is not None else None, "sparse": sparse}
        report["errors"] = gl.errors()
        report["passed"] = all(row["passed"] for row in report["checks"]) and not report["errors"]
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if old_fbo is not None:
            old_fbo.use()
            ctx.viewport = old_viewport
        for resource in reversed(resources):
            resource.release()
    return report


def run_gpu_controls(dataset_metadata_path=None):
    """Invisible Qt surface with the production Renderer.resize/readback code."""
    from .__main__ import configure_qt
    from .renderer import Renderer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    import moderngl
    if QApplication.instance() is None:
        configure_qt()
    app = QApplication.instance() or QApplication([])
    surface = QOffscreenSurface()
    surface.setFormat(QSurfaceFormat.defaultFormat())
    surface.create()
    qt_context = QOpenGLContext()
    qt_context.setFormat(surface.format())
    report = {"passed": False, "checks": [], "mode": "invisible_gpu_controls"}
    renderer = None
    try:
        if not qt_context.create() or not qt_context.makeCurrent(surface):
            raise RuntimeError("Could not make the diagnostic Qt OpenGL context current")
        ctx = moderngl.create_context(require=410)
        report.update(environment_report(ctx, qt_context))
        from .config import DATA_DIR
        try:
            report["dataset_metadata"] = dataset_metadata_identity(dataset_metadata_path or DATA_DIR / "anatomy.json")
        except (OSError, ValueError, KeyError, TypeError) as error:
            report["dataset_metadata"] = {"available": False, "geometry_loaded": False, "error": type(error).__name__}
        synthetic = SimpleNamespace(n=max(SENTINELS), structures=[{} for _ in range(max(SENTINELS))],
                                    materials=[{"color": [0.5, 0.2, 0.1], "distinct": [0.5, 0.2, 0.1],
                                                "alpha": 1.0, "category": "other"}])
        renderer = Renderer(ctx, synthetic, sentinel_vertex_bytes(SENTINELS[0], material=0),
                            struct.pack("<3I", 0, 1, 2))
        renderer.resize(64, 64)
        report["control_buffer_size"] = list(renderer.size)
        report["controls"] = independent_gpu_controls(renderer)
        report["production_controls"] = production_gpu_controls(renderer)
        report["model_viewer_controls"] = model_viewer_readback_controls(ctx)
        uniform = all(row["passed"] for row in report["controls"]["uniform"]) and len(report["controls"]["uniform"]) == len(SENTINELS)
        attribute = all(row["passed"] for row in report["controls"]["integer_attribute"]) and len(report["controls"]["integer_attribute"]) == len(SENTINELS)
        report["localization"] = control_localization(uniform, attribute, report["production_controls"]["passed"])
        report["passed"] = (report["controls"]["passed"] and report["production_controls"]["passed"]
                            and report["model_viewer_controls"]["passed"])
        report["checks"] = [{"name": f"{kind} encoded {row['expected_encoded']}", "passed": row["passed"]}
                            for kind in ("uniform", "integer_attribute") for row in report["controls"][kind]]
        report["checks"].extend({"name": f"production Renderer encoded {row['expected_encoded']}", "passed": row["passed"]}
                                for row in report["production_controls"]["rows"])
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if renderer is not None:
            renderer.release()
        qt_context.doneCurrent()
        surface.destroy()
    return report


def pump(app, seconds=0.15):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def run_native_trace(path, seconds=120, use_saved_view_settings=False, _on_ready=None):
    """Opt-in physical input capture using unchanged MainWindow/QMenu handlers.

    Study storage and QSettings writes go to a temporary diagnostic directory.
    Optional saved view preferences are copied read-only before that isolation.
    Each event flushes a report, so native crashes leave preceding evidence.
    """
    from .__main__ import configure_qt
    from . import config
    from .data import Dataset
    from PySide6.QtCore import QEvent, QObject, QSettings, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QMenu

    if QApplication.instance() is not None:
        raise RuntimeError("Native input capture requires its own process")
    configure_qt()
    app = QApplication([])
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.ORG_NAME)
    report = {"mode": "physical_input_main_window", "passed": False, "checks": [], "events": [],
              "native_menu_substituted": False, "physical_trackpad_verified": False,
              "picking_validated": False, "physical_menu_visibility_validated": False,
              "settings_source": "copied saved view preferences" if use_saved_view_settings else "defaults",
              "interpretation": "Event capture only. A Qt menu show event does not prove physical menu visibility."}
    capture_errors = []

    def flush():
        path.write_text(json.dumps(json_safe(report), indent=2, allow_nan=False), encoding="utf-8")

    def record(kind, **details):
        report["events"].append({"seconds": round(time.perf_counter() - started, 3), "kind": kind, **details})
        flush()

    started = time.perf_counter()
    old_format = QSettings.defaultFormat()
    saved = None
    if use_saved_view_settings:
        original = QSettings(old_format, QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        saved = original.value("view_settings", "{}")
    original_paths = config.USER_DIR, config.LOG_DIR
    original_cache_candidates = config.cache_candidates
    temporary_holder = tempfile.TemporaryDirectory(prefix="anatomy-native-picking-")
    temporary = temporary_holder.name
    window = None
    try:
        directory = Path(temporary).resolve(strict=True)
        config.USER_DIR, config.LOG_DIR = directory / "user", directory / "logs"

        def isolated_cache_candidates(path):
            path = Path(path)
            try:
                relative = path.relative_to(config.ROOT)
            except ValueError:
                relative = Path(hashlib.sha256(str(path).encode("utf-8")).hexdigest()) / path.name
            destination = directory / "cache" / relative
            return [destination, path], destination  # bundled read; temporary writes

        config.cache_candidates = isolated_cache_candidates
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(directory / "settings"))
        QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(directory / "settings-system"))
        if saved is not None:
            isolated = QSettings(QSettings.IniFormat, QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
            isolated.setValue("view_settings", saved)
            isolated.sync()
        from .main_window import MainWindow
        ds = Dataset(config.DATA_DIR)
        window = MainWindow(ds, restore=False)
        view = window.viewport
        window.setWindowTitle("Anatomy Explorer — native picking capture")
        window.resize(1120, 760)
        latest_pointer = {}

        class Events(QObject):
            def eventFilter(self, obj, event):
                try:
                    kind = event.type()
                    if obj is view and kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                        latest_pointer.clear()
                        latest_pointer.update(logical_xy=[event.position().x(), event.position().y()],
                                              global_xy=[event.globalPosition().x(), event.globalPosition().y()],
                                              button=event.button().name, spontaneous=event.spontaneous(),
                                              event_kind=kind.name)
                        record(kind.name, **latest_pointer)
                        QTimer.singleShot(0, latest_pointer.clear)
                    if obj is window and kind in (QEvent.WindowActivate, QEvent.WindowDeactivate):
                        record(kind.name, active=window.isActiveWindow())
                    if isinstance(obj, QMenu) and kind == QEvent.Polish:
                        if not obj.property("picking_trace_connected"):
                            obj.setProperty("picking_trace_connected", True)
                            obj.aboutToShow.connect(lambda menu=obj: record("menu_about_to_show", actions=[a.text() for a in menu.actions()]))
                            obj.aboutToHide.connect(lambda: record("menu_about_to_hide"))
                            obj.triggered.connect(lambda action: record("menu_action_triggered", text=action.text()))
                    if isinstance(obj, QMenu) and kind in (QEvent.Show, QEvent.Hide):
                        record("menu_" + kind.name.lower(), visible=obj.isVisible(),
                               actions=[action.text() for action in obj.actions()],
                               geometry=[obj.x(), obj.y(), obj.width(), obj.height()])
                except Exception:
                    capture_errors.append(traceback.format_exc())
                    record("capture_callback_error", error=capture_errors[-1])
                return False

        events = Events(app)
        app.installEventFilter(events)
        original_pick = view.pick_at

        def captured_pick(pos):
            sid = original_pick(pos)
            # Only press/release/hover calls at the last pointer location are
            # logged; diagnostic sampling does not synthesize physical events.
            if latest_pointer and latest_pointer["logical_xy"] == [pos.x(), pos.y()]:
                details = {"logical_xy": [pos.x(), pos.y()], "id": sid,
                           "name": ds.structures[sid]["name"] if sid >= 0 else None,
                           "side": ds.structures[sid].get("side") if sid >= 0 else None,
                           "pointer": dict(latest_pointer), "dpr": view.devicePixelRatioF(),
                           "logical_size": [view.width(), view.height()],
                           "buffer_size": list(view.renderer.size),
                           "mapped_pixel": list(view._gl_xy(pos)),
                           "window_active": window.isActiveWindow(), "viewport_has_focus": view.hasFocus(),
                           "application_state": app.applicationState().name,
                           "frame_ok": view.renderer.frame_ok,
                           "state_dirty": view._state_dirty,
                           "frame_key": repr(view._pick_frame_key), "current_frame_key": repr(view._frame_key()),
                           "camera_view": view.camera.view().tolist(), "last_vp": view.renderer.last_vp.tolist()}
                view.makeCurrent()
                try:
                    gl = NativeGL()
                    details["gl_errors_before_sample"] = gl.errors()
                    details["gl_state_before_sample"] = gl.state()
                    x, y = view._gl_xy(pos)
                    rgba = np.full(4, np.nan, np.float32)
                    if 0 <= x < view.renderer.size[0] and 0 <= y < view.renderer.size[1]:
                        view.renderer.gbuffer.read_into(rgba, viewport=(x, y, 1, 1), components=4, attachment=2, dtype="f4")
                        details["raw_rgba"] = rgba.tolist()
                        details["raw_depth"] = view.renderer._read_float(x, y, -1)
                    details["gl_errors_after_sample"] = gl.errors()
                    details["gl_state_after_sample"] = gl.state()
                except Exception:
                    details["capture_sample_error"] = traceback.format_exc()
                    capture_errors.append(details["capture_sample_error"])
                finally:
                    view.doneCurrent()
                record("pick_returned", **details)
                latest_pointer.clear()
            return sid

        view.pick_at = captured_pick
        view.structureClicked.connect(lambda sid, mods: record("structure_clicked", id=sid, selected=sorted(window.state.selected)))
        view.contextMenuRequested.connect(lambda sid, pos: record("context_menu_signal_completed", id=sid,
                                                                 global_xy=[pos.x(), pos.y()]))
        window.state.render_changed.connect(lambda: record("scene_state_changed", selected=sorted(window.state.selected),
                                                     visible_count=int(window.state.visible_mask().sum())))
        window.cmds.actions["hide"].triggered.connect(lambda: record("hide_action_completed", selected=sorted(window.state.selected),
                                                                      visible_count=int(window.state.visible_mask().sum())))
        errors = []
        old_hook = sys.excepthook
        sys.excepthook = lambda *args: (errors.append("".join(traceback.format_exception(*args))),
                                      record("qt_callback_error", error=errors[-1]))
        flush()
        try:
            window.show()
            pump(app, 0.8)
            view.makeCurrent()
            try:
                report.update(environment_report(view.ctx, view.context()))
                report["dataset"] = dataset_identity(ds)
                report["controls"] = independent_gpu_controls(view.renderer)
                # The controls overwrite this isolated G-buffer; restore a
                # genuine atlas frame before allowing any pointer input.
                view._pick_frame_key = None
                view.paintGL()
            finally:
                view.doneCurrent()
            record("ready_for_physical_input", controls_passed=report["controls"]["passed"])
            print("Native capture: click the forearm, click background, then right-click the forearm; dismiss the real menu or choose Hide. Close the capture window when done.", flush=True)
            if _on_ready is not None:
                report["synthetic_test_driver"] = True
                _on_ready(window)
            QTimer.singleShot(max(1, int(seconds * 1000)), window.close)
            app.exec()
            report.update(passed=not errors and not capture_errors, capture_completed=True,
                          capture_incomplete=bool(capture_errors), capture_errors=capture_errors,
                          physical_validation="Parent/user must assess exact anatomy and native popup visibility.")
        except Exception:
            report["error"] = traceback.format_exc()
        finally:
            view.pick_at = original_pick
            window.close()
            app.removeEventFilter(events)
            sys.excepthook = old_hook
            flush()
    except Exception:
        report["error"] = traceback.format_exc()
        flush()
    finally:
        # Workers retain the scoped cache callable they imported. Never remove
        # their directory while they can still write to it. A slow worker leaves
        # an owned temp directory rather than touching installation caches.
        workers = [getattr(getattr(window, name, None), "_thread", None)
                   for name in ("relations", "depth_index", "section_index")]
        for worker in workers:
            if worker is not None:
                worker.join(timeout=1)
        if any(worker is not None and worker.is_alive() for worker in workers):
            temporary_holder._finalizer.detach()
            report["temporary_cache_cleanup_deferred"] = True
        else:
            temporary_holder.cleanup()
        config.USER_DIR, config.LOG_DIR = original_paths
        config.cache_candidates = original_cache_candidates
        QSettings.setDefaultFormat(old_format)
        flush()
    return report


def run_checks():
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QNativeGestureEvent, QPointingDevice, QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .__main__ import configure_qt
    from .config import DATA_DIR, DEFAULT_SETTINGS
    from .data import Dataset
    from .state import SceneState
    from .viewport import Viewport

    if QApplication.instance() is None:
        configure_qt()
    app = QApplication.instance() or QApplication([])
    ds = Dataset(DATA_DIR)
    settings = dict(DEFAULT_SETTINGS)
    state = SceneState(ds, settings)
    view = Viewport(ds, state, settings)
    view.setWindowTitle("Isolated atlas picking diagnostics")
    view.setAttribute(Qt.WA_ShowWithoutActivating)
    view.resize(640, 480)
    report = {"platform": sys.platform, "checks": [], "macos_gpu_run": sys.platform == "darwin",
              "physical_trackpad_verified": False}
    qt_errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *args: qt_errors.append("".join(traceback.format_exception(*args)))

    def check(condition, name):
        report["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    def gl_error():
        view.makeCurrent()
        try:
            return view.ctx.error
        finally:
            view.doneCurrent()

    def raw_ids():
        view.makeCurrent()
        try:
            w, h = view.renderer.size
            pixels = np.full((h, w, 4), np.nan, np.float32)
            native = NativeGL()
            before = native.state()
            before_errors = native.errors()
            previous_fbo, previous_viewport = view.ctx.fbo, view.ctx.viewport
            if previous_fbo is None:
                raise RuntimeError("Atlas ID read requires a restorable framebuffer")
            try:
                view.renderer.gbuffer.use()
                view.renderer.gbuffer.read_into(pixels, components=4, attachment=2, dtype="f4")
            finally:
                previous_fbo.use()
                view.ctx.viewport = previous_viewport
            err = view.ctx.error
            finite = pixels[..., 0][np.isfinite(pixels[..., 0])]
            values, counts = np.unique(finite, return_counts=True)
            report.setdefault("atlas_raw_reads", []).append({"size": [w, h], "gl_state_before": before,
                "errors_before": before_errors, "gl_state_after": native.state(), "gl_error_after": err,
                "finite_pixels": int(finite.size), "total_pixels": w * h,
                "encoded_values": [{"raw": float(value), "pixels": int(count)} for value, count in zip(values, counts)],
                "interpretation": "Observations from the GPU buffer; not an independent anatomy oracle."})
            check(err == "GL_NO_ERROR", "RGBA ID buffer read succeeds: " + err)
            check(np.isfinite(pixels[..., 0]).all(), "ID buffer read returns initialized finite pixels")
            return np.rint(pixels[..., 0]).astype(np.int32) - 1
        finally:
            view.doneCurrent()

    def candidates():
        # Interior pixels avoid boundary differences from logical click rounding.
        out = {}
        raw = raw_ids()
        for y in range(8, view.height() - 8, 8):
            for x in range(8, view.width() - 8, 8):
                gx, gy = view._gl_xy(QPoint(x, y))
                sid = int(raw[gy, gx])
                if sid not in out and (raw[max(0, gy-2):gy+3, max(0, gx-2):gx+3] == sid).all():
                    out[sid] = QPoint(x, y)
        check(-1 in out and len(out) >= 4, "Real atlas has background and at least three visible targets")
        return out

    try:
        view.show()
        pump(app, 0.6)
        check(view.renderer is not None, "OpenGL atlas initializes")
        view.makeCurrent()
        try:
            report.update(environment_report(view.ctx, view.context()))
            report["dataset"] = dataset_identity(ds)
            report["controls"] = independent_gpu_controls(view.renderer)
            view._pick_frame_key = None
            view.paintGL()
        finally:
            view.doneCurrent()
        check(report["controls"]["passed"], "Independent uniform and integer attribute sentinels survive production readback")
        report.update(gpu=view.ctx.info["GL_RENDERER"], gl_version=view.ctx.info["GL_VERSION"],
                      dpr=view.devicePixelRatioF(), logical_size=[view.width(), view.height()],
                      buffer_size=view.renderer.size, after_paint_gl_error=gl_error())
        points = candidates()
        real_ids = [sid for sid in points if sid >= 0]
        report["targets"] = [{"id": sid, "name": ds.structures[sid]["name"],
                              "logical_xy": [points[sid].x(), points[sid].y()]} for sid in real_ids]
        for sid in [-1] + real_ids[:6]:
            check(view.pick_at(points[sid]) == sid, f"Pointer selects expected atlas ID {sid}")
        check(gl_error() == "GL_NO_ERROR", "Single-pixel RGBA reads have no GL errors")

        clicked, contexts = [], []
        view.structureClicked.connect(lambda sid, mods: (clicked.append(sid), state.select([sid]) if sid >= 0 else state.clear_selection()))
        view.contextMenuRequested.connect(lambda sid, pos: contexts.append(sid))
        for sid in real_ids[:3]:
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, points[sid])
            check(clicked[-1] == sid, f"Normal mouse click selects structure {sid}")
            view._last_hover_pick = 0
            pos = QPointF(points[sid])
            event = QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            QApplication.sendEvent(view, event)
            check(state.hovered == sid, f"No-button pointer move refreshes hover to {sid}")

        target = real_ids[1]
        QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, points[target])
        check(contexts[-1] == target, "Right-click captures pointer target instead of previous selection")
        # Execute the real atlas context-menu and Hide handlers with a minimal
        # isolated window harness. Substitute only the blocking popup surface;
        # no MainWindow settings, caches or study widgets are initialized.
        from PySide6.QtGui import QAction
        from . import main_window
        from .main_window import MainWindow
        actions = {key: QAction(key) for key in ("frame", "xray", "isolate", "hide", "both_sides", "note")}
        harness = SimpleNamespace(quiz=None, cmds=SimpleNamespace(actions=actions), state=state, ds=ds,
                                  viewport=view, info=SimpleNamespace(show_welcome=lambda: None),
                                  content=SimpleNamespace(micro_for_structures=lambda ids: [],
                                                          histology_for_structures=lambda ids: []),
                                  on_structure_clicked=lambda sid, mods: state.select([sid]),
                                  pick_color=lambda: None)
        actions["hide"].triggered.connect(lambda: MainWindow.hide_selection(harness))

        class Popup:
            def __init__(self, parent):
                self.items = []

            def addAction(self, action, callback=None):
                action = QAction(action) if isinstance(action, str) else action
                self.items.append(action)
                return action

            def addSeparator(self):
                pass

            def exec(self, pos):
                check(actions["hide"] in self.items, "Real context menu offers Hide for pointer target")
                actions["hide"].trigger()

        old_menu = main_window.QMenu
        main_window.QMenu = Popup
        try:
            MainWindow.on_context_menu(harness, contexts[-1], QPoint())
        finally:
            main_window.QMenu = old_menu
        check(not state.visible_mask()[target], "Context target Hide changes visibility")
        check(view.pick_at(points[target]) != target, "Immediate pick after Hide cannot return stale hidden target")
        state.set_hidden([target], False)
        check(view.pick_at(points[target]) == target, "Immediate Show restores correct target before queued paint")

        settings["trackpad_mode"] = "Trackpad"
        center = QPointF(view.width()/2, view.height()/2)
        for mods, pixel, angle, label in (
            (Qt.NoModifier, QPoint(24, 8), QPoint(), "trackpad orbit"),
            (Qt.ShiftModifier, QPoint(12, 4), QPoint(), "trackpad pan"),
            (Qt.ControlModifier, QPoint(), QPoint(0, 30), "Windows precision pinch"),
        ):
            event = QWheelEvent(center, center, pixel, angle, Qt.NoButton, mods, Qt.ScrollUpdate, False)
            before = view.camera.view().copy()
            QApplication.sendEvent(view, event)
            view.pick_at(center)
            check(not np.array_equal(before, view.camera.view()), label + " changes camera")
            expected = view.camera.proj(view.renderer.size[0]/view.renderer.size[1]) @ view.camera.view()
            check(np.allclose(view.renderer.last_vp, expected), label + " pick uses current camera frame")

        for gesture, value, label in ((Qt.ZoomNativeGesture, 0.08, "macOS native pinch"),
                                      (Qt.RotateNativeGesture, 7.0, "macOS native rotate")):
            event = QNativeGestureEvent(gesture, QPointingDevice.primaryPointingDevice(), 2,
                                        center, center, center, value, QPointF())
            before = view.camera.view().copy()
            QApplication.sendEvent(view, event)
            view.pick_at(center)
            check(not np.array_equal(before, view.camera.view()), label + " changes camera")
            expected = view.camera.proj(view.renderer.size[0]/view.renderer.size[1]) @ view.camera.view()
            check(np.allclose(view.renderer.last_vp, expected), label + " pick uses current camera frame")

        for width, height, scale in ((641, 479, 0.67), (791, 533, 1.0), (640, 480, 0.5)):
            view.resize(width, height)
            settings["render_scale"] = scale
            view.reset_view(animate=False)
            view.pick_at(QPoint(0, 0))
            w, h = view.renderer.size
            check(view._gl_xy(QPointF(0, 0)) == (0, h-1), f"Top-left maps to top ID pixel at scale {scale}")
            check(view._gl_xy(QPointF(view.width()-0.01, view.height()-0.01)) == (w-1, 0),
                  f"Bottom-right maps to bottom ID pixel at scale {scale}")
            check(view.pick_at(QPointF(-0.1, 0)) == -1 and view.pick_at(QPointF(view.width(), 0)) == -1,
                  f"Outside viewport never selects at scale {scale}")
            pump(app)
            fresh = candidates()
            for sid in [k for k in fresh if k >= 0][:3]:
                check(view.pick_at(fresh[sid]) == sid, f"Fresh selection after resize/scale {scale}, ID {sid}")

        renderer = view.renderer
        real_fbo = renderer.gbuffer
        for value, label in ((None, "unwritten failed read"), (np.nan, "NaN"),
                             (np.inf, "infinity"), (2.5, "fractional ID"), (ds.n+1, "out-of-range ID")):
            def bad_read(buffer, value=value, **kwargs):
                if value is not None:
                    buffer[0] = value
            renderer.gbuffer = SimpleNamespace(read_into=bad_read, use=real_fbo.use)
            check(renderer.pick(10, 10) == -1, label + " cannot select an arbitrary structure")
            if value is None or not math.isfinite(value) or value > 1:
                check(renderer.world_at(10, 10) is None, label + " cannot yield a bogus world point")
        renderer.gbuffer = real_fbo
        check(not qt_errors, "Qt input/render callbacks raised no exceptions")
        report["passed"] = True
    except Exception:
        report.update(passed=False, error=traceback.format_exc())
    finally:
        if view.renderer is not None:
            if "real_fbo" in locals():
                view.renderer.gbuffer = real_fbo
            view.makeCurrent()
            view.renderer.release()
            view.doneCurrent()
        view.close()
        sys.excepthook = old_hook
        if qt_errors:
            report["qt_errors"] = qt_errors
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pick-diagnostics", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path, help="JSON report path (otherwise a new temp file)")
    parser.add_argument("--gpu-controls-only", action="store_true", help="Invisible independent GPU controls; no atlas or model assets")
    parser.add_argument("--native-trace", action="store_true", help="Opt-in physical input capture with actual MainWindow and QMenu")
    parser.add_argument("--seconds", type=float, default=120, help="Native trace maximum duration")
    parser.add_argument("--use-saved-view-settings", action="store_true", help="Copy saved view preferences read-only into isolated native trace")
    args = parser.parse_args(argv)
    if args.native_trace and args.gpu_controls_only:
        parser.error("Choose either native trace or GPU controls only")
    if args.report:
        path = args.report
    else:
        with tempfile.NamedTemporaryFile(prefix="anatomy-picking-", suffix=".json", delete=False) as f:
            path = Path(f.name)
    if args.native_trace:
        report = run_native_trace(path, args.seconds, args.use_saved_view_settings)
    else:
        report = run_gpu_controls() if args.gpu_controls_only else run_checks()
    path.write_text(json.dumps(json_safe(report), indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "gpu": report.get("gpu") or report.get("gl", {}).get("GL_RENDERER"), "dpr": report.get("dpr"),
                      "error": report.get("error")}, indent=2))
    print("Picking diagnostics report:", path)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
