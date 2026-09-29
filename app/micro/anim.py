"""Animation for micro models: morph targets, particle flow and glow, evaluated on the GPU.

A model animates through two kinds of data:

* per vertex, built with the model and cached next to it (data/micro_cache/<id>.anim.npz): up to four morph
  targets (displacements from the rest position) and one phase in 0..1. A builder attaches them to a part as
  ``part.anim = {"morph": (n, k, 3), "phase": (n,)}``, in the vertex order of ``part.mesh.arrays()``;
* per part, evaluated every frame on the CPU from the model's :class:`Animation`: the four morph weights, and a
  mode with a glow strength. That is two texels per part, so a frame uploads a few kilobytes however large the
  model is - the vertex buffers never change.

The vertex shader (shaders.GEOMETRY_VS) then places every vertex at rest + sum(weight_k * morph_k), and in

* MODE_MORPH uses the part's four weights as they are (a heart chamber contracting, a valve swinging open);
* MODE_FLOW runs each vertex on its own clock, tau = fract(cycle * rate + phase), with weights (tau, tau^2,
  pulse(tau), w3): morph 0 and 1 are the linear and quadratic terms of a curved path and morph 2 pulls the
  vertex onto its particle's centre, so particles ride along a path, appearing and vanishing at its ends;
* MODE_WAVE adds a travelling glow: each vertex lights up when the cycle passes its phase (its activation time)
  and fades with the part's decay constant - an impulse running along the conduction system.

Picking, cut-aways and caps all run through the same vertex shader, so they follow the moving geometry.
"""
import numpy as np

from .base import MicroModel

N_TARGETS = 4
MODE_MORPH, MODE_FLOW, MODE_WAVE = 0, 1, 2
ANIM_FORMAT = "4f2 4f2 4f2 4f2 1f"
ANIM_ATTRS = ("in_m0", "in_m1", "in_m2", "in_m3", "in_phase")
ANIM_STRIDE = 4 * 8 + 4


# ------------------------------------------------------------------------------------------------ time curves
def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def ramp(t, t0, t1):
    """0 before t0, 1 after t1, smooth in between."""
    return float(smooth((t - t0) / max(t1 - t0, 1e-9)))


def window(t, up0, up1, down0, down1):
    """Rises over [up0, up1], holds, falls over [down0, down1]; times may wrap past 1 (a cyclic window)."""
    t = t % 1.0

    def at(tt):
        return ramp(tt, up0, up1) * (1.0 - ramp(tt, down0, down1))
    return max(at(t), at(t + 1.0), at(t - 1.0))


class Track:
    """What one part does over the cycle. `weights(t)` -> up to four morph weights, `glow` a strength or a
    function of t; t is the cycle phase in 0..1."""

    def __init__(self, weights=None, glow=0.0, mode=MODE_MORPH, decay=0.08, rate=1.0):
        self.weights = weights
        self.glow = glow
        self.mode = mode
        self.decay = decay
        self.rate = rate


class Animation:
    """A looping animation: its period in seconds, the tracks of the parts that move (matched by exact name,
    else by the first key that the name starts with) and a default track for every other part. `phases` names
    the stages of the cycle as (start, end, label), for the viewer's readout."""

    def __init__(self, period, tracks=None, default=None, phases=(), title="Animation", speeds=(1.0, 0.5, 0.25, 0.1)):
        self.period = float(period)
        self.tracks = dict(tracks or {})
        self.default = default
        self.phases = list(phases)
        self.title = title
        self.speeds = tuple(speeds)

    def track_for(self, name):
        if name in self.tracks:
            return self.tracks[name]
        for key, tr in self.tracks.items():
            if name.startswith(key):
                return tr
        return self.default

    def phase_label(self, t):
        t = t % 1.0
        for a, b, label in self.phases:
            if a <= t < b or (a > b and (t >= a or t < b)):
                return label
        return ""

    def frame(self, names, t):
        """Per-part texels for cycle phase t: (2, n, 4) float32 - row 0 the weights, row 1 (mode, glow, decay,
        rate)."""
        out = np.zeros((2, len(names), 4), np.float32)
        for i, name in enumerate(names):
            tr = self.track_for(name)
            if tr is None:
                continue
            if tr.weights is not None:
                w = np.asarray(tr.weights(t), np.float32).ravel()[:N_TARGETS]
                out[0, i, :len(w)] = w
            g = tr.glow(t) if callable(tr.glow) else tr.glow
            out[1, i] = (tr.mode, g, tr.decay, tr.rate)
        return out


# ------------------------------------------------------------------------------------------------ model + cache
def _anim_path(model_id):
    from .cache import CACHE_DIR
    return CACHE_DIR / f"{model_id}.anim.npz"


def save_anim(model_id, parts, digest):
    arrays = {"digest": np.frombuffer(digest.encode(), np.uint8)}
    for i, p in enumerate(parts):
        a = getattr(p, "anim", None)
        if a:
            arrays[f"m{i}"] = np.asarray(a["morph"], np.float16)
            arrays[f"f{i}"] = np.asarray(a["phase"], np.float32)
    path = _anim_path(model_id)
    tmp = path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(path)


def load_anim(model_id, parts, digest):
    path = _anim_path(model_id)
    if not path.exists():
        return False
    try:
        with np.load(path) as z:
            if bytes(z["digest"]).decode() != digest:
                return False
            for i, p in enumerate(parts):
                if f"m{i}" in z:
                    p.anim = {"morph": z[f"m{i}"].astype(np.float32), "phase": z[f"f{i}"]}
        return True
    except (OSError, ValueError, KeyError):
        return False


class AnimatedModel(MicroModel):
    """A micro model with an :class:`Animation`. Its per-vertex animation data is built with the parts and cached
    beside them under the same source digest."""

    def __init__(self, *args, animation=None, **kw):
        super().__init__(*args, **kw)
        self.animation = animation

    def parts(self):
        if self._parts is None:
            from .cache import load_parts, save_parts, source_digest
            digest = source_digest(self)
            parts = load_parts(self.id, digest)
            if parts is not None and not load_anim(self.id, parts, digest):
                parts = None
            if parts is None:
                parts = self.build()
                try:
                    save_parts(self.id, parts, digest)
                    save_anim(self.id, parts, digest)
                except OSError:
                    pass
            self._parts = parts
        return self._parts
