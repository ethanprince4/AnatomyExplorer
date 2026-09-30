"""Small owned GLB fixtures; no authored model asset is loaded."""
import json
import struct

def write_fixture_model(path):
    """Small self-contained GLB, using only installed NumPy and the stdlib."""
    import numpy as np
    positions = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                          [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype="<f4")
    positions *= (0.25, 0.45, 0.15)
    normals = (positions / np.linalg.norm(positions, axis=1, keepdims=True)).astype("<f4")
    indices = np.array([0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4,
                        3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5], dtype="<u2")
    binary = positions.tobytes() + normals.tobytes() + indices.tobytes()
    data = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}],
            "nodes": [{"name": "Fixture block", "mesh": 0},
                      {"name": "Fixture small block", "mesh": 0, "translation": [0.6, 0.1, 0], "scale": [0.5] * 3}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2}]}],
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": positions.nbytes},
                            {"buffer": 0, "byteOffset": positions.nbytes, "byteLength": normals.nbytes},
                            {"buffer": 0, "byteOffset": positions.nbytes + normals.nbytes, "byteLength": indices.nbytes}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
                           "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
                          {"bufferView": 1, "componentType": 5126, "count": 8, "type": "VEC3"},
                          {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"}]}
    encoded = json.dumps(data).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary)) +
                     struct.pack("<I4s", len(encoded), b"JSON") + encoded +
                     struct.pack("<I4s", len(binary), b"BIN\0") + binary)
