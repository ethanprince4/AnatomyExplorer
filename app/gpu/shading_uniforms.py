"""Packs the model viewer's shading uniforms into the bytes of the WGSL `ShadeU` struct (wgsl/shading.wgsl).

Input is a dict {GLSL uniform name: value} exactly as app/viewer/renderer.py sets them through `_U` (floats, ints,
bools, tuples, 1-D numpy vectors, 2-D numpy matrices) and as `u_sh` is written raw (a (9, 3) array).  The field names
of `ShadeU` are the GLSL uniform names, and the layout is parsed from the struct in shading.wgsl so there is a single
source of truth; the WGSL uniform-address-space alignment rules are applied here and checked against a real GPU
round trip in tests/gpu/test_shading_uniforms.py.

2-D arrays are written transposed (column-major), like `_U.__call__`.  Names that are legitimately set on the shaded
programs but are not part of ShadeU (vertex stage inputs, samplers, shadow maps, other passes) are in IGNORED; any
other unknown name raises KeyError so a renamed uniform cannot silently drop out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SHADING_WGSL = Path(__file__).with_name("wgsl") / "shading.wgsl"

# set by the renderer on the shaded programs, not consumed by shade_main
IGNORED = frozenset(
    # vertex stage (vertex.wgsl PartXf)
    ["u_model", "u_nmat", "u_viewproj", "u_anim", "u_anim_t", "u_aw", "u_ag"]
    # textures and samplers (bound as textures in group 1)
    + ["u_ao", "u_spec", "u_tex", "u_items"]
    # shadows are off in the model viewer
    + [f"u_{n}{i}" for n in ("lmat", "ltexel", "lsoft", "shadow") for i in range(3)] + ["u_shadow_on"]
    # other passes of the same programs (OIT, ghosting)
    + ["u_ghost_alpha", "u_ghost", "u_alpha_mul", "u_facing", "u_facing_on"])


@dataclass(frozen=True)
class Field:
    name: str
    wgsl_type: str
    offset: int
    size: int
    align: int
    base: str            # f32 | i32 | u32
    shape: tuple         # () scalar, (n,) vector, (c, r) matrix (columns, rows), (count, n) array of vectors
    stride: int          # array element stride / matrix column stride (0 for scalars and vectors)


def _round_up(x: int, a: int) -> int:
    return (x + a - 1) // a * a


_VEC = re.compile(r"^vec([234])<(f32|i32|u32)>$")
_MAT = re.compile(r"^mat([234])x([234])<f32>$")
_ARR = re.compile(r"^array<vec([234])<(f32|i32|u32)>,\s*(\d+)>$")


def _type_info(t: str):
    """(align, size, base, shape, stride) of a WGSL type in the uniform address space."""
    t = t.replace(" ", "")
    if t in ("f32", "i32", "u32"):
        return 4, 4, t, (), 0
    m = _VEC.match(t)
    if m:
        n = int(m.group(1))
        return (8 if n == 2 else 16), 4 * n, m.group(2), (n,), 0
    m = _MAT.match(t)
    if m:
        c, r = int(m.group(1)), int(m.group(2))
        col_align = 8 if r == 2 else 16
        stride = _round_up(4 * r, col_align)
        return col_align, stride * c, "f32", (c, r), stride
    m = _ARR.match(t)
    if m:
        n, base, count = int(m.group(1)), m.group(2), int(m.group(3))
        stride = _round_up(4 * n, 16)
        return 16, stride * count, base, (count, n), stride
    raise ValueError(f"unsupported ShadeU member type {t!r}")


def parse_layout(source: str | None = None):
    """(fields, total_size) of `struct ShadeU` in shading.wgsl (or in `source`)."""
    text = SHADING_WGSL.read_text(encoding="utf-8") if source is None else source
    text = re.sub(r"//[^\n]*", "", text)
    body = re.search(r"struct\s+ShadeU\s*\{(.*?)\n\}", text, re.S).group(1)
    fields, offset, max_align = [], 0, 1
    for member in body.splitlines():
        member = member.strip().rstrip(",").strip()
        if not member:
            continue
        name, wtype = (x.strip() for x in member.split(":", 1))
        align, size, base, shape, stride = _type_info(wtype)
        offset = _round_up(offset, align)
        fields.append(Field(name, wtype.replace(" ", ""), offset, size, align, base, shape, stride))
        offset += size
        max_align = max(max_align, align)
    return fields, _round_up(offset, max_align)


FIELDS, SIZE = parse_layout()
FIELD_BY_NAME = {f.name: f for f in FIELDS}


def _write(buf: bytearray, f: Field, value) -> None:
    dtype = {"f32": np.float32, "i32": np.int32, "u32": np.uint32}[f.base]
    if not f.shape:
        buf[f.offset:f.offset + 4] = np.asarray(value).astype(dtype).reshape(-1)[:1].tobytes()
        return
    arr = np.asarray(value)
    if len(f.shape) == 1:
        flat = arr.astype(dtype).reshape(-1)
        if flat.size != f.shape[0]:
            raise ValueError(f"{f.name}: expected {f.shape[0]} components, got {flat.size}")
        buf[f.offset:f.offset + 4 * flat.size] = flat.tobytes()
        return
    count, n = f.shape
    if f.wgsl_type.startswith("mat"):
        # a numpy matrix is row-major with column vectors: column j is arr[:, j] -> arr.T[j], as `_U` writes arr.T
        if arr.ndim == 1:
            cols = np.ascontiguousarray(arr.reshape(count, n), dtype=dtype)   # flat column-major data
        elif arr.shape == (n, count):
            cols = np.ascontiguousarray(arr.T, dtype=dtype)   # (count columns, n rows)
        else:
            raise ValueError(f"{f.name}: expected a {n}x{count} matrix, got {arr.shape}")
    else:
        arr = arr.reshape(count, -1)                          # u_sh: (9, 3) written raw (not transposed)
        if arr.shape[0] != count or arr.shape[1] > n:
            raise ValueError(f"{f.name}: expected {count}x<={n}, got {arr.shape}")
        cols = np.zeros((count, n), dtype=dtype)
        cols[:, :arr.shape[1]] = arr
    for i in range(count):
        o = f.offset + i * f.stride
        buf[o:o + 4 * n] = cols[i].tobytes()


def pack_shading_uniforms(values: dict, previous: bytes | bytearray | None = None) -> bytes:
    """ShadeU bytes for {GLSL uniform name: value}.

    `previous` carries GL's sticky uniform state: members absent from `values` keep their bytes from it (zeros
    without it).  Names in IGNORED are accepted and skipped; any other name that is not a ShadeU member raises KeyError.
    """
    buf = bytearray(SIZE) if previous is None else bytearray(previous)
    if len(buf) != SIZE:
        raise ValueError(f"previous buffer is {len(buf)} bytes, ShadeU is {SIZE}")
    for name, value in values.items():
        f = FIELD_BY_NAME.get(name)
        if f is None:
            if name in IGNORED:
                continue
            raise KeyError(f"{name} is not a ShadeU member and not in IGNORED")
        _write(buf, f, value)
    return bytes(buf)
