"""Layout of app/gpu/shading_uniforms.py against shading.wgsl's ShadeU and against a real GPU read-back."""
from __future__ import annotations

import re
import struct

import numpy as np
import pytest

from app.gpu import shading_uniforms as su
from app.viewer import shaders


def _glsl_uniforms():
    """{name: glsl type} of the uniforms MAIN_FS declares (CLIP_COMMON + SHADING_COMMON + MAIN_FS), arrays folded."""
    text = shaders.MAIN_FS
    out = {}
    for m in re.finditer(r"uniform\s+(\w+)\s+(\w+)(\[\d+\])?\s*;", text):
        out[m.group(2)] = m.group(1)
    return out


def test_layout_is_aligned_and_disjoint():
    end = 0
    for f in su.FIELDS:
        assert f.offset % f.align == 0, f.name
        assert f.offset >= end, f"{f.name} overlaps the previous member"
        end = f.offset + f.size
    assert su.SIZE % 16 == 0 and su.SIZE >= end
    assert len({f.name for f in su.FIELDS}) == len(su.FIELDS)


def test_known_offsets():
    # hand-computed from the WGSL uniform-address-space rules (vec3 aligns to 16 but a following f32 packs at +12)
    by = su.FIELD_BY_NAME
    assert by["u_clip_on"].offset == 48 and by["u_clip_mode"].offset == 60
    assert by["u_campos"].offset == 80 and by["u_alpha_cut"].offset == 92
    assert by["u_view"].offset == 112 and by["u_view"].size == 64
    assert by["u_screen"].offset == 176 and by["u_ao_direct"].offset == 184
    assert by["u_sh"].offset == 288 and by["u_sh"].size == 9 * 16
    assert by["u_detail"].offset % 16 == 0
    assert su.SIZE == 624


def test_every_glsl_uniform_is_covered_or_ignored():
    samplers = {"sampler2D", "sampler2DArray", "sampler2DShadow"}
    for name, glsl_type in _glsl_uniforms().items():
        if glsl_type in samplers:
            continue
        assert name in su.FIELD_BY_NAME or name in su.IGNORED, f"{name} ({glsl_type}) is neither packed nor ignored"
    # and every packed member is a real GLSL uniform of MAIN_FS
    glsl = _glsl_uniforms()
    for f in su.FIELDS:
        assert f.name in glsl, f"ShadeU.{f.name} does not exist in MAIN_FS"


def test_pack_semantics():
    view = np.arange(16, dtype=np.float32).reshape(4, 4)          # numpy row-major math matrix
    sh = np.arange(27, dtype=np.float32).reshape(9, 3)
    buf = su.pack_shading_uniforms({
        "u_view": view, "u_sh": sh, "u_clip_on": (True, False, True), "u_ortho": 1, "u_base": np.array([0.1, 0.2, 0.3]),
        "u_rough": 0.25, "u_stripe_p": (1.0, 2.0, 3.0, 4.0), "u_model": np.eye(4), "u_shadow_on": 1.0})
    assert len(buf) == su.SIZE
    f = su.FIELD_BY_NAME
    got = np.frombuffer(buf, np.float32, 16, f["u_view"].offset).reshape(4, 4)
    assert np.array_equal(got, view.T)                             # column-major, as _U writes arr.T
    sh_got = np.frombuffer(buf, np.float32, 36, f["u_sh"].offset).reshape(9, 4)
    assert np.array_equal(sh_got[:, :3], sh) and not sh_got[:, 3].any()      # u_sh is raw, not transposed
    assert struct.unpack_from("3i", buf, f["u_clip_on"].offset) == (1, 0, 1)
    assert struct.unpack_from("i", buf, f["u_ortho"].offset)[0] == 1
    assert struct.unpack_from("3f", buf, f["u_base"].offset) == pytest.approx((0.1, 0.2, 0.3))
    assert struct.unpack_from("f", buf, f["u_rough"].offset)[0] == 0.25
    assert struct.unpack_from("4f", buf, f["u_stripe_p"].offset) == (1.0, 2.0, 3.0, 4.0)
    # sticky GL state: members absent from the new dict keep the previous bytes
    buf2 = su.pack_shading_uniforms({"u_rough": 0.5}, previous=buf)
    assert struct.unpack_from("f", buf2, f["u_rough"].offset)[0] == 0.5
    assert buf2[f["u_view"].offset:f["u_view"].offset + 64] == buf[f["u_view"].offset:f["u_view"].offset + 64]


def test_unknown_name_raises():
    with pytest.raises(KeyError):
        su.pack_shading_uniforms({"u_not_a_uniform": 1.0})
    with pytest.raises(ValueError):
        su.pack_shading_uniforms({"u_base": (1.0, 2.0)})


