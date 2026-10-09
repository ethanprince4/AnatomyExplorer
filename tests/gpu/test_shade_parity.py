"""WGSL surface shading (app/gpu/wgsl/vertex.wgsl + shading.wgsl) against the GLSL original, small version of
tools/perf/gpu/shade_parity.py.  Skips when there is no wgpu adapter on the GPU that owns the GL context, or no GL context.

Anisotropy is off on both sides: the GL driver and Vulkan filter anisotropically in different (both valid) ways, which
gives up to a few /255 on grazing high-frequency textures (see the tool's report); everything else must match."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

wgpu = pytest.importorskip("wgpu")
moderngl = pytest.importorskip("moderngl")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "perf" / "gpu"))

VENDORS = ("nvidia", "intel", "amd", "radeon")


def _gl_vendor():
    try:
        ctx = moderngl.create_standalone_context(require=410)
    except Exception as ex:                                             # noqa: BLE001 - no GL 4.1 context
        pytest.skip(f"no GL context: {ex}")
    name = ctx.info["GL_RENDERER"].lower()
    ctx.release()
    return next((v for v in VENDORS if v in name), None)


@pytest.fixture(scope="module")
def result():
    import shade_parity as sp
    vendor = _gl_vendor()
    if vendor is None:
        pytest.skip("unknown GL vendor")
    try:
        adapters = [a for a in wgpu.gpu.enumerate_adapters_sync()
                    if a.info.get("backend_type") == "Vulkan" and vendor in a.summary.lower()]
    except Exception as ex:                                             # noqa: BLE001
        pytest.skip(f"no wgpu: {ex}")
    if not adapters:
        pytest.skip(f"no wgpu Vulkan adapter for {vendor}")
    out = sp.run(size=512, adapter=vendor, scale=1.0, aniso=1, probe=True)
    return {c["case"]: c for c in out["cases"]}, out


def test_front_facing_agrees(result):
    probe = result[1]["front_facing_probe"]
    assert probe["mismatch_px"] == 0


@pytest.mark.parametrize("case", ["default", "textured", "tissue_ortho", "clip_batched", "anim_corner"])
def test_case_matches(result, case):
    r = result[0][case]
    assert r["compared"] > 5000
    assert r["nonfinite_wgpu"] == 0 and r["nonfinite_gl"] == 0
    if result[1]["wgpu"].lower().find("nvidia") < 0:
        pytest.skip("bit-level parity (sin hash, sampler rounding) is only asserted on the same GPU vendor")
    limit = 2.5 if case == "textured" else 0.5                    # 1/255 units after tone mapping; the sampler's own rounding
    assert r["max_err"] <= limit, r["worst"][:2]
    assert r["mean_err"] <= 0.2
    assert r["only_gl"] + r["only_wgpu"] <= 0.001 * r["compared"]
