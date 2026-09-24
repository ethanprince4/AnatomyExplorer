"""A small reader for binary glTF (.glb) files: meshes flattened into world space, plus their materials and images.

Only what the viewer draws is read - positions, normals, the first UV set, vertex colours, base colour (metal/rough
or the older spec/gloss extension) and alpha mode. Skins and morph targets are ignored and the scene is taken at its
rest pose. Node transforms are applied, so the result is in the file's own Y-up world.
"""
import json
import struct

import numpy as np

COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
UNSUPPORTED = {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_texture_basisu"}


class GltfError(Exception):
    pass


class Primitive:
    """One drawable piece: triangles of a single material, already in world space."""

    def __init__(self, node, path, pos, nrm, idx, uv, color, material):
        self.node = node              # index of the node that instanced the mesh
        self.path = path              # node names from the scene root down to that node
        self.pos = pos                # (n, 3) float32
        self.nrm = nrm                # (n, 3) float32 or None
        self.idx = idx                # (m, 3) int64
        self.uv = uv                  # (n, 2) float32 or None
        self.color = color            # (n, 4) float32 linear, or None
        self.material = material      # index into Gltf.materials, or None


class Material:
    def __init__(self, raw):
        self.name = raw.get("name", "")
        pbr = raw.get("pbrMetallicRoughness") or {}
        sg = (raw.get("extensions") or {}).get("KHR_materials_pbrSpecularGlossiness")
        if sg is not None:
            self.factor = list(sg.get("diffuseFactor", [1, 1, 1, 1]))
            tex = sg.get("diffuseTexture")
        else:
            self.factor = list(pbr.get("baseColorFactor", [1, 1, 1, 1]))
            tex = pbr.get("baseColorTexture")
        self.texture = tex.get("index") if tex else None
        self.texcoord = tex.get("texCoord", 0) if tex else 0
        self.alpha_mode = raw.get("alphaMode", "OPAQUE")
        trans = (raw.get("extensions") or {}).get("KHR_materials_transmission") or {}
        self.transmission = float(trans.get("transmissionFactor", 0.0))      # glass-like: light passes through
        self.alpha_cutoff = raw.get("alphaCutoff", 0.5)
        self.double_sided = bool(raw.get("doubleSided"))


def _node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]), dtype=np.float64)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    s = np.array(node.get("scale", [1, 1, 1]), dtype=np.float64)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.identity(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


class Gltf:
    def __init__(self, path):
        data = memoryview(path.read_bytes())       # slices of a memoryview are views, not copies
        if data[:4] != b"glTF":
            raise GltfError("not a binary glTF file")
        self.json, self.bin = None, b""
        off = 12
        while off < len(data):
            if off + 8 > len(data):
                raise GltfError("file is truncated")
            length, kind = struct.unpack_from("<II", data, off)
            if off + 8 + length > len(data):
                raise GltfError("file is truncated")
            chunk = data[off + 8:off + 8 + length]
            if kind == 0x4E4F534A:
                self.json = json.loads(bytes(chunk))
            elif kind == 0x004E4942:
                self.bin = chunk
            off += 8 + length
        if self.json is None:
            raise GltfError("no JSON chunk")
        missing = UNSUPPORTED & set(self.json.get("extensionsRequired", []))
        if missing:
            raise GltfError(f"needs {', '.join(sorted(missing))}, which this reader does not decode")
        self.materials = [Material(m) for m in self.json.get("materials", [])]

    # ------------------------------------------------------------------ raw data
    def _view_bytes(self, view_index):
        v = self.json["bufferViews"][view_index]
        if v.get("buffer", 0) != 0:
            raise GltfError("external buffers are not supported")
        start = v.get("byteOffset", 0)
        return self.bin[start:start + v["byteLength"]], v.get("byteStride")

    def accessor(self, index):
        a = self.json["accessors"][index]
        dtype = np.dtype(COMPONENT[a["componentType"]])
        width = WIDTH[a["type"]]
        count = a["count"]
        if "bufferView" in a:
            raw, stride = self._view_bytes(a["bufferView"])
            base = a.get("byteOffset", 0)
            item = dtype.itemsize * width
            end = base + (count - 1) * (stride or item) + item if count else base
            if end > len(raw):
                raise GltfError(f"accessor {index} runs past the end of its buffer view")
            if stride and stride != item:
                rows = np.lib.stride_tricks.as_strided(
                    np.frombuffer(raw, dtype=np.uint8, offset=base), shape=(count, item), strides=(stride, 1))
                out = np.ascontiguousarray(rows).view(dtype).reshape(count, width)
            else:
                out = np.frombuffer(raw, dtype=dtype, count=count * width, offset=base).reshape(count, width)
        else:
            out = np.zeros((count, width), dtype=dtype)
        if "sparse" in a:
            sp = a["sparse"]
            ii = sp["indices"]
            raw, _ = self._view_bytes(ii["bufferView"])
            where = np.frombuffer(raw, dtype=COMPONENT[ii["componentType"]], count=sp["count"],
                                  offset=ii.get("byteOffset", 0))
            vv = sp["values"]
            raw, _ = self._view_bytes(vv["bufferView"])
            vals = np.frombuffer(raw, dtype=dtype, count=sp["count"] * width,
                                 offset=vv.get("byteOffset", 0)).reshape(-1, width)
            out = out.copy()
            out[where] = vals
        if a.get("normalized") and dtype.kind in "iu":
            out = out.astype(np.float32) / float(np.iinfo(dtype).max)
            if dtype.kind == "i":
                out = np.maximum(out, -1.0)
        return out

    def image_bytes(self, texture_index):
        """Encoded bytes (PNG/JPEG/...) of a texture's image, or None."""
        tex = self.json.get("textures", [])[texture_index]
        src = tex.get("source")
        if src is None:
            ext = tex.get("extensions") or {}
            src = next((e.get("source") for e in ext.values() if isinstance(e, dict) and "source" in e), None)
        if src is None:
            return None
        img = self.json["images"][src]
        if "bufferView" in img:
            raw, _ = self._view_bytes(img["bufferView"])
            return bytes(raw)
        uri = img.get("uri", "")
        if uri.startswith("data:"):
            import base64
            return base64.b64decode(uri.split(",", 1)[1])
        return None

    def sampler_repeats(self, texture_index):
        tex = self.json.get("textures", [])[texture_index]
        s = self.json.get("samplers", [])[tex["sampler"]] if "sampler" in tex else {}
        return s.get("wrapS", 10497) == 10497, s.get("wrapT", 10497) == 10497

    # ------------------------------------------------------------------ scene
    def scene_roots(self):
        scenes = self.json.get("scenes")
        if not scenes:                          # no scene: every node that is nobody's child is a root
            nodes = self.json.get("nodes", [])
            children = {c for n in nodes for c in n.get("children", [])}
            return [i for i in range(len(nodes)) if i not in children]
        return scenes[self.json.get("scene", 0)].get("nodes", [])

    def walk(self):
        """(node index, world matrix, [names from the root]) for every node in the default scene."""
        nodes = self.json.get("nodes", [])
        stack = [(n, np.identity(4), []) for n in reversed(self.scene_roots())]
        while stack:
            i, parent, path = stack.pop()
            node = nodes[i]
            m = parent @ _node_matrix(node)
            here = path + [node.get("name", "")]
            yield i, m, here
            for c in reversed(node.get("children", [])):
                stack.append((c, m, here))

    def primitives(self, keep=None):
        """Every triangle primitive in world space. `keep(path)` can drop whole branches (e.g. animation frames)."""
        nodes = self.json.get("nodes", [])
        meshes = self.json.get("meshes", [])
        out = []
        for i, m, path in self.walk():
            node = nodes[i]
            if "mesh" not in node or (keep is not None and not keep(path)):
                continue
            lin = m[:3, :3]
            normal_m = np.linalg.inv(lin).T if abs(np.linalg.det(lin)) > 1e-12 else lin
            flip = np.linalg.det(lin) < 0
            for prim in meshes[node["mesh"]]["primitives"]:
                mode = prim.get("mode", 4)
                if mode not in (4, 5, 6):
                    continue                      # points and lines have nothing to shade
                attrs = prim["attributes"]
                if "POSITION" not in attrs:
                    continue
                pos = self.accessor(attrs["POSITION"]).astype(np.float64)
                if "indices" in prim:
                    idx = self.accessor(prim["indices"]).astype(np.int64).ravel()
                else:
                    idx = np.arange(len(pos), dtype=np.int64)
                if mode == 5:
                    k = np.arange(len(idx) - 2)
                    tri = np.stack([idx[k], idx[k + 1], idx[k + 2]], 1)
                    tri[1::2] = tri[1::2][:, [1, 0, 2]]
                elif mode == 6:
                    k = np.arange(1, len(idx) - 1)
                    tri = np.stack([np.full_like(k, idx[0]), idx[k], idx[k + 1]], 1)
                else:
                    tri = idx[:len(idx) - len(idx) % 3].reshape(-1, 3)
                if len(tri) == 0:
                    continue
                if tri.min() < 0 or tri.max() >= len(pos):
                    raise GltfError(f"mesh {node['mesh']} has indices past its vertices")
                if flip:
                    tri = tri[:, [0, 2, 1]]
                nrm = None
                if "NORMAL" in attrs:
                    nrm = self.accessor(attrs["NORMAL"]).astype(np.float64)
                mat = prim.get("material")
                texcoord = self.materials[mat].texcoord if mat is not None and mat < len(self.materials) else 0
                uv = self.accessor(attrs[f"TEXCOORD_{texcoord}"]).astype(np.float32) \
                    if f"TEXCOORD_{texcoord}" in attrs else None
                color = None
                if "COLOR_0" in attrs:
                    c = self.accessor(attrs["COLOR_0"]).astype(np.float32)
                    if c.shape[1] == 3:
                        c = np.concatenate([c, np.ones((len(c), 1), np.float32)], 1)
                    color = c
                # primitives may index into one shared vertex array: keep only the vertices this one uses
                used = np.zeros(len(pos), dtype=bool)
                used[tri.ravel()] = True
                if not used.all():
                    remap = np.cumsum(used) - 1
                    tri = remap[tri]
                    pos = pos[used]
                    nrm = nrm[used] if nrm is not None else None
                    uv = uv[used] if uv is not None else None
                    color = color[used] if color is not None else None
                wpos = (pos @ lin.T + m[:3, 3]).astype(np.float32)
                if nrm is not None:
                    n = nrm @ normal_m.T
                    nrm = (n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)).astype(np.float32)
                out.append(Primitive(i, path, wpos, nrm, tri, uv, color, mat))
        return out
