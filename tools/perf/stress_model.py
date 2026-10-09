"""Combine copies of a prepared library model into one big ViewerModel, offset on a grid, with real (duplicated)
geometry - what a 250M-triangle atlas would put in memory. Offsets are baked into the vertex positions. Level-of-detail
index lists of the base model are copied and shifted too, so the renderer behaves as it does for a loaded model.
"""
from __future__ import annotations

import copy
import dataclasses
import math

import numpy as np

ITEM_CAP = 4000          # SceneState asserts n_items <= 4096 (app/state.py:31)


def copies_for(base, target_triangles):
    return max(1, int(math.ceil(target_triangles / max(base.triangle_count, 1))))


def tile(base, k_copies):
    """(model, info). Memory use is the combined arrays plus the shifted LOD lists; the base is left untouched."""
    from app.viewer.lod import PartLod
    from app.viewer.model import Group, Item
    V, I, P, N = len(base.vertices), len(base.indices), len(base.parts), len(base.items)
    if k_copies * V >= 2**32:
        raise ValueError("combined vertex count exceeds uint32 indices")
    share_items = k_copies * N > ITEM_CAP
    max_pid = max(p.id for p in base.parts)
    lo, hi = np.asarray(base.bounds_min, float), np.asarray(base.bounds_max, float)
    ext = hi - lo
    cols = int(math.ceil(math.sqrt(k_copies)))
    gap = 1.15
    m = copy.copy(base)
    m.vertices = np.empty((k_copies * V, base.vertices.shape[1]), dtype=base.vertices.dtype)
    m.indices = np.empty(k_copies * I, dtype=np.uint32)
    m.parts, m.items, m.groups = [], [], []
    lod = {}
    base_lod = getattr(base, "lod", None) or {}
    group_items = {g.key: [] for g in base.groups}
    node_inv = {}
    for k in range(k_copies):
        gx, gz = k % cols, k // cols
        world_off = np.array([gx * ext[0] * gap, 0.0, gz * ext[2] * gap])
        m.vertices[k * V:(k + 1) * V] = base.vertices
        m.indices[k * I:(k + 1) * I] = base.indices
        m.indices[k * I:(k + 1) * I] += np.uint32(k * V)
        item_shift = 0 if share_items else k * N
        for p in base.parts:
            M3 = base.node_matrix(p.node)[:3, :3]
            if p.node not in node_inv:
                node_inv[p.node] = np.linalg.inv(M3)
            local = node_inv[p.node] @ world_off
            if p.vertex_count:
                m.vertices[k * V + p.vertex_base:k * V + p.vertex_base + p.vertex_count, :3] += local.astype(np.float32)
            q = dataclasses.replace(
                p, id=p.id + k * max_pid, first=p.first + k * I, vertex_base=p.vertex_base + k * V,
                local_centre=p.local_centre + local, local_min=p.local_min + local, local_max=p.local_max + local,
                item=p.item + item_shift)
            m.parts.append(q)
            if p.id in base_lod:
                src = base_lod[p.id]
                lod[q.id] = PartLod(src.cells.copy(), [(a + np.uint32(k * V)).astype(np.uint32) for a in src.indices])
        if not share_items:
            for it in base.items:
                new = dataclasses.replace(it, index=it.index + item_shift, key=f"{it.key}#{k}", parts=[])
                m.items.append(new)
                group_items.setdefault(it.group, []).append(new.index)
    if not share_items:
        by_item = {}
        for q in m.parts:
            by_item.setdefault(q.item, []).append(q)
        for it in m.items:
            it.parts = by_item.get(it.index, [])
        m.groups = [Group(g.key, g.title, group_items[g.key], g.colour) for g in base.groups]
    else:
        m.items, m.groups = base.items, base.groups
    m.lod = lod
    m._item_boxes = None
    m.item_offsets = None
    corner = np.array([(cols - 1) * ext[0] * gap, 0.0, ((k_copies - 1) // cols) * ext[2] * gap])
    m.bounds_min, m.bounds_max = lo.copy(), hi + corner
    info = {"copies": k_copies, "grid_columns": cols, "items": len(m.items), "items_shared_with_base": share_items,
            "parts": len(m.parts), "triangles": m.triangle_count, "vertices": len(m.vertices),
            "lod_parts": len(lod)}
    return m, info
