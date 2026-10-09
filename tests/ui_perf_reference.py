"""The model viewer side-panel code as it was before the 5,000-structure optimisation, kept verbatim as the oracle
for tests/test_ui_scaling.py and tools/perf/bench_ui.py. Not used by the app."""
from PySide6.QtCore import Qt

from app.ui.model_view import ROLE
from app.ui.search_panel import normalized
from app.viewer.catalog import _norm


def old_filter_tree(self, text):
    terms = normalized(text).split()
    rows = [*self.category_items, *self.group_items.values()]
    if terms and self._filter_expanded is None:
        self._filter_expanded = {id(row) for row in rows if row.isExpanded()}

    def visit(row, context):
        kind, val = row.data(0, ROLE)
        if kind == "part":
            part = self.vmodel.items[val]
            show = all(term in normalized(f"{part.name} {part.key} {context}") for term in terms)
            row.setHidden(not show)
            return int(show)
        label = f"{context} {val if kind == 'group' else ''} {row.text(0)}"
        if kind == "family" or (kind == "group" and val in self.family_rows):
            sids = self._sids_of(row)
            searchable = normalized(label + " " + " ".join(self.vmodel.items[i].name for i in sids))
            show = all(term in searchable for term in terms)
            row.setHidden(not show)
            return len(sids) if show else 0
        shown = sum(visit(row.child(index), label) for index in range(row.childCount()))
        row.setHidden(not shown)
        if terms and shown:
            row.setExpanded(True)
        return shown

    root = self.tree.invisibleRootItem()
    matches = sum(visit(root.child(index), "") for index in range(root.childCount()))
    if not terms and self._filter_expanded is not None:
        for row in rows:
            row.setExpanded(id(row) in self._filter_expanded)
        self._filter_expanded = None
    self.parts_status.setText("Check to show or hide" if matches else
                              "No matching parts. Clear the filter to see the full model.")
    self._parts_layout_changed()
    return matches


def old_sync_tree(self):
    vis = self.state.visible_mask()
    self._sync = True
    for sid, it in self.part_items.items():
        if it.data(0, ROLE)[0] == "part":
            it.setCheckState(0, Qt.Checked if vis[sid] else Qt.Unchecked)
    for gi in [*self.family_items.values(), *self.group_items.values(), *self.category_items]:
        sids = self._sids_of(gi)
        n = int(vis[sids].sum()) if sids else 0
        gi.setCheckState(0, Qt.Checked if n == len(sids) else Qt.Unchecked if n == 0 else Qt.PartiallyChecked)
    self._sync = False
    self._update_selection_controls()


def old_resolve(self, model, names):
    by_name, by_group = {}, {}
    for it in model.items:
        by_name.setdefault(_norm(it.name), []).append(it.index)
        by_name.setdefault(_norm(it.key), []).append(it.index)
        for former in getattr(it, "former_names", ()):
            by_name.setdefault(_norm(former), []).append(it.index)
    for g in model.groups:
        by_group[_norm(g.title)] = list(g.items)
        by_group[_norm(g.key)] = list(g.items)
    key_of = {it.key: it.index for it in model.items}
    group_items = {}
    for g in model.groups:
        for sid in {model.items[i].parts[0].structure_id for i in g.items if model.items[i].parts}:
            if sid:
                group_items.setdefault(sid, []).extend(g.items)
    aliases = {_norm(k): v for k, v in self.aliases.items()}
    if self.id == "kidney_nephron":
        families = {
            "Segmental arteries": ("Segmental artery (",),
            "Interlobar arteries": ("Interlobar artery (",),
            "Arcuate arteries": ("Arcuate artery (",),
            "Anterior and posterior divisions of the renal artery":
                ("Anterior division of the renal artery", "Posterior division of the renal artery"),
            "Renal pyramids": ("Renal pyramid",),
            "Renal cortex": ("Renal cortex,",),
        }
        for alias, prefixes in families.items():
            aliases[_norm(alias)] = [item.name for item in model.items if item.name.startswith(prefixes)]
        aliases[_norm("Renal capsule (fibrous capsule)")] = ["Renal capsule"]
    out, missing = [], []
    for n in names or ():
        k = _norm(n)
        hit = by_name.get(k) or by_group.get(k)
        if not hit and k in aliases:
            hit = []
            for target in aliases[k]:
                if target.startswith("group:"):
                    g = target[6:]
                    hit.extend(group_items.get(g) or by_group.get(_norm(g), []))
                elif target in key_of:
                    hit.append(key_of[target])
                else:
                    hit.extend(by_name.get(_norm(target), []))
        if hit:
            out.extend(i for i in hit if i not in out)
        else:
            missing.append(n)
    return out, missing
