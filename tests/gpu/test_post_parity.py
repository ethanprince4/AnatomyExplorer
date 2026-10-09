"""wgpu post passes against the GLSL originals (skips when no adapter or no GL context is available)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "perf" / "gpu"))

wgpu = pytest.importorskip("wgpu")
pytest.importorskip("moderngl")

from app.gpu import post as P  # noqa: E402


def test_uniform_struct_sizes_and_offsets():
    # packed sizes match the WGSL structs (field offsets in the comments of the pack_* functions)
    assert len(P.pack_backdrop((1, 2, 3), (4, 5, 6))) == P.UNIFORM_SIZES["backdrop"]
    assert len(P.pack_ssao((1, 2), 1, 16, 3, 4, 5, 6, 7, 8)) == P.UNIFORM_SIZES["ssao"]
    assert len(P.pack_blur((1, 2))) == P.UNIFORM_SIZES["blur"]
    assert len(P.pack_prefilter(1, 2)) == P.UNIFORM_SIZES["prefilter"]
    c = P.pack_composite((1, 2, 3), 9, (4, 5, 6), 7, (8, 10), 11, 1, 1, 1)
    assert len(c) == P.UNIFORM_SIZES["composite"]
    import struct
    f = lambda o: struct.unpack_from("<f", c, o)[0]  # noqa: E731
    i = lambda o: struct.unpack_from("<i", c, o)[0]  # noqa: E731
    assert (f(0), f(4), f(8), f(12)) == (1, 2, 3, 9)           # outline, hover
    assert (f(16), f(20), f(24), f(28)) == (4, 5, 6, 7)        # hover_outline, exposure
    assert (f(32), f(36), f(40)) == (8, 10, 11)                # texel, outline_px
    assert (i(44), i(48), i(52)) == (1, 1, 1)                  # oit_on, has_sel, tonemap
    s = P.pack_ssao((1, 2), 1, 16, 3, 4, 5, 6, 7, 8)
    assert struct.unpack_from("<2f2i6f", s, 0) == (1, 2, 1, 16, 3, 4, 5, 6, 7, 8)


def test_wgsl_struct_layout_matches():
    # the WGSL member order the packers assume
    comp = (P.WGSL_DIR / "post_composite.wgsl").read_text()
    names = re.findall(r"^\s+(\w+): (?:vec[23]<f32>|f32|i32),", comp.split("struct U {")[1].split("};")[0], re.M)
    assert names == ["outline", "hover", "hover_outline", "exposure", "texel", "outline_px", "oit_on", "has_sel",
                     "tonemap", "_p0", "_p1"]


@pytest.fixture(scope="module")
def env():
    import post_parity as pp
    ad = pp.pick_adapter(None)
    if ad is None:
        pytest.skip("no wgpu adapter")
    try:
        dev = pp.make_device(ad)
        gl = pp.GL()
    except Exception as ex:  # no GL context
        pytest.skip(f"no device/GL context: {ex}")
    return pp, dev, P.PostPasses(dev), gl


@pytest.mark.parametrize("idx", [0, 1])
def test_composite_and_chain_parity(env, idx):
    pp, dev, pas, gl = env
    cmb = dict(pp.COMBOS[idx])
    cmb["size"] = (640, 360) if idx == 0 else (704, 396)   # h <= 810: outline_px = 1.5 tie case covered
    rows, lines = [], []
    s = pp.run_combo(gl, dev, pas, cmb, {}, rows, lines.append)
    assert s["max"] <= 2.0 and s["mean"] <= 0.2, lines
    ssao = [r for r in rows if r["pass_"] == "ssao AO (a)"][0]
    assert ssao["pct_over1"] < 0.5 and ssao["mean"] < 0.1       # isolated sample flips only
    neg = [r for r in rows if r["pass_"].startswith("composite flipped")][0]
    assert neg["mean"] > 5.0                                     # the metric is orientation sensitive


def test_prefilter_levels(env):
    pp, dev, pas, gl = env
    rows = []
    pp.run_env(gl, dev, pas, rows, lambda *_: None)
    for r in rows:
        if r["pass_"].startswith("prefilter f32"):
            assert r["max"] < 20.0, r        # units of 1e-3 radiance
        if r["pass_"].startswith("Environment.spec"):
            assert r["max"] < 20.0, r

def test_pack_depth_is_an_exact_copy_of_nd_w():
    """The SSAO taps read the r32float copy of nd.w: it must equal the rgba32float channel bit for bit (any size)."""
    import numpy as np
    import post_parity as pp
    ad = pp.pick_adapter(None)
    if ad is None:
        pytest.skip("no wgpu adapter")
    dev = pp.make_device(ad)
    pas = P.PostPasses(dev)
    rng = np.random.default_rng(3)
    for w, h in ((97, 61), (256, 128), (97, 61)):             # the repeat checks that the cached texture is rewritten
        nd = rng.standard_normal((h, w, 4)).astype(np.float32)
        nd[..., 3] = np.where(rng.random((h, w)) < 0.3, 0.0, np.abs(nd[..., 3]) * 5.0)
        t = P.make_texture(dev, w, h, "rgba32float", nd)
        d = pas.pack_depth(t)
        got = P.read_texture(dev, d, np.float32, 1)[..., 0]
        assert got.shape == (h, w) and np.array_equal(got.view(np.uint32), nd[..., 3].view(np.uint32))

