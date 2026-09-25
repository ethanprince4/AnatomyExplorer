import html
import math
import re

import numpy as np
from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QMenu, QPushButton, QSlider, QSplitter, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..micro.base import MicroDataset
from ..state import SceneState
from ..viewport import Viewport
from .flow import FlowLayout

ROLE = Qt.UserRole + 1


def esc(s):
    return html.escape(str(s or ""), quote=True)


class MicroView(QWidget):
    openHistology = Signal(str, int)
    openMicro = Signal(str)
    openOnline = Signal(str)          # a downloaded Sketchfab model's uid, to see it in Sketchfab's own player

    BLOCK_UNITS = 2.0          # every model is built about two units wide

    @staticmethod
    def _scale_from_note(note):
        """Millimetres per model unit.

        Only a note that states the width of the block is trusted; everything else falls back to the 3 mm block
        the models are drawn to."""
        m = re.search(r"block\b[^.]*?(\d+(?:\.\d+)?)\s*mm", (note or "").lower())
        if not m:
            return 1.5
        return max(float(m.group(1)) / MicroView.BLOCK_UNITS, 1e-4)

    def __init__(self, model, content, settings, parent=None):
        super().__init__(parent)
        self.model = model
        self.content = content
        self.settings = settings
        self.info = None
        # a downloaded Sketchfab model brings its own dataset, which carries its colours and textures
        self.mds = model.dataset() if hasattr(model, "dataset") else MicroDataset(model)
        self.state = SceneState(self.mds, settings)
        self.gl_widget = Viewport(self.mds, self.state, settings)
        self.gl_widget.home_view = self.reset_view         # trackpad smart zoom goes to this model's home framing
        self.gl_widget.clip_axes = [tuple(model.cutaway[0]), tuple(model.cutaway[1]), (0.0, 1.0, 0.0)]
        self.gl_widget.clip_pos = [model.cut_at[0], model.cut_at[1], 0.0]
        self.gl_widget.clip_flip = [False, True, False]
        self.gl_widget.clip_mode = 1
        cut_on = getattr(model, "cut_on", True)       # a model that is its own cutaway opens uncut
        self.gl_widget.clip_on = [cut_on, cut_on, False]
        self.gl_widget.measure_scale = model.metres_per_unit if hasattr(model, "metres_per_unit") else \
            self._scale_from_note(model.scale_note) / 1000.0
        self.labels_on = False
        self.click_hook = None        # Practice mode: callable(sid) -> True when it took the click
        self.rclick_hook = None       # Practice mode: callable(sid), a right click in the 3D view

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        lay.addWidget(split)

        side = QWidget()
        side.setMinimumWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 10, 6, 6)
        title = QLabel(model.name)
        title.setWordWrap(True)
        title.setStyleSheet("font-size:12.5pt; font-weight:600; color:#eef3f8;")
        sl.addWidget(title)
        summ = QLabel(model.summary)
        summ.setWordWrap(True)
        summ.setStyleSheet("color:#aab3c0;")
        sl.addWidget(summ)
        if model.scale_note:
            note = QLabel(model.scale_note)
            note.setWordWrap(True)
            note.setStyleSheet("color:#7f8b9b; font-size:8.5pt;")
            sl.addWidget(note)
        credit = getattr(model, "credit_html", "")
        if credit:
            c = QLabel(credit)
            c.setWordWrap(True)
            c.setOpenExternalLinks(True)
            c.setTextInteractionFlags(Qt.TextBrowserInteraction)
            c.setStyleSheet("color:#7f8b9b; font-size:8.5pt;")
            sl.addWidget(c)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        sl.addWidget(self.tree, 1)
        self._build_tree()
        split.addWidget(side)
        self.side = side

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        # the controls wrap onto a second row rather than hold the window wider than a laptop screen
        bar = FlowLayout(spacing=6)
        bar.setContentsMargins(8, 6, 8, 6)

        def labelled(text, slider):
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(6, 0, 0, 0)
            hl.setSpacing(6)
            hl.addWidget(QLabel(text))
            hl.addWidget(slider)
            return box

        self.cut = QCheckBox("Cut-away")
        self.cut.setChecked(cut_on)
        self.cut.toggled.connect(self._toggle_cut)
        bar.addWidget(self.cut)
        self.labels = QCheckBox("Labels")
        self.labels.toggled.connect(self._toggle_labels)
        bar.addWidget(self.labels)
        if self.mds.bulk_mask.any():
            self.opacity = QSlider(Qt.Horizontal)
            self.opacity.setRange(8, 100)
            self.opacity.setValue(100)
            self.opacity.setFixedWidth(110)
            self.opacity.valueChanged.connect(self._opacity)
            bar.addWidget(labelled("Tissue opacity", self.opacity))
        self.explode = QSlider(Qt.Horizontal)
        self.explode.setRange(0, 100)
        self.explode.setFixedWidth(140)
        self.explode.valueChanged.connect(self._explode)
        bar.addWidget(labelled("Separate parts" if hasattr(model, "dataset") else "Separate layers", self.explode))
        for text, fn in (("X-ray others", self._xray), ("Isolate", self._isolate), ("Show all", self._show_all),
                         ("Reset view", self.reset_view)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        if getattr(model, "uid", None):
            online = QPushButton("Sketchfab player")
            online.setToolTip("The same model in Sketchfab's own player, with the creator's annotations (online)")
            online.clicked.connect(lambda: self.openOnline.emit(model.uid))
            bar.add_right(online)
        if model.histology or model.related:
            more = QToolButton()
            more.setText("Related ▾")
            more.setPopupMode(QToolButton.InstantPopup)
            m = QMenu(more)
            for tid in model.histology:
                t = content.tissues.get(tid)
                if t and t.get("images"):
                    m.addAction(f"Histology · {t['name']}", lambda x=tid: self.openHistology.emit(x, 0))
            for mid in model.related:
                other = content.micro_models.get(mid)
                if other:
                    m.addAction(f"Model · {other.name}", lambda x=mid: self.openMicro.emit(x))
            more.setMenu(m)
            bar.add_right(more)
        top = QWidget()
        top.setLayout(bar)
        top.setStyleSheet("background:#14171c;")
        rl.addWidget(top)
        rl.addWidget(self.gl_widget, 1)
        split.addWidget(right)
        split.setSizes([280, 1200])

        self.gl_widget.structureClicked.connect(self._clicked)
        self.gl_widget.structureDoubleClicked.connect(self._double_clicked)
        self.gl_widget.contextMenuRequested.connect(lambda sid, _pos: self.rclick_hook and self.rclick_hook(sid))
        self.state.visibility_changed.connect(self._sync_tree)
        self.state.visibility_changed.connect(self._refresh_labels)
        QTimer.singleShot(0, self.reset_view)

    # ------------------------------------------------------------------ tree
    def _build_tree(self):
        self._sync = True
        self.part_items = {}
        groups = {}
        for sid, p in enumerate(self.mds.parts):
            g = groups.get(p.group)
            if g is None:
                g = QTreeWidgetItem(self.tree)
                g.setText(0, p.group)
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                g.setFlags(g.flags() | Qt.ItemIsUserCheckable)
                g.setCheckState(0, Qt.Checked)
                g.setData(0, ROLE, ("group", p.group))
                g.setExpanded(True)
                groups[p.group] = g
            it = QTreeWidgetItem(g)
            it.setText(0, p.name)
            it.setToolTip(0, p.description[:240])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)
            it.setData(0, ROLE, ("part", sid))
            self.part_items[sid] = it
        self.group_items = groups
        self._sync = False

    def _sids_of(self, item):
        kind, val = item.data(0, ROLE)
        if kind == "part":
            return [val]
        return [i for i, p in enumerate(self.mds.parts) if p.group == val]

    def _item_changed(self, item, col):
        if self._sync:
            return
        self.state.set_hidden(self._sids_of(item), item.checkState(0) == Qt.Unchecked)

    def _item_clicked(self, item, col):
        sids = self._sids_of(item)
        self.state.select(sids)
        self._show_selection()

    def _item_double_clicked(self, item, col):
        self.gl_widget.frame_structures(self._sids_of(item))

    def _sync_tree(self):
        vis = self.state.visible_mask()
        self._sync = True
        for sid, it in self.part_items.items():
            it.setCheckState(0, Qt.Checked if vis[sid] else Qt.Unchecked)
        for g, it in self.group_items.items():
            sids = self._sids_of(it)
            n = int(vis[sids].sum())
            it.setCheckState(0, Qt.Checked if n == len(sids) else Qt.Unchecked if n == 0 else Qt.PartiallyChecked)
        self._sync = False

    # ------------------------------------------------------------------ view controls
    def reset_view(self):
        cam = self.gl_widget.camera
        bmin, bmax = self.mds.scene_bbox
        center = (bmin + bmax) / 2
        radius = float(np.linalg.norm(bmax - bmin) / 2)
        yaw, pitch = getattr(self.model, "home_view", (-0.62, 0.42))
        cam.animate_to(center, cam.fit_distance(radius * 0.95, self.gl_widget.aspect()), yaw, pitch, 0.01)
        self.gl_widget.update()

    def _toggle_cut(self, on):
        self.gl_widget.clip_on = [on, on, False]
        self.gl_widget.update()

    def _toggle_labels(self, on):
        self.labels_on = on
        self._refresh_labels()

    def _refresh_labels(self):
        if self.labels_on:
            vis = self.state.visible_mask()
            hosts = [sid for sid in range(self.mds.n) if vis[sid]]
        elif self.state.selected:
            hosts = list(self.state.selected)
        else:
            hosts = []
        self.gl_widget.landmark_hosts = hosts
        self.gl_widget.update()

    def _explode(self, value):
        amount = value / 100.0 * 0.35
        gl = self.gl_widget
        if gl.renderer is None:
            return
        gl.makeCurrent()
        try:
            gl.renderer.vbo.write(self.mds.vertex_bytes(amount).tobytes())
        finally:
            gl.doneCurrent()
        gl.update()

    def _opacity(self, value):
        self.state.part_alpha = np.where(self.mds.bulk_mask, value / 100.0, 1.0).astype(np.float32)
        self.state.render_changed.emit()

    def _xray(self):
        if self.state.ghost_focus is not None:
            self.state.clear_ghost()
        elif self.state.selected:
            self.state.set_ghost_focus(self.state.selected)

    def _isolate(self):
        if self.state.selected:
            self.state.isolate(self.state.selected)

    def _show_all(self):
        self.state.hidden[:] = False
        self.state.isolated = None
        self.state.ghost_focus = None
        self.state._vis_dirty()

    # ------------------------------------------------------------------ selection & details
    def _clicked(self, sid, modifiers):
        if self.click_hook is not None and self.click_hook(sid):
            return
        if sid < 0:
            self.state.clear_selection()
        else:
            self.state.select([sid], add=bool(modifiers & Qt.ControlModifier))
            it = self.part_items.get(sid)
            if it:
                self.tree.blockSignals(True)
                self.tree.setCurrentItem(it)
                self.tree.blockSignals(False)
        self._refresh_labels()
        self._show_selection()

    def _double_clicked(self, sid):
        if sid >= 0 and self.click_hook is None:
            self.state.select([sid])
            self.gl_widget.frame_structures([sid])
            self._show_selection()

    # ------------------------------------------------------------------ lessons & practice
    def part_ids(self, names):
        """Part indices for a list of exact part names (case-insensitive), and the names that matched nothing."""
        by_lower = {}
        for i, p in enumerate(self.mds.parts):
            by_lower.setdefault(p.name.lower(), []).append(i)
        sids, missing = [], []
        for n in names or ():
            hit = by_lower.get(str(n).strip().lower())
            if hit:
                sids.extend(hit)
            else:
                missing.append(n)
        return sids, missing

    def focus_parts(self, names):
        """A lesson step's "micro_focus": select these parts, x-ray the rest, label and frame them.
        Returns the names that are not parts of this model."""
        sids, missing = self.part_ids(names)
        if sids:
            self.state.set_hidden(sids, False)
            self.state.select(sids)
            self.state.set_ghost_focus(sids)
            self._refresh_labels()
            self._show_selection()
            # after reset_view, which a freshly opened model queues for its first frame
            QTimer.singleShot(250, lambda: self.gl_widget.frame_structures(sids))
        return missing

    def set_practice(self, click=None, rclick=None):
        """Practice mode takes the clicks, and the parts list and labels are put away: they would give the answer."""
        on = click is not None
        self.click_hook, self.rclick_hook = click, rclick
        self.side.setVisible(not on)
        if on:
            self.labels.setChecked(False)
            self._show_all()
            self.state.clear_selection()
            self.reset_view()
        self._refresh_labels()

    def on_activated(self, info):
        self.info = info
        self._show_selection()

    def _show_selection(self):
        if not self.info:
            return
        sel = self.state.selected
        m = self.model
        hist = []
        for tid in m.histology:
            t = self.content.tissues.get(tid)
            if not t or not t.get("images"):
                continue
            thumbs = "".join(
                f'<td style="padding:2px"><a href="histo:{esc(tid)}|{i}"><img src="'
                f'{QUrl.fromLocalFile(str(self.content.thumb_path(img))).toString()}" width="96" height="72"></a></td>'
                for i, img in enumerate(t["images"][:3]))
            hist.append(f'<p><b><a href="histo:{esc(tid)}|0">{esc(t["name"])}</a></b></p>'
                        f'<table cellspacing="0" cellpadding="0"><tr>{thumbs}</tr></table>')
        related = " · ".join(f'<a href="micro:{esc(r)}">{esc(self.content.micro_models[r].name)}</a>'
                             for r in m.related if r in self.content.micro_models)
        clinical = "".join(f"<p><b>{esc(t)}</b><br>{esc(x)}</p>" for t, x in m.clinical)
        tail = ""
        if clinical:
            tail += f"<h3>CLINICAL CORRELATIONS</h3>{clinical}"
        if hist:
            tail += "<h3>HISTOLOGY</h3>" + "".join(hist)
        if related:
            tail += f"<h3>RELATED MODELS</h3><p>{related}</p>"
        if len(sel) == 1:
            p = self.mds.parts[sel[0]]
            siblings = [q.name for q in self.mds.parts if q.group == p.group and q is not p]
            atlas = ""
            if getattr(p, "structures", None):
                atlas = (f"<p><a href=\"atlas:{esc('|'.join(p.structures))}\">Show {esc(p.name.lower())} in the "
                         f"atlas</a></p>")
            body = (f"<div class='crumb'>{esc(m.name)} › {esc(p.group)}</div>"
                    f"<p class='summary'>{esc(p.description)}</p>{atlas}"
                    + (f"<h3>ALSO IN {esc(p.group.upper())}</h3><p class='muted'>{esc(' · '.join(siblings))}</p>"
                       if siblings else "") + tail)
            self.info.show_html(f"<h1>{esc(p.name)}</h1>", body)
        else:
            groups = []
            for g in dict.fromkeys(q.group for q in self.mds.parts):
                names = " · ".join(esc(q.name) for q in self.mds.parts if q.group == g)
                groups.append(f"<p><b>{esc(g)}</b><br><span class='muted'>{names}</span></p>")
            body = (f"<p class='summary'>{esc(m.summary)}</p>"
                    f"<p class='muted'>Click any part in 3D or in the list to read about it. Use Cut-away, "
                    f"Separate layers and X-ray to see inside.</p>"
                    f"<h3>LAYERS &amp; PARTS</h3>{''.join(groups)}{tail}")
            self.info.show_html(f"<h1>{esc(m.name)}</h1>", body)
