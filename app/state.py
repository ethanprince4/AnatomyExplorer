import numpy as np
from PySide6.QtCore import QObject, Signal

STATE_TEX_WIDTH = 4096

F_VISIBLE = 1
F_GHOST = 2
F_SELECTED = 4
F_HOVERED = 8
F_OVERRIDE = 32
F_NOCLIP = 64


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


class SceneState(QObject):
    """Visibility, selection, ghosting and color state for every structure."""

    render_changed = Signal()
    visibility_changed = Signal()
    selection_changed = Signal()

    def __init__(self, ds, settings):
        super().__init__()
        self.ds = ds
        self.settings = settings
        n = ds.n
        assert n <= STATE_TEX_WIDTH
        self.hidden = np.zeros(n, dtype=bool)
        self.forced = np.zeros(n, dtype=bool)
        self.isolated = None
        self.system_on = np.array([s["default_visible"] for s in ds.systems], dtype=bool)
        self.system_alpha = np.ones(len(ds.systems), dtype=np.float32)
        self.subsystem_on = np.array(ds.subsystem_default, dtype=bool)
        self.region_on = np.ones(len(ds.regions), dtype=bool)
        self.ghost_focus = None  # np bool mask of structures kept solid while others are ghosted
        self.depth = None        # relative depth per structure, filled in by DepthIndex when it is ready
        self.depth_cut = 0.0     # dissection level: everything shallower than this has been peeled away
        self.depth_band = 0.0    # > 0 shows only the slab between depth_cut and depth_cut + band
        self.selected = []
        self.hovered = -1
        self.custom_colors = {}
        self._undo = []
        self._visible_cache = None
        self._sys_colors_lin = srgb_to_linear([s["color"] for s in ds.systems])

    # ------------------------------------------------------------------ visibility
    def visible_mask(self):
        if self._visible_cache is not None:
            return self._visible_cache
        ds = self.ds
        vis = self.system_on[ds.system_of].copy()
        sub = ds.subsystem_of
        has = sub >= 0
        vis[has] &= self.subsystem_on[sub[has]]
        if not self.region_on.all():
            bits = sum(1 << i for i, on in enumerate(self.region_on) if on)
            rm = ds.region_mask
            vis &= ((rm & bits) != 0) | (rm == 0)
        if self.isolated is not None:
            vis = self.isolated.copy()
        vis &= ~self.hidden
        if self.depth is not None and (self.depth_cut > 0.0 or self.depth_band > 0.0):
            known = self.depth >= 0.0
            vis &= ~(known & (self.depth < self.depth_cut))
            if self.depth_band > 0.0:
                vis &= ~(known & (self.depth > self.depth_cut + self.depth_band))
        vis |= self.forced          # an explicit "show this" beats both hiding and the dissection level
        self._visible_cache = vis
        return vis

    def _snapshot(self):
        return (self.hidden.copy(), self.forced.copy(), None if self.isolated is None else self.isolated.copy(),
                self.system_on.copy(), self.subsystem_on.copy(), self.region_on.copy(),
                None if self.ghost_focus is None else self.ghost_focus.copy(), self.depth_cut, self.depth_band,
                self.system_alpha.copy())

    def push_undo(self):
        self._undo.append(self._snapshot())
        if len(self._undo) > 100:
            self._undo.pop(0)

    def restore(self, snapshot):
        """Put the scene back exactly as `_snapshot` found it. One place knows the layout."""
        (self.hidden, self.forced, self.isolated, self.system_on, self.subsystem_on, self.region_on,
         self.ghost_focus, self.depth_cut, self.depth_band, self.system_alpha) = snapshot
        self._vis_dirty()

    def undo(self):
        if not self._undo:
            return False
        self.restore(self._undo.pop())
        return True

    def _vis_dirty(self):
        self._visible_cache = None
        self.visibility_changed.emit()
        self.render_changed.emit()

    def subsystems_of_system(self, idx):
        return self.ds.subsystems_by_system[idx]

    def set_system(self, idx, on, undo=True):
        """Turning a system on activates all of its subsystems and structures."""
        if undo:
            self.push_undo()
        members = self.ds.system_of == idx
        self.system_on[idx] = on
        self.forced[members] = False
        if on:
            self.subsystem_on[self.subsystems_of_system(idx)] = True
            self.hidden[members] = False
            if self.isolated is not None:
                self.isolated[members] = True
        elif self.isolated is not None:
            self.isolated[members] = False
        self._vis_dirty()

    def set_systems(self, mask):
        self.push_undo()
        self.system_on[:] = mask
        for i, on in enumerate(mask):
            if on:
                self.subsystem_on[self.subsystems_of_system(i)] = True
        self.hidden[:] = False
        self.forced[:] = False
        self.isolated = None
        self._vis_dirty()

    def set_subsystem(self, idx, on):
        """Turning a subsystem on while its system is off activates only that subsystem."""
        self.push_undo()
        sys_idx = self.ds.subsystem_system[idx]
        subs = self.subsystems_of_system(sys_idx)
        members = self.ds.subsystem_of == idx
        if on:
            if not self.system_on[sys_idx]:
                self.system_on[sys_idx] = True
                self.subsystem_on[subs] = False
            self.subsystem_on[idx] = True
            self.hidden[members] = False
            if self.isolated is not None:
                self.isolated[members] = True
        else:
            self.subsystem_on[idx] = False
            if self.isolated is not None:
                self.isolated[members] = False
            if not self.subsystem_on[subs].any():
                self.system_on[sys_idx] = False
                self.subsystem_on[subs] = True
        self.forced[members] = False
        self._vis_dirty()

    def tree_toggle(self, nid, on):
        """Checkbox in the anatomy tree. Checking a node inside an inactive branch activates only that node."""
        ds = self.ds
        node = ds.nodes[nid]
        sys_idx = ds.system_index[node["system"]]
        if node["kind"] == "system":
            self.set_system(sys_idx, on)
            return
        sids = np.array(ds.node_structures(nid), dtype=np.int64)
        self.push_undo()
        if not on:
            self.hidden[sids] = True
            self.forced[sids] = False
            if self.selected:
                hs = set(sids.tolist())
                self.selected = [s for s in self.selected if s not in hs]
                self.selection_changed.emit()
        else:
            vis = self.visible_mask()
            top = None
            for anc in ds.ancestors(nid):
                if ds.nodes[anc]["kind"] == "system":
                    continue
                if not vis[ds.node_structures(anc)].any():
                    top = anc
                    break
            if not self.system_on[sys_idx]:
                self.system_on[sys_idx] = True
                self.subsystem_on[self.subsystems_of_system(sys_idx)] = False
                self.hidden[ds.system_of == sys_idx] = True
            needed = np.unique(ds.subsystem_of[sids])
            for sub in needed[needed >= 0]:
                if not self.subsystem_on[sub]:
                    self.subsystem_on[sub] = True
                    self.hidden[ds.subsystem_of == sub] = True
            if top is not None:
                self.hidden[ds.node_structures(top)] = True
            self.hidden[sids] = False
            self.forced[sids] = False
            if self.isolated is not None:
                self.isolated[sids] = True
            self._visible_cache = None
            vis = self.visible_mask()
            self.forced[sids[~vis[sids]]] = True
        self._vis_dirty()

    def set_depth(self, cut, band=None):
        """Dissection level. `cut` peels away everything above it; `band` limits the view to one layer."""
        cut = float(max(0.0, min(1.2, cut)))
        band = self.depth_band if band is None else float(max(0.0, band))
        if cut == self.depth_cut and band == self.depth_band:
            return
        self.depth_cut, self.depth_band = cut, band
        self._vis_dirty()

    def depth_counts(self):
        """(peeled away, still visible) for the status readout."""
        if self.depth is None:
            return 0, 0
        known = self.depth >= 0.0
        peeled = int((known & (self.depth < self.depth_cut)).sum())
        return peeled, int(self.visible_mask().sum())

    def set_region(self, idx, on):
        self.push_undo()
        self.region_on[idx] = on
        self._vis_dirty()

    def set_regions(self, mask):
        self.push_undo()
        self.region_on[:] = mask
        self._vis_dirty()

    def set_system_alpha(self, idx, alpha):
        self.system_alpha[idx] = alpha
        self.render_changed.emit()

    def set_hidden(self, sids, hidden, undo=True):
        if undo:
            self.push_undo()
        sids = np.asarray(list(sids), dtype=np.int64)
        if len(sids) == 0:
            return
        self.hidden[sids] = hidden
        if hidden:
            self.forced[sids] = False
            if self.selected:
                hs = set(sids.tolist())
                self.selected = [s for s in self.selected if s not in hs]
                self.selection_changed.emit()
        else:
            vis = self.visible_mask()
            self.forced[sids] = ~vis[sids] | self.forced[sids]
        self._vis_dirty()

    def isolate(self, sids):
        self.push_undo()
        mask = np.zeros(self.ds.n, dtype=bool)
        mask[list(sids)] = True
        self.isolated = mask
        self.forced[~mask] = False
        self.hidden[mask] = False
        self.ghost_focus = None
        self._vis_dirty()

    def show_all(self):
        """Reveal normal anatomy; pathology findings remain explicitly opt-in."""
        self.push_undo()
        self.hidden[:] = False
        self.forced[:] = False
        self.isolated = None
        self.ghost_focus = None
        self.system_on[:] = True
        self.system_on[[i for i, s in enumerate(self.ds.systems)
                        if s["key"] in ("reference", "regions", "attachments", "fascia", "findings")]] = False
        self.subsystem_on[:] = True
        self.region_on[:] = True
        self._vis_dirty()

    def reset_visibility(self):
        self.push_undo()
        self.hidden[:] = False
        self.forced[:] = False
        self.isolated = None
        self.ghost_focus = None
        self.system_on[:] = [s["default_visible"] for s in self.ds.systems]
        self.subsystem_on[:] = self.ds.subsystem_default
        self.region_on[:] = True
        self._vis_dirty()

    def force_show(self, sids):
        vis = self.visible_mask()
        sids = list(sids)
        changed = False
        for s in sids:
            if not vis[s]:
                self.forced[s] = True
                self.hidden[s] = False
                changed = True
        if changed:
            self._vis_dirty()

    # ------------------------------------------------------------------ ghosting
    def set_ghost_focus(self, sids):
        mask = np.zeros(self.ds.n, dtype=bool)
        mask[list(sids)] = True
        self.ghost_focus = mask
        self._vis_dirty()

    def clear_ghost(self):
        if self.ghost_focus is not None:
            self.ghost_focus = None
            self._vis_dirty()
            return True
        return False

    def clear_forced(self):
        if self.forced.any():
            self.forced[:] = False
            self._vis_dirty()

    # ------------------------------------------------------------------ selection
    def select(self, sids, add=False):
        sids = [int(s) for s in sids]
        if add:
            cur = list(self.selected)
            for s in sids:
                if s in cur:
                    cur.remove(s)
                else:
                    cur.append(s)
            self.selected = cur
        else:
            self.selected = sids
        self.selection_changed.emit()
        self.render_changed.emit()

    def clear_selection(self):
        if self.selected:
            self.selected = []
            self.selection_changed.emit()
            self.render_changed.emit()
            return True
        return False

    def set_hovered(self, sid):
        if sid != self.hovered:
            self.hovered = sid
            self.render_changed.emit()

    def set_custom_color(self, sids, rgb):
        for s in sids:
            if rgb is None:
                self.custom_colors.pop(s, None)
            else:
                self.custom_colors[s] = rgb
        self.render_changed.emit()

    # ------------------------------------------------------------------ GPU packing
    def build_texture(self):
        ds = self.ds
        n = ds.n
        tex = np.zeros((2, STATE_TEX_WIDTH, 4), dtype=np.float32)
        vis = self.visible_mask()
        flags = np.where(vis, F_VISIBLE, 0).astype(np.int32)
        if self.ghost_focus is not None:
            flags |= np.where(vis & ~self.ghost_focus, F_GHOST, 0).astype(np.int32)
        if self.selected:
            sel = np.array(self.selected, dtype=np.int64)
            flags[sel] |= F_SELECTED
            flags[sel] &= ~F_GHOST
        if 0 <= self.hovered < n:
            flags[self.hovered] |= F_HOVERED
        noclip = getattr(ds, "noclip_mask", None)
        if noclip is not None:
            flags |= np.where(noclip, F_NOCLIP, 0).astype(np.int32)
        if self.settings.get("color_mode") == 2:
            tex[0, :n, :3] = self._sys_colors_lin[ds.system_of]
            flags |= F_OVERRIDE
        for s, rgb in self.custom_colors.items():
            tex[0, s, :3] = srgb_to_linear(rgb)
            flags[s] |= F_OVERRIDE
        tex[0, :n, 3] = flags
        tex[1, :n, 0] = self.system_alpha[ds.system_of]
        part_alpha = getattr(self, "part_alpha", None)
        if part_alpha is not None:
            tex[1, :n, 0] *= part_alpha
        return tex

    def visible_triangle_count(self):
        vis = self.visible_mask()
        counts = np.array([s["i_count"] for s in self.ds.structures], dtype=np.int64) // 3
        return int(counts[vis].sum()), int(vis.sum())
