"""Validated glTF bytes shared by the authored and downloaded model readers.

This module owns container framing, local resource access, accessor decoding and
scene topology. Callers keep their distinct materials, naming and transforms.
Decoded accessors are cached, read-only arrays. No network access is performed;
external resources must resolve inside the selected model's directory.
"""
from __future__ import annotations

from .load_control import checkpoint

import base64
import binascii
import json
import struct
from collections import deque
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlsplit

import numpy as np

GLB_MAGIC = b"glTF"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
UNSUPPORTED = {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_texture_basisu"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
# Bound even a sparse/zero-filled accessor whose count is not backed by bytes.
MAX_ACCESSOR_BYTES = 512 * 1024 * 1024


class GltfError(Exception):
    """An import could not be safely decoded; the current scene remains usable."""


def _uint(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise GltfError(f"{label} must be an integer >= {minimum}")
    return value


def _at(values, index, label):
    index = _uint(index, label)
    if index >= len(values):
        raise GltfError(f"{label} {index} is out of range")
    return values[index]


def read_container(path, *, binary_only=False):
    checkpoint()
    data = Path(path).read_bytes()
    checkpoint()
    try:
        if data[:4] != GLB_MAGIC:
            if binary_only:
                raise GltfError("not a binary glTF file")
            doc, binary = json.loads(data.decode("utf-8-sig")), None
        else:
            if len(data) < 20:
                raise GltfError("file is shorter than a GLB header")
            _, version, length = struct.unpack_from("<4sII", data)
            if version != 2:
                raise GltfError(f"GLB version {version}; only 2 is supported")
            if length != len(data):
                raise GltfError("GLB declared length does not match the file")
            offset, doc, binary = 12, None, None
            while offset < length:
                if offset + 8 > length:
                    raise GltfError("truncated GLB chunk header")
                size, kind = struct.unpack_from("<II", data, offset)
                end = offset + 8 + size
                if size % 4 or end > length:
                    raise GltfError("invalid GLB chunk length")
                chunk = memoryview(data)[offset + 8:end]
                if offset == 12 and kind != CHUNK_JSON:
                    raise GltfError("the first GLB chunk must be JSON")
                if kind == CHUNK_JSON:
                    if doc is not None:
                        raise GltfError("duplicate GLB JSON chunk")
                    doc = json.loads(bytes(chunk).decode("utf-8"))
                elif kind == CHUNK_BIN:
                    if binary is not None:
                        raise GltfError("duplicate GLB BIN chunk")
                    binary = chunk
                offset = end
            if doc is None:
                raise GltfError("GLB has no JSON chunk")
        if not isinstance(doc, dict):
            raise GltfError("glTF JSON must be an object")
        version = str(doc.get("asset", {}).get("version", ""))
        if version != "2.0":
            raise GltfError(f"glTF version {version!r}; only 2.0 is supported")
        missing = UNSUPPORTED & set(doc.get("extensionsRequired", []))
        if missing:
            raise GltfError(f"needs {', '.join(sorted(missing))}, which this reader does not decode")
        return doc, binary
    except (UnicodeError, ValueError, TypeError, AttributeError) as exc:
        raise GltfError(f"invalid glTF container: {exc}") from exc


def read_uri(uri, folder, *, missing_ok=False):
    if not isinstance(uri, str):
        raise GltfError("resource URI must be a string")
    if uri.startswith("data:"):
        header, separator, data = uri.partition(",")
        if not separator or not header.endswith(";base64"):
            raise GltfError("only base64 data URIs are supported")
        try:
            return base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise GltfError("invalid base64 resource") from exc
    parts = urlsplit(uri)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        raise GltfError("resource URI must be a local relative path")
    name = unquote(parts.path, errors="strict")
    # Apply Windows drive/UNC rules on every OS, including when reviewing on Linux.
    if not name or "\0" in name or "\\" in name or Path(name).is_absolute() or PureWindowsPath(name).drive:
        raise GltfError("resource URI must be a local relative path")
    folder = Path(folder).resolve()
    path = (folder / name).resolve()
    if not path.is_relative_to(folder):
        raise GltfError("resource URI escapes the model directory")
    try:
        checkpoint()
        data = path.read_bytes()
        checkpoint()
        return data
    except FileNotFoundError:
        if missing_ok:
            return b""
        raise


def load_buffers(gltf, binchunk, folder):
    out = []
    for i, record in enumerate(gltf.get("buffers", [])):
        checkpoint()
        size = _uint(record.get("byteLength"), f"buffer {i} byteLength")
        uri = record.get("uri")
        if uri is None:
            if i != 0 or binchunk is None:
                raise GltfError(f"buffer {i} has no URI or matching BIN chunk")
            raw = binchunk
        else:
            raw = memoryview(read_uri(uri, folder))
        if len(raw) < size:
            raise GltfError(f"buffer {i} is shorter than its declared length")
        out.append(raw[:size])  # chunk padding is not addressable accessor data
    return out


class Accessors:
    """Typed read-only arrays, validated before allocation or construction of views."""

    def __init__(self, gltf, buffers):
        self.g = gltf
        self.buffers = buffers
        self.cache = {}

    def view_bytes(self, index):
        view = _at(self.g.get("bufferViews", []), index, "bufferView")
        raw = _at(self.buffers, view.get("buffer"), "buffer")
        offset = _uint(view.get("byteOffset", 0), "bufferView byteOffset")
        size = _uint(view.get("byteLength"), "bufferView byteLength")
        if offset + size > len(raw):
            raise GltfError("bufferView runs past its buffer")
        stride = view.get("byteStride")
        if stride is not None:
            _uint(stride, "byteStride", 4)
            if stride > 252 or stride % 4:
                raise GltfError("byteStride must be a multiple of 4 between 4 and 252")
        return raw[offset:offset + size], stride

    def _dense(self, record, count, kind, dtype):
        width = NCOMP[kind]
        if "bufferView" not in record:
            if record.get("byteOffset", 0):
                raise GltfError("an accessor without a bufferView cannot have a byteOffset")
            return np.zeros((count, width), dtype=dtype)
        raw, stride = self.view_bytes(record["bufferView"])
        offset = _uint(record.get("byteOffset", 0), "accessor byteOffset")
        view = self.g["bufferViews"][record["bufferView"]]
        if (offset + view.get("byteOffset", 0)) % dtype.itemsize:
            raise GltfError("accessor is not aligned to its component size")
        rows = int(kind[-1]) if kind.startswith("MAT") else width
        columns = rows if kind.startswith("MAT") else 1
        column_stride = ((rows * dtype.itemsize + 3) // 4) * 4 if columns > 1 else rows * dtype.itemsize
        element_stride = columns * column_stride
        element_end = (columns - 1) * column_stride + rows * dtype.itemsize
        stride = stride or element_stride
        if stride < element_stride or stride % dtype.itemsize:
            raise GltfError("accessor byteStride is smaller than its element or misaligned")
        end = offset + (count - 1) * stride + element_end if count else offset
        if end > len(raw):
            raise GltfError("accessor runs past the end of its buffer view")
        # ndarray(buffer=...) checks bounds too, unlike as_strided. Matrix column
        # padding is preserved by strides and removed only in the returned copy.
        data = np.ndarray((count, columns, rows), dtype=dtype, buffer=raw,
                          offset=offset, strides=(stride, column_stride, dtype.itemsize))
        return data.reshape(count, width)

    def get(self, index, as_float=True, *, normalize=None):
        checkpoint()
        _uint(index, "accessor")
        normalize = as_float if normalize is None else normalize
        key = (index, as_float, normalize)
        if key in self.cache:
            return self.cache[key]
        try:
            record = _at(self.g.get("accessors", []), index, "accessor")
            dtype = np.dtype(COMPONENT[record["componentType"]]).newbyteorder("<")
            kind = record["type"]
            width = NCOMP[kind]
            count = _uint(record["count"], "accessor count", 1)
            if count * width * max(dtype.itemsize, 4) > MAX_ACCESSOR_BYTES:
                raise GltfError("decoded accessor exceeds the 512 MiB import limit")
            data = self._dense(record, count, kind, dtype).copy()
            sparse = record.get("sparse")
            if sparse:
                size = _uint(sparse["count"], "sparse count", 1)
                if size > count:
                    raise GltfError("sparse count exceeds accessor count")
                indices = sparse["indices"]
                if indices["componentType"] not in (5121, 5123, 5125):
                    raise GltfError("sparse indices must be unsigned integers")
                idx_dtype = np.dtype(COMPONENT[indices["componentType"]]).newbyteorder("<")
                where = self._dense(indices, size, "SCALAR", idx_dtype).reshape(-1)
                if np.any(where >= count) or (len(where) > 1 and np.any(where[1:] <= where[:-1])):
                    raise GltfError("sparse indices must increase strictly within the accessor")
                values = self._dense(sparse["values"], size, kind, dtype)
                data[where] = values
            if normalize and record.get("normalized") and dtype.kind in "iu":
                if record["componentType"] == 5125:
                    raise GltfError("unsigned int accessors cannot be normalized")
                data = np.maximum(data.astype(np.float32) / np.iinfo(dtype).max, -1.0)
            elif as_float:
                data = data.astype(np.float32, copy=False)
            data.flags.writeable = False
            self.cache[key] = data
            return data
        except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
            raise GltfError(f"invalid accessor {index}: {exc}") from exc

    def indices(self, index, vertex_count):
        """Unsigned scalar triangle/strip/fan indices, checked before GPU upload."""
        record = _at(self.g.get("accessors", []), index, "indices accessor")
        if (record.get("type") != "SCALAR" or record.get("componentType") not in (5121, 5123, 5125)
                or record.get("normalized", False)):
            raise GltfError("primitive indices must be non-normalized unsigned SCALAR values")
        indices = self.get(index, as_float=False).reshape(-1)
        if len(indices) and indices.max() >= vertex_count:
            raise GltfError("primitive has indices past its vertices")
        return indices


def scene_topology(gltf):
    """Validate the entire strict forest; return selected roots and parent indices."""
    nodes = gltf.get("nodes", [])
    parents = [None] * len(nodes)
    for i, node in enumerate(nodes):
        checkpoint()
        if "mesh" in node:
            _at(gltf.get("meshes", []), node["mesh"], "node mesh")
        for child in node.get("children", []):
            _at(nodes, child, "child node")
            if parents[child] is not None:
                raise GltfError("a scene node cannot have multiple parents or duplicate edges")
            parents[child] = i
    pending = deque(i for i, parent in enumerate(parents) if parent is None)
    visited = 0
    while pending:
        i = pending.popleft()
        visited += 1
        pending.extend(nodes[i].get("children", []))
    if visited != len(nodes):
        raise GltfError("scene node hierarchy contains a cycle")
    scenes = gltf.get("scenes", [])
    roots = list(_at(scenes, gltf.get("scene", 0), "scene").get("nodes", [])) if scenes else [
        i for i, parent in enumerate(parents) if parent is None]
    for root in roots:
        _at(nodes, root, "scene root")
        if parents[root] is not None:
            raise GltfError("a scene root cannot also be a child")
    if len(set(roots)) != len(roots):
        raise GltfError("duplicate scene roots")
    return roots, parents
