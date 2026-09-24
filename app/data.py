import json
from collections import defaultdict
from pathlib import Path

import numpy as np


class Dataset:
    """Loads the prebuilt anatomy dataset (see tools/build_dataset.py)."""

    def __init__(self, data_dir: Path):
        self.dir = data_dir
        meta = json.loads((data_dir / "anatomy.json").read_text(encoding="utf-8"))
        from .findings import attach as attach_findings
        self.findings = attach_findings(meta, data_dir)   # pathology meshes, if they have been built
        self.attribution = meta["attribution"]
        self.systems = meta["systems"]
        self.system_index = {s["key"]: i for i, s in enumerate(self.systems)}
        self.regions = meta["regions"]
        self.region_bit = {r["key"]: 1 << i for i, r in enumerate(self.regions)}
        self.materials = meta["materials"]
        self.structures = meta["structures"]
        self.tree_roots = meta["tree"]["roots"]
        self.nodes = meta["tree"]["nodes"]
        self.landmarks = meta["landmarks"]
        self.scene_bbox = np.array(meta["scene_bbox"], dtype=np.float64)
        self.counts = meta["counts"]
        self._definitions = None

        n = len(self.structures)
        self.n = n
        self.bbox_min = np.array([s["bbox"][0] for s in self.structures], dtype=np.float64)
        self.bbox_max = np.array([s["bbox"][1] for s in self.structures], dtype=np.float64)
        self.centroid = np.array([s["centroid"] for s in self.structures], dtype=np.float64)
        self.system_of = np.array([self.system_index[s["system"]] for s in self.structures], dtype=np.int32)
        self.region_mask = np.array(
            [sum(self.region_bit[r] for r in s["regions"]) for s in self.structures], dtype=np.int64)
        self.subsystems = []
        sub_ids = {}
        sub_of = np.full(n, -1, dtype=np.int32)
        for sid, s in enumerate(self.structures):
            if s["subsystem"]:
                key = (s["system"], s["subsystem"])
                if key not in sub_ids:
                    sub_ids[key] = len(self.subsystems)
                    self.subsystems.append(key)
                sub_of[sid] = sub_ids[key]
        self.subsystem_of = sub_of
        self.subsystem_index = sub_ids
        order = {(s["key"], x["name"]): (i, j) for i, s in enumerate(self.systems) for j, x in enumerate(s["subsystems"])}
        remap = sorted(range(len(self.subsystems)), key=lambda k: order.get(self.subsystems[k], (99, 99)))
        new_index = {old: new for new, old in enumerate(remap)}
        self.subsystems = [self.subsystems[k] for k in remap]
        sub_ids = {k: i for i, k in enumerate(self.subsystems)}
        sub_of = np.array([new_index[x] if x >= 0 else -1 for x in sub_of], dtype=np.int32)
        self.subsystem_of = sub_of
        self.subsystem_index = sub_ids
        self.subsystem_system = np.array([self.system_index[k[0]] for k in self.subsystems], dtype=np.int32)
        self.subsystems_by_system = [np.nonzero(self.subsystem_system == i)[0] for i in range(len(self.systems))]
        sub_defaults = {(s["key"], x["name"]): x["default_visible"] for s in self.systems for x in s["subsystems"]}
        self.subsystem_default = [sub_defaults.get(k, True) for k in self.subsystems]

        self.node_of_structure = {}
        self.parent_node = {}
        for nid, node in self.nodes.items():
            if "sid" in node:
                self.node_of_structure[node["sid"]] = nid
            for c in node["children"]:
                self.parent_node[c] = nid

        self.by_base = defaultdict(list)
        self.by_name = defaultdict(list)
        for s in self.structures:
            self.by_base[(s["base"], s["system"], s["role"])].append(s["id"])
            self.by_name[s["base"]].append(s["id"])

        self.attachments_on = defaultdict(list)
        self.attachments_of_muscle = defaultdict(list)
        for s in self.structures:
            if s["system"] == "attachments":
                if "on" in s:
                    self.attachments_on[s["on"]].append(s["id"])
                self.attachments_of_muscle[(s["base"], s["side"])].append(s["id"])

        self.landmarks_of = defaultdict(list)
        for i, lm in enumerate(self.landmarks):
            self.landmarks_of[lm["sid"]].append(i)

        self.muscles_by_nerve = defaultdict(list)
        for s in self.structures:
            for nerve in s.get("innervation", ()):
                self.muscles_by_nerve[nerve].append(s["id"])

    @property
    def definitions(self):
        if self._definitions is None:
            self._definitions = json.loads((self.dir / "definitions.json").read_text(encoding="utf-8"))
        return self._definitions

    def load_geometry(self):
        vertices = np.fromfile(self.dir / "vertices.bin", dtype=np.uint8)
        indices = np.fromfile(self.dir / "indices.bin", dtype=np.uint8)
        if self.findings is not None:
            v, i = self.findings.geometry()
            vertices = np.concatenate([vertices, np.frombuffer(v, dtype=np.uint8)])
            indices = np.concatenate([indices, np.frombuffer(i, dtype=np.uint8)])
        return vertices, indices

    def node_structures(self, nid):
        out = []
        stack = [nid]
        while stack:
            node = self.nodes[stack.pop()]
            if "sid" in node:
                out.append(node["sid"])
            stack.extend(node["children"])
        return out

    def ancestors(self, nid):
        chain = []
        p = self.parent_node.get(nid)
        while p is not None:
            chain.append(p)
            p = self.parent_node.get(p)
        return list(reversed(chain))

    def bounds_of(self, sids):
        sids = list(sids)
        if not sids:
            return None
        return self.bbox_min[sids].min(axis=0), self.bbox_max[sids].max(axis=0)

    def counterpart(self, sid):
        s = self.structures[sid]
        return [x for x in self.by_base[(s["base"], s["system"], s["role"])] if x != sid]

    def structures_named(self, base):
        return list(self.by_name.get(base, ()))
