"""Weighted blended OIT on wgpu (app/gpu/oit.py + wgsl/oit.wgsl) against the GLSL OIT_FS and the composite, small version
of tools/perf/gpu/oit_parity.py.  The record packing test needs no GPU; the parity test skips when there is no GL 4.1
context or no wgpu Vulkan adapter on the GPU that owns it.

    python -m pytest tests/gpu/test_oit.py -q -p no:cacheprovider
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tools" / "perf" / "gpu")):
    if p not in sys.path:
        sys.path.insert(0, p)

VENDORS = ("nvidia", "intel", "amd", "radeon")


def _fake_geom():
    return types.SimpleNamespace(
        const_tail=np.arange(26, dtype=np.float32).reshape(2, 13),
        stream_base=np.array([[-1, -1, -1, -1, -1], [5, -1, 7, -1, 9]], np.int64),
        vbase=np.array([0, 100], np.int64))


def test_record_layout_matches_the_wgsl_struct():
    pytest.importorskip("wgpu")
    from app.gpu import oit as O
    src = (ROOT / "app" / "gpu" / "wgsl" / "oit.wgsl").read_text(encoding="utf-8")
    body = src.split("struct OitDraw {")[1].split("}")[0]
    fields = [ln.split(":")[0].strip() for ln in body.splitlines() if ":" in ln.split("//")[0]]
    assert fields == ["model", "nmat0", "nmat1", "nmat2", "tail0", "tail1", "tail2", "tail3", "sb0", "sb1", "misc",
                      "facing"]
    assert O.DRAW_FLOATS == 16 + 12 + 16 + 4 * 4
    M = np.eye(4)
    M[:3, 3] = (1, 2, 3)
    nm = np.arange(9, dtype=np.float64).reshape(3, 3)
    u = {"u_model": M, "u_nmat": nm, "u_weight": 0.25, "u_ghost": 1, "u_ghost_alpha": 0.1, "u_alpha_mul": 0.7,
         "u_facing_on": 1, "u_facing": (0.1, 0.8, 1.5)}
    rec = O.pack_draws([O.OitDraw(1, 0, 3, 6, u), O.OitDraw(0, 0, 3, 2, {"u_model": M, "u_nmat": nm})], _fake_geom())
    iv = rec.view(np.int32)
    assert rec.shape == (2, O.DRAW_FLOATS)
    assert list(rec[0, 12:16]) == [1, 2, 3, 1]                       # column-major: translation in column 3
    assert list(rec[0, 16:19]) == [0, 3, 6] and list(rec[0, 20:23]) == [1, 4, 7]       # u_nmat columns
    assert list(rec[0, 28:41]) == list(range(13, 26))                # const tail of part 1
    assert list(iv[0, 44:47]) == [5, -1, 7] and iv[0, 47] == -1 and iv[0, 48] == 9
    assert iv[0, 49] == 100 and iv[0, 50] == 6
    assert list(np.round(rec[0, 52:60], 3)) == [0.25, 1.0, 0.1, 0.7, 0.1, 0.8, 1.5, 1.0]
    assert list(rec[1, 52:60]) == [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]   # defaults: alpha_mul 1, no facing


def _gl_vendor():
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context(require=410)
    except Exception as ex:                                             # noqa: BLE001
        pytest.skip(f"no GL context: {ex}")
    name = ctx.info["GL_RENDERER"].lower()
    ctx.release()
    return next((v for v in VENDORS if v in name), None)


@pytest.fixture(scope="module")
def result():
    wgpu = pytest.importorskip("wgpu")
    import oit_parity as op
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
    out = op.run(size=256, samples=4, adapter=vendor, scale=0.6, aniso=1)
    return {c["case"]: c for c in out["cases"]}, out


@pytest.mark.parametrize("case", ["mix", "ortho_clip_batched"])
def test_composite_matches_gl(result, case):
    r = result[0][case]
    assert r["ghost_parts"] >= 5 and r["active_px"] > 5000
    assert np.isfinite(r["accum"]["max_abs"]) and np.isfinite(r["weight"]["max_abs"])
    if "nvidia" not in result[1]["wgpu"].lower():
        pytest.skip("pixel-level parity is only asserted on the same GPU vendor (Intel rounds pow/exp/f16 blends differently: 1-level noise, sampler alpha at hole rims)")
    # 1/255 units, bottom-up rasterisation; a lone pixel can differ by one sample (not the alpha test: persists with alpha_cut 0)
    assert r["composite"]["n_gt_2"] <= 2, r["composite"]
    assert r["composite"]["max"] <= 8.0, r["composite"]
    assert r["composite"]["mean"] <= 0.2
    assert r["weight_only_gl"] + r["weight_only_wgpu"] <= 0.001 * r["active_px"]
