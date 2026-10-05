"""A self-contained glTF 2.0 / GLB reader (numpy only).

Reads the GLB header and its JSON and BIN chunks (or a .gltf with data: URIs or sibling .bin files), nodes and
their transforms, meshes and triangle primitives, accessors (strided, normalised and sparse), morph targets,
animations, materials with the common KHR material extensions, extras, custom ``_`` attributes and embedded
images. Nothing here touches the network: external URIs are only read from the file's own folder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..load_control import checkpoint
from ..gltf_data import (Accessors as _Accessors, GltfError, read_container as _read_container,
                         load_buffers as _load_buffers, read_uri, scene_topology)


@dataclass
class Material:
    name: str = ""
    base_colour: tuple = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.5
    emissive: tuple = (0.0, 0.0, 0.0)
    emissive_strength: float = 1.0
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float = 0.5
    double_sided: bool = False
    ior: float = 1.5
    specular: float = 1.0
    specular_colour: tuple = (1.0, 1.0, 1.0)
    transmission: float = 0.0
    thickness: float = 0.0
    attenuation_colour: tuple = (1.0, 1.0, 1.0)
    clearcoat: float = 0.0
    clearcoat_roughness: float = 0.0
    sheen_colour: tuple = (0.0, 0.0, 0.0)
    sheen_roughness: float = 0.0
    base_colour_texture: int | None = None      # image index
    extras: dict = field(default_factory=dict)


@dataclass
class Primitive:
    attributes: dict          # semantic -> np.ndarray (N, k) float32 (or int for JOINTS)
    indices: np.ndarray       # (M,) uint32 triangle list
    material: int | None
    targets: list             # [{"POSITION": (N,3), "NORMAL": (N,3)}]


@dataclass
class Mesh:
    name: str
    primitives: list
    weights: list
    target_names: list
    extras: dict


@dataclass
class Node:
    name: str
    children: list
    mesh: int | None
    translation: np.ndarray
    rotation: np.ndarray     # quaternion x, y, z, w
    scale: np.ndarray
    matrix: np.ndarray | None
    extras: dict
    parent: int | None = None


@dataclass
class Channel:
    node: int
    path: str                # translation | rotation | scale | weights
    times: np.ndarray        # (K,)
    values: np.ndarray       # (K, n)
    interpolation: str


@dataclass
class Animation:
    name: str
    channels: list
    t_start: float
    t_end: float


@dataclass
class Document:
    path: Path
    json: dict
    nodes: list
    meshes: list
    materials: list
    animations: list
    scene_roots: list
    images: list              # raw encoded bytes (PNG/JPEG) per image
    image_mime: list


# --------------------------------------------------------------------------------------------------

def _material(m: dict) -> Material:
    pbr = m.get("pbrMetallicRoughness", {})
    ext = m.get("extensions", {})
    out = Material(
        name=m.get("name", ""),
        base_colour=tuple(pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0))),
        metallic=float(pbr.get("metallicFactor", 1.0)),
        roughness=float(pbr.get("roughnessFactor", 1.0)),
        emissive=tuple(m.get("emissiveFactor", (0.0, 0.0, 0.0))),
        alpha_mode=m.get("alphaMode", "OPAQUE"),
        alpha_cutoff=float(m.get("alphaCutoff", 0.5)),
        double_sided=bool(m.get("doubleSided", False)),
        extras=m.get("extras", {}) or {},
    )
    if "baseColorTexture" in pbr:
        out.base_colour_texture = pbr["baseColorTexture"].get("index")
    e = ext.get("KHR_materials_emissive_strength")
    if e:
        out.emissive_strength = float(e.get("emissiveStrength", 1.0))
    e = ext.get("KHR_materials_ior")
    if e:
        out.ior = float(e.get("ior", 1.5))
    e = ext.get("KHR_materials_specular")
    if e:
        out.specular = float(e.get("specularFactor", 1.0))
        out.specular_colour = tuple(e.get("specularColorFactor", (1.0, 1.0, 1.0)))
    e = ext.get("KHR_materials_transmission")
    if e:
        out.transmission = float(e.get("transmissionFactor", 0.0))
    e = ext.get("KHR_materials_volume")
    if e:
        out.thickness = float(e.get("thicknessFactor", 0.0))
        out.attenuation_colour = tuple(e.get("attenuationColor", (1.0, 1.0, 1.0)))
    e = ext.get("KHR_materials_clearcoat")
    if e:
        out.clearcoat = float(e.get("clearcoatFactor", 0.0))
        out.clearcoat_roughness = float(e.get("clearcoatRoughnessFactor", 0.0))
    e = ext.get("KHR_materials_sheen")
    if e:
        out.sheen_colour = tuple(e.get("sheenColorFactor", (0.0, 0.0, 0.0)))
        out.sheen_roughness = float(e.get("sheenRoughnessFactor", 0.0))
    return out


def load(path) -> Document:
    path = Path(path)
    gltf, binchunk = _read_container(path)
    ver = str(gltf.get("asset", {}).get("version", "2.0"))
    if not ver.startswith("2"):
        raise GltfError(f"glTF version {ver}; only 2.x is supported")
    roots, parents = scene_topology(gltf)
    buffers = _load_buffers(gltf, binchunk, path.parent)
    acc = _Accessors(gltf, buffers)

    materials = [_material(m) for m in gltf.get("materials", [])]

    meshes = []
    for mi, m in enumerate(gltf.get("meshes", [])):
        checkpoint()
        prims = []
        for p in m.get("primitives", []):
            mode = p.get("mode", 4)
            if mode not in (4, 5, 6):
                continue                      # points and lines are not drawn
            attrs = {}
            for sem, ai in p.get("attributes", {}).items():
                attrs[sem] = acc.get(ai, as_float=not sem.startswith("JOINTS"))
            if "POSITION" not in attrs:
                continue
            n = len(attrs["POSITION"])
            if "indices" in p:
                idx = acc.indices(p["indices"], n).astype(np.uint32)
            else:
                idx = np.arange(n, dtype=np.uint32)
            if attrs["POSITION"].shape[1] != 3 or not np.isfinite(attrs["POSITION"]).all():
                raise GltfError(f"mesh {mi} positions must be finite VEC3 values")
            if any(len(value) != n for value in attrs.values()):
                raise GltfError(f"mesh {mi} attributes have inconsistent vertex counts")
            if len(idx) and idx.max() >= n:
                raise GltfError(f"mesh {mi} has indices past its vertices")
            if len(idx) < 3:
                continue
            if mode == 4 and len(idx) % 3:
                raise GltfError(f"mesh {mi} triangle indices are not a multiple of three")
            if mode == 5:                     # triangle strip -> list
                k = len(idx) - 2
                tri = np.stack([idx[:k], idx[1:k + 1], idx[2:k + 2]], 1)
                tri[1::2] = tri[1::2][:, [1, 0, 2]]
                idx = tri.reshape(-1)
            elif mode == 6:                   # fan -> list
                k = len(idx) - 2
                idx = np.stack([np.full(k, idx[0]), idx[1:k + 1], idx[2:k + 2]], 1).reshape(-1)
            targets = []
            for t in p.get("targets", []):
                targets.append({sem: acc.get(ai) for sem, ai in t.items()})
            prims.append(Primitive(attrs, idx, p.get("material"), targets))
        extras = m.get("extras", {}) or {}
        meshes.append(Mesh(m.get("name", f"mesh{mi}"), prims, list(m.get("weights", [])),
                           list(extras.get("targetNames", [])), extras))

    nodes = []
    for i, nd in enumerate(gltf.get("nodes", [])):
        checkpoint()
        mat = None
        if "matrix" in nd:
            mat = np.array(nd["matrix"], dtype=np.float64).reshape(4, 4).T
        nodes.append(Node(
            name=nd.get("name", f"node{i}"), children=list(nd.get("children", [])), mesh=nd.get("mesh"),
            translation=np.array(nd.get("translation", (0, 0, 0)), dtype=np.float64),
            rotation=np.array(nd.get("rotation", (0, 0, 0, 1)), dtype=np.float64),
            scale=np.array(nd.get("scale", (1, 1, 1)), dtype=np.float64),
            matrix=mat, extras=nd.get("extras", {}) or {}))
    for i, node in enumerate(nodes):
        node.parent = parents[i]

    animations = []
    for ai, a in enumerate(gltf.get("animations", [])):
        chans = []
        t0, t1 = float("inf"), float("-inf")
        for c in a.get("channels", []):
            tgt = c.get("target", {})
            if "node" not in tgt:
                continue
            s = a["samplers"][c["sampler"]]
            times = acc.get(s["input"]).reshape(-1).astype(np.float64)
            vals = acc.get(s["output"]).astype(np.float64)
            interp = s.get("interpolation", "LINEAR")
            if tgt["path"] == "weights":
                vals = vals.reshape(len(times) * (3 if interp == "CUBICSPLINE" else 1), -1)
            if interp == "CUBICSPLINE":       # keep the value, drop the tangents
                vals = vals.reshape(len(times), 3, -1)[:, 1, :]
            else:
                vals = vals.reshape(len(times), -1)
            chans.append(Channel(tgt["node"], tgt["path"], times, vals, interp))
            if len(times):
                t0, t1 = min(t0, times[0]), max(t1, times[-1])
        if chans:
            animations.append(Animation(a.get("name", f"animation{ai}"), chans, t0, t1))

    images, mimes = [], []
    for im in gltf.get("images", []):
        checkpoint()
        if "bufferView" in im:
            raw, _ = acc.view_bytes(im["bufferView"])
            images.append(bytes(raw))
        elif im.get("uri"):
            images.append(read_uri(im["uri"], path.parent, missing_ok=True))
        else:
            images.append(b"")
        mimes.append(im.get("mimeType", ""))
    # textures -> image indices
    textures = gltf.get("textures", [])
    for m in materials:
        if m.base_colour_texture is not None and m.base_colour_texture < len(textures):
            m.base_colour_texture = textures[m.base_colour_texture].get("source")
        else:
            m.base_colour_texture = None

    return Document(path, gltf, nodes, meshes, materials, animations, roots, images, mimes)


# --------------------------------------------------------------------------------------------------
# Transform helpers

def quat_to_mat3(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], dtype=np.float64)


def trs_matrix(t, r, s):
    m = np.eye(4)
    m[:3, :3] = quat_to_mat3(r) * np.asarray(s)[None, :]
    m[:3, 3] = t
    return m


def slerp(q0, q1, f):
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + f * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - f) * th) * q0 + np.sin(f * th) * q1) / np.sin(th)


def sample_channel(ch: Channel, t: float):
    ts = ch.times
    if len(ts) == 0:
        return None
    if t <= ts[0]:
        return ch.values[0].copy()
    if t >= ts[-1]:
        return ch.values[-1].copy()
    i = int(np.searchsorted(ts, t, side="right")) - 1
    if ch.interpolation == "STEP":
        return ch.values[i].copy()
    f = (t - ts[i]) / max(ts[i + 1] - ts[i], 1e-12)
    if ch.path == "rotation":
        return slerp(ch.values[i], ch.values[i + 1], f)
    return ch.values[i] * (1 - f) + ch.values[i + 1] * f
