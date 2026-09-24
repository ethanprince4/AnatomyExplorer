import json
import math
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QSettings, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QApplication, QColorDialog, QDockWidget, QFileDialog, QInputDialog, QLabel,
                               QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
                               QTabWidget, QToolButton, QVBoxLayout, QWidget, QDialog, QHBoxLayout)

from .actions import ActionRegistry
from .config import APP_NAME, DEFAULT_SETTINGS, ORG_NAME
from .content import ContentIndex
from .search import SearchIndex
from .state import SceneState
from .ui.info_panel import InfoPanel
from .ui.search_panel import SearchPanel
from .ui.settings_dialog import SettingsDialog
from .ui.systems_panel import RegionsPanel, SystemsPanel
from .ui.theme import apply_theme
from .ui.tree_panel import TreePanel
from .ui.view_panel import DISSECTION_STOPS, ViewPanel
from .viewport import VIEWS, Viewport


class MainWindow(QMainWindow):
    def __init__(self, ds, script=None):
        super().__init__()
        self._borderless = False        # before anything that can reach the event filter
        self._pre_borderless = None
        self.ds = ds
        self.setWindowTitle(APP_NAME)
        self.qsettings = QSettings(ORG_NAME, APP_NAME)
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            saved = json.loads(self.qsettings.value("view_settings", "{}"))
            self.settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
        except (TypeError, ValueError):
            pass
        apply_theme(QApplication.instance(), float(self.settings["ui_scale"]))
        self.state = SceneState(ds, self.settings)
        self.index = SearchIndex(ds)
        self.content = ContentIndex(ds)
        self.index.add_content(self.content)
        self.history = []
        self.history_pos = -1
        self._navigating = False
        self.settings_dialog = None
        self.micro_tabs = {}
        self.sketchfab_panel = None

        # ---------------------------------------------------------------- center
        self.viewport = Viewport(ds, self.state, self.settings)
        self.radiology_panel = None
        self.anatomy_tab = QSplitter(Qt.Horizontal)
        self.anatomy_tab.setChildrenCollapsible(False)
        self.anatomy_tab.gl_widget = self.viewport      # so anything asking the tab for its 3D view still works
        try:
            from .radiology import load_cases
            from .ui.radiology import RadiologyPanel
            self.radiology_cases = load_cases()
            if self.radiology_cases:
                self.radiology_panel = RadiologyPanel()
                self.radiology_panel.hide()
                self.anatomy_tab.addWidget(self.radiology_panel)
        except (ImportError, OSError, ValueError):
            self.radiology_cases = []
        self.anatomy_tab.addWidget(self.viewport)
        self.center = QTabWidget()
        self.center.setDocumentMode(True)
        self.center.setTabsClosable(True)
        self.center.setTabBarAutoHide(True)
        self.center.addTab(self.anatomy_tab, "3D Anatomy")
        self.center.tabBar().setTabButton(0, self.center.tabBar().ButtonPosition.RightSide, None)
        self.center.tabCloseRequested.connect(self._close_center_tab)
        self.center.currentChanged.connect(self._center_changed)
        self.setCentralWidget(self.center)

        # ---------------------------------------------------------------- left dock
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self.search = SearchPanel(ds, self.index)
        ll.addWidget(self.search)
        self.tabs = QTabWidget()
        self.systems = SystemsPanel(ds, self.state)
        self.regions = RegionsPanel(ds, self.state)
        self.tree = TreePanel(ds, self.state)
        self.view_panel = ViewPanel(self.settings, self.viewport)
        self.tabs.addTab(self.systems, "Systems")
        self.tabs.addTab(self.regions, "Regions")
        self.tabs.addTab(self.tree, "Tree")
        self.histology_panel = None
        try:
            from .ui.histology import HistologyBrowser
            self.histology_panel = HistologyBrowser(ds, self.content)
            self.tabs.addTab(self.histology_panel, "Histology")
            self.histology_panel.imageRequested.connect(self.open_histology)
            self.histology_panel.structuresRequested.connect(self._histology_structures)
            self.histology_panel.microRequested.connect(self.open_micro)
        except ImportError:
            pass
        self._attachment_tint = []
        self.radiology_browser = None
        if self.radiology_panel is not None:
            from .ui.radiology import RadiologyBrowser
            self.radiology_browser = RadiologyBrowser(self.radiology_cases)
            self.tabs.addTab(self.radiology_browser, "Radiology")
            self.radiology_browser.caseChosen.connect(self.open_radiology)
            self.index.add_radiology(self.radiology_cases)
        self.lessons_panel = None
        try:
            from .lessons import Resolver, load_lessons
            from .ui.lessons import LessonsPanel
            lessons = load_lessons()
            if lessons:
                self.lesson_resolver = Resolver(ds, self.index)
                self.lessons_panel = LessonsPanel(lessons)
                self.tabs.addTab(self.lessons_panel, "Lessons")
                self.lessons_panel.stepRequested.connect(self.apply_lesson_step)
                self.lessons_panel.lessonClosed.connect(self._lesson_closed)
                self.lessons_panel.lessonOpened.connect(self._remember_lesson)
                self.lessons_panel.quizRequested.connect(self.quiz_lesson)
                self.lessons_panel.linkActivated.connect(self.on_link)
                from .micro.registry import MODELS as MICRO_MODELS
                self.lessons_panel.set_reference_titles(
                    micro={k: m.name for k, m in MICRO_MODELS.items()},
                    histo={k: v.get("name", k) for k, v in self.content.tissues.items()},
                    rad={c.id: c.title for c in self.radiology_cases})
                self.index.add_lessons(lessons)
        except (ImportError, OSError, ValueError):
            self.lessons_panel = None
        from .sketchfab import SketchfabIndex, load_catalog
        from .lessons import Resolver as _Resolver
        self.sketchfab_models = load_catalog()
        if getattr(self, "lesson_resolver", None) is None:
            self.lesson_resolver = _Resolver(ds, self.index)
        self.sketchfab = SketchfabIndex(ds, self.sketchfab_models, self.lesson_resolver)
        self.index.add_sketchfab(self.sketchfab_models)
        self.tabs.addTab(self.view_panel, "View")
        ll.addWidget(self.tabs, 1)
        self.left_layout = ll
        self.left_dock = QDockWidget("EXPLORE")
        self.left_dock.setObjectName("explore_dock")
        self.left_dock.setWidget(left)
        self.left_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                                   QDockWidget.DockWidgetClosable)
        left.setMinimumWidth(330)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock)

        # ---------------------------------------------------------------- right dock
        self.info = InfoPanel(ds, self.content)
        self.info.n_radiology = len(self.radiology_cases)
        self.info.n_lessons = len(self.lessons_panel.lessons) if self.lessons_panel is not None else 0
        self.info.set_font_scale(float(self.settings["details_scale"]))
        self.info.sketchfab = self.sketchfab
        from .relations import RelationsIndex
        self.relations = RelationsIndex(ds)
        self.info.relations = self.relations
        from .depth import DepthIndex
        self.depth_index = DepthIndex(ds)
        from .section import SectionIndex
        self.section_index = SectionIndex(ds)
        self.viewport.section = self.section_index
        self.viewport.sectionChanged = lambda items: self.view_panel.show_section(items, ds)
        self.right_dock = QDockWidget("DETAILS")
        self.right_dock.setObjectName("details_dock")
        self.right_dock.setWidget(self.info)
        self.right_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                                    QDockWidget.DockWidgetClosable)
        self.info.setMinimumWidth(340)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)
        self.resizeDocks([self.left_dock, self.right_dock], [360, 420], Qt.Horizontal)

        self.cmds = ActionRegistry(self, self.viewport, self.qsettings)
        self._register_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        # ---------------------------------------------------------------- signals
        self.search.activated.connect(self.on_search_activated)
        self.search.queryActive.connect(self._on_query_active)
        self.viewport.structureClicked.connect(self.on_structure_clicked)
        self.viewport.structureDoubleClicked.connect(self.on_structure_double_clicked)
        self.viewport.contextMenuRequested.connect(self.on_context_menu)
        self.viewport.hoverChanged.connect(self._on_hover)
        self.viewport.frameTimed.connect(self._on_frame)
        self.viewport.glReady.connect(self._on_gl_ready)
        self.viewport.historyRequested.connect(self.navigate)
        self.tree.nodeActivated.connect(self.on_node_activated)
        self.tree.nodeAction.connect(self.on_node_action)
        self.info.linkActivated.connect(self.on_link)
        self.view_panel.settingChanged.connect(self.on_setting)
        self.view_panel.clipChanged.connect(self.viewport.update)
        self.view_panel.clipChanged.connect(self.viewport.refresh_section)
        self.view_panel.depthChanged.connect(self.on_depth_changed)
        self.viewport.measureChanged.connect(
            lambda text: self.statusBar().showMessage(text, 0) if text else self.statusBar().clearMessage())
        self.view_panel.sectionPicked.connect(lambda sid: self.select_and_focus([sid], frame=False))
        if self.radiology_panel is not None:
            self.radiology_panel.structuresPicked.connect(self.on_radiology_pick)
            self.radiology_panel.sceneRequested.connect(lambda case: self.apply_scene(case.scene))
            self.radiology_panel.closeRequested.connect(self.close_radiology)
            self.radiology_panel.caseStepped.connect(self.step_radiology)
        self.state.visibility_changed.connect(self.viewport.refresh_section)
        self.view_panel.settingsRequested.connect(self.open_settings)
        self.state.visibility_changed.connect(self._update_counts)
        self.state.selection_changed.connect(self._on_selection_changed)

        self._default_window_state = self.saveState()
        geo = self.qsettings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            scr = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(int(scr.width() * 0.88), int(scr.height() * 0.88))
        st = self.qsettings.value("window_state")
        if st is not None:
            self.restoreState(st)
        self.dock_side_panels()
        self._update_counts()
        self._script = [c.strip() for c in script.split(";") if c.strip()] if script else None
        self._restore_pending = bool(self.settings.get("restore_session")) and not script
        if str(self.qsettings.value("borderless", "0")).lower() in ("1", "true"):
            QTimer.singleShot(0, lambda: self.set_borderless(True))

    # ------------------------------------------------------------------ actions, menus, toolbar
    def _register_actions(self):
        vp = self.viewport
        reg = self.cmds.register
        reg("search", self.search.focus_search)
        reg("settings", lambda: self.open_settings())
        reg("screenshot", lambda: self.screenshot())
        reg("export_figure", lambda: self.export_figure())
        reg("fullscreen", self.toggle_fullscreen)
        reg("borderless", self.toggle_borderless)
        for key in ("fullscreen", "borderless"):
            self.cmds.actions[key].setCheckable(True)
        reg("toggle_panels", self.toggle_panels)
        reg("escape", self.escape)
        reg("back", lambda: self.navigate(-1))
        reg("forward", lambda: self.navigate(1))
        reg("save_view", self.save_view_dialog)
        reg("histology_tab", self.show_histology_tab)
        reg("frame", lambda: self._sketchfab_cam("frame") or self.frame_selection())
        reg("reset_view", lambda: self._sketchfab_cam("reset_view") or vp.reset_view())
        for v in VIEWS:
            reg(f"view_{v}", lambda _=False, n=v: self._sketchfab_cam("set_view", n) or vp.set_view(n))
        reg("orbit_left", lambda: vp.key_orbit(1, 0))
        reg("orbit_right", lambda: vp.key_orbit(-1, 0))
        reg("orbit_up", lambda: vp.key_orbit(0, 1))
        reg("orbit_down", lambda: vp.key_orbit(0, -1))
        reg("zoom_in", lambda: vp.key_zoom(1))
        reg("zoom_out", lambda: vp.key_zoom(-1))
        self.auto_rotate_action = reg("auto_rotate", self.toggle_auto_rotate)
        self.auto_rotate_action.setCheckable(True)
        reg("hide", self.hide_selection)
        reg("isolate", self.isolate_selection)
        self.xray_action = reg("xray", self.toggle_xray)
        self.xray_action.setCheckable(True)
        reg("both_sides", self.select_both_sides)
        reg("show_all", self.show_all)
        reg("default_visibility", self.reset_visibility)
        reg("undo", self.undo)
        reg("landmarks", lambda: self.on_setting("show_landmarks", not self.settings["show_landmarks"], sync=True))
        reg("color_mode", lambda: self.on_setting("color_mode", (int(self.settings["color_mode"]) + 1) % 3, sync=True))
        self.measure_action = reg("measure", self.toggle_measure)
        self.measure_action.setCheckable(True)
        reg("peel_in", lambda: self.view_panel.step_depth(1))
        reg("peel_out", lambda: self.view_panel.step_depth(-1))
        reg("peel_reset", lambda: self.view_panel.set_depth(0.0, False))
        reg("clip_sagittal", lambda: self.view_panel.toggle_clip(0))
        reg("clip_coronal", lambda: self.view_panel.toggle_clip(1))
        reg("clip_transverse", lambda: self.view_panel.toggle_clip(2))
        reg("note", self.edit_note)
        reg("lessons", lambda: self.show_lessons())
        reg("radiology", lambda: self.show_radiology())
        try:
            from .ui.quiz import QuizController
            self.quiz = QuizController(self)
            reg("quiz", self.quiz.toggle)
        except ImportError:
            self.quiz = None

    def _build_menus(self):
        a = self.cmds.actions
        mb = self.menuBar()
        mb.installEventFilter(self)      # so a borderless window can still be dragged by its menu bar
        f = mb.addMenu("&File")
        f.addAction(a["screenshot"])
        f.addAction(a["export_figure"])
        f.addAction(a["settings"])
        f.addSeparator()
        f.addAction("Exit", self.close)

        v = mb.addMenu("&View")
        self.left_dock.toggleViewAction().setText("Explore panel")
        self.right_dock.toggleViewAction().setText("Details panel")
        v.addAction(self.left_dock.toggleViewAction())
        v.addAction(self.right_dock.toggleViewAction())
        v.addAction(a["toggle_panels"])
        v.addAction(a["fullscreen"])
        v.addAction(a["borderless"])
        v.addAction("Dock the side panels", self.dock_side_panels)
        v.addAction("Reset panel layout", self.reset_layout)
        v.addSeparator()
        cam = v.addMenu("Camera")
        for key in VIEWS:
            cam.addAction(a[f"view_{key}"])
        cam.addSeparator()
        cam.addAction(a["frame"])
        cam.addAction(a["reset_view"])
        cam.addAction(a["auto_rotate"])
        colors = v.addMenu("Colors")
        self.color_group = QActionGroup(self)
        self.color_actions = []
        for i, name in enumerate(("Realistic", "Distinct segments", "By body system")):
            act = colors.addAction(name, lambda idx=i: self.on_setting("color_mode", idx, sync=True))
            act.setCheckable(True)
            self.color_group.addAction(act)
            self.color_actions.append(act)
        self.color_actions[int(self.settings["color_mode"])].setChecked(True)
        colors.addSeparator()
        colors.addAction(a["color_mode"])
        clips = v.addMenu("Cross-sections")
        clips.addAction(a["clip_sagittal"])
        clips.addAction(a["clip_coronal"])
        clips.addAction(a["clip_transverse"])
        clips.addAction("Clear cross-sections", self.view_panel.reset_clips)
        v.addAction(a["landmarks"])
        v.addAction(a["measure"])
        dis = v.addMenu("Dissection")
        dis.addAction(a["peel_in"])
        dis.addAction(a["peel_out"])
        dis.addAction(a["peel_reset"])
        for pct, label in DISSECTION_STOPS:
            dis.addAction(f"{label}  ({pct * 100:.0f}%)", lambda _=False, p=pct: self.view_panel.set_depth(p))

        s = mb.addMenu("&Selection")
        for key in ("back", "forward", None, "frame", "hide", "isolate", "xray", "both_sides", None, "show_all",
                    "default_visibility", "undo", "escape"):
            if key is None:
                s.addSeparator()
            else:
                s.addAction(a[key])

        self.views_menu = mb.addMenu("Saved &views")
        self.views_menu.aboutToShow.connect(self._fill_views_menu)

        st = mb.addMenu("S&tudy")
        if self.lessons_panel is not None:
            st.addAction(a["lessons"])
        if self.radiology_browser is not None:
            st.addAction(a["radiology"])
        st.addAction(a["histology_tab"])
        if self.sketchfab_models:
            st.addAction(f"Online 3D models (Sketchfab, {len(self.sketchfab_models)})…", lambda: self.open_sketchfab())
            local = [m for m in self.sketchfab_models if m.local]
            if local:
                sub = st.addMenu(f"Downloaded 3D models ({len(local)})")
                for m in sorted(local, key=lambda x: x.name.lower()):
                    sub.addAction(m.name, lambda _=False, u=m.uid: self.open_local_model(u))
        if "quiz" in a:
            st.addAction(a["quiz"])
        st.addAction(a["note"])
        st.addAction("All my notes…", self.show_all_notes)
        st.addSeparator()
        st.addAction("My progress…", self.show_progress)

        h = mb.addMenu("&Help")
        h.addAction("Keyboard shortcuts…", lambda: self.open_settings(page=3))
        h.addAction("About", self.about)

    def _build_toolbar(self):
        a = self.cmds.actions
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)

        def add(text, action, tip=None):
            action.setIconText(text)
            keys = [s.toString(QKeySequence.NativeText) for s in action.shortcuts()]
            action.setToolTip((tip or action.text()) + (f" ({', '.join(keys)})" if keys else ""))
            tb.addAction(action)
            return action

        add("◀", a["back"], "Back")
        add("▶", a["forward"], "Forward")
        tb.addSeparator()
        for key in VIEWS:
            add(key.capitalize(), a[f"view_{key}"])
        tb.addSeparator()
        add("Frame", a["frame"])
        add("Reset view", a["reset_view"])
        tb.addSeparator()
        add("Hide", a["hide"])
        add("Isolate", a["isolate"])
        self.xray_tb = add("X-ray", a["xray"])
        add("Show all", a["show_all"])
        add("Default", a["default_visibility"])
        add("Undo", a["undo"])
        tb.addSeparator()
        dissect_btn = QToolButton()
        dissect_btn.setText("Dissect ▾")
        dissect_btn.setToolTip("Peel the body apart layer by layer")
        dissect_btn.setPopupMode(QToolButton.InstantPopup)
        dm = QMenu(dissect_btn)
        dm.addAction(a["peel_in"])
        dm.addAction(a["peel_out"])
        dm.addAction(a["peel_reset"])
        dm.addSeparator()
        for pct, label in DISSECTION_STOPS:
            dm.addAction(f"{label}  ({pct * 100:.0f}%)", lambda _=False, p=pct: self.view_panel.set_depth(p))
        dissect_btn.setMenu(dm)
        tb.addWidget(dissect_btn)
        clip_btn = QToolButton()
        clip_btn.setText("Cross-section ▾")
        clip_btn.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(clip_btn)
        for key in ("clip_sagittal", "clip_coronal", "clip_transverse"):
            m.addAction(a[key])
        m.addSeparator()
        m.addAction("Clear cross-sections", self.view_panel.reset_clips)
        m.addSeparator()
        m.addAction("Quiz me on this section", self.quiz_section)
        clip_btn.setMenu(m)
        tb.addWidget(clip_btn)
        views_btn = QToolButton()
        views_btn.setText("Saved views ▾")
        views_btn.setPopupMode(QToolButton.InstantPopup)
        views_btn.setMenu(self.views_menu)
        tb.addWidget(views_btn)
        self.measure_tb = add("Measure", a["measure"], "Measure distances between two points")
        tb.addSeparator()
        if self.lessons_panel is not None:
            add("Lessons", a["lessons"])
        if self.radiology_browser is not None:
            add("Radiology", a["radiology"])
        if "quiz" in a:
            add("Quiz", a["quiz"])
        add("Screenshot", a["screenshot"])
        add("⚙ Settings", a["settings"])

    def _build_statusbar(self):
        sb = self.statusBar()
        self.hover_label = QLabel("")
        self.sel_label = QLabel("")
        self.count_label = QLabel("")
        self.perf_label = QLabel("")
        sb.addWidget(self.hover_label, 1)
        sb.addPermanentWidget(self.sel_label)
        sb.addPermanentWidget(self.count_label)
        sb.addPermanentWidget(self.perf_label)
        self._frame_times = []
        self._last_perf = 0.0

    # ------------------------------------------------------------------ status
    def _on_gl_ready(self):
        self.relations.start()
        self.depth_index.start()
        self.section_index.start()
        self._depth_timer = QTimer(self)
        self._depth_timer.timeout.connect(self._depth_ready)
        self._depth_timer.start(150)
        self.perf_label.setToolTip(self.viewport.gl_info)
        if self._restore_pending:
            QTimer.singleShot(50, self.restore_session)
        if self._script:
            QTimer.singleShot(400, self._run_script)

    def _depth_ready(self):
        """Poll the two background indices and switch their features on as they land."""
        done = True
        if self.state.depth is None:
            if self.depth_index.depth is not None:
                self.state.depth = self.depth_index.depth
                self.info.depth = self.depth_index.depth
                self.view_panel.enable_depth(True)
            elif not getattr(self.depth_index, "failed", False):
                done = False
        if self.section_index.ready:
            self.viewport.refresh_section()
            self.viewport.update()
        else:
            done = False
        if done:
            self._depth_timer.stop()

    def on_depth_changed(self, cut, band):
        first = self.state.depth_cut == 0.0 and self.state.depth_band == 0.0
        if first and (cut > 0.0 or band > 0.0):
            self.state.push_undo()
        self.state.set_depth(cut, band)
        if self.state.depth is not None:
            peeled, visible = self.state.depth_counts()
            if cut > 0.0 or band > 0.0:
                self.statusBar().showMessage(f"Dissection {cut * 100:.0f}% deep · {peeled:,} structures removed · "
                                             f"{visible:,} visible", 4000)

    def _on_frame(self, ms):
        if not self.settings.get("show_perf", True):
            self.perf_label.setText("")
            return
        self._frame_times.append(ms)
        now = time.perf_counter()
        if now - self._last_perf > 0.5:
            avg = sum(self._frame_times) / len(self._frame_times)
            self.perf_label.setText(f"{avg:.1f} ms/frame")
            self._frame_times.clear()
            self._last_perf = now

    def _on_hover(self, sid):
        if self.quiz is not None and self.quiz.names_hidden():
            self.hover_label.setText("")  # the status bar must not answer the question for you
            return
        if sid < 0:
            self.hover_label.setText("")
            return
        s = self.ds.structures[sid]
        extra = f"  ·  {s['latin']}" if s.get("latin") else ""
        side = f" ({s['side'].lower()})" if s["side"] else ""
        self.hover_label.setText(f"{s['name']}{side}{extra}")

    def _update_counts(self):
        tris, n = self.state.visible_triangle_count()
        self.count_label.setText(f"{n:,} structures · {tris / 1e6:.2f} M triangles visible")
        self.xray_action.setChecked(self.state.ghost_focus is not None)

    def _on_selection_changed(self):
        n = len(self.state.selected)
        self.sel_label.setText(f"{n} selected" if n else "")

    def _on_query_active(self, active):
        self.tabs.setVisible(not active)
        self.left_layout.setStretchFactor(self.search, 1 if active else 0)

    def on_setting(self, key, value, sync=False):
        if key in ("section_labels", "max_section_labels"):
            self.settings[key] = value
            self.viewport.refresh_section()
            self.viewport.update()
        self.settings[key] = value
        if key == "color_mode":
            self.state.render_changed.emit()
            if hasattr(self, "color_actions"):
                self.color_actions[int(value)].setChecked(True)
        elif key == "ui_scale":
            apply_theme(QApplication.instance(), float(value))
        elif key == "details_scale":
            self.info.set_font_scale(float(value))
        elif key == "fov":
            self.viewport.camera.fov = float(value)
        if sync:
            self.view_panel.sync_from_settings()
            if self.settings_dialog is not None:
                self.settings_dialog.close()
                self.settings_dialog = None
        self.viewport.update()

    # ------------------------------------------------------------------ settings / window
    def open_settings(self, page=None):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self.settings, self.cmds, self)
            self.settings_dialog.settingChanged.connect(self._dialog_setting)
        if isinstance(page, int):
            self.settings_dialog.tabs.setCurrentIndex(page)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _dialog_setting(self, key, value):
        self.on_setting(key, value)
        self.view_panel.sync_from_settings()

    def eventFilter(self, obj, event):
        """With no title bar, the empty stretch of the menu bar becomes the place you drag the window by."""
        if (self._borderless and obj is self.menuBar() and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton and self.menuBar().actionAt(event.position().toPoint()) is None):
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ window mode
    def _work_area(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _sync_window_actions(self):
        self.cmds.actions["fullscreen"].setChecked(self.isFullScreen())
        self.cmds.actions["borderless"].setChecked(self._borderless)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.set_borderless(False)          # the two modes are alternatives, not layers
            self.showFullScreen()
        self._sync_window_actions()

    def toggle_borderless(self):
        self.set_borderless(not self._borderless)

    def set_borderless(self, on):
        """A frameless window filling the screen's work area.

        Real fullscreen takes the whole screen and puts the window above the shell, so the taskbar, the clock
        and anything else you might want are out of reach until you come back out of it. This gives up the
        title bar instead of giving up the desktop: the same working area, minus about thirty pixels of window
        chrome, with every other window still where it was."""
        on = bool(on)
        if on == self._borderless:
            return
        if on:
            if self.isFullScreen():
                self.showNormal()
            # the QByteArray is what QSettings wants; the QRect restores without the frame drift that
            # saveGeometry/restoreGeometry accumulates every time you toggle
            self._pre_borderless = (self.saveGeometry(), self.geometry(), self.isMaximized())
            if self.isMaximized():
                self.showNormal()               # a maximised window ignores setGeometry
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.show()
            self.setGeometry(self._work_area())
            self.statusBar().showMessage("Borderless window — Shift+F11 to bring the title bar back, "
                                         "drag the empty part of the menu bar to move it", 6000)
        else:
            self.setWindowFlag(Qt.FramelessWindowHint, False)
            self.show()
            _blob, rect, was_maximised = self._pre_borderless or (None, None, False)
            if was_maximised:
                self.showMaximized()
            elif rect is not None:
                # once the frame is back: setting it in the same tick is measured against the old frame and
                # the window walks down the screen a title bar at a time
                QTimer.singleShot(0, lambda r=rect: self.setGeometry(r))
            self._pre_borderless = None
        self._borderless = on
        self.qsettings.setValue("borderless", "1" if on else "0")
        self._sync_window_actions()
        self.raise_()
        self.activateWindow()

    def toggle_panels(self):
        visible = self.left_dock.isVisible() or self.right_dock.isVisible()
        self.left_dock.setVisible(not visible)
        self.right_dock.setVisible(not visible)

    def dock_side_panels(self):
        """Put a panel that was left floating back on its side of the window.

        A dock widget floats if its title bar is double-clicked or dragged a little off the edge, and the
        layout is saved on exit - so one stray gesture is enough to make the Details panel open as a separate
        window from then on. Explore and Details are side panels; that is how they open."""
        moved = False
        for dock, area in ((self.left_dock, Qt.LeftDockWidgetArea), (self.right_dock, Qt.RightDockWidgetArea)):
            if dock.isFloating():
                dock.setFloating(False)
                moved = True
            if self.dockWidgetArea(dock) == Qt.NoDockWidgetArea:
                self.addDockWidget(area, dock)
                moved = True
        if moved:
            self.resizeDocks([self.left_dock, self.right_dock], [360, 420], Qt.Horizontal)
        return moved

    def reset_layout(self):
        self.restoreState(self._default_window_state)
        self.left_dock.show()
        self.right_dock.show()
        self.dock_side_panels()

    def toggle_auto_rotate(self):
        bridge = self._active_bridge()
        on = bridge.toggle_auto_rotate() if bridge is not None else self.viewport.toggle_auto_rotate()
        self.auto_rotate_action.setChecked(on)

    def _active_bridge(self):
        """The Sketchfab camera bridge, when it is what the user is looking at and driving."""
        p = self.sketchfab_panel
        if p is not None and self.center.currentWidget() is p and p.bridge.active:
            return p.bridge
        return None

    def _sketchfab_cam(self, method, *args):
        """Send a camera command to the embedded model instead of the atlas if that is the view in front.
        Returns True when it was handled, so the atlas's own version is skipped."""
        bridge = self._active_bridge()
        if bridge is None:
            return False
        getattr(bridge, method)(*args)
        return True

    def about(self):
        QMessageBox.about(self, APP_NAME, f"<h3>{APP_NAME}</h3><p>Personal 3D anatomy atlas.</p><p>"
                          + "<br>".join(self.ds.attribution) + "</p>")

    def _close_center_tab(self, index):
        if index == 0:
            return
        w = self.center.widget(index)
        self.center.removeTab(index)
        gl = getattr(w, "gl_widget", None)
        if gl is not None and getattr(gl, "renderer", None) is not None:
            gl.makeCurrent()                # shared contexts keep GPU memory alive until it is freed explicitly
            try:
                gl.renderer.release()
            finally:
                gl.renderer = None
                gl.doneCurrent()
        for k, v in list(self.micro_tabs.items()):
            if v is w:
                del self.micro_tabs[k]
        if w is self.sketchfab_panel:
            self.sketchfab_panel = None
        w.deleteLater()

    def _center_changed(self, index):
        w = self.center.widget(index)
        if hasattr(w, "on_activated"):
            w.on_activated(self.info)
        elif w in (self.viewport, self.anatomy_tab) and self.state.selected:
            self.info.show_structures(self.state.selected)

    # ------------------------------------------------------------------ history
    def _record(self, entry):
        if self._navigating:
            return
        if 0 <= self.history_pos < len(self.history) and self.history[self.history_pos] == entry:
            return
        del self.history[self.history_pos + 1:]
        self.history.append(entry)
        if len(self.history) > 200:
            self.history.pop(0)
        self.history_pos = len(self.history) - 1

    def navigate(self, step):
        pos = self.history_pos + step
        if not (0 <= pos < len(self.history)):
            return
        self.history_pos = pos
        kind, payload = self.history[pos]
        self._navigating = True
        try:
            if self.center.currentIndex() != 0:
                self.center.setCurrentIndex(0)
            if kind == "sids":
                self.select_and_focus(list(payload), xray=self.state.ghost_focus is not None)
            elif kind == "node":
                self.on_node_activated(payload, xray=self.state.ghost_focus is not None)
            elif kind == "lm":
                self.focus_landmark(payload)
        finally:
            self._navigating = False

    # ------------------------------------------------------------------ selection logic
    def select_and_focus(self, sids, xray=False, frame=True, info=True):
        sids = [int(x) for x in sids]
        if not sids:
            return
        self.center.setCurrentIndex(0)
        self.state.force_show(sids)
        self.state.select(sids)
        if xray:
            self.state.set_ghost_focus(sids)
        if frame:
            self.viewport.frame_structures(sids)
        self.viewport.landmark_hosts = sids if len(sids) <= 2 else []
        self.viewport.focus_landmark = None
        if info:
            self.info.show_structures(sids)
        self.tree.reveal(sids[0])
        self._update_counts()
        self._record(("sids", tuple(sids)))

    def on_search_activated(self, entry):
        xray = bool(self.settings.get("xray_on_search", True))
        if entry.kind == "group":
            self.on_node_activated(entry.node, xray=xray)
        elif entry.kind == "tissue":
            self.open_histology(entry.node, 0)
        elif entry.kind == "micro":
            self.open_micro(entry.node)
        elif entry.kind == "sketchfab":
            m = next((x for x in self.sketchfab_models if x.uid == entry.node), None)
            if m is not None and m.local:
                self.open_local_model(entry.node)
            else:
                self.open_sketchfab(entry.node)
        elif entry.kind == "lesson":
            self.show_lessons(entry.node)
        elif entry.kind == "radiology":
            self.show_radiology(entry.node)
        elif entry.kind == "clinical":
            self.select_and_focus(entry.sids, xray=xray)
            key = f"clin:{entry.title}"
            self.info._open[key] = True
            self.info._open["clinical"] = True
            self.info.show_structures(entry.sids)
        elif entry.kind == "landmark":
            self.focus_landmark(entry.landmark, xray=xray)
        else:
            self.select_and_focus(entry.sids, xray=xray)

    def focus_landmark(self, idx, xray=None):
        lm = self.ds.landmarks[idx]
        sid = lm["sid"]
        self.center.setCurrentIndex(0)
        if xray is None:
            xray = self.state.ghost_focus is not None
        self.state.force_show([sid])
        self.state.select([sid])
        if xray:
            self.state.set_ghost_focus([sid])
        self.viewport.landmark_hosts = [sid]
        self.viewport.focus_landmark = idx
        radius = float(np.linalg.norm(self.ds.bbox_max[sid] - self.ds.bbox_min[sid]) / 2)
        self.viewport.frame_point(lm["anchor"], max(min(radius * 0.7, 0.12), 0.03))
        self.info.show_landmark(idx)
        self.tree.reveal(sid)
        self._update_counts()
        self._record(("lm", idx))

    def on_node_activated(self, nid, xray=False):
        node = self.ds.nodes[nid]
        if "sid" in node:
            self.select_and_focus([node["sid"]], xray=xray)
            return
        self.center.setCurrentIndex(0)
        sids = self.ds.node_structures(nid)
        if node["kind"] == "system":
            vis = self.state.visible_mask()
            shown = [s for s in sids if vis[s]]
            self.state.clear_selection()
            if shown:
                self.viewport.frame_structures(shown)
            self.info.show_node(nid)
            return
        self.state.force_show(sids)
        self.state.select(sids)
        if xray:
            self.state.set_ghost_focus(sids)
        self.viewport.frame_structures(sids)
        self.viewport.landmark_hosts = []
        self.viewport.focus_landmark = None
        self.info.show_node(nid)
        self._update_counts()
        self._record(("node", nid))

    def on_node_action(self, nid, action):
        sids = self.ds.node_structures(nid)
        if action == "focus":
            self.on_node_activated(nid)
        elif action == "xray":
            self.on_node_activated(nid, xray=True)
        elif action == "isolate":
            self.state.select(sids)
            self.state.isolate(sids)
            self.viewport.frame_structures(sids)
        elif action == "hide":
            self.state.set_hidden(sids, True)
        elif action == "show":
            self.state.set_hidden(sids, False)

    def on_structure_clicked(self, sid, modifiers):
        if self.quiz is not None and self.quiz.handle_click(sid, modifiers):
            return
        add = bool(modifiers & Qt.ControlModifier)
        if sid < 0:
            if not add and self.state.clear_selection():
                self.viewport.landmark_hosts = []
                self.viewport.focus_landmark = None
                self.info.show_welcome()
            return
        targets = [sid]
        if self.settings.get("select_both_sides"):
            targets += self.ds.counterpart(sid)
        if add:
            self.state.select(targets, add=True)
        else:
            self.state.select(targets)
        sel = self.state.selected
        self.viewport.landmark_hosts = sel if len(sel) <= 2 else []
        self.viewport.focus_landmark = None
        if sel:
            self.info.show_structures(sel)
            self.tree.reveal(sid)
            if not add:
                self._record(("sids", tuple(sel)))
            if self.settings.get("click_action") == "Select and focus":
                self.viewport.frame_structures(sel)
        else:
            self.info.show_welcome()

    def on_structure_double_clicked(self, sid):
        if sid < 0 or (self.quiz is not None and self.quiz.active and self.quiz.current is not None):
            return
        action = self.settings.get("double_click_action", "Focus")
        targets = [sid] + (self.ds.counterpart(sid) if self.settings.get("select_both_sides") else [])
        if action == "Isolate":
            self.state.select(targets)
            self.state.isolate(targets)
            self.viewport.frame_structures(targets)
            self.info.show_structures(targets)
        else:
            self.select_and_focus(targets, xray=action == "X-ray focus")

    def select_both_sides(self):
        if self.state.selected:
            sids = set(self.state.selected)
            for s in list(sids):
                sids.update(self.ds.counterpart(s))
            self.select_and_focus(sorted(sids), xray=self.state.ghost_focus is not None, frame=False)

    def on_context_menu(self, sid, global_pos):
        if self.quiz is not None and self.quiz.handle_right_click(sid):
            return                        # in the hunt, right-click peels a structure away instead
        a = self.cmds.actions
        m = QMenu(self)
        if sid >= 0:
            if sid not in self.state.selected:
                self.on_structure_clicked(sid, Qt.NoModifier)
            s = self.ds.structures[sid]
            title = m.addAction(s["name"] + (f" ({s['side'].lower()})" if s["side"] else ""))
            title.setEnabled(False)
            m.addSeparator()
            for key in ("frame", "xray", "isolate", "hide"):
                m.addAction(a[key])
            if self.ds.counterpart(sid):
                m.addAction(a["both_sides"])
            sysidx = int(self.ds.system_of[sid])
            m.addAction(f"Hide {self.ds.systems[sysidx]['name']}", lambda: self.state.set_system(sysidx, False))
            models = self.content.micro_for_structures([sid])
            if models:
                sub = m.addMenu("Open microanatomy")
                for model in models:
                    sub.addAction(model.name, lambda mid=model.id: self.open_micro(mid))
            tissues = self.content.histology_for_structures([sid])
            if tissues:
                sub = m.addMenu("Open histology")
                for t in tissues:
                    sub.addAction(t["name"], lambda tid=t["id"]: self.open_histology(tid, 0))
            m.addSeparator()
            m.addAction(a["note"])
            m.addAction("Set color…", self.pick_color)
            m.addAction("Reset color", lambda: self.state.set_custom_color(self.state.selected, None))
            m.addAction("Copy name", lambda: QGuiApplication.clipboard().setText(s["name"]))
        else:
            for key in ("show_all", "default_visibility", "reset_view", "undo", "auto_rotate"):
                m.addAction(a[key])
        m.exec(global_pos)

    def pick_color(self):
        if not self.state.selected:
            return
        c = QColorDialog.getColor(parent=self, title="Structure color")
        if c.isValid():
            self.state.set_custom_color(self.state.selected, (c.redF(), c.greenF(), c.blueF()))

    def on_link(self, scheme, payload):
        xray = self.state.ghost_focus is not None
        if scheme == "url":
            QDesktopServices.openUrl(QUrl(payload))
        elif scheme == "sid":
            self.select_and_focus([int(payload)], xray=xray)
        elif scheme == "sids":
            self.select_and_focus([int(x) for x in payload.split(",") if x], xray=xray)
        elif scheme == "node":
            self.on_node_activated(payload, xray=xray)
        elif scheme == "lm":
            self.focus_landmark(int(payload))
        elif scheme == "histo":
            tid, _, idx = payload.partition("|")
            self.open_histology(tid, int(idx or 0))
        elif scheme == "micro":
            self.open_micro(payload)
        elif scheme == "rad":
            self.show_radiology(payload)
        elif scheme == "sfab":
            self.open_sketchfab(payload)
        elif scheme == "sfmodel":
            self.open_local_model(payload)
        elif scheme == "atlas":
            self._sketchfab_structures([n for n in payload.split("|") if n])
        elif scheme == "note":
            self.edit_note(payload)
        elif scheme == "attach":
            att = [int(x) for x in payload.split(",") if x]
            bones = sorted(set(self.ds.structures[x]["on"] for x in att if "on" in self.ds.structures[x]))
            self.state.force_show(att + bones)
            self.state.set_ghost_focus(att + bones)
            self.state.select(att)
            self.viewport.frame_structures(att + bones)
            self.viewport.landmark_hosts = []
            self.colour_attachments(att)
            self._update_counts()
        elif scheme == "act":
            if payload == "frame":
                self.frame_selection()
            elif payload == "xray":
                if self.state.selected:
                    self.state.set_ghost_focus(self.state.selected)
                    self._update_counts()
            elif payload == "isolate":
                self.isolate_selection()
            elif payload == "hide":
                self.hide_selection()
            elif payload == "show":
                if self.state.selected:
                    self.state.set_hidden(self.state.selected, False)
            elif payload == "both":
                self.select_both_sides()

    # ------------------------------------------------------------------ histology & microanatomy
    def show_histology_tab(self):
        if self.histology_panel is not None:
            self.left_dock.show()
            self.tabs.setCurrentWidget(self.histology_panel)

    def open_histology(self, tissue_id, index=0):
        try:
            from .ui.histology import HistologyViewer
        except ImportError:
            return
        tissue = self.content.tissues.get(tissue_id)
        if not tissue or not tissue.get("images"):
            self.statusBar().showMessage("No images downloaded for this tissue yet.", 4000)
            return
        viewer = self.micro_tabs.get("__histology__")
        if viewer is None:
            viewer = HistologyViewer(self.ds, self.content)
            viewer.structuresRequested.connect(self._histology_structures)
            self.micro_tabs["__histology__"] = viewer
            self.center.addTab(viewer, "Histology")
        viewer.show_tissue(tissue_id, index)
        self.center.setCurrentWidget(viewer)
        self.center.setTabText(self.center.indexOf(viewer), f"Histology · {self.content.tissues[tissue_id]['name']}")
        viewer.on_activated(self.info)

    def _histology_structures(self, names):
        sids = [s for n in names for s in self.ds.structures_named(n)]
        if sids:
            self.select_and_focus(sids, xray=True)

    def open_sketchfab(self, uid=None):
        """Sketchfab's own player for an online model, in a tab beside the atlas. Nothing is downloaded."""
        if not self.sketchfab_models:
            return
        if self.sketchfab_panel is None:
            try:
                from .ui.sketchfab_view import SketchfabPanel
            except ImportError:
                self.statusBar().showMessage("Online models need Qt WebEngine, which this Python install lacks.", 6000)
                return
            self.sketchfab_panel = SketchfabPanel(self.sketchfab_models, self.settings, self.cmds)
            self.sketchfab_panel.structuresRequested.connect(self._sketchfab_structures)
            self.sketchfab_panel.openLocal.connect(self.open_local_model)
            self.center.addTab(self.sketchfab_panel, "Sketchfab")
        self.center.setCurrentWidget(self.sketchfab_panel)
        if uid:
            self.sketchfab_panel.open(uid)

    def open_local_model(self, uid):
        """A downloaded Sketchfab model, drawn by the atlas's own renderer in a tab of its own - works offline."""
        key = f"sketchfab:{uid}"
        view = self.micro_tabs.get(key)
        if view is None:
            try:
                from .sketchfab_local import load_local
                from .ui.micro_view import MicroView
            except ImportError:
                return
            cm = next((m for m in self.sketchfab_models if m.uid == uid), None)
            try:
                model = load_local(uid, cm)
            except Exception as exc:                      # noqa: BLE001 - a bad curation file must not crash
                self.statusBar().showMessage(f"Could not open that model: {exc}", 8000)
                return
            if model is None:
                self.statusBar().showMessage("That model has not been downloaded (tools/fetch_sketchfab.py).", 5000)
                return
            self.statusBar().showMessage(f"Loading 3D model: {model.name}…")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            try:
                view = MicroView(model, self.content, self.settings)
            except Exception as exc:                      # noqa: BLE001 - a bad file must not take the app down
                self.statusBar().showMessage(f"Could not open {model.name}: {exc}", 8000)
                return
            finally:
                QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
            view.gl_widget.measureChanged.connect(
                lambda text: self.statusBar().showMessage(text, 0) if text else self.statusBar().clearMessage())
            view.openHistology.connect(self.open_histology)
            view.openMicro.connect(self.open_micro)
            view.openOnline.connect(self.open_sketchfab)
            self.micro_tabs[key] = view
            self.center.addTab(view, f"3D · {model.name}")
        self.center.setCurrentWidget(view)
        view.on_activated(self.info)

    def _sketchfab_structures(self, names):
        """'Show in the atlas': back to the 3D view with what the online model depicts selected and framed."""
        sids = self.lesson_resolver.resolve_all(names) if getattr(self, "lesson_resolver", None) else []
        if not sids:
            self.statusBar().showMessage("Nothing in the atlas matches this model.", 3000)
            return
        self.center.setCurrentIndex(0)
        self.state.force_show(sids)
        self.select_and_focus(sids, xray=True)

    def open_micro(self, model_id):
        try:
            from .ui.micro_view import MicroView
        except ImportError:
            return
        view = self.micro_tabs.get(model_id)
        if view is None:
            model = self.content.micro_models[model_id]
            # a model whose cache is missing or stale is rebuilt here, which can take several seconds
            self.statusBar().showMessage(f"Loading microanatomy model: {model.name}…")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            try:
                view = MicroView(model, self.content, self.settings)
            finally:
                QApplication.restoreOverrideCursor()
                self.statusBar().clearMessage()
            view.gl_widget.measureChanged.connect(
                lambda text: self.statusBar().showMessage(text, 0) if text else self.statusBar().clearMessage())
            view.openHistology.connect(self.open_histology)
            view.openMicro.connect(self.open_micro)
            self.micro_tabs[model_id] = view
            self.center.addTab(view, f"Micro · {model.name}")
        self.center.setCurrentWidget(view)
        view.on_activated(self.info)

    # ------------------------------------------------------------------ notes
    def _note_key(self, payload=None):
        if payload:
            return payload
        if self.state.selected:
            return self.ds.structures[self.state.selected[0]]["base"]
        return None

    def edit_note(self, payload=None):
        key = payload if isinstance(payload, str) and payload else self._note_key()
        if not key:
            self.statusBar().showMessage("Select a structure to attach a note to it.", 3000)
            return
        from .ui.notes import NoteDialog
        dlg = NoteDialog(key, self.content.notes.get(key, ""), self)
        if dlg.exec():
            self.content.set_note(key, dlg.text())
            self.info._rerender()

    def show_all_notes(self):
        from .ui.notes import AllNotesDialog
        dlg = AllNotesDialog(self.content, self)
        dlg.noteActivated.connect(lambda name: self._histology_structures([name]))
        dlg.exec()

    def show_progress(self):
        """Accuracy, the spaced-repetition schedule and the structures that keep catching you out."""
        import json

        from .config import ROOT
        from .ui.progress import ProgressDialog
        stats = {}
        path = ROOT / "data" / "user" / "quiz_stats.json"
        try:
            stats = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stats = {}
        lessons = self.lessons_panel.lessons if self.lessons_panel is not None else None
        lesson_progress = self.lessons_panel.progress if self.lessons_panel is not None else None
        ProgressDialog(stats, lessons, lesson_progress, self).exec()

    # ------------------------------------------------------------------ radiology
    def show_radiology(self, case_id=None):
        if self.radiology_browser is None:
            return
        self.tabs.setCurrentWidget(self.radiology_browser)
        self.left_dock.show()
        if case_id:
            self.open_radiology(case_id)
        elif self.radiology_panel.case is None and self.radiology_cases:
            self.open_radiology(self.radiology_cases[0].id)

    def open_radiology(self, case_id):
        """Show a radiograph beside the 3D view and set the model up to match it."""
        case = next((c for c in self.radiology_cases if c.id == case_id), None)
        if case is None or self.radiology_panel is None:
            return
        self.center.setCurrentIndex(0)
        self.radiology_panel.show_case(case)
        if not self.radiology_panel.isVisible():
            self.radiology_panel.show()
            total = max(self.anatomy_tab.width(), 800)
            self.anatomy_tab.setSizes([int(total * 0.42), int(total * 0.58)])
        self.apply_scene(case.scene)
        self.statusBar().showMessage(f"{case.title} — click a numbered label, or a line in its legend, to find it "
                                     "in 3D", 8000)

    def close_radiology(self):
        if self.radiology_panel is not None:
            self.radiology_panel.hide()

    def step_radiology(self, delta):
        panel = self.radiology_panel
        if panel is None or panel.case is None:
            return
        ids = [c.id for c in self.radiology_cases]
        i = (ids.index(panel.case.id) + delta) % len(ids)
        self.open_radiology(ids[i])

    def on_radiology_pick(self, names, frame=True):
        """A label on the radiograph was clicked: select the same thing in the model."""
        sids = self.lesson_resolver.resolve_all(names) if getattr(self, "lesson_resolver", None) else []
        if not sids:
            self.statusBar().showMessage("That label has no matching structure in the model.", 3000)
            return
        case = self.radiology_panel.case if self.radiology_panel is not None else None
        side = ((case.scene.get("side") if case else "") or "").lower()
        if side:                        # a film of one limb should not select and frame both of them
            sids = [s for s in sids if self.ds.structures[s]["side"].lower() in (side, "")] or sids
        self.state.force_show(sids)
        self.select_and_focus(sids, xray=bool(self.settings.get("xray_on_search", True)), frame=frame)

    # ------------------------------------------------------------------ lessons
    def show_lessons(self, lesson_id=None):
        if self.lessons_panel is None:
            return
        self.tabs.setCurrentWidget(self.lessons_panel)
        self.left_dock.show()
        if lesson_id:
            self.lessons_panel.open_lesson(lesson_id)

    def quiz_section(self):
        """Test yourself on everything the current cross-section passes through."""
        if self.quiz is None or not self.viewport.section_anchors:
            self.statusBar().showMessage("Turn on a cross-section first.", 4000)
            return
        bases = sorted({self.ds.structures[sid]["base"] for sid, _a, _w in self.viewport.section_anchors})
        if len(bases) < 4:
            self.statusBar().showMessage("This section does not cut through enough structures for a quiz.", 4000)
            return
        self.quiz.open()
        self.quiz.start(bases=bases)

    def quiz_lesson(self, lesson):
        """Start a quiz built from every structure the lesson pointed at."""
        if self.quiz is None:
            return
        names = []
        for step in lesson.steps:
            names.extend(step.get("focus", []))
            names.extend(step.get("show", []))
        sids = self.lesson_resolver.resolve_all(names)
        bases = sorted({self.ds.structures[s]["base"] for s in sids})
        if len(bases) < 4:
            self.statusBar().showMessage("This lesson does not name enough structures for a quiz.", 4000)
            return
        self.state.show_all()
        self.state.force_show(sids)
        self.quiz.open()
        self.quiz.start(bases=bases)

    def _remember_lesson(self, lesson):
        self.qsettings.setValue("last_lesson", lesson.id)

    def _lesson_closed(self):
        self.state.clear_ghost()
        self.state.clear_forced()
        self.view_panel.set_depth(0.0, False)
        self.view_panel.reset_clips()

    def apply_lesson_step(self, step):
        return self.apply_scene(step)

    def apply_scene(self, step):
        """Set the 3D view up from a scene description - used by guided lessons and radiology cases alike."""
        st, vp = self.state, self.viewport
        res = self.lesson_resolver
        st.push_undo()
        if "systems" in step:
            wanted = set(step["systems"])
            st.set_systems([s["key"] in wanted for s in self.ds.systems])
        if "regions" in step:
            wanted = set(step["regions"])
            st.set_regions([r["key"] in wanted for r in self.ds.regions])
        st.clear_ghost()
        st.clear_forced()
        if step.get("reset_clips", True):
            self.view_panel.reset_clips()
        self.view_panel.set_depth(float(step.get("dissect", 0.0)), bool(step.get("layer_only", False)))
        side = (step.get("side") or "").lower()

        def pick(names):
            sids = res.resolve_all(names)
            if side:                                   # a lesson can keep to one side so the view zooms in properly
                one = [s for s in sids if self.ds.structures[s]["side"].lower() in (side, "")]
                return one or sids
            return sids

        show = pick(step.get("show", []))
        focus = pick(step.get("focus", []))
        if show:
            st.set_hidden(show, False, undo=False)
            st.force_show(show)
        if focus:
            st.set_hidden(focus, False, undo=False)
            st.force_show(focus)
        if step.get("isolate") and (focus or show):
            st.isolate(focus or show)
        ghost = pick(step.get("ghost_focus", []))
        if ghost:
            # the radiographic look: keep these solid and let everything in front of them go translucent
            st.force_show(ghost)
            st.set_ghost_focus(ghost)
        clip = step.get("clip")
        if clip:
            self.view_panel.set_clip(int(clip[0]), True, float(clip[1]), bool(clip[2]) if len(clip) > 2 else False)
        want_view = step.get("view")
        if clip:
            # a sectioned step should frame the whole cut, not just whatever it also selected
            vp.refresh_section()
            cut = [sid for sid, _anchor, _w in vp.section_anchors]
            if cut and step.get("frame", True) and not step.get("frame_on"):
                vp.frame_structures(sorted(set(cut + focus)), view=want_view)
                want_view = None
        if focus:
            st.select(focus)
            vp.landmark_hosts = focus if len(focus) <= 2 else []
            self.info.show_structures(focus)
            if step.get("xray", True):
                st.set_ghost_focus(focus)
            if step.get("frame", True) and not clip:
                vp.frame_structures(focus, view=want_view)   # one move: swing round and zoom in together
                want_view = None
        frame_on = pick(step.get("frame_on", []))
        if frame_on:
            vp.frame_structures(frame_on, view=want_view)
            want_view = None
        if want_view:
            vp.set_view(want_view)
        cam = step.get("camera")
        if cam:
            c = vp.camera
            c.animate_to(np.array(cam[0], dtype=float), float(cam[1]), math.radians(float(cam[2])),
                         math.radians(float(cam[3])), vp.duration())
        lm = res.landmark(step["landmark"]) if step.get("landmark") else None
        vp.focus_landmark = lm
        if step.get("micro"):
            self.open_micro(step["micro"])
        elif step.get("histology"):
            self.open_histology(step["histology"], 0)
        elif self.center.currentIndex() != 0:
            self.center.setCurrentIndex(0)
        missing = [n for n in list(step.get("show", [])) + list(step.get("focus", [])) if not res.resolve(n)]
        if missing:
            self.statusBar().showMessage("Lesson step could not find: " + ", ".join(missing), 4000)
        self._update_counts()
        vp.update()

    # ------------------------------------------------------------------ saved views & session
    def capture_view(self):
        st = self.state
        cam = self.viewport.camera
        vp = self.viewport
        return {
            "camera": [cam.target.tolist(), cam.distance, cam.yaw, cam.pitch],
            "hidden": np.nonzero(st.hidden)[0].tolist(),
            "forced": np.nonzero(st.forced)[0].tolist(),
            "isolated": None if st.isolated is None else np.nonzero(st.isolated)[0].tolist(),
            "ghost": None if st.ghost_focus is None else np.nonzero(st.ghost_focus)[0].tolist(),
            "system_on": st.system_on.tolist(),
            "subsystem_on": st.subsystem_on.tolist(),
            "region_on": st.region_on.tolist(),
            "selected": list(st.selected),
            "clip": [list(vp.clip_on), list(vp.clip_pos), list(vp.clip_flip)],
            "dissection": [st.depth_cut, st.depth_band],
            "custom_colors": {str(k): list(v) for k, v in st.custom_colors.items()},
        }

    def apply_view(self, data, animate=True):
        st = self.state
        n = self.ds.n
        try:
            def mask(idxs):
                m = np.zeros(n, dtype=bool)
                m[[i for i in idxs if 0 <= i < n]] = True
                return m
            st.push_undo()
            st.hidden = mask(data.get("hidden", []))
            st.forced = mask(data.get("forced", []))
            st.isolated = None if data.get("isolated") is None else mask(data["isolated"])
            st.ghost_focus = None if data.get("ghost") is None else mask(data["ghost"])
            if len(data.get("system_on", [])) == len(st.system_on):
                st.system_on[:] = data["system_on"]
            if len(data.get("subsystem_on", [])) == len(st.subsystem_on):
                st.subsystem_on[:] = data["subsystem_on"]
            if len(data.get("region_on", [])) == len(st.region_on):
                st.region_on[:] = data["region_on"]
            st.custom_colors = {int(k): tuple(v) for k, v in data.get("custom_colors", {}).items()}
            st._vis_dirty()
            sel = [s for s in data.get("selected", []) if 0 <= s < n]
            st.select(sel)
            self.viewport.landmark_hosts = sel if len(sel) <= 2 else []
            if sel:
                self.info.show_structures(sel)
            clip = data.get("clip")
            if clip:
                self.view_panel.set_clips(*clip)
            cut, band = data.get("dissection", [0.0, 0.0])
            self.view_panel.set_depth(float(cut), bool(band))
            target, dist, yaw, pitch = data["camera"]
            cam = self.viewport.camera
            if animate:
                cam.animate_to(np.array(target), dist, yaw, pitch, self.viewport.duration())
            else:
                cam.target, cam.distance, cam.yaw, cam.pitch = np.array(target), dist, yaw, pitch
            self.viewport.update()
            self._update_counts()
        except (KeyError, ValueError, TypeError) as e:
            self.statusBar().showMessage(f"Could not restore view: {e}", 5000)

    def _saved_views(self):
        try:
            return json.loads(self.qsettings.value("saved_views", "[]"))
        except (TypeError, ValueError):
            return []

    def _store_views(self, views):
        self.qsettings.setValue("saved_views", json.dumps(views))

    def save_view_dialog(self):
        default = ""
        if self.state.selected:
            default = self.ds.structures[self.state.selected[0]]["base"]
        name, ok = QInputDialog.getText(self, "Save view", "Name:", text=default)
        if ok and name.strip():
            views = [v for v in self._saved_views() if v["name"] != name.strip()]
            views.append({"name": name.strip(), "created": datetime.now().isoformat(timespec="minutes"),
                          "data": self.capture_view()})
            self._store_views(views)
            self.statusBar().showMessage(f"Saved view “{name.strip()}”", 3000)

    def _fill_views_menu(self):
        m = self.views_menu
        m.clear()
        m.addAction(self.cmds.actions["save_view"])
        views = self._saved_views()
        if views:
            m.addSeparator()
            for v in sorted(views, key=lambda v: v["name"].lower()):
                m.addAction(v["name"], lambda data=v["data"]: self.apply_view(data))
            m.addSeparator()
            m.addAction("Manage saved views…", self.manage_views)

    def manage_views(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Saved views")
        dlg.resize(360, 420)
        lay = QVBoxLayout(dlg)
        lst = QListWidget()
        lay.addWidget(lst)
        row = QHBoxLayout()
        lay.addLayout(row)

        def refresh():
            lst.clear()
            for v in sorted(self._saved_views(), key=lambda v: v["name"].lower()):
                lst.addItem(v["name"])

        def rename():
            it = lst.currentItem()
            if not it:
                return
            new, ok = QInputDialog.getText(dlg, "Rename view", "Name:", text=it.text())
            if ok and new.strip():
                views = self._saved_views()
                for v in views:
                    if v["name"] == it.text():
                        v["name"] = new.strip()
                self._store_views(views)
                refresh()

        def delete():
            it = lst.currentItem()
            if it:
                self._store_views([v for v in self._saved_views() if v["name"] != it.text()])
                refresh()

        for label, fn in (("Open", lambda: [self.apply_view(v["data"]) for v in self._saved_views()
                                             if lst.currentItem() and v["name"] == lst.currentItem().text()]),
                          ("Rename", rename), ("Delete", delete)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        refresh()
        dlg.exec()

    def restore_session(self):
        try:
            data = json.loads(self.qsettings.value("last_session", "null"))
        except (TypeError, ValueError):
            data = None
        if data:
            self.apply_view(data, animate=False)

    # ------------------------------------------------------------------ commands
    def frame_selection(self):
        if self.state.selected:
            self.viewport.frame_structures(self.state.selected)
        else:
            vis = np.nonzero(self.state.visible_mask())[0]
            if len(vis):
                self.viewport.frame_structures(vis)

    def hide_selection(self):
        if self.state.selected:
            sel = list(self.state.selected)
            self.state.set_hidden(sel, True)
            self.viewport.landmark_hosts = []
            self.info.show_welcome()

    def isolate_selection(self):
        if self.state.selected:
            self.state.isolate(self.state.selected)
            self.viewport.frame_structures(self.state.selected)

    ORIGIN_COLOR = (0.93, 0.35, 0.28)
    INSERTION_COLOR = (0.29, 0.58, 0.93)

    def colour_attachments(self, att):
        """Paint origins red and insertions blue, so a bone reads at a glance."""
        self.clear_attachment_colours()
        for sid in att:
            role = self.ds.structures[sid].get("role")
            if role == "Origin":
                self.state.set_custom_color([sid], self.ORIGIN_COLOR)
            elif role == "Insertion":
                self.state.set_custom_color([sid], self.INSERTION_COLOR)
            else:
                continue
            self._attachment_tint.append(sid)
        if self._attachment_tint:
            self.statusBar().showMessage("Origins are red, insertions blue. Esc puts the colours back.", 6000)

    def clear_attachment_colours(self):
        if self._attachment_tint:
            self.state.set_custom_color(self._attachment_tint, None)
            self._attachment_tint = []
            return True
        return False

    def active_viewport(self):
        """The 3D view the user is actually looking at - the atlas, or a microanatomy tab."""
        w = self.center.currentWidget()
        return getattr(w, "gl_widget", w if isinstance(w, Viewport) else self.viewport)

    def toggle_measure(self):
        vp = self.active_viewport()
        on = not vp.measure_mode
        for other in (self.viewport, vp):
            other.set_measure(on if other is vp else False)
        self.measure_action.setChecked(on)
        if not on:
            self.statusBar().clearMessage()

    def toggle_xray(self):
        if self.state.ghost_focus is not None:
            self.state.clear_ghost()
        elif self.state.selected:
            self.state.set_ghost_focus(self.state.selected)
        self._update_counts()

    def show_all(self):
        self.view_panel.set_depth(0.0, False)      # "show all" has to undo the dissection too
        self.state.show_all()

    def reset_visibility(self):
        self.view_panel.set_depth(0.0, False)
        self.state.reset_visibility()

    def undo(self):
        self.state.undo()

    def escape(self):
        if self.clear_attachment_colours():
            return
        vp = self.active_viewport()
        if vp.measure_points:
            vp.clear_measure()
            return
        if self.search.edit.hasFocus() and self.search.edit.text():
            self.search.edit.clear()
            return
        if self.quiz is not None and self.quiz.active:
            self.quiz.stop()
            return
        if self.state.ghost_focus is not None:
            self.state.clear_ghost()
            self.state.clear_forced()
        elif self.state.selected:
            self.state.clear_selection()
            self.viewport.landmark_hosts = []
            self.viewport.focus_landmark = None
            self.info.show_welcome()
        self._update_counts()

    def screenshot(self, path=None):
        widget = self.center.currentWidget()
        img = widget.grab()
        if not path:
            pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
            default = str(Path(pics) / f"anatomy_{datetime.now():%Y%m%d_%H%M%S}.png")
            path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", default, "PNG image (*.png)")
            if not path:
                return
        img.save(path)
        self.statusBar().showMessage(f"Saved {path}", 4000)

    def export_figure(self, path=None):
        """Save the current view as a captioned plate: the picture, what is in it, and how it was set up."""
        from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter
        widget = self.center.currentWidget()
        shot = widget.grab().toImage()
        dpr = shot.devicePixelRatio() or 1.0

        st = self.state
        sel = [self.ds.structures[s]["name"] for s in st.selected]
        title = sel[0] if len(sel) == 1 else (f"{len(sel)} structures" if sel else "Anatomy figure")
        bits = []
        if self.viewport.section_anchors:
            names = [self.ds.structures[sid]["name"] for sid, _a, _w in self.viewport.section_anchors]
            plane = ["Sagittal", "Coronal", "Transverse"][self.viewport.active_section()[0]]
            bits.append(f"{plane} section through: " + ", ".join(names))
        elif sel:
            bits.append(", ".join(sorted(set(sel))))
        if st.depth_cut > 0:
            bits.append(f"Dissected to {st.depth_cut * 100:.0f}% depth")
        visible = int(st.visible_mask().sum())
        bits.append(f"{visible:,} structures visible")

        scale = dpr
        pad = int(18 * scale)
        font_title = QFont(self.font())
        font_title.setPointSizeF(font_title.pointSizeF() * 1.7)
        font_title.setBold(True)
        font_body = QFont(self.font())
        fm_t, fm_b = QFontMetrics(font_title), QFontMetrics(font_body)
        width = shot.width()
        text_w = width - 2 * pad
        caption = "  ·  ".join(bits)
        body_rect = fm_b.boundingRect(0, 0, text_w, 10000, int(Qt.TextWordWrap), caption)
        head_h = fm_t.height() + pad
        foot_h = body_rect.height() + fm_b.height() + int(pad * 1.6)
        out = QImage(width, shot.height() + head_h + foot_h, QImage.Format_RGB32)
        out.setDevicePixelRatio(dpr)
        dark = bool(self.settings.get("dark_background", True))
        bg = QColor("#14171c") if dark else QColor("#f3f5f8")
        fg = QColor("#e8edf3") if dark else QColor("#1b1f26")
        muted = QColor("#9aa4b2") if dark else QColor("#57606d")
        out.fill(bg)
        p = QPainter(out)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(font_title)
        p.setPen(fg)
        p.drawText(pad, int(pad * 0.4), text_w, fm_t.height(), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.drawImage(0, head_h, shot)
        p.setFont(font_body)
        p.setPen(muted)
        p.drawText(pad, shot.height() + head_h + int(pad * 0.4), text_w, body_rect.height(),
                   Qt.AlignLeft | Qt.TextWordWrap, caption)
        p.drawText(pad, out.height() - fm_b.height() - int(pad * 0.4), text_w, fm_b.height(), Qt.AlignLeft,
                   "Anatomy Explorer · BodyParts3D / Z-Anatomy, CC BY-SA")
        p.end()

        if not path:
            pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
            default = str(Path(pics) / f"anatomy_figure_{datetime.now():%Y%m%d_%H%M%S}.png")
            path, _ = QFileDialog.getSaveFileName(self, "Export figure", default, "PNG image (*.png)")
            if not path:
                return
        out.save(path)
        QGuiApplication.clipboard().setImage(out)
        self.statusBar().showMessage(f"Saved {path} (also copied to the clipboard)", 5000)

    # ------------------------------------------------------------------ automation (used for testing)
    def _run_script(self):
        if not self._script:
            return
        cmd = self._script.pop(0)
        name, _, arg = cmd.partition(":")
        delay = 350
        if name == "search":
            self.search.edit.setText(arg)
            self.search._timer.stop()
            self.search._run()
            delay = 200
        elif name == "activate":
            self.search._activate_current()
            delay = 900
        elif name == "tab":
            self.tabs.setCurrentIndex(int(arg))
        elif name == "center":
            self.center.setCurrentIndex(int(arg))
        elif name == "view":
            self.viewport.set_view(arg)
            delay = 900
        elif name == "clear":
            self.search.edit.clear()
        elif name == "esc":
            self.escape()
        elif name == "clip":
            idx, val = arg.split("=")
            self.view_panel.set_clip(int(idx), True, float(val))
        elif name == "preset":
            self.state.set_systems([s["key"] in arg.split(",") for s in self.ds.systems])
        elif name == "set":
            key, _, val = arg.partition("=")
            cur = DEFAULT_SETTINGS.get(key)
            val = (val == "1") if isinstance(cur, bool) else type(cur)(val) if cur is not None else val
            self.on_setting(key, val, sync=True)
        elif name == "action":
            self.cmds.actions[arg].trigger()
        elif name == "link":
            scheme, _, payload = arg.partition("=")
            self.on_link(scheme, payload)
            delay = 900
        elif name == "info":
            self.info._anchor(QUrl(arg))
        elif name == "orbit":
            dx, dy = arg.split(",")
            self.viewport.camera.orbit(float(dx), float(dy))
            self.viewport.update()
        elif name == "zoom":
            self.viewport.camera.dolly(float(arg))
            self.viewport.update()
        elif name in ("click", "rclick", "dclick", "hover"):
            from PySide6.QtCore import QPoint, QPointF
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtTest import QTest
            target = self.center.currentWidget()
            target = getattr(target, "gl_widget", target)
            rx, ry = (float(v) for v in arg.split(","))
            pt = QPoint(int(rx * target.width()), int(ry * target.height()))
            if name == "click":
                QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, pt)
            elif name == "rclick":
                QTest.mouseClick(target, Qt.RightButton, Qt.NoModifier, pt)
            elif name == "dclick":
                QTest.mouseDClick(target, Qt.LeftButton, Qt.NoModifier, pt)
            else:
                ev = QMouseEvent(QMouseEvent.MouseMove, QPointF(pt), QPointF(target.mapToGlobal(pt)),
                                 Qt.NoButton, Qt.NoButton, Qt.NoModifier)
                target.mouseMoveEvent(ev)
            delay = 700
        elif name == "settings":
            self.open_settings(page=int(arg or 0))
        elif name == "wait":
            delay = int(arg)
        elif name == "shot":
            self.grab().save(arg)
        elif name == "figure":
            self.export_figure(arg)
        elif name == "shotdlg":
            if self.settings_dialog:
                self.settings_dialog.grab().save(arg)
        elif name == "eval":
            exec(arg, {"w": self, "np": np})
        elif name == "quit":
            self.close()
            return
        QTimer.singleShot(delay, self._run_script)

    def closeEvent(self, e):
        if self.quiz is not None:
            self.quiz.stop()
        if self._borderless and self._pre_borderless is not None:
            self.qsettings.setValue("geometry", self._pre_borderless[0])   # the size to come back to
        else:
            self.qsettings.setValue("geometry", self.saveGeometry())
        self.qsettings.setValue("window_state", self.saveState())
        self.qsettings.setValue("view_settings", json.dumps(self.settings))
        if self.settings.get("restore_session") and not self._script:
            self.qsettings.setValue("last_session", json.dumps(self.capture_view()))
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        super().closeEvent(e)