def _adapter():
    try:
        import wgpu
        return wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception:                                               # noqa: BLE001 - no wgpu or no adapter
        return None


def test_gpu_round_trip():
    """A compute shader reads every ShadeU member through the compiler's own layout; the values must be the inputs."""
    adapter = _adapter()
    if adapter is None:
        pytest.skip("no wgpu adapter")
    import wgpu
    rng = np.random.default_rng(11)
    values, expected = {}, []
    lines = []
    for f in su.FIELDS:
        if f.base == "f32":
            v = rng.normal(size=f.shape if f.shape else ()).astype(np.float32)
        else:
            v = rng.integers(-5, 5, size=f.shape if f.shape else ()).astype(np.int32)
        if f.wgsl_type.startswith("array"):
            v = v[:, :3]
        values[f.name] = v
        cnt = len(expected)
        # accessors and the matching expected words (row-major numpy matrix -> WGSL columns are arr[:, c])
        if not f.shape:
            lines.append(f"o[{cnt}] = bitcast<u32>(su.{f.name});")
            expected.append(np.asarray(v).reshape(-1)[:1].view(np.uint32)[0])
        elif len(f.shape) == 1:
            for k, c in enumerate("xyzw"[:f.shape[0]]):
                lines.append(f"o[{cnt + k}] = bitcast<u32>(su.{f.name}.{c});")
                expected.append(np.asarray(v).reshape(-1)[k:k + 1].view(np.uint32)[0])
        elif f.wgsl_type.startswith("mat"):
            cols, rows = f.shape
            k = 0
            for c in range(cols):
                for r in range(rows):
                    lines.append(f"o[{cnt + k}] = bitcast<u32>(su.{f.name}[{c}][{r}]);")
                    expected.append(np.asarray(v)[r, c:c + 1].view(np.uint32)[0])
                    k += 1
        else:
            count, n = f.shape
            k = 0
            vv = np.zeros((count, 4), np.float32)
            vv[:, :np.asarray(v).shape[1]] = v
            for i in range(count):
                for c in "xyz":
                    lines.append(f"o[{cnt + k}] = bitcast<u32>(su.{f.name}[{i}].{c});")
                    expected.append(vv[i, "xyz".index(c):"xyz".index(c) + 1].view(np.uint32)[0])
                    k += 1
    n_words = len(expected)
    src = su.SHADING_WGSL.read_text(encoding="utf-8") + f"""
@group(2) @binding(0) var<storage, read_write> o: array<u32, {n_words}>;
@compute @workgroup_size(1) fn read_all() {{
{chr(10).join(lines)}
}}
"""
    device = adapter.request_device_sync()
    module = device.create_shader_module(code=src)
    bgl1 = device.create_bind_group_layout(entries=[{"binding": 0, "visibility": wgpu.ShaderStage.COMPUTE,
                                                     "buffer": {"type": "uniform"}}])
    bgl2 = device.create_bind_group_layout(entries=[{"binding": 0, "visibility": wgpu.ShaderStage.COMPUTE,
                                                     "buffer": {"type": "storage"}}])
    empty = device.create_bind_group_layout(entries=[])
    layout = device.create_pipeline_layout(bind_group_layouts=[empty, bgl1, bgl2])
    pipe = device.create_compute_pipeline(layout=layout, compute={"module": module, "entry_point": "read_all"})
    data = su.pack_shading_uniforms(values)
    ub = device.create_buffer_with_data(data=data, usage=wgpu.BufferUsage.UNIFORM)
    ob = device.create_buffer(size=n_words * 4, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
    rb = device.create_buffer(size=n_words * 4, usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
    g1 = device.create_bind_group(layout=bgl1, entries=[{"binding": 0, "resource": {"buffer": ub}}])
    g2 = device.create_bind_group(layout=bgl2, entries=[{"binding": 0, "resource": {"buffer": ob}}])
    enc = device.create_command_encoder()
    cp = enc.begin_compute_pass()
    cp.set_pipeline(pipe)
    cp.set_bind_group(1, g1)
    cp.set_bind_group(2, g2)
    cp.dispatch_workgroups(1)
    cp.end()
    enc.copy_buffer_to_buffer(ob, 0, rb, 0, n_words * 4)
    device.queue.submit([enc.finish()])
    rb.map_sync(wgpu.MapMode.READ)
    got = np.frombuffer(rb.read_mapped(), np.uint32).copy()
    rb.unmap()
    assert np.array_equal(got, np.array(expected, np.uint32))
