"""Synthetic scenes for the wgpu frame's morph / animation / texture checks (no library model has any of them).

    glb_bytes(...)   a GLB with a morph-target sphere, an alpha-cut textured sphere and an opaque textured plane
    attach_animation(model, ...)   per-vertex procedural-animation streams (model.anim_vertices) like app/viewer/procedural.py
    anim_frame(model, t)           the (2, n_items, 4) frame state (weights; mode, glow, decay, rate) for cycle phase t
"""
from __future__ import annotations

import io
import json
import struct

import numpy as np


def uv_sphere(nu, nv, radius=1.0, centre=(0.0, 0.0, 0.0), uv_tile=(3.0, 2.0)):
    """(positions, normals, uvs, indices): vertices on a (nu+1) x (nv+1) grid, outward normals."""
    u = np.linspace(0.0, 1.0, nu + 1)
    v = np.linspace(0.0, 1.0, nv + 1)
    uu, vv = np.meshgrid(u, v)
    phi, th = uu * 2 * np.pi, vv * np.pi
    n = np.stack([np.sin(th) * np.cos(phi), np.cos(th), np.sin(th) * np.sin(phi)], axis=-1).reshape(-1, 3)
    pos = n * radius + np.asarray(centre)
    uv = np.stack([uu * uv_tile[0], vv * uv_tile[1]], axis=-1).reshape(-1, 2)
    idx = []
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i
            b = a + 1
            c = a + nu + 1
            d = c + 1
            idx += [a, c, b, b, c, d]
    return pos.astype("<f4"), n.astype("<f4"), uv.astype("<f4"), np.array(idx, dtype="<u4")


def checker_png(size=128, cells=8, holes=True):
    """RGBA PNG: coloured checker; with holes the odd cells carry alpha 0 (alpha-cut MASK material)."""
    from PIL import Image
    y, x = np.mgrid[0:size, 0:size]
    cell = ((x * cells // size) + (y * cells // size)) % 2
    rgb = np.where(cell[..., None] == 0, np.array([220, 90, 40]), np.array([40, 120, 220])).astype(np.uint8)
    rgb = (rgb * (0.6 + 0.4 * (x / size))[..., None]).astype(np.uint8)
    a = np.where(cell == 0, 255, 0 if holes else 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(np.dstack([rgb, a]), "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def glb_bytes(nu=48, nv=32, morph_weight=0.8, alpha_cut=False):
    """alpha_cut=False makes node 1 an opaque textured sphere (the wgpu renderer refuses alpha-cut models).
    Nodes: 0 morph sphere (plain material, vertex colours off), 1 alpha-cut textured sphere (MASK), 2 opaque textured plane
    seen at a grazing angle (mipmaps / anisotropy), 3 plain ball (untextured, the ghost focus)."""
    blobs, views, accs = [], [], []

    def add(arr, target=None, **acc):
        raw = np.ascontiguousarray(arr).tobytes()
        off = sum(len(b) for b in blobs)
        blobs.append(raw + b"\0" * (-len(raw) % 4))
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw), **({"target": target} if target else {})})
        if acc:
            accs.append({"bufferView": len(views) - 1, **acc})
            return len(accs) - 1
        return len(views) - 1

    p0, n0, uv0, i0 = uv_sphere(nu, nv, 0.5, (-0.7, 0.0, 0.0))
    rad = n0
    dpos = (0.35 * rad * np.sin(5.0 * np.arctan2(p0[:, 2], p0[:, 0] + 0.7))[:, None] * np.sin(3.0 * np.arccos(n0[:, 1]))[:, None]).astype("<f4")
    dnrm = (0.5 * np.stack([np.sin(4 * p0[:, 1]), 0 * p0[:, 0], np.cos(4 * p0[:, 1])], axis=1)).astype("<f4")
    p1, n1, uv1, i1 = uv_sphere(nu, nv, 0.5, (0.7, 0.0, 0.0))
    g = np.linspace(-1.0, 1.0, 17)
    gx, gz = np.meshgrid(g, g)
    p2 = np.stack([gx * 1.4, -0.65 + 0 * gx, gz * 1.4], axis=-1).reshape(-1, 3).astype("<f4")
    n2 = np.tile(np.array([0, 1, 0], "<f4"), (len(p2), 1))
    uv2 = np.stack([(gx + 1) * 3.0, (gz + 1) * 3.0], axis=-1).reshape(-1, 2).astype("<f4")
    i2 = []
    for j in range(16):
        for i in range(16):
            a = j * 17 + i
            i2 += [a, a + 17, a + 1, a + 1, a + 17, a + 18]
    i2 = np.array(i2, "<u4")
    p3, n3, uv3, i3 = uv_sphere(24, 16, 0.3, (0.0, 0.7, -0.8))
    meshes = []
    for k, (p, n, uv, ix) in enumerate(((p0, n0, uv0, i0), (p1, n1, uv1, i1), (p2, n2, uv2, i2), (p3, n3, uv3, i3))):
        pa = add(p, 34962, componentType=5126, count=len(p), type="VEC3", min=p.min(0).tolist(), max=p.max(0).tolist())
        na = add(n, 34962, componentType=5126, count=len(n), type="VEC3")
        ua = add(uv, 34962, componentType=5126, count=len(uv), type="VEC2")
        ia = add(ix, 34963, componentType=5125, count=len(ix), type="SCALAR")
        prim = {"attributes": {"POSITION": pa, "NORMAL": na, "TEXCOORD_0": ua}, "indices": ia, "material": 0 if k == 3 else k}
        mesh = {"primitives": [prim]}
        if k == 0:
            da = add(dpos, 34962, componentType=5126, count=len(dpos), type="VEC3", min=dpos.min(0).tolist(), max=dpos.max(0).tolist())
            dn = add(dnrm, 34962, componentType=5126, count=len(dnrm), type="VEC3")
            prim["targets"] = [{"POSITION": da, "NORMAL": dn}]
            mesh["weights"] = [morph_weight]
        meshes.append(mesh)
    img_cut = add(np.frombuffer(checker_png(128, 8, True), np.uint8))
    img_opq = add(np.frombuffer(checker_png(128, 16, False), np.uint8))
    data = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1, 2, 3]}],
        "nodes": [{"name": "Morph sphere", "mesh": 0, "weights": [morph_weight]}, {"name": "Cut sphere", "mesh": 1},
                  {"name": "Textured plane", "mesh": 2}, {"name": "Plain ball", "mesh": 3}],
        "meshes": meshes,
        "materials": [
            {"name": "plain", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.45, 0.4, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.5}},
            {"name": "cut", "alphaMode": "MASK" if alpha_cut else "OPAQUE", "alphaCutoff": 0.5, "doubleSided": True,
             "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 0.6}},
            {"name": "opaque", "pbrMetallicRoughness": {"baseColorTexture": {"index": 1}, "metallicFactor": 0.0, "roughnessFactor": 0.7}}],
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"bufferView": img_cut, "mimeType": "image/png"}, {"bufferView": img_opq, "mimeType": "image/png"}],
        "samplers": [], "accessors": accs, "bufferViews": views,
        "buffers": [{"byteLength": sum(len(b) for b in blobs)}],
    }
    binary = b"".join(blobs)
    js = json.dumps(data).encode("utf-8")
    js += b" " * (-len(js) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(js) + len(binary)) + struct.pack("<I4s", len(js), b"JSON") + js +
            struct.pack("<I4s", len(binary), b"BIN\0") + binary)


