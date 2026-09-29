"""A viewer model seen through the atlas's dataset interface, so the atlas's own SceneState can hold its
visibility, selection, x-ray, colours and undo history: hide, isolate, x-ray, show all and Ctrl+Z then behave in a
model exactly as they do in the atlas. Groups play the part of body systems."""
from collections import defaultdict

import numpy as np


class ModelDataset:
    def __init__(self, model):
        self.model = model
        items = model.items
        self.parts = items                    # practice and lessons read .parts[i].name
        self.n = len(items)
        self.systems = [{"key": g.key, "name": g.title, "default_visible": True, "color": list(g.colour),
                         "subsystems": []} for g in model.groups]
        self.system_index = {g.key: i for i, g in enumerate(model.groups)}
        self.system_of = np.array([self.system_index[it.group] for it in items], dtype=np.int32)
        self.subsystems = []
        self.subsystem_index = {}
        self.subsystem_default = []
        self.subsystem_system = np.zeros(0, dtype=np.int32)
        self.subsystems_by_system = [np.zeros(0, dtype=np.int64) for _ in model.groups]
        self.subsystem_of = np.full(self.n, -1, dtype=np.int32)
        self.regions = []
        self.region_bit = {}
        self.region_mask = np.zeros(self.n, dtype=np.int64)
        self.landmarks = []
        self.landmarks_of = defaultdict(list)
        self.structures = [{"id": it.index, "name": it.name, "base": it.name, "side": "", "role": None,
                            "system": it.group, "subsystem": None, "regions": [], "latin": None,
                            "i_count": sum(p.count for p in it.parts)} for it in items]
        self.by_name = defaultdict(list)
        for it in items:
            self.by_name[it.name].append(it.index)

    def counterpart(self, sid):
        return []

    def structures_named(self, name):
        return list(self.by_name.get(name, ()))

    def bounds_of(self, sids):
        return self.model.item_bounds(list(sids))
