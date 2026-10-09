"""GL vs wgpu on synthetic scenes with morph weights, procedural animation, textures and alpha-cut (no library model has any).

    python tools/perf/gpu/b2_check.py [--size 640 400] [--cases morph,anim,anim_modes,tex,ghost_anim,...] [--adapter NAME] [--dump DIR]

Per case: the model of tests/gpu/b2_scene.py is shown in a real ModelViewport (GL) and rendered by WgpuRenderer with the same camera,
settings and frame state; prints mean abs diff (0..255), % of pixels over 8/255, max, and id agreement.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT, ROOT / "tests", ROOT / "tests" / "gpu"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import b2_scene as sc                                           # noqa: E402


def load_model(anim=False, ghost=False, morph_weight=0.8, alpha_cut=False):
    from app.viewer.model import Model
    d = Path(tempfile.mkdtemp())
    (d / "m.glb").write_bytes(sc.glb_bytes(morph_weight=morph_weight, alpha_cut=alpha_cut))
    m = Model(d / "m.glb")
    m.evaluate(m.clip_range[0], None, 0.0)
    if anim:
        sc.attach_animation(m, None)
    return m


def open_gl(model, size, mutate=None, backend_env=None):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["b2"])
    from app.config import DEFAULT_SETTINGS
    from app.state import SceneState
    from app.viewer.dataset import ModelDataset
    from app.viewer.viewport import ModelViewport
    settings = dict(DEFAULT_SETTINGS)
    state = SceneState(ModelDataset(model), settings)
    state.opaque_materials = False
    state.part_alpha = np.ones(len(model.items), dtype=np.float32)
    w = ModelViewport(model, state, settings, SimpleNamespace(key="b2", name="b2"))
    w.resize(*size)
    w.reset_view(animate=False)
    if mutate:
        mutate(w, state, model)
    for _ in range(3):
        img = w.grabFramebuffer()
    if w.graphics_error or w.renderer is None:
        raise RuntimeError(f"no OpenGL: {w.graphics_error}")
    img = img.convertToFormat(img.Format.Format_RGBA8888)
    arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes()).reshape(
        img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :3].copy()
    return w, arr


def wgpu_image(gpu, renderer, w, frames=3):
    import wgpu
    pw, ph = w._physical_size()
    rw, rh = w._render_size()
    tex = gpu.device.create_texture(size=(pw, ph, 1), format="rgba8unorm", usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                                    | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.TEXTURE_BINDING)
    w._sync_settings()
    for _ in range(frames):
        renderer.render(tex, (rw, rh), w.camera, w.rsettings, w.frame_state(), out_size=(pw, ph))
    img = renderer.read_final(tex, (pw, ph))
    tex.destroy()
    return img


# ---------------------------------------------------------------- cases: (model kwargs, mutate(w, state, model))
def _weights(model, wgt):
    for p in model.parts:
        if p.has_morph:
            model.node_weights[p.node] = wgt


def _only(st, items, n=3):
    st.hidden[:] = True
    for i in items:
        st.hidden[i] = False
    st._visible_cache = None


def case_static0(w, st, m):
    pass
    _only(st, [0])


def case_morph(w, st, m):
    _weights(m, 0.8)
    _only(st, [0])


def case_anim(w, st, m):
    w.anim_t = 0.37
    m.anim_frame = lambda t: sc.anim_frame(m, t)
    _weights(m, 0.0)
    _only(st, [0])


def case_anim_modes(w, st, m):
    w.anim_t = 0.62
    mode0 = MODES.get(0, 1)
    m.anim_frame = lambda t: sc.anim_frame(m, t, {0: mode0, 1: 2, 2: 0})
    _weights(m, 0.0)
    _only(st, [0])


def case_anim_wave(w, st, m):
    MODES[0] = 2
    case_anim_modes(w, st, m)
    MODES.clear()


def case_tex(w, st, m):                      # opaque textured plane + morph sphere + plain ball (the alpha-cut sphere is refused)
    _only(st, [0, 2, 3])


def case_ghost_tex(w, st, m):                # the textured plane ghosted, the plain ball solid
    _only(st, [0, 2, 3])
    st.set_ghost_focus([3])


def case_ghost(w, st, m):
    _only(st, [0, 3])
    st.set_ghost_focus([3])


def case_ghost_anim(w, st, m):
    case_anim_modes(w, st, m)
    _only(st, [0, 3])
    st.set_ghost_focus([3])


def case_explode(w, st, m):
    _only(st, [0, 2, 3])
    _weights(m, 0.5)
    w.set_explode(0.6)


MODES = {}
CASES = {"static0": ({"morph_weight": 0.0}, case_static0), "anim_wave": ({"anim": True, "morph_weight": 0.0}, case_anim_wave), "morph": ({}, case_morph), "tex": ({}, case_tex), "ghost_tex": ({}, case_ghost_tex), "ghost_morph": ({}, case_ghost), "ghost_morph0": ({"morph_weight": 0.0}, case_ghost), "explode_morph": ({}, case_explode),
         "anim": ({"anim": True, "morph_weight": 0.0}, case_anim), "anim_modes": ({"anim": True, "morph_weight": 0.0}, case_anim_modes),
         "ghost_anim": ({"anim": True, "morph_weight": 0.0}, case_ghost_anim)}


ANISO1 = [False]


def gl_anisotropy_off():
    """GL textures with anisotropy 1 (the wgpu side then uses a max_anisotropy 1 sampler): isolates the filter-footprint gap
    of the two drivers (port-changes.md row 1) from LOD / mip-chain errors. Case name suffix "_aniso1"."""
    import app.viewer.renderer as VR
    cls = [c for c in vars(VR).values() if isinstance(c, type) and hasattr(c, "_texture")][0]
    if getattr(cls, "_b2_patched", False):
        return
    orig = cls._texture

    def wrapped(self, i):
        t = orig(self, i)
        if t is not self.white and ANISO1[0]:
            t.anisotropy = 1.0
        return t
    cls._texture, cls._b2_patched = wrapped, True


def stats(a, b, thr=8):
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    px = d.max(axis=2)
    return {"mean": round(float(d.mean()), 4), "pct_over": round(float((px > thr).mean() * 100), 4), "max": int(d.max())}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", nargs=2, type=int, default=(480, 300))
    ap.add_argument("--cases", default=",".join(CASES))
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--dump", default=None)
    a = ap.parse_args(argv)
    from tools.perf import perfkit as pk
    pk.env_setup()
    import os
    if a.adapter:
        os.environ["ANATOMY_WGPU_ADAPTER"] = a.adapter
    from app.gpu.device import get_gpu
    from app.gpu.renderer import WgpuRenderer
    gpu = get_gpu()
    out = []
    base = gbase = None
    for name in a.cases.split(","):
        aniso1 = name.endswith("_aniso1")
        kw, mut = CASES[name[:-7] if aniso1 else name]
        ANISO1[0] = aniso1
        gl_anisotropy_off()
        model = load_model(**kw)
        w, gl = open_gl(model, a.size, mut)
        r = WgpuRenderer(gpu)
        if aniso1:
            r._s_tex = r.oit.s_tex = gpu.device.create_sampler(
                mag_filter="linear", min_filter="linear", mipmap_filter="linear", address_mode_u="repeat",
                address_mode_v="repeat", max_anisotropy=1)
        r.set_model(model)
        wg = wgpu_image(gpu, r, w)
        row = {"case": name, **stats(gl, wg)}
        if name == "static0":
            base = gl
        if name == "ghost_morph0":
            gbase = gl
        ctrl = gbase if name.startswith("ghost") else base
        if ctrl is not None and name not in ("static0", "ghost_morph0"):
            row["gl_change"] = stats(gl, ctrl)["mean"]
        if a.dump:
            from PIL import Image
            Path(a.dump).mkdir(parents=True, exist_ok=True)
            Image.fromarray(gl).save(Path(a.dump) / f"{name}_gl.png")
            Image.fromarray(wg).save(Path(a.dump) / f"{name}_wgpu.png")
            Image.fromarray(np.abs(gl.astype(np.int16) - wg.astype(np.int16)).max(2).clip(0, 255).astype(np.uint8)).save(Path(a.dump) / f"{name}_diff.png")
        out.append(row)
        print(json.dumps(row), flush=True)
        r.release()
        w.close()
    return out


if __name__ == "__main__":
    main()