def attach_animation(model, items=None, seed=3):
    """model.anim_vertices for the parts of `items` (all when None): four morph targets (float16) and a phase per vertex,
    zero elsewhere, as ViewerModel._build_animation (app/viewer/procedural.py) lays them out."""
    rng = np.random.default_rng(seed)
    n = len(model.vertices)
    buf = np.zeros(n, dtype=[("m", "<f2", (4, 4)), ("phase", "<f4")])
    for p in model.parts:
        if items is not None and p.item not in items:
            continue
        a, b = p.vertex_base, p.vertex_base + p.vertex_count
        pos = model.vertices[a:b, :3]
        for k in range(4):
            buf["m"][a:b, k, :3] = (0.12 * np.sin((k + 2) * pos + 0.7 * k) * (1 + 0.3 * k)).astype(np.float16)
        buf["phase"][a:b] = rng.random(b - a).astype(np.float32)
    model.anim_vertices = buf
    model.animation = type("Anim", (), {"period": 4.0})()
    model.anim_names = [it.key for it in model.items]
    return buf


def anim_frame(model, t, modes=None):
    """(2, n_items, 4): morph weights, and (mode, glow, decay, rate) per item. modes: item -> mode (0 plain, 1 particles, 2 wave)."""
    n = len(model.items)
    f = np.zeros((2, n, 4), np.float32)
    for i in range(n):
        f[0, i] = (np.sin(2 * np.pi * (t + 0.1 * i)) * 0.5 + 0.5, np.cos(2 * np.pi * t) * 0.5 + 0.5, 0.25 * (i + 1), 1.0 - 0.2 * i)
        mode = (modes or {}).get(i, 0)
        f[1, i] = (mode, 0.6 if mode else 0.3, 0.4, 1.7)
    return f
