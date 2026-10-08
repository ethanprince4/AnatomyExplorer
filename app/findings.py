"""Pathology meshes, appended to the atlas so the 3D view can show a finding beside the film that reveals it.

A finding is ordinary geometry - an effusion, a collapsed lung, an enlarged heart - built by tools/build_findings.py
from the normal anatomy, so it sits in the same space and behaves like any other structure: selectable, hideable,
x-rayable, framed and named by a cross-section. They live in their own "Findings" system, off by default, and a
radiology case turns on only the ones it needs.

If data/findings is missing the atlas loads exactly as before.
"""
import json

import numpy as np

VDTYPE = np.dtype([("pos", "<f4", 3), ("nrm", "<f4", 3), ("obj", "<u2"), ("mat", "<u2")])
SYSTEM = {"key": "findings", "name": "Findings (pathology)", "default_visible": False,
          "color": [0.85, 0.55, 0.30]}


class Findings:
    """The extra geometry, held until the viewport asks the dataset for its buffers."""

    def __init__(self, path, base_vertices, spans):
        self.path = path
        self.base_vertices = base_vertices
        self.spans = spans              # (v_start, v_count, structure id, material id) per finding
        self._geo = None

    def geometry(self):
        """(vertex bytes, index bytes) ready to concatenate onto the atlas buffers."""
        if self._geo is None:
            with np.load(self.path / "findings.npz") as z:
                verts = z["verts"].astype(VDTYPE, copy=True)
                tris = z["tris"].astype("<u4") + np.uint32(self.base_vertices)
            # the mesh is built before it knows its place in the atlas: stamp on the ids it ends up with
            for v0, n, sid, mat in self.spans:
                verts["obj"][v0:v0 + n] = sid
                verts["mat"][v0:v0 + n] = mat
            self._geo = verts.tobytes(), tris.tobytes()
        return self._geo


def attach(meta, data_dir):
    """Append the findings to a loaded anatomy.json in place. Returns a Findings, or None if there are none."""
    path = data_dir.parent / "findings"
    index = path / "findings.json"
    if not index.is_file() or not (path / "findings.npz").is_file():
        return None
    try:
        doc = json.loads(index.read_text(encoding="utf-8"))
    except ValueError:
        return None
    records = doc.get("findings") or []
    if not records:
        return None

    mat_base = len(meta["materials"])
    mat_id = {}
    for i, m in enumerate(doc.get("materials", [])):
        mat_id[m["name"]] = mat_base + i
        meta["materials"].append({"name": m["name"], "category": "finding", "color": m["color"],
                                  "alpha": m.get("alpha", 1.0), "distinct": m["color"]})

    subsystems = list(dict.fromkeys(r["subsystem"] for r in records))
    meta["systems"].append(dict(SYSTEM, subsystems=[{"name": s, "default_visible": True} for s in subsystems]))

    sid = len(meta["structures"])
    v_base = meta["counts"]["vertices"]
    i_base = meta["counts"]["triangles"] * 3
    tri_added = 0
    spans = []
    for r in records:
        spans.append((r["v_start"], r["v_count"], sid, mat_id[r["material"]]))
        meta["structures"].append({
            "id": sid, "raw": r["name"], "name": r["name"], "base": r["name"], "side": "", "role": "None",
            "system": "findings", "subsystem": r["subsystem"], "type": "MESH", "def": r["note"],
            "latin": r.get("latin", ""), "ta2": "", "regions": r.get("regions") or ["thorax"],
            "collections": ["Findings", r["subsystem"]],
            "i_start": i_base + r["i_start"], "i_count": r["i_count"],
            "bbox": r["bbox"], "centroid": r["centroid"], "material": mat_id[r["material"]],
        })
        sid += 1
        tri_added += r["i_count"] // 3

    meta["counts"]["vertices"] = v_base + sum(r["v_count"] for r in records)
    meta["counts"]["triangles"] = meta["counts"]["triangles"] + tri_added
    return Findings(path, v_base, spans)
