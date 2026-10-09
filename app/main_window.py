import json
import math
import time
import weakref
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QByteArray, QEvent, QPoint, QSettings, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QApplication, QColorDialog, QDockWidget, QFileDialog, QInputDialog, QLabel,
                               QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter,
                               QTabWidget, QToolButton, QToolBar, QVBoxLayout, QWidget, QDialog, QHBoxLayout, QProgressBar)

from .actions import WORKSPACE_MODIFIER, ActionRegistry, default_key_text
from .camera import OrbitCamera
from .config import APP_NAME, DEFAULT_SETTINGS, ORG_NAME
from .content import ContentIndex
from .search import SearchIndex
from .state import SceneState
from .ui.info_panel import InfoPanel
from .ui.nav import NavTabWidget
from .ui.places import PlaceHistory
from .ui.search_panel import SearchPanel, ModelCatalogPanel
from .ui.shell import CommandPalette, ElidingLabel, WorkspaceNotice
from .ui.settings_dialog import SettingsDialog
from .ui.systems_panel import RegionsPanel, SystemsPanel
from .ui import theme
from .ui.theme import apply_theme
from .ui.tree_panel import TreePanel
from .ui.view_panel import DISSECTION_STOPS, ViewPanel
from .viewport import VIEWS, Viewport


# Match the numeric domains offered by SettingsDialog's controls. A finite
# number can still be unusable (zero FOV, negative scale, or huge resolution).
_SETTING_LIMITS = {
    "fov": (15, 70), "camera_duration": (0, 1.5), "key_orbit_step": (1, 45),
    "auto_rotate_speed": (2, 90), "orbit_sensitivity": (0.05, 1.5),
    "pan_sensitivity": (0.2, 3), "zoom_sensitivity": (0.2, 3),
    "trackpad_swipe_sensitivity": (0.2, 3), "trackpad_pinch_sensitivity": (0.2, 3),
    "ui_scale": (0.8, 1.6), "details_scale": (0.8, 1.8), "label_size": (6, 16),
    "max_landmarks": (5, 150), "render_scale": (0.5, 2),
    "ssao_strength": (0, 1.5), "ghost_alpha": (0.02, 0.5),
}


def _validated_settings(saved):
    """Keep known preferences with the types their controls and renderer accept."""
    if not isinstance(saved, dict):
        return {}
    valid = {}
    for key, value in saved.items():
        if key not in DEFAULT_SETTINGS:
            continue
        default = DEFAULT_SETTINGS[key]
        if type(default) in (int, float):
            if type(value) not in (int, float):
                continue
            try:
                if not math.isfinite(value):
                    continue
            except OverflowError:
                continue
            limits = _SETTING_LIMITS.get(key)
            if limits is not None and not limits[0] <= value <= limits[1]:
                continue
            if type(default) is int:
                if value != int(value):
                    continue
                value = int(value)  # integer controls can be saved through a float-valued slider
        elif type(value) is not type(default):
            continue
        if key == "color_mode" and value not in (0, 1, 2):
            continue
        valid[key] = value
    return valid


# Systems a scan section always includes: everything with tissue, not lines, attachment patches or skin regions.
SECTION_SYSTEMS = {"skeletal", "joints", "muscular", "cardiovascular", "lymphatic", "nervous", "visceral"}


class MainWindow(QMainWindow):
    def __init__(self, ds, script=None, restore=True):
        super().__init__()
        self._borderless = False        # before anything that can reach the event filter
        self._pre_borderless = None
        self._compact_layout = False
        self._layout_pending = False
        self._ui_ready = False
        self._startup_notices = []
        self.ds = ds
        self.setWindowTitle(APP_NAME)
        self.qsettings = QSettings(QSettings.defaultFormat(), QSettings.UserScope, ORG_NAME, APP_NAME)
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            saved = json.loads(self.qsettings.value("view_settings", "{}"))
            self.settings.update(_validated_settings(saved))
        except (TypeError, ValueError):
            pass
        # Retire the older saved default once, while retaining future user choices.
        if self.qsettings.value('gizmo_default_off_revision', 0, type=int) < 1:
            self.settings['show_gizmo'] = False
            self.qsettings.setValue('view_settings', json.dumps(self.settings))
            self.qsettings.setValue('gizmo_default_off_revision', 1)
        if self.qsettings.value('studio_startup_revision', 0, type=int) < 1:
            self.settings['restore_session'] = False
            self.qsettings.setValue('view_settings', json.dumps(self.settings))
            self.qsettings.setValue('studio_startup_revision', 1)
        self.settings['show_structure_labels'] = False
        # The shell and live scene share one backdrop; this does not change lights or materials.
        self.settings.update(custom_background=True, bg_top='#141b22', bg_bottom='#141b22')
        apply_theme(QApplication.instance(), float(self.settings["ui_scale"]),
                    mode=str(self.qsettings.value("ui_theme", "porcelain")))
        self.state = SceneState(ds, self.settings)
        self.index = SearchIndex(ds)
        self.content = ContentIndex(ds)
        if self.content.model_catalog_error:
            self._startup_notices.append(self.content.model_catalog_error)
        self.index.add_content(self.content)
        # Back/Forward across the whole app (ui/places.py): a place is recorded once a click has settled.
        self.places = PlaceHistory()
        self._restoring_place = False
        self._place_info = {}           # place key -> the Details page it showed (group / landmark pages)
        self._place_timer = QTimer(self)
        self._place_timer.setSingleShot(True)
        self._place_timer.setInterval(350)
        self._place_timer.timeout.connect(self._capture_place)
        self.settings_dialog = None
        self.micro_tabs = {}             # every open model tab (and the histology viewer), by id
        self._loading_models = {}
        self._reference_loads = {}
        self._preference_commits = {}
        from .ui.model_loading import ModelLoader
        self._model_loader = ModelLoader(self)
        self._model_loader.finished.connect(self._model_load_finished)
        self._closing = False
        # QObject destruction can bypass closeEvent. Retire Python-owned loading
        # state before Qt deletes child objects and their destruction callbacks.
        self.destroyed.connect(lambda: self._discard_model_loads())

        # ---------------------------------------------------------------- center
        self.viewport = Viewport(ds, self.state, self.settings)
        self.radiology_panel = None
        self.anatomy_tab = QSplitter(Qt.Horizontal)
        self.anatomy_tab.setObjectName("anatomyComparison")
        self.anatomy_tab.setStyleSheet("QSplitter#anatomyComparison {background:#141b22;}")
        self.anatomy_tab.splitterMoved.connect(lambda *_: self._layout_studio_chrome())
        self.anatomy_tab.setChildrenCollapsible(False)
        self.anatomy_tab.setHandleWidth(6)
        self.anatomy_tab.setAccessibleName("Radiology and anatomy comparison")
        self.anatomy_tab.gl_widget = self.viewport      # so anything asking the tab for its 3D view still works
        try:
            from .radiology import load_cases
            from .ui.radiology import RadiologyPanel
            self.radiology_cases = load_cases(include_missing=True)
            self.radiology_panel = RadiologyPanel()
            self.radiology_panel.hide()
            self.anatomy_tab.addWidget(self.radiology_panel)
        except (ImportError, OSError, ValueError) as exc:
            self.radiology_cases = []
            self._startup_notices.append(f"Radiology could not be opened: {exc}")
        self.anatomy_tab.addWidget(self.viewport)
        self.center = QTabWidget()
        self.center.setDocumentMode(True)
        self.center.setTabsClosable(True)
        self.center.setTabBarAutoHide(False)
        self.center.setAccessibleName("Open anatomy and image workspaces")
        self.center.tabBar().setElideMode(Qt.ElideRight)
        self.center.tabBar().setUsesScrollButtons(True)
        self.center.addTab(self.anatomy_tab, "3D Anatomy")
        self.center.tabBar().setTabButton(0, self.center.tabBar().ButtonPosition.RightSide, None)
        self.center.tabCloseRequested.connect(self._close_center_tab)
        self.center.currentChanged.connect(self._center_changed)
        # Moving between the atlas, a library and an open model is a place for Back too, even when the
        # library's own page did not change (e.g. Explore -> 3D Models -> open a model -> Back).
        self.center.currentChanged.connect(self._note_place)
        self.workspace = QWidget()
        self.workspace_layout = QVBoxLayout(self.workspace)
        self.workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.workspace_layout.setSpacing(0)
        self.notice = WorkspaceNotice()
        self.workspace_layout.addWidget(self.notice)
        self.lesson_splitter = QSplitter(Qt.Horizontal)
        self.lesson_splitter.setObjectName("lessonWorkspaceSplit")
        self.lesson_splitter.setStyleSheet(
            "QSplitter#lessonWorkspaceSplit {background:#141b22;}"
            "QSplitter#lessonWorkspaceSplit::handle {background:#141b22;}")
        self.lesson_splitter.setChildrenCollapsible(False)
        self.lesson_reader = QWidget()
        self.lesson_reader.setObjectName("lessonWorkspace")
        self.lesson_reader.setAttribute(Qt.WA_StyledBackground, True)
        self.lesson_reader.setStyleSheet("QWidget#lessonWorkspace {background:transparent;border:none;}")
        self.lesson_reader_layout = QVBoxLayout(self.lesson_reader)
        self.lesson_reader_layout.setContentsMargins(24, 12, 12, 16)
        self.lesson_card = QWidget(self.lesson_reader)
        self.lesson_card.setObjectName("lessonStudyCard")
        self.lesson_card.setAttribute(Qt.WA_StyledBackground, True)
        self.lesson_card.setStyleSheet(
            "QWidget#lessonStudyCard {background:#f2f6f8;border:1px solid #94a6b1;border-radius:14px;}")
        self.lesson_card_layout = QVBoxLayout(self.lesson_card)
        self.lesson_card_layout.setContentsMargins(12, 12, 12, 12)
        self.lesson_reader_layout.addWidget(self.lesson_card)
        self.lesson_splitter.addWidget(self.lesson_reader)
        self.lesson_splitter.addWidget(self.center)
        self.lesson_splitter.setStretchFactor(0, 0)
        self.lesson_splitter.setStretchFactor(1, 1)
        self.lesson_reader.hide()
        self.workspace_layout.addWidget(self.lesson_splitter, 1)
        self.setCentralWidget(self.workspace)
        self.setAcceptDrops(True)            # a .glb dropped on the window opens in the model viewer

        # ---------------------------------------------------------------- left dock
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self.search = SearchPanel(ds, self.index)
        ll.addWidget(self.search)
        self.tabs = NavTabWidget()          # Browse / Study / View, each with a small selector (see ui/nav.py)
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
                self.lessons_panel.saveFailed.connect(
                    lambda message: self.statusBar().showMessage(f"Could not save lesson progress: {message}", 10000))
                self.lessons_panel.saveSucceeded.connect(
                    lambda: self.statusBar().clearMessage()
                    if self.statusBar().currentMessage().startswith("Could not save lesson progress:") else None)
                self.tabs.addTab(self.lessons_panel, "Lessons")
                self.lessons_panel.stepRequested.connect(self.apply_lesson_step)
                self.lessons_panel.lessonClosed.connect(self._lesson_closed)
                self.lessons_panel.lessonOpened.connect(self._remember_lesson)
                for signal in (self.lessons_panel.stepRequested, self.lessons_panel.lessonOpened,
                               self.lessons_panel.lessonClosed):
                    signal.connect(self._note_place)
                self.lessons_panel.quizRequested.connect(self.quiz_lesson)
                self.tabs.entry_picked.connect(self._study_entry_picked)
                # Diagrams stay in the lesson; enlargement is an explicit action.
                self.lessons_panel.linkActivated.connect(self.on_link)
                self.lessons_panel.set_reference_titles(
                    micro={k: m.name for k, m in self.content.micro_models.items()},
                    histo={k: v.get("name", k) for k, v in self.content.tissues.items()},
                    rad={c.id: c.title for c in self.radiology_cases})
                self.index.add_lessons(lessons)
        except (ImportError, OSError, ValueError):
            self.lessons_panel = None
        from .lessons import Resolver as _Resolver
        if getattr(self, "lesson_resolver", None) is None:
            self.lesson_resolver = _Resolver(ds, self.index)
        self.tabs.addTab(self.view_panel, "View")
        # Append new pages so historical tab:N script indices remain stable.
        self.catalog = ModelCatalogPanel(self.content)
        self.catalog.activated.connect(self.open_micro)
        self.catalog.linkActivated.connect(self.on_link)
        self.catalog.variantChosen.connect(self.switch_model_variant)
        from .variants.readiness import retry_dataset_readiness, cancel_dataset_readiness
        self.tabs.addTab(self.catalog, "Models")
        self.tabs.setTabToolTip(self.tabs.indexOf(self.catalog), "Browse every installed 3D model")
        ll.addWidget(self.tabs.nav)
        ll.addWidget(self.tabs, 1)
        self.left_layout = ll
        self.left_dock = QDockWidget("Explore")
        self.left_dock.setObjectName("explore_dock")
        self.left_dock.setWidget(left)
        self.left_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                                   QDockWidget.DockWidgetClosable)
        left.setMinimumWidth(300)
        left.setAccessibleName("Anatomy and study navigation")
        self.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock)

        # ---------------------------------------------------------------- right dock
        self.info = InfoPanel(ds, self.content)
        self.info.n_radiology = len(self.radiology_cases)
        self.info.n_lessons = len(self.lessons_panel.lessons) if self.lessons_panel is not None else 0
        self.info.set_font_scale(float(self.settings["details_scale"]))
        from .relations import RelationsIndex
        self.relations = RelationsIndex(ds)
        self.info.relations = self.relations
        from .depth import DepthIndex
        self.depth_index = DepthIndex(ds)
        from .section import SectionIndex
        self.section_index = SectionIndex(ds)
        self.viewport.section = self.section_index
        self.viewport.sectionChanged = lambda items: self.view_panel.show_section(items, ds)
        self.right_dock = QDockWidget("Details")
        self.right_dock.setObjectName("details_dock")
        self.right_dock.setWidget(self.info)
        self.right_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                                    QDockWidget.DockWidgetClosable)
        self.info.setMinimumWidth(300)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)
        self.resizeDocks([self.left_dock, self.right_dock], [360, 420], Qt.Horizontal)

        self.cmds = ActionRegistry(self, self.viewport, self.qsettings)
        self._register_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._build_workspace_header()
        self._register_workspace_actions()

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
            lambda text: self._on_measure_changed(self.viewport, text))
        self.view_panel.sectionPicked.connect(lambda sid: self.select_and_focus([sid], frame=False))
        if self.radiology_panel is not None:
            self.radiology_panel.structuresPicked.connect(self.on_radiology_pick)
            self.radiology_panel.sceneRequested.connect(self.apply_radiology_scene)
            self.radiology_panel.labelsToggled.connect(self._show_radiology_labels)
            self.radiology_panel.closeRequested.connect(self.close_radiology)
            self.radiology_panel.caseStepped.connect(self.step_radiology)
            self.radiology_panel.browserRequested.connect(
                lambda: self._show_nav_page(self.radiology_browser))
            self.radiology_panel.detailsRequested.connect(self.right_dock.show)
        self.state.visibility_changed.connect(self.viewport.refresh_section)
        self.view_panel.settingsRequested.connect(self.open_settings)
        self.state.visibility_changed.connect(self._update_counts)
        self.state.selection_changed.connect(self._on_selection_changed)

        self._default_window_state = self.saveState()
        layout_types = (QByteArray, bytes, bytearray, memoryview)
        geo = self.qsettings.value("geometry") if restore else None
        if not isinstance(geo, layout_types) or not self.restoreGeometry(geo):
            scr = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(int(scr.width() * 0.88), int(scr.height() * 0.88))
        st = self.qsettings.value("window_state") if restore else None
        if self.qsettings.value('studio_layout_revision', 0, type=int) != 2:
            st = None
        if isinstance(st, layout_types):
            self.restoreState(st)
        # Saved legacy layouts must not bring back the duplicate navigation bar.
        for bar in self.findChildren(QToolBar):
            if bar.objectName() == 'main_toolbar':
                bar.hide()
        self.dock_side_panels()
        self.qsettings.setValue('studio_layout_revision', 2)
        self._update_counts()
        self._script = [c.strip() for c in script.split(";") if c.strip()] if script else None
        # Always begin in Explore; saved window and display preferences still apply.
        self._restore_pending = False
        if restore and str(self.qsettings.value("borderless", "0")).lower() in ("1", "true"):
            QTimer.singleShot(0, self, lambda: self.set_borderless(True))
        from .ui.study_layout import StudyLayout
        self.study_layout = StudyLayout(self)
        self._ui_ready = True
        self.tabs.currentChanged.connect(self._update_workspace_header)
        self.state.selection_changed.connect(self._update_workspace_header)
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(500)
        self._activity_timer.timeout.connect(self._update_activity)
        self._activity_timer.start()
        self._update_workspace_header()
        QTimer.singleShot(0, self._adapt_workspace)
        if not script:
            QTimer.singleShot(0, self._startup_explore)
        QTimer.singleShot(0, self, self._note_place)  # the opening view is the first place Back can return to
        if self._startup_notices:
            if self.content.model_catalog_error:
                self.notice.show_message(" · ".join(self._startup_notices), "Browse models", self._show_catalog)
            else:
                self.notice.show_message(" · ".join(self._startup_notices), "Open settings", self.open_settings)

    # ------------------------------------------------------------------ actions, menus, toolbar
    def _register_actions(self):
        vp = self.viewport
        reg = self.cmds.register
        reg("search", self._focus_search)
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
        mv = self.active_model_view
        av = self.active_viewport
        reg("frame", lambda: mv().frame_selection() if mv() else self.frame_selection())
        reg("reset_view", lambda: mv().reset_view() if mv() else vp.reset_view())
        for v in VIEWS:
            reg(f"view_{v}", lambda _=False, n=v: av().set_view(n))
        reg("orbit_left", lambda: av().key_orbit(1, 0))
        reg("orbit_right", lambda: av().key_orbit(-1, 0))
        reg("orbit_up", lambda: av().key_orbit(0, 1))
        reg("orbit_down", lambda: av().key_orbit(0, -1))
        reg("zoom_in", lambda: av().key_zoom(1))
        reg("zoom_out", lambda: av().key_zoom(-1))
        self.auto_rotate_action = reg("auto_rotate", self.toggle_auto_rotate)
        self.auto_rotate_action.setCheckable(True)
        reg("hide", lambda: mv().hide_selection() if mv() else self.hide_selection())
        reg("isolate", lambda: mv().isolate_selection() if mv() else self.isolate_selection())
        self.xray_action = reg("xray", self.toggle_xray)
        self.xray_action.setCheckable(True)
        reg("both_sides", lambda: None if mv() else self.select_both_sides())
        reg("show_all", lambda: mv().show_all() if mv() else self.show_all())
        reg("default_visibility", lambda: mv().show_all() if mv() else self.reset_visibility())
        reg("undo", lambda: mv().undo() if mv() else self.undo())
        reg("landmarks", lambda: mv().toggle_labels() if mv() else
            self.on_setting("show_landmarks", not self.settings["show_landmarks"], sync=True))
        structure_labels = reg("structure_labels", lambda: self.on_setting(
            "show_structure_labels", not self.settings.get("show_structure_labels", False)))
        structure_labels.setCheckable(True)
        structure_labels.setChecked(bool(self.settings.get("show_structure_labels", False)))
        reg("color_mode", lambda: self.on_setting("color_mode", (int(self.settings["color_mode"]) + 1) % 3, sync=True))
        self.measure_action = reg("measure", self.toggle_measure)
        self.measure_action.setCheckable(True)
        reg("peel_in", lambda: None if mv() else self.view_panel.step_depth(1))
        reg("peel_out", lambda: None if mv() else self.view_panel.step_depth(-1))
        reg("peel_reset", lambda: None if mv() else self.view_panel.set_depth(0.0, False))
        reg("clip_sagittal", lambda: mv().toggle_section(0) if mv() else self.view_panel.toggle_clip(0))
        reg("clip_coronal", lambda: mv().toggle_section(1) if mv() else self.view_panel.toggle_clip(1))
        reg("clip_transverse", lambda: mv().toggle_section(2) if mv() else self.view_panel.toggle_clip(2))
        # the model viewer's own commands: they act on the model in front and do nothing in the atlas
        reg("model_next_view", lambda: mv() and mv().step_view(1)).setEnabled(False)
        reg("model_prev_view", lambda: mv() and mv().step_view(-1)).setEnabled(False)
        reg("model_projection", lambda: mv() and mv().toggle_projection())
        reg("model_state", lambda: mv() and mv().toggle_state())
        reg("model_play", lambda: mv() and mv().toggle_play())
        reg("open_model_file", self.open_model_file)
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
        """The menu bar, and the drop-down menus the toolbar shares with it.

        Each group of commands is built once as a QMenu and hung in both places (the menu bar for anyone who
        looks there, a toolbar drop-down for the mouse), so the two can never drift apart. Every command in
        actions.py is in at least one of them, with its shortcut shown beside it."""
        a = self.cmds.actions
        mb = self.menuBar()
        mb.installEventFilter(self)      # so a borderless window can still be dragged by its menu bar

        # ---- shared menus
        self.camera_menu = cam = QMenu("&Camera", self)
        for key in VIEWS:
            cam.addAction(a[f"view_{key}"])
        cam.addSeparator()
        cam.addAction(a["frame"])
        cam.addAction(a["reset_view"])
        cam.addAction(a["auto_rotate"])
        keys = cam.addMenu("Rotate and zoom")
        self._fill_menu(keys, ("orbit_left", "orbit_right", "orbit_up", "orbit_down", None, "zoom_in", "zoom_out"))

        self.show_menu = shm = QMenu("&Show", self)
        self._fill_menu(shm, ("hide", "isolate", "xray", "both_sides", None, "show_all", "default_visibility", "undo",
                              None, "landmarks"))

        self.dissect_menu = dm = QMenu("&Dissection", self)
        dm.addAction(a["peel_in"])
        dm.addAction(a["peel_out"])
        dm.addAction(a["peel_reset"])
        dm.addSeparator()
        for pct, label in DISSECTION_STOPS:
            text = f"{label.replace('&', '&&')}  ({pct * 100:.0f}%)"      # a lone & would be read as a mnemonic
            dm.addAction(text, lambda _=False, p=pct: self.view_panel.set_depth(p))

        self.section_menu = sm = QMenu("Cross-&sections", self)
        for key in ("clip_sagittal", "clip_coronal", "clip_transverse"):
            sm.addAction(a[key])
        sm.addSeparator()
        sm.addAction("Clear cross-sections", self.view_panel.reset_clips)
        sm.addSeparator()
        sm.addAction("Quiz me on this section", self.quiz_section)

        self.views_menu = QMenu("Saved &views", self)
        self.views_menu.aboutToShow.connect(self._fill_views_menu)
        self._fill_views_menu()          # so its shortcut (Ctrl+D) is listed before it is first opened

        self.tools_menu = tm = QMenu("&Tools", self)
        tm.addAction(a["measure"])
        tm.addMenu(self.views_menu)
        tm.addSeparator()
        tm.addAction(a["screenshot"])
        tm.addAction(a["export_figure"])
        tm.addSeparator()
        tm.addAction(a["settings"])

        self.study_menu = st = QMenu("S&tudy", self)
        if self.lessons_panel is not None:
            st.addAction(a["lessons"])
        if "quiz" in a:
            st.addAction(a["quiz"])
        if self.radiology_browser is not None:
            st.addAction(a["radiology"])
        st.addAction(a["histology_tab"])
        st.addSeparator()
        st.addAction("My progress…", self.show_progress)
        st.addAction(a["note"])
        st.addAction("All my notes…", self.show_all_notes)
        st.addSeparator()
        self._add_models_menu(st)

        # ---- the menu bar
        f = mb.addMenu("&File")
        f.addAction(a["open_model_file"])
        f.addSeparator()
        f.addAction(a["screenshot"])
        f.addAction(a["export_figure"])
        f.addAction(a["settings"])
        f.addSeparator()
        f.addAction("Exit", self.close)

        s = mb.addMenu("&Selection")
        self._fill_menu(s, ("search", None, "back", "forward", None, "frame", "hide", "isolate", "xray", "both_sides",
                            None, "show_all", "default_visibility", "undo", "escape"))

        v = mb.addMenu("&View")
        self.left_dock.toggleViewAction().setText("Explore panel")
        self.right_dock.toggleViewAction().setText("Details panel")
        v.addAction(self.left_dock.toggleViewAction())
        v.addAction(self.right_dock.toggleViewAction())
        v.addAction(a["toggle_panels"])
        v.addAction(a["fullscreen"])
        v.addAction(a["borderless"])
        v.addAction("Arrange floating panels", self.dock_side_panels)
        v.addAction("Reset panel layout", self.reset_layout)
        v.addSeparator()
        v.addMenu(cam)
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
        v.addMenu(sm)
        v.addMenu(dm)
        v.addAction(a["landmarks"])
        mm = v.addMenu("3D model views")
        self._fill_menu(mm, ("model_next_view", "model_prev_view", "model_projection", "model_state", "model_play"))

        mb.addMenu(tm)
        mb.addMenu(st)

        h = mb.addMenu("&Help")
        h.addAction("Keyboard shortcuts…", lambda: self.open_settings(page=3))
        h.addAction("About", self.about)

    def _fill_menu(self, menu, keys):
        """Add registered commands to a menu in order; None is a separator."""
        for key in keys:
            if key is None:
                menu.addSeparator()
            else:
                menu.addAction(self.cmds.actions[key])

    def _build_toolbar(self):
        """Back / Forward, then one drop-down per kind of job instead of a button for every command."""
        a = self.cmds.actions
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setAccessibleName("Anatomy workspace tools")

        def add(text, action, tip=None):
            action.setIconText(text)
            keys = [s.toString(QKeySequence.NativeText) for s in action.shortcuts()]
            action.setToolTip((tip or action.text()) + (f" ({', '.join(keys)})" if keys else ""))
            tb.addAction(action)
            return action

        def drop(text, menu, tip):
            b = QToolButton()
            b.setText(text)
            b.setAccessibleName(text + " menu")
            b.setFocusPolicy(Qt.StrongFocus)
            b.setToolTip(tip)
            b.setPopupMode(QToolButton.InstantPopup)
            b.setMenu(menu)
            tb.addWidget(b)
            return b

        for key, glyph in (("back", "back"), ("forward", "forward"), ("settings", "settings")):
            a[key].setIcon(theme.icon(glyph))
            a[key].setIconVisibleInMenu(False)
        tb.setIconSize(QSize(16, 16))
        add("Back", a["back"], "Back")
        add("Forward", a["forward"], "Forward")
        tb.addSeparator()
        self.camera_btn = drop("View", self.camera_menu,
                               "Anterior, posterior, lateral, superior and inferior views; frame; reset")
        self.show_btn = drop("Show", self.show_menu, "Hide, isolate or x-ray the selection; show everything again")
        self.dissect_btn = drop("Dissect", self.dissect_menu, "Peel the body apart layer by layer")
        self.section_btn = drop("Section", self.section_menu, "Sagittal, coronal and transverse cross-sections")
        self.tools_btn = drop("Tools", self.tools_menu, "Measure, saved views, screenshot, export a figure")
        tb.addSeparator()
        self.study_btn = drop("Study", self.study_menu, "Lessons, quiz, radiology, histology, your progress and notes")
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        add("Settings", a["settings"])
        settings_btn = tb.widgetForAction(a["settings"])
        if settings_btn is not None:
            settings_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        # a drop-down lights up while something inside it is switched on, so a mode is never on unseen
        a["xray"].toggled.connect(lambda on: self._mark_active(self.show_btn, on))
        a["measure"].toggled.connect(lambda on: self._mark_active(self.tools_btn, on))
        self.view_panel.clipChanged.connect(
            lambda: self._mark_active(self.section_btn, any(self.viewport.clip_on)))

    @staticmethod
    def _mark_active(button, on):
        if bool(button.property("active")) != bool(on):
            button.setProperty("active", bool(on))
            button.style().unpolish(button)
            button.style().polish(button)

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
        self.activity_label = QLabel("")
        self.activity_label.setAccessibleName("Background loading status")
        self.activity_progress = QProgressBar()
        self.activity_progress.setRange(0, 0)
        self.activity_progress.setTextVisible(False)
        self.activity_progress.setFixedWidth(68)
        self.activity_progress.setMaximumHeight(8)
        self.activity_progress.hide()
        sb.addPermanentWidget(self.activity_label)
        sb.addPermanentWidget(self.activity_progress)
        sb.setVisible(bool(self.settings.get("show_status_bar", False)))
        self._frame_times = []
        self._last_perf = 0.0

    def _build_workspace_header(self):
        from .ui.studio_shell import StudioHeader, CollectionWorkspace, atlas_dock
        self.studio_header = StudioHeader(self)
        self.workspace.setObjectName('studioShell')
        self.center.setObjectName('studioWorkspaces')
        self.center.tabBar().hide()
        self.menuBar().hide()
        self.workspace_title = self.studio_header.title
        self.workspace_context = self.studio_header.context
        self.studio_header.exploreRequested.connect(self._studio_explore)
        self.studio_header.learnRequested.connect(self._studio_learn)
        self.studio_header.collectionRequested.connect(self._show_catalog)
        self.studio_header.radiologyRequested.connect(self._studio_radiology)
        self.studio_header.histologyRequested.connect(self.show_histology_tab)
        self.studio_header.searchRequested.connect(self._studio_search)
        self.studio_header.backRequested.connect(lambda: self.go_place(-1))
        self.studio_header.forwardRequested.connect(lambda: self.go_place(1))
        self.studio_header.places_menu.aboutToShow.connect(self._fill_places_menu)
        self.workspace_layout.insertWidget(0, self.studio_header)
        self.studio_header.layout().removeWidget(self.studio_header.subject)
        self.studio_header.subject.setParent(self.workspace)
        self.tabs.removeTab(self.tabs.indexOf(self.catalog))
        for page in (self.histology_panel,self.radiology_browser,self.lessons_panel):
            if page is not None and self.tabs.indexOf(page)>=0:
                self.tabs.removeTab(self.tabs.indexOf(page))
        self.collection_workspace = CollectionWorkspace(self.catalog, self)
        self.collection_workspace.pages.currentChanged.connect(self._note_place)
        self.center.addTab(self.collection_workspace, "Collection")
        self.center.tabBar().setTabButton(self.center.indexOf(self.collection_workspace),
                                         self.center.tabBar().ButtonPosition.RightSide, None)
        self._studio_last_scene = self.anatomy_tab
        self.studio_tools = atlas_dock(self)
        self.studio_tools.setParent(self.workspace)
        self.lesson_splitter.splitterMoved.connect(lambda *_: self._layout_studio_chrome())
        # The full original menu/toolbar remains available, without duplicate
        # tool rows taking space from the study canvas on first launch.
        for bar in self.findChildren(QToolBar):
            if bar.objectName() == 'main_toolbar':bar.hide()
        self.left_dock.hide()
        self.right_dock.hide()

    def _studio_search(self, text):
        self._focus_search()
        self.search.edit.setText(text)

    def _startup_explore(self):
        """The opening Explore view, unless a page was already opened before the event loop started."""
        if self._closing:
            return
        if self.center.currentIndex() == 0:
            self._studio_explore()

    def _studio_explore(self):
        if self._closing:
            return
        self.lesson_reader.hide()
        if self.radiology_panel is not None and not self.radiology_panel.isHidden():
            self.close_radiology()
            for checkbox,*_ in self.view_panel.clip_widgets:checkbox.setChecked(False)
            self.viewport.clip_on[:]=[False,False,False]
            self.viewport.set_radiology_section_labels(None)
            self.viewport.focus_landmark=None
            self.clear_attachment_colours()
            self.reset_visibility()
            self.state.clear_selection()
            self.viewport.refresh_section()
            self.viewport.reset_view()
        self._show_atlas()
        self._update_workspace_header()
        if self.center.currentWidget() is self.anatomy_tab:
            self._show_nav_page(self.tree)

    def _layout_studio_chrome(self):
        if not hasattr(self, 'studio_tools'):
            return
        w, h = self.workspace.width(), self.workspace.height()
        scene_origin = self.center.mapTo(self.workspace, QPoint(0, 0)).x()
        self.studio_header.subject.setGeometry(scene_origin+28, self.studio_header.geometry().bottom()+18, max(1,self.center.width()-56), 56 if self.workspace_context.isHidden() else 84)
        origin=scene_origin
        available=self.center.width()
        if (self.center.currentWidget() is self.anatomy_tab and self.radiology_panel is not None
                and not self.radiology_panel.isHidden()):
            origin=self.viewport.mapTo(self.workspace,QPoint(0,0)).x()
            available=self.viewport.width()
        width=min(max(640,self.studio_tools.sizeHint().width()),max(1,available-32))
        height=self.studio_tools.sizeHint().height()
        self.studio_tools.setGeometry(origin+(available-width)//2,max(0,h-height-12),width,height)
        self.studio_header.subject.raise_()
        self.studio_tools.raise_()

    def _studio_radiology(self):
        on_library = (self.center.currentWidget() is self.collection_workspace
                      and self.collection_workspace.pages.currentWidget() is self.radiology_browser)
        if on_library:
            return
        if self.radiology_panel is not None and self.radiology_panel.case is not None:
            self.open_radiology(self.radiology_panel.case.id)
        else:
            self._show_nav_page(self.radiology_browser)

    def _studio_learn(self):
        self.show_lessons()

    def _show_lesson_reader(self):
        """Keep the reader outside scene tabs so model changes cannot hide it."""
        panel = self.lessons_panel
        attach = self.lesson_card_layout.indexOf(panel) < 0
        if attach:
            self.collection_workspace.pages.removeWidget(panel)
            self.lesson_card_layout.addWidget(panel)
        if self.center.currentWidget() is self.collection_workspace:
            scene = self._studio_last_scene
            self.center.setCurrentWidget(scene if self.center.indexOf(scene) >= 0 else self.anatomy_tab)
        panel.show()
        self.lesson_reader.show()
        if attach:
            self.lesson_splitter.setSizes([440, max(480, self.width()-440)])
        self.left_dock.hide()
        self.right_dock.hide()
        self._update_workspace_header()

    def _show_lesson_library(self):
        panel = self.lessons_panel
        self.lesson_reader.hide()
        if self.collection_workspace.pages.indexOf(panel) < 0:
            self.lesson_card_layout.removeWidget(panel)
            self.collection_workspace.pages.addWidget(panel)
        self.collection_workspace.show_page(panel, 'Lessons')

    def _register_workspace_actions(self):
        self.workspace_actions = []
        menu = self.menuBar().addMenu("&Workspace")
        entries = [("3D Anatomy", self._show_atlas, WORKSPACE_MODIFIER + "1"),
                   ("Model library", self._show_catalog, WORKSPACE_MODIFIER + "2"),
                   ("Lessons", self.show_lessons, WORKSPACE_MODIFIER + "3"),
                   ("Radiology", self.show_radiology, WORKSPACE_MODIFIER + "4"),
                   ("Histology", self.show_histology_tab, WORKSPACE_MODIFIER + "5"),
                   ("Find a command…", self.show_command_palette, "Ctrl+Shift+P")]
        for title, callback, shortcut in entries:
            action = QAction(title, self)
            occupied = {key.toString() for item in self.cmds.actions.values() for key in item.shortcuts()}
            if QKeySequence(shortcut).toString() not in occupied:
                action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.WindowShortcut)
            action.triggered.connect(lambda _checked=False, fn=callback: fn())
            self.addAction(action)
            menu.addAction(action)
            self.workspace_actions.append(action)
        self.workspace_actions[2].setEnabled(self.lessons_panel is not None)
        self.workspace_actions[3].setEnabled(self.radiology_browser is not None)
        self.workspace_actions[4].setEnabled(self.histology_panel is not None)

    def _focus_search(self):
        self.left_dock.show()
        self.left_dock.raise_()
        self.search.show()
        self.search.focus_search()

    def _show_atlas(self):
        self.close_radiology()
        self.center.setCurrentIndex(0)
        self._update_workspace_header()
        self.viewport.setFocus(Qt.ShortcutFocusReason)

    def _show_nav_page(self, page):
        if page is None:return
        if page is self.lessons_panel:
            from .ui.lessons import PAGE_RUNNER
            if page.stack.currentIndex() == PAGE_RUNNER:
                self._show_lesson_reader()
            else:
                self._show_lesson_library()
            return
        if page in (self.histology_panel,self.radiology_browser,self.lessons_panel):
            title='Histology' if page is self.histology_panel else 'Radiology' if page is self.radiology_browser else 'Lessons'
            self.collection_workspace.show_page(page,title)
            return
        if page is self.catalog:
            self._show_catalog();return
        self.search.edit.clear()
        self.search.kind_filter.setCurrentIndex(0)
        self.search._timer.stop()
        self.search._run()
        self._on_query_active(False)
        self.tabs.show()
        self.left_dock.show()
        self.left_dock.raise_()
        self.tabs.setCurrentWidget(page)

    def _show_catalog(self):
        self.search.edit.clear()
        self.collection_workspace.show_page(self.catalog,'3D models')
        self.left_dock.hide()
        self.right_dock.hide()
        self.catalog.focus_search()

    def _show_model_lessons(self, model_id):
        if self.lessons_panel is not None:
            self.show_lessons()
            self.lessons_panel.show_model_lessons(model_id)
            self.left_dock.raise_()

    def show_command_palette(self):
        actions = list(self.cmds.actions.values()) + list(self.workspace_actions)
        actions.extend((self.left_dock.toggleViewAction(), self.right_dock.toggleViewAction()))
        for menu in self.findChildren(QMenu):
            for action in menu.actions():
                if action.menu() is None and action not in actions:
                    actions.append(action)
        CommandPalette(actions, self).exec()

    def _save_theme_preference(self, name):
        if name not in theme.THEMES:
            return
        self.qsettings.setValue("ui_theme", name)
        self.notice.show_message("Interface appearance saved. Restart Anatomy Explorer to apply it.")

    def _update_workspace_header(self, *_):
        if not getattr(self, "_ui_ready", False):
            return
        current = self.center.currentWidget()
        title = self.center.tabText(self.center.currentIndex()).replace("&&", "&")
        subtitle = "Your selection stays with its workspace"
        if current is self.anatomy_tab:
            case = self.radiology_panel.case if self.radiology_panel is not None else None
            if case is not None and not self.radiology_panel.isHidden():
                title = case.title
                subtitle = "Radiology · Authored anatomical reference"
            else:
                count = len(self.state.selected)
                title = "3D Anatomy"
                subtitle = ""
        self.workspace_title.setText(title)
        self.workspace_context.setText(subtitle)
        self.workspace_context.setVisible(bool(subtitle))
        if hasattr(self, 'studio_header'):
            self.center.tabBar().hide()
            collection = current is self.collection_workspace
            if collection:
                self.lesson_reader.hide()
            reading = not self.lesson_reader.isHidden()
            if hasattr(self, "study_layout"):
                self.study_layout.sync()
            for view in self.micro_tabs.values():
                studio = getattr(view, "studio", None)
                if studio is not None:
                    studio.set_lesson_mode(reading and current is view)
            radiology_visible=self.radiology_panel is not None and not self.radiology_panel.isHidden()
            if collection:
                workspace = self.collection_workspace.navigation_mode
            elif reading:
                workspace = 'lessons'
            elif current is self.micro_tabs.get("__histology__"):
                workspace = 'histology'      # an open slide belongs to Histology, not Explore
            elif current is self.anatomy_tab and radiology_visible:
                workspace = 'radiology'      # an open case belongs to Radiology
            elif (current is not self.anatomy_tab and current in self.micro_tabs.values()
                  or current in self._loading_models.values()):
                workspace = '3d models'      # an open (or loading) model belongs to 3D Models
            else:
                workspace = 'explore'
            self.studio_header.set_workspace(workspace)
            self.studio_header.subject.setVisible(current is self.anatomy_tab and not radiology_visible)
            self.studio_tools.setVisible(current is self.anatomy_tab)
            self._layout_studio_chrome()
            if not collection:self._studio_last_scene = current
        self._update_place_buttons()

    def _update_activity(self):
        if self._closing:
            return
        count = sum(p.serial is not None for p in self._loading_models.values()) + len(self._reference_loads)
        self.activity_label.setText(f"Loading {count} model" + ("s" if count != 1 else "") if count else "")
        self.activity_progress.setVisible(bool(count))

    def _model_load_error(self, model_id, pending, message):
        self._model_loader.cancel(model_id)
        commit_key = getattr(pending, "commit_key", None)
        if commit_key is not None:
            self._model_loader.cancel(commit_key)
            self._preference_commits.pop(commit_key, None)
        pending.serial = None
        callbacks, pending.callbacks = pending.callbacks, []
        pending.set_error(message)
        self._notify_model_callbacks(callbacks, None)
        self._update_activity()

    def _retry_model_load(self, model_id, pending):
        if self._closing or self._loading_models.get(model_id) is not pending:
            return
        entry = pending.entry
        if hasattr(entry, "meta") and hasattr(entry, "store") and hasattr(entry, "variant"):
            from .variants.catalog import DeferredVariantEntry
            entry = DeferredVariantEntry(entry.meta, entry.store, entry.variant, component=getattr(entry, "component", None))
        self._close_center_tab(self.center.indexOf(pending))
        self.open_micro(model_id, entry, persist_variant=getattr(pending, "persist_variant", False))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_ui_ready", False) and not self._layout_pending:
            self._layout_pending = True
            QTimer.singleShot(0, self._adapt_workspace)

    def _adapt_workspace(self):
        self._layout_pending = False
        if not self._ui_ready or self._closing:
            return
        panels = getattr(self, '_floating_panels', None)
        if panels is not None:
            panels.layout()
        self._compact_layout = self.width() < 1240

    # ------------------------------------------------------------------ status
    def _on_gl_ready(self):
        self.relations.start()
        self.depth_index.start()
        self.section_index.start()
        self._section_index_presented = False
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
                self.state._vis_dirty()
                self.view_panel.enable_depth(True)
            elif not getattr(self.depth_index, "failed", False):
                done = False
        if self.section_index.ready:
            if not getattr(self, "_section_index_presented", False):
                self.viewport.refresh_section()
                self.viewport.update()
                self._section_index_presented = True
        elif not getattr(self.section_index, "failed", False):
            done = False
        if done:
            self._depth_timer.stop()

    def on_depth_changed(self, cut, band):
        first = self.state.depth_cut == 0.0 and self.state.depth_band == 0.0
        if first and (cut > 0.0 or band > 0.0):
            self.state.push_undo()
        self.state.set_depth(cut, band)
        if hasattr(self, "dissect_btn"):
            self._mark_active(self.dissect_btn, cut > 0.0 or band > 0.0)
        if self.state.depth is not None:
            peeled, visible = self.state.depth_counts()
            if cut > 0.0 or band > 0.0:
                self.statusBar().showMessage(f"Dissection {cut * 100:.0f}% deep · {peeled:,} structures removed · "
                                             f"{visible:,} visible", 4000)
            elif self.statusBar().currentMessage().startswith("Dissection "):
                self.statusBar().clearMessage()

    def _on_frame(self, ms):
        if not self.settings.get("show_perf", True):
            self.perf_label.setText("")
            return
        self._frame_times.append(ms)
        now = time.perf_counter()
        if now - self._last_perf > 0.5:
            avg = sum(self._frame_times) / len(self._frame_times)
            self.perf_label.setText(f"Recent draw: {avg:.1f} ms")
            self.perf_label.setToolTip("Recent rendering work, including initial label placement. This reading stays unchanged while idle; it is not continuous FPS.")
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
        mv = self.active_model_view()
        if mv is not None:
            tris, n = mv.state.visible_triangle_count()
            self.count_label.setText(f"{n:,} {'part' if n == 1 else 'parts'} · {tris:,} triangles visible")
            self.xray_action.setChecked(mv.state.ghost_focus is not None)
        elif self.center.currentWidget() in (self.viewport, self.anatomy_tab):
            tris, n = self.state.visible_triangle_count()
            self.count_label.setText(f"{n:,} structures · {tris / 1e6:.2f} M triangles visible")
            self.xray_action.setChecked(self.state.ghost_focus is not None)
        else:
            self.count_label.clear()
            self.xray_action.setChecked(False)

    def _on_selection_changed(self):
        mv = self.active_model_view()
        if mv is not None:
            n = len(mv.state.selected)
        elif self.center.currentWidget() in (self.viewport, self.anatomy_tab):
            n = len(self.state.selected)
        else:
            n = 0
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
        if key == "show_structure_labels":
            self.cmds.actions["structure_labels"].setChecked(bool(value))
        if key == "show_status_bar":
            self.statusBar().setVisible(bool(value))
        if key == "color_mode":
            self.state.render_changed.emit()
            if hasattr(self, "color_actions"):
                self.color_actions[int(value)].setChecked(True)
        elif key == "ui_scale":
            apply_theme(QApplication.instance(), float(value))
            self._adapt_workspace()
        elif key == "details_scale":
            self.info.set_font_scale(float(value))
        elif key == "fov":
            self.viewport.camera.fov = float(value)
        for view in list(self.micro_tabs.values()):
            gl = getattr(view, "gl_widget", None)
            if gl is not None and hasattr(gl, "invalidate_labels"):
                gl.invalidate_labels()       # colours, backgrounds, labels and outlines are read every frame
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
            self.settings_dialog.themeChanged.connect(self._save_theme_preference)
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
            self.statusBar().showMessage(f"Borderless window — {default_key_text('borderless')} to bring the title bar "
                                         "back, drag the empty part of the top bar to move it", 6000)
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
        # Hide both only when both are showing; otherwise bring back whichever was closed.
        visible = self.left_dock.isVisible() and self.right_dock.isVisible()
        self.left_dock.setVisible(not visible)
        self.right_dock.setVisible(not visible)

    def dock_side_panels(self):
        """Keep Explore and Details in the canvas without consuming dock space."""
        from .ui.studio_shell import FloatingPanels
        if not hasattr(self, '_floating_panels'):
            self._floating_panels = FloatingPanels(self)
        self._floating_panels.layout()
        return False

    def reset_layout(self):
        if not hasattr(self, "_floating_panels"):
            self.restoreState(self._default_window_state)
        self.left_dock.show()
        self.right_dock.show()
        self.dock_side_panels()

    def toggle_auto_rotate(self):
        on = self.active_viewport().toggle_auto_rotate()
        self.auto_rotate_action.setChecked(on)

    def active_model_view(self):
        """The model tab in front, or None when it is the atlas (or the histology viewer)."""
        from .ui.model_view import ModelView
        w = self.center.currentWidget()
        reference = getattr(self, "_radiology_model_view", None)
        if w is self.anatomy_tab and reference is not None and not reference.isHidden():
            return reference
        return w if isinstance(w, ModelView) else None

    def about(self):
        try:
            from .ui.about import open_about
        except ImportError:
            pass
        else:
            open_about(self)
            return
        QMessageBox.about(self, APP_NAME, f"<h3>{APP_NAME}</h3><p>Personal 3D anatomy atlas.</p><p>"
                          + "<br>".join(self.ds.attribution) + "</p>")

    def _close_center_tab(self, index):
        if index <= 0:
            return
        w = self.center.widget(index)
        if w is None:
            return
        if w is getattr(self, '_lesson_visual', None):
            self._studio_explore()
            return
        if w is getattr(self, 'collection_workspace', None):
            self._studio_explore()
            return
        for key, pending in list(self._loading_models.items()):
            if pending is w:
                self._cancel_model_load(key, pending)
        # A cancellation observer may open/close another tab. Resolve the old
        # widget again rather than removing whatever moved into its index.
        index = self.center.indexOf(w)
        if index >= 0:
            self.center.removeTab(index)
        session = getattr(w, "runtime_session", None)
        if session is not None:
            session.close()
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
        w.deleteLater()

    def _center_changed(self, index):
        w = self.center.widget(index)
        mv = self.active_model_view()
        for key in ("model_next_view", "model_prev_view"):
            self.cmds.actions[key].setEnabled(mv is not None)
        for key in ("both_sides", "peel_in", "peel_out", "peel_reset"):
            self.cmds.actions[key].setEnabled(w is self.anatomy_tab)
        self.xray_action.setChecked(mv.state.ghost_focus is not None if mv else self.state.ghost_focus is not None)
        self.auto_rotate_action.setChecked(self.active_viewport().auto_rotate)
        vp = self._measurement_viewport()
        self._on_measure_changed(vp, vp.measure_text() if vp is not None else "")
        if hasattr(w, "on_activated"):
            w.on_activated(self.info)
        elif w in (self.viewport, self.anatomy_tab):
            self.info.show_structures(self.state.selected)
        self._update_counts()
        self._on_selection_changed()
        self._update_workspace_header()
        self._note_place()

    # ------------------------------------------------------------------ history
    def _record(self, entry):
        """An atlas selection, landmark or radiology pick the user made: it settles into a place for Back."""
        self._note_place()

    def navigate(self, step):
        """Back and Forward (keys and mouse buttons) go through every place visited, not only atlas selections."""
        self.go_place(step)

    # ------------------------------------------------------------------ places (Back / Forward)
    def _note_place(self, *_):
        # closing also removes the center tabs, which emits currentChanged after the place timer may be gone
        if not self._restoring_place and not self._closing:
            self._place_timer.start()

    def _capture_place(self):
        if self._restoring_place or self._closing or not hasattr(self, "studio_header"):
            return
        if self.center.currentWidget() in self._loading_models.values():
            # A model's loading placeholder is not a place (it read as "3D anatomy" and made Back stop there);
            # the model view that replaces it is recorded when it arrives.
            self._place_timer.start()
            return
        place = self._current_place()
        if place is not None:
            self.places.push(*place)
            # A group or landmark page in Details is not recoverable from the selection alone (Biceps brachii is
            # four meshes), so remember which page this place showed.
            view = getattr(self.info, "_view", None)
            if view and getattr(view[0], "__name__", "") in ("show_node", "show_landmark"):
                self._place_info[place[0]] = view
            else:
                self._place_info.pop(place[0], None)
        self._update_place_buttons()

    def _current_place(self):
        """(key, label) for what is on screen: the scene and the lesson step read beside it, if any."""
        from .ui.model_view import ModelView
        w = self.center.currentWidget()
        panel = self.lessons_panel
        lesson = None
        if panel is not None and panel.lesson is not None and not self.lesson_reader.isHidden():
            lesson = (panel.lesson.id, int(panel.index))
        if w is getattr(self, "collection_workspace", None):
            title = self.collection_workspace.navigation_mode
            scene, label = ("page", title), f"{title[:1].upper()}{title[1:]} library".replace("3d", "3D")
            lesson = None
        elif w is self.micro_tabs.get("__histology__"):
            if w.tissue is None:
                return None
            scene, label = ("histology", w.tissue["id"], int(w.index)), f"Histology – {w.tissue['name']}"
        elif isinstance(w, ModelView):
            selected = sorted(int(i) for i in w.state.selected)[:30]
            scene = ("model", w.entry.id, tuple(selected))
            label = f"{w.entry.name} model"
            if len(selected) == 1:
                label += f" – {w.vmodel.items[selected[0]].name}"
            elif selected:
                label += f" – {len(selected)} parts"
        elif self.radiology_panel is not None and not self.radiology_panel.isHidden() and self.radiology_panel.case:
            case = self.radiology_panel.case
            scene, label = ("radiology", case.id), f"Radiology – {case.title}"
        else:
            selected = [int(i) for i in self.state.selected][:30]
            scene = ("atlas", tuple(selected))
            label = "3D anatomy"
            if len(selected) == 1:
                label += f" – {self.ds.structures[selected[0]]['name']}"
            elif selected:
                label += f" – {len(selected)} structures"
        if lesson is not None:
            label = f"Lesson: {panel.lesson.title}, step {lesson[1] + 1}" + (
                f" · {label}" if scene[0] != "atlas" else "")
        return (scene, lesson), label

    def go_place(self, step):
        self._restore_place(self.places.go(step))

    def _restore_place(self, key):
        if key is None:
            return
        self._place_timer.stop()
        self._restoring_place = True
        try:
            scene, lesson = key
            panel = self.lessons_panel
            if lesson is not None and panel is not None:
                from .ui.lessons import PAGE_RUNNER
                lesson_id, step = lesson
                if panel.lesson is None or panel.lesson.id != lesson_id or panel.stack.currentIndex() != PAGE_RUNNER:
                    panel.open_lesson(lesson_id)
                panel.go(step)
                self._show_lesson_reader()
            elif scene[0] != "page" and not self.lesson_reader.isHidden():
                self.lesson_reader.hide()
            kind = scene[0]
            if kind == "page":
                pages = {"3d models": self._show_catalog, "lessons": self._show_lesson_library,
                         "histology": self.show_histology_tab,
                         "radiology": lambda: self._show_nav_page(self.radiology_browser)}
                pages.get(scene[1], self._show_atlas)()
            elif kind == "histology":
                self.open_histology(scene[1], scene[2])
            elif kind == "radiology":
                self.open_radiology(scene[1])
            elif kind == "model":
                def select(view, parts=list(scene[2])):
                    if view is not None and list(view.state.selected) != parts:
                        view.state.select(parts)
                self.open_micro(scene[1], on_ready=select)
            else:
                if self.center.currentIndex() != 0 or (self.radiology_panel is not None
                                                       and not self.radiology_panel.isHidden()):
                    self._show_atlas()
                if scene[1]:
                    self.select_and_focus(list(scene[1]))
                elif self.state.selected:
                    self.state.select([])
                view = self._place_info.get(key)
                if view is not None:
                    view[0](*view[1])
        finally:
            # what the restore itself changes (a lesson step applying its scene, a model finishing loading) is
            # part of going back, not a new place
            QTimer.singleShot(500, self._end_place_restore)
        self._update_place_buttons()

    def _end_place_restore(self):
        self._restoring_place = False

    def _fill_places_menu(self):
        menu = self.studio_header.places_menu
        menu.clear()
        for index, label, current in self.places.recent():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(current)
            action.triggered.connect(lambda _checked=False, i=index: self._restore_place(self.places.jump(i)))
        if menu.isEmpty():
            menu.addAction("No places yet").setEnabled(False)

    def _update_place_buttons(self):
        back, forward = self.places.label(-1), self.places.label(1)
        self.cmds.actions["back"].setEnabled(bool(back))
        self.cmds.actions["forward"].setEnabled(bool(forward))
        if hasattr(self, "studio_header"):
            self.studio_header.set_places(back, forward)

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
        m.deleteLater()

    def pick_color(self):
        if not self.state.selected:
            return
        c = QColorDialog.getColor(parent=self, title="Structure color")
        if c.isValid():
            self.state.set_custom_color(self.state.selected, (c.redF(), c.greenF(), c.blueF()))

    def on_link(self, scheme, payload):
        xray = self.state.ghost_focus is not None
        if scheme == "modeloverview":
            view = self.active_model_view()
            if view is not None and view.entry.id == payload:
                view.state.select([])        # an empty selection shows the model's own overview in Details
            return
        if scheme == "modelpart":
            view = self.active_model_view()
            model_id, separator, raw_index = payload.rpartition("|")
            try:
                index = int(raw_index)
            except ValueError:
                return
            if (view is None or not separator or view.entry.id != model_id
                    or index not in view.state.selected or not 0 <= index < len(view.vmodel.items)):
                return
            view.state.select([index])
            self.right_dock.show()
            self.right_dock.raise_()
        elif scheme == "url":
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
        elif scheme == "sfmodel":
            self.open_local_model(payload)
        elif scheme == "atlas":
            self._atlas_structures([n for n in payload.split("|") if n])
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
            self._show_nav_page(self.histology_panel)

    def open_histology(self, tissue_id, index=0):
        try:
            from .ui.histology import HistologyViewer
        except ImportError:
            return
        tissue = self.content.tissues.get(tissue_id)
        if not tissue:
            self.notice.show_message("This tissue is not in the installed histology library.",
                                     "Browse histology", self.show_histology_tab)
            return
        viewer = self.micro_tabs.get("__histology__")
        if viewer is None:
            viewer = HistologyViewer(self.ds, self.content)
            viewer.structuresRequested.connect(self._histology_structures)
            viewer.browserRequested.connect(self.show_histology_tab)
            viewer.detailsRequested.connect(self.right_dock.show)
            self.micro_tabs["__histology__"] = viewer
            self.center.addTab(viewer, "Histology")
        viewer.show_tissue(tissue_id, index)
        self.center.setCurrentWidget(viewer)
        title = f"Histology · {self.content.tissues[tissue_id]['name']}"
        self.center.setTabText(self.center.indexOf(viewer), title.replace("&", "&&"))   # "&" is a mnemonic
        viewer.on_activated(self.info)
        self.left_dock.hide()
        self.right_dock.hide()
        self._note_place()

    def _histology_structures(self, names):
        sids = [s for n in names for s in self.ds.structures_named(n)]
        if sids:
            self.select_and_focus(sids, xray=True)

    def open_local_model(self, uid):
        """A downloaded model, by its Sketchfab uid (old links and saved references use it)."""
        self.open_micro(f"sketchfab:{uid}")

    def _atlas_structures(self, names):
        """'Show in the atlas': back to the 3D anatomy with what a model's part depicts selected and framed."""
        sids = self.lesson_resolver.resolve_all(names) if getattr(self, "lesson_resolver", None) else []
        if not sids:
            self.statusBar().showMessage("Nothing in the atlas matches this part.", 3000)
            return
        self.center.setCurrentIndex(0)
        self.state.force_show(sids)
        self.select_and_focus(sids, xray=True)

    def switch_model_variant(self, model_id, variant, *, component=None):
        """Replace the model's current view with one independently verified version.

        Resolve before retiring the former view. Preferences are committed by
        the successful result handler, never by a failed or cancelled request.
        """
        if self._closing or variant not in ("pre", "post"):
            return
        entry = self.content.micro_models.get(model_id)
        if entry is None or not hasattr(entry, "for_variant"):
            return
        active = self.micro_tabs.get(model_id)
        scene = component or getattr(getattr(active, "entry", None), "component", "main")
        if (active is not None and getattr(active.entry, "variant", None) == variant
                and getattr(active.entry, "component", "main") == scene):
            self.center.setCurrentWidget(active)
            return
        try:
            chosen = entry.for_variant(variant)
            if hasattr(chosen, "for_component"):
                chosen = chosen.for_component(scene)
            elif component is not None:
                raise ValueError("This model has no selectable inset scene")
        except Exception as exc:
            self.notice.show_message(f"This model version could not be verified: {exc}",
                                     "Browse models", self._show_catalog)
            self.catalog._preview()
            return
        practice = getattr(self.lessons_panel, "practice", None)
        if practice is not None:
            practice.stop()
        if self.quiz is not None:
            self.quiz.stop()
        reference_key = "radiology-reference:" + model_id
        reference = getattr(self, "_radiology_model_view", None)
        if (reference_key in self._reference_loads
                or getattr(getattr(reference, "entry", None), "id", None) == model_id):
            self._radiology_frame_token = getattr(self, "_radiology_frame_token", 0) + 1
            self._model_loader.cancel(reference_key)
            self._reference_loads.pop(reference_key, None)
        pending = self._loading_models.get(model_id)
        if pending is not None:
            self._close_center_tab(self.center.indexOf(pending))
        for key, view in list(self.micro_tabs.items()):
            if getattr(getattr(view, "entry", None), "id", None) != model_id:
                continue
            index = self.center.indexOf(view)
            if index >= 0:
                self._close_center_tab(index)
            else:
                view.hide()
                session = getattr(view, "runtime_session", None)
                if session is not None:
                    session.close()
                gl = getattr(view, "gl_widget", None)
                if gl is not None:
                    gl.release_gl()
                self.micro_tabs.pop(key, None)
                if getattr(self, "_radiology_model_view", None) is view:
                    self._radiology_model_view = None
                    self.viewport.show()
                    self.anatomy_tab.gl_widget = self.viewport
                view.deleteLater()
        self.open_micro(model_id, entry=chosen, persist_variant=component is None)

    def switch_model_component(self, model_id, component):
        """One matching inset/main scene, without writing a version preference."""
        if model_id != "axillary_skin" or component not in ("main", "cell_inset"):
            return
        active = self.micro_tabs.get(model_id)
        if active is not None:
            self.switch_model_variant(model_id, active.entry.variant, component=component)

    def open_micro(self, model_id, entry=None, *, on_ready=None, persist_variant=False):
        """Open/reuse a tab; prepare CPU data off-thread, build widgets only here.

        Callers needing part selection/practice must use on_ready rather than
        assuming the model has finished when this method returns.
        """
        if self._closing:
            return
        view = self.micro_tabs.get(model_id)
        if view is not None:
            self.center.setCurrentWidget(view)
            view.on_activated(self.info)
            if on_ready is not None:
                self._when_view_interactive(view, on_ready)
            return
        pending = self._loading_models.get(model_id)
        if pending is not None:
            if on_ready is not None:
                if pending.serial is None:
                    on_ready(None)  # failed tabs remain visible, but must not strand an observer
                else:
                    pending.callbacks.append(on_ready)
            self.center.setCurrentWidget(pending)
            return
        entry = entry or self.content.micro_models.get(model_id)
        if entry is None:
            self.statusBar().showMessage(f"There is no 3D model called {model_id}.", 5000)
            if on_ready is not None:
                on_ready(None)
            return
        from .ui.model_loading import ModelLoadingTab
        pending = ModelLoadingTab(entry, self.center)
        pending.persist_variant = persist_variant
        if on_ready is not None:
            pending.callbacks.append(on_ready)
        self._loading_models[model_id] = pending
        pending.cancelled.connect(lambda: self._close_center_tab(self.center.indexOf(pending)))
        pending.retryRequested.connect(lambda: self._retry_model_load(model_id, pending))
        pending.destroyed.connect(lambda: self._cancel_model_load(model_id, pending))
        label = "3D · " if entry.kind != "procedural" else "Micro · "
        version = ""
        self.center.addTab(pending, f"{label}{entry.name}{version}".replace("&", "&&"))
        self.center.setCurrentWidget(pending)
        self.left_dock.hide()
        self.right_dock.hide()
        try:
            pending.serial = self._model_loader.request(model_id, entry)
        except Exception as exc:
            self._model_load_error(model_id, pending, str(exc))

    def when_model_ready(self, model_id, callback):
        """Observe an existing load without starting it or changing navigation."""
        if self._closing:
            return
        view = self.micro_tabs.get(model_id)
        if view is not None:
            self._when_view_interactive(view, callback)
        elif (pending := self._loading_models.get(model_id)) is not None:
            if pending.serial is None:
                callback(None)
            else:
                pending.callbacks.append(callback)
        else:
            callback(None)

    def _cancel_model_load(self, model_id, pending):
        if self._loading_models.get(model_id) is not pending:
            return
        del self._loading_models[model_id]
        self._model_loader.cancel(model_id)
        prepared = getattr(pending, "prepared_view", None)
        if prepared is not None:
            session = getattr(prepared, "runtime_session", None)
            if session is not None:
                session.close()
            prepared.gl_widget.release_gl()
        callbacks, pending.callbacks = pending.callbacks, []
        self._notify_model_callbacks(callbacks, None)

    def _notify_model_callbacks(self, callbacks, view, model_id=None):
        for callback in callbacks:
            if self._closing or (view is not None and self.micro_tabs.get(model_id) is not view):
                break
            try:
                callback(view)
            except Exception:
                # An observer must not strand a pending tab or prevent the
                # remaining lifetime cleanup. Report its own failure separately.
                import traceback
                traceback.print_exc()

    def _when_view_interactive(self, view, callback):
        """CPU completion is not graphics readiness; wait for the actual first draw."""
        viewport = view.gl_widget
        if getattr(viewport, "graphics_error", ""):
            callback(None)
            return
        ready_signal = getattr(viewport, "interactiveReady", None)
        if ready_signal is None or getattr(viewport, "interactive_ready", False):
            callback(view)
            return
        finished = [False]
        def finish(value):
            if finished[0]:
                return
            finished[0] = True
            if not self._closing:
                callback(value)
        ready_signal.connect(lambda: finish(view))
        viewport.graphicsFailed.connect(lambda message: finish(None))
        viewport.destroyed.connect(lambda: finish(None))

    def _connect_model_view(self, view):
        panel = self.lessons_panel
        if not self.lesson_reader.isHidden() and panel is not None and panel.lesson is not None:
            view.studio.set_lesson_mode(panel.lesson.steps[panel.index].get("micro") == view.entry.id)
        g = view.gl_widget
        g.measureChanged.connect(lambda text, vp=g: self._on_measure_changed(vp, text))
        g.hoverChanged.connect(lambda sid, v=view: self._on_model_hover(v, sid))
        g.frameTimed.connect(self._on_frame)
        g.historyRequested.connect(self.navigate)
        for action in self.cmds.actions.values():
            if action.shortcutContext() == Qt.WidgetWithChildrenShortcut:
                g.addAction(action)
        view.openHistology.connect(self.open_histology)
        view.openMicro.connect(self.open_micro)
        view.variantRequested.connect(lambda variant, mid=view.entry.id: self.switch_model_variant(mid, variant))
        view.componentRequested.connect(lambda component, mid=view.entry.id: self.switch_model_component(mid, component))
        view.atlasRequested.connect(self._atlas_structures)
        view.lessonsRequested.connect(self._show_model_lessons)
        if self.lessons_panel is not None:
            view.set_lessons_available(len(self.lessons_panel.lessons_for_model(view.entry.id)))
        view.state.visibility_changed.connect(self._update_model_actions)
        view.state.selection_changed.connect(self._on_selection_changed)

    def _model_load_finished(self, result):
        if self._closing:
            return
        commit = self._preference_commits.get(result.key)
        if commit is not None:
            serial, prepared_result, pending, view = commit
            if serial != result.serial:
                return
            del self._preference_commits[result.key]
            if self._loading_models.get(prepared_result.key) is not pending:
                return
            if result.error:
                self._fail_prepared_model(prepared_result, pending, view, result.error)
            elif result.model.token != view.entry.descriptor.token:
                self._fail_prepared_model(prepared_result, pending, view, "Selected generation changed before preference commit")
            else:
                self._publish_model_load(prepared_result, pending, view)
            return
        reference = self._reference_loads.get(result.key)
        if reference is not None:
            serial, callback = reference
            if serial == result.serial:
                del self._reference_loads[result.key]
                callback(result)
            return
        pending = self._loading_models.get(result.key)
        if pending is None or pending.serial != result.serial:
            return
        index = self.center.indexOf(pending)
        if index < 0:
            self._cancel_model_load(result.key, pending)
            pending.deleteLater()
            return
        entry = getattr(result.model, "runtime_entry", pending.entry)
        pending.entry = entry
        if result.error:
            self._model_load_error(result.key, pending, str(result.error))
            return
        from .ui.model_view import ModelView
        view = None
        try:
            # Parent partial construction to the pending tab so exceptions cannot
            # strand a half-built QWidget. Reparent after successful construction.
            view = ModelView(entry, self.content, self.settings, parent=pending, prepared=result)
            self._connect_model_view(view)
            pending.prepared_view = view
        except Exception as exc:
            if view is not None:
                view.gl_widget.release_gl()
                view.deleteLater()
            self._model_load_error(result.key, pending, str(exc))
            return
        QTimer.singleShot(0, view, lambda: self._complete_model_load(result, pending, view))

    def _complete_model_load(self, result, pending, view):
        if (self._closing or self._loading_models.get(result.key) is not pending
                or pending.serial != result.serial):
            return
        index = self.center.indexOf(pending)
        if index < 0:
            self._cancel_model_load(result.key, pending)
            pending.deleteLater()
            return
        if not view.runtime_opening_done:
            QTimer.singleShot(0, view, lambda: self._complete_model_load(result, pending, view))
            return
        entry = pending.entry
        try:
            if view.runtime_opening_error:
                raise ValueError(view.runtime_opening_error)
            if getattr(pending, "persist_variant", False) and hasattr(entry, "commit_selection"):
                from .variants.catalog import VariantPreferenceCommit
                if getattr(pending, "commit_key", None) is not None:
                    return
                key = "variant-preference:" + result.key
                serial = self._model_loader.request(key, VariantPreferenceCommit(entry))
                pending.commit_key = key
                self._preference_commits[key] = (serial, result, pending, view)
                return
        except Exception as exc:
            self._fail_prepared_model(result, pending, view, str(exc))
            return
        self._publish_model_load(result, pending, view)

    def _fail_prepared_model(self, result, pending, view, message):
        session = getattr(view, "runtime_session", None)
        if session is not None:
            session.close()
        view.gl_widget.release_gl()
        view.deleteLater()
        pending.prepared_view = None
        self._model_load_error(result.key, pending, str(message))

    def _publish_model_load(self, result, pending, view):
        if self._closing or self._loading_models.get(result.key) is not pending:
            return
        index = self.center.indexOf(pending)
        if index < 0:
            self._cancel_model_load(result.key, pending)
            return
        entry = view.entry
        if hasattr(entry, "commit_selection"):
            from .variants.catalog import DeferredVariantEntry
            display = DeferredVariantEntry(entry.meta, entry.store, entry.variant, component=getattr(entry, "component", None))
            for field in ("outcome", "validation_scope", "baseline_defects"):
                setattr(display, field, getattr(entry, field, None))
            display.verification_state = "verified_selected"
            self.content.micro_models[result.key] = display
            self.catalog._run()
        current = self.center.currentWidget()
        if current is pending:
            self.left_dock.hide()
        title = self.center.tabText(index)
        callbacks, pending.callbacks = pending.callbacks, []
        del self._loading_models[result.key]
        self.micro_tabs[result.key] = view
        view.setParent(self.center)
        view.state.selection_changed.connect(self._note_place)
        # No stale completion steals focus from a newer tab or atlas navigation.
        self.center.blockSignals(True)
        try:
            self.center.removeTab(index)
            self.center.insertTab(index, view, title)
            self.center.setCurrentWidget(view if current is pending else current)
        finally:
            self.center.blockSignals(False)
        pending.deleteLater()
        self._center_changed(self.center.currentIndex())
        if callbacks:
            self._when_view_interactive(view, lambda ready:
                self._notify_model_callbacks(callbacks, ready, result.key))

    def _on_model_hover(self, view, sid):
        if self.quiz is not None and self.quiz.names_hidden():
            self.hover_label.setText("")
            return
        if sid < 0 or view.click_hook is not None:
            self.hover_label.setText("")
            return
        it = view.vmodel.items[sid]
        self.hover_label.setText(f"{it.name}  ·  {it.group}" if it.group != it.name else it.name)

    def _update_model_actions(self):
        self._update_counts()

    def open_model_file(self, path=None):
        """File -> Open 3D model file: any glTF / GLB file (with a .viewer.json sidecar beside it if it has one)
        opens in the model viewer."""
        if not path:
            start = self.qsettings.value("model_dir", str(Path.home()))
            path, _ = QFileDialog.getOpenFileName(self, "Open a 3D model", start, "glTF models (*.glb *.gltf)")
            if not path:
                return
        from .viewer.catalog import FileEntry
        entry = FileEntry(path)
        self.qsettings.setValue("model_dir", str(Path(path).parent))
        self.open_micro(entry.id, entry)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith((".glb", ".gltf"))
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith((".glb", ".gltf")):
                self.open_model_file(u.toLocalFile())
                break

    def _add_models_menu(self, menu):
        """Study -> 3D models: every model the viewer can open, by kind."""
        entries = list(self.content.micro_models.values())
        sub = menu.addMenu(f"3D models ({len(entries)})")
        for kind, title in (("glb", None), ("procedural", "Microanatomy"), ("downloaded", "Downloaded")):
            group = sorted((e for e in entries if e.kind == kind), key=lambda e: e.name.lower())
            if not group:
                continue
            target = sub if title is None else sub.addMenu(f"{title} ({len(group)})")
            for e in group:
                target.addAction(e.name.replace("&", "&&"), lambda _=False, i=e.id: self.open_micro(i))

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
        dlg = NoteDialog(key, self.content.notes.get(key, ""), self,
                         save=lambda text: self.content.set_note(key, text))
        if dlg.exec():
            self.info._rerender()

    def show_all_notes(self):
        from .ui.notes import AllNotesDialog
        dlg = AllNotesDialog(self.content, self)
        dlg.noteActivated.connect(lambda name: self._histology_structures([name]))
        dlg.exec()

    def show_progress(self):
        """Accuracy, the spaced-repetition schedule and the structures that keep catching you out."""
        import json

        from .config import USER_DIR
        from .ui.progress import ProgressDialog
        quiz = getattr(self, "quiz", None)
        if quiz is not None:
            stats = quiz.stats
        else:
            stats = {}
            path = USER_DIR / "quiz_stats.json"
            try:
                from .srs import normalize_stats
                stats = normalize_stats(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                stats = {}
        lessons = self.lessons_panel.lessons if self.lessons_panel is not None else None
        lesson_progress = self.lessons_panel.progress if self.lessons_panel is not None else None
        ProgressDialog(stats, lessons, lesson_progress, self).exec()

    # ------------------------------------------------------------------ radiology
    def show_radiology(self, case_id=None):
        if self.radiology_browser is None:
            return
        self._show_nav_page(self.radiology_browser)
        if case_id:
            self.open_radiology(case_id)
        elif self.radiology_panel.case is None and self.radiology_cases:
            self.open_radiology(self.radiology_cases[0].id)

    def open_radiology(self, case_id):
        """Show an authored case beside its deterministic anatomical reference."""
        case = next((c for c in self.radiology_cases if c.id == case_id), None)
        if case is None or self.radiology_panel is None:
            return
        self.lesson_reader.hide()
        self.center.setCurrentIndex(0)
        self.radiology_panel.show_case(case)
        if self.radiology_browser is not None:
            self.radiology_browser.set_current_case(case.id)
        if not self.radiology_panel.isVisible():
            self.radiology_panel.show()
            total = max(self.anatomy_tab.width(), 800)
            self.anatomy_tab.setSizes([int(total * 0.42), int(total * 0.58)])
        self.apply_radiology_scene(case)
        self.statusBar().showMessage(f"{case.title} - labels highlight anatomy already in this reference view.", 8000)
        self._record(("rad_case", case.id))
        self._update_workspace_header()
        self.left_dock.hide()
        self.right_dock.hide()

    def apply_radiology_scene(self, case):
        """Reapply explicit case anatomy from a baseline without changing preferences.

        Only authored show/focus/ghost_focus sets introduce anatomy. Image labels
        are not an implicit Show All command, particularly on projection cases.
        Reference reset and first/open/reentry share this same boundary.
        """
        if self.radiology_panel is None or self.radiology_panel.case is not case:
            return
        self._radiology_frame_token = getattr(self, "_radiology_frame_token", 0) + 1
        frame_token = self._radiology_frame_token
        self._cancel_reference_loads()
        st, vp = self.state, self.viewport
        old_reference = getattr(self, "_radiology_model_view", None)
        if old_reference is not None:
            old_reference.hide()
        self._radiology_model_view = None
        self.viewport.show()
        self.anatomy_tab.gl_widget = self.viewport
        before = st._snapshot()
        previous_undo = list(st._undo)
        baseline = SceneState(self.ds, self.settings)
        st.restore(baseline._snapshot())
        st.clear_selection()
        st.set_hovered(-1)
        st.set_custom_color(list(st.custom_colors), None)
        vp.landmark_hosts = []
        vp.focus_landmark = None
        self.hover_label.setText("")
        self.info.show_welcome()
        scene = dict(case.scene)
        # This case embeds an existing model alongside its scan. Do not open or
        # change the user's ordinary model tab through apply_scene's micro path.
        model_id = scene.pop("micro", None) if scene.get("micro_focus") else None
        # Case entry always replaces the former cut. An authored new cut still
        # applies below; reset_clips=False cannot inherit a previous case's cut.
        scene["reset_clips"] = True
        if scene.get("slice_only") is True and scene.get("clip"):
            # A scan section shows everything the plane passes through, not a hand-picked few systems.
            scene["systems"] = sorted(set(scene.get("systems", [])) | SECTION_SYSTEMS)
        side = (scene.get("side") or "").lower()
        if side:
            for key in ("show", "focus", "ghost_focus", "frame_on"):
                if key in scene:
                    scene[key] = [name for name in scene[key]
                                  if not self.lesson_resolver.resolve(name) or
                                  any(self.ds.structures[s]["side"].lower() in (side, "")
                                      for s in self.lesson_resolver.resolve(name))]
        try:
            self.apply_scene(scene)
            # A section's audited anatomical links belong to its FIRST reference
            # view. Clicking a label only highlights them later. Projection cases
            # keep their purposeful authored show/isolation instead.
            if scene.get("slice_only") is True:
                from .radiology_reference import resolve_reference
                required = set()
                for label in case.labels:
                    required.update(resolve_reference(self.ds, self.lesson_resolver,
                                                       label.structures, label.side or side))
                # The soft tissue between the organs, so the cut reads as a body rather than empty space.
                regions = set(scene.get("regions") or [r["key"] for r in self.ds.regions])
                required.update(sid for sid, st_ in enumerate(self.ds.structures)
                                if st_["subsystem"] == "Section fill" and regions & set(st_["regions"]))
                if required:
                    st.set_hidden(sorted(required), False, undo=False)
                    st.force_show(sorted(required))
                    if st.isolated is not None:
                        st.isolated[list(required)] = True
                        st._vis_dirty()
                    vp.refresh_section()
                    if scene.get("frame", True) and not scene.get("camera") and not scene.get("frame_on"):
                        vp.frame_section(view=scene.get("view"))
                        # Showing the case pane can change the splitter's size
                        # again in the queued layout pass. Refit using the final
                        # viewport, but never let a stale case move a later view.
                        # A cancelled context-bound timer can outlive its Qt
                        # owner in the Python binding. Never let its callable
                        # retain the window or the viewport's CPU geometry.
                        window_ref, viewport_ref = weakref.ref(self), weakref.ref(vp)
                        def settled_section_frame():
                            window, viewport = window_ref(), viewport_ref()
                            if (window is not None and viewport is not None
                                    and not getattr(window, "_closing", False)
                                    and getattr(window, "_radiology_frame_token", None) == frame_token
                                    and window.radiology_panel.case is case
                                    and window.radiology_panel.isVisible()
                                    and viewport.radiology_slice):
                                viewport.frame_section(view=scene.get("view"))
                        QTimer.singleShot(0, self, settled_section_frame)
            self._radiology_groups = self._radiology_label_groups(case, scene, side)
            self._show_radiology_labels(self.radiology_panel.labels_on.isChecked())
            if model_id and scene.get("micro_focus"):
                self._open_radiology_model(model_id, case, scene, frame_token)
        finally:
            # Existing apply_scene/state helpers create several snapshots; one
            # case entry is one visibility undo action with its pre-entry state.
            st._undo[:] = (previous_undo + [before])[-100:]

    def _radiology_label_groups(self, case, scene, side):
        """The 3D names for a case: its authored reference labels, else its image labels, numbered as on the scan.
        None when the case has none, which keeps the atlas's own section labels."""
        from .radiology_reference import resolve_reference
        if scene.get("micro_focus"):
            return None                                 # the case's model reference names its own parts
        authored = scene.get("reference_labels")
        if authored is not None:
            return [(entry["text"], resolve_reference(self.ds, self.lesson_resolver, entry.get("structures", []),
                                                      entry.get("side") or side), bool(entry.get("surface_anchor")))
                    + ((tuple(entry["at"]),) if entry.get("at") else ())
                    for entry in authored]
        groups = []
        for number, label in enumerate(case.labels, 1):
            ids = resolve_reference(self.ds, self.lesson_resolver, label.structures, label.side or side)
            if ids:
                # a pinned label carries its point, so several labels can name places on one structure
                at = getattr(label, "at", None)
                groups.append((f"{number}  {label.text}", ids, False) + ((at,) if at else ()))
        return groups or None

    def _show_radiology_labels(self, on):
        """The scan's Labels box names the same anatomy in the 3D reference, atlas or model."""
        groups = getattr(self, "_radiology_groups", None)
        self.viewport.set_radiology_section_labels(groups if on or groups is None else [])
        view = getattr(self, "_radiology_model_view", None)
        if view is not None and getattr(view, "_radiology_labels", None) is not None:
            view.gl_widget.reference_labels = view._radiology_labels if on else {}
            view.gl_widget.invalidate_labels()
            view.gl_widget.update()

    def _cancel_reference_loads(self):
        for key in self._reference_loads:
            self._model_loader.cancel(key)
        self._reference_loads.clear()
        self._preference_commits.clear()

    def _open_radiology_model(self, model_id, case, scene, frame_token):
        key = "radiology-reference:" + model_id
        def current():
            return (not self._closing and self._radiology_frame_token == frame_token
                    and self.radiology_panel.case is case and not self.radiology_panel.isHidden())
        def activate(view):
            if not current():
                return
            self._radiology_model_view = view
            self.viewport.hide()
            view.show()
            self.anatomy_tab.gl_widget = view.gl_widget
            view._radiology_ready = False
            def configure():
                if not current():
                    return
                ms, mg = view.state, view.gl_widget
                ms.restore(SceneState(view.mds, self.settings)._snapshot())
                ms.clear_selection()
                ms.set_hovered(-1)
                ms.set_custom_color(list(ms.custom_colors), None)
                mg.sections = [None, None, None]
                mg.cut_on = False
                mg.show_state("assembled")
                focus, missing = view.part_ids(scene["micro_focus"])
                context, _ = view.part_ids(scene.get("micro_context", []))
                if missing:
                    self.statusBar().showMessage("Reference parts unavailable: " + ", ".join(missing), 6000)
                if focus:
                    ms.isolate(sorted(set(focus + context)))
                    ms.set_ghost_focus(focus)
                    view.labels.setChecked(False)
                    view.side.hide()
                    bar = view.findChild(QWidget, "modelBar")
                    if bar is not None:
                        bar.hide()
                    view.section_bar.hide()
                    mg.frame_structures(focus, duration=0.0, view=scene.get("model_view", "anterior"))
                # The case's image labels, numbered as on the scan, name the same parts of the model.
                visible = ms.visible_mask()
                names = {}
                for number, label in enumerate(case.labels, 1):
                    ids, _ = view.part_ids(label.structures)
                    shown = [i for i in ids if visible[i] and i not in names]
                    if shown:
                        names[max(shown, key=lambda i: len(view.vmodel.items[i].parts))] = f"{number}  {label.text}"
                view._radiology_labels = names
                mg.reference_labels = names if self.radiology_panel.labels_on.isChecked() else {}
                mg.invalidate_labels()
                view._radiology_ready = True
                self._center_changed(self.center.currentIndex())
            QTimer.singleShot(0, view, configure)
        view = self.micro_tabs.get(key)
        if view is not None:
            activate(view)
            return
        entry = self.content.micro_models.get(model_id)
        if entry is None:
            self.statusBar().showMessage(f"Reference model unavailable: {model_id}", 6000)
            return
        def loaded(result):
            if not current():
                return
            if result.error:
                self.notice.show_message(f"The anatomical reference for this case could not open: {result.error}",
                                         "Retry reference", lambda: self._retry_radiology_reference(case))
                return
            from .ui.model_view import ModelView
            owner = QWidget(self.anatomy_tab)
            try:
                prepared_entry = getattr(result.model, "runtime_entry", entry)
                view = ModelView(prepared_entry, self.content, self.settings, parent=owner, prepared=result)
                self._connect_model_view(view)
                self.anatomy_tab.addWidget(view)
            except Exception as exc:
                self.notice.show_message(f"The anatomical reference for this case could not open: {exc}",
                                         "Retry reference", lambda: self._retry_radiology_reference(case))
                return
            finally:
                owner.deleteLater()
            self.micro_tabs[key] = view
            activate(view)
        try:
            serial = self._model_loader.request(key, entry)
        except Exception as exc:
            self.notice.show_message(f"The anatomical reference could not start loading: {exc}",
                                     "Retry reference", lambda: self._retry_radiology_reference(case))
            return
        self._reference_loads[key] = (serial, loaded)

    def _retry_radiology_reference(self, case):
        if (not self._closing and self.radiology_panel is not None
                and self.radiology_panel.case is case and not self.radiology_panel.isHidden()):
            self.apply_radiology_scene(case)

    def close_radiology(self):
        self._cancel_reference_loads()
        self._radiology_frame_token = getattr(self, "_radiology_frame_token", 0) + 1
        model_view = getattr(self, "_radiology_model_view", None)
        if model_view is not None:
            model_view.hide()
        self._radiology_model_view = None
        self.viewport.show()
        self.anatomy_tab.gl_widget = self.viewport
        self.viewport.set_radiology_slice(False)
        if self.radiology_panel is not None:
            self.radiology_panel.hide()

    def step_radiology(self, delta):
        panel = self.radiology_panel
        if panel is None or panel.case is None:
            return
        ids = self.radiology_browser.visible_case_ids() if self.radiology_browser is not None else []
        if panel.case.id not in ids:
            ids = [c.id for c in self.radiology_cases]
        if not ids or panel.case.id not in ids:
            return
        i = (ids.index(panel.case.id) + delta) % len(ids)
        self.open_radiology(ids[i])

    def on_radiology_pick(self, names, frame=True, side=""):
        """Highlight an existing reference link without changing its presentation."""
        case = self.radiology_panel.case if self.radiology_panel is not None else None
        model_view = getattr(self, "_radiology_model_view", None) if case else None
        if model_view is not None and case.scene.get("micro_focus"):
            ids, _missing = model_view.part_ids(names)
            visible = model_view.state.visible_mask()
            ids = [sid for sid in ids if visible[sid]]
            if ids:
                self.center.setCurrentIndex(0)
                model_view.state.select(ids)
                model_view._show_selection()
            else:
                self.statusBar().showMessage("That image label has no visible part in this illustrative reference.", 5000)
            return
        side = (side or (case.scene.get("side") if case else "") or "").lower()
        from .radiology_reference import resolve_reference
        sids = resolve_reference(self.ds, self.lesson_resolver, names, side) if getattr(self, "lesson_resolver", None) else []
        if not sids:
            self.statusBar().showMessage("That label has no matching structure in the model for this reference.", 4000)
            return
        sids = self.viewport.radiology_reference_ids(sids)
        if not sids:
            self.statusBar().showMessage("That anatomy is not visible on this reference; the label does not add off-plane anatomy. Use Reset 3D to restore the reference.", 5000)
            return
        # Selection alone retains authored ghost/context, cutting plane and
        # camera. Search preferences apply to search, not numbered image labels.
        self.center.setCurrentIndex(0)
        self.state.select(sids)
        self.viewport.landmark_hosts = sids if len(sids) <= 2 else []
        self.viewport.focus_landmark = None
        self.info.show_structures(sids)
        self.tree.reveal(sids[0])
        self._update_counts()
        if case is not None:
            self._record(("rad_pick", (case.id, tuple(names), side)))

    # ------------------------------------------------------------------ lessons
    def show_lessons(self, lesson_id=None):
        restore_reader = self.lesson_reader.isHidden() or (
            self.radiology_panel is not None and not self.radiology_panel.isHidden())
        self.close_radiology()
        if self.lessons_panel is None:
            return
        self._show_nav_page(self.lessons_panel)
        if lesson_id:
            self.lessons_panel.open_lesson(lesson_id)
        elif restore_reader:
            from .ui.lessons import PAGE_RUNNER
            panel = self.lessons_panel
            if panel.lesson is not None and panel.stack.currentIndex() == PAGE_RUNNER:
                self.apply_lesson_step(panel.lesson.steps[panel.index])

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
        if self.quiz.active:
            self.quiz.stop()
        self.quiz.open()
        self.state.show_all()
        self.state.force_show(sids)
        self.quiz.start(bases=bases)

    def _remember_lesson(self, lesson):
        self.qsettings.setValue("last_lesson", lesson.id)
        from .ui.lessons import PAGE_RUNNER
        if self.lessons_panel.stack.currentIndex() == PAGE_RUNNER:
            self._show_lesson_reader()
        else:
            self._show_lesson_library()

    def _study_entry_picked(self, label):
        """"Lab course", "Lecture exams" and "Lessons" share the lesson page: the first two open it as that course,
        the last as the library."""
        if self.lessons_panel is None:
            return
        if label == "Lab course":
            self.lessons_panel.show_course()
        elif label == "Lecture exams":
            self.lessons_panel.show_lecture()
        elif label == "Lessons" and self.lessons_panel.group_by in ("course", "lecture"):
            self.lessons_panel._set_group("system")

    def _lesson_closed(self):
        self._show_lesson_library()
        self.state.clear_ghost()
        self.state.clear_forced()
        self.view_panel.set_depth(0.0, False)
        self.view_panel.reset_clips()

    def apply_lesson_step(self, step):
        self.close_radiology()
        if step.get("lesson_view") in ("diagram", "reading"):
            visual = getattr(self, "_lesson_visual", None)
            if visual is None:
                from .ui.diagram import LessonVisual
                visual = self._lesson_visual = LessonVisual()
                self.center.addTab(visual, "Lesson visual")
                self.center.tabBar().setTabButton(self.center.indexOf(visual),
                    self.center.tabBar().ButtonPosition.RightSide, None)
            self.state.clear_selection()
            self.state.clear_ghost()
            visual.set_step(step)
            self.center.setCurrentWidget(visual)
            self._update_workspace_header()
            return
        return self.apply_scene(step)

    def apply_scene(self, step):
        """Set the 3D view up from a scene description - used by guided lessons and radiology cases alike."""
        st, vp = self.state, self.viewport
        vp.set_radiology_slice(False)
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
            if step.get("frame", True) and not step.get("frame_on"):
                # Section anchors may not exist yet (index still building or no
                # sampled intersections). Do not retain an unrelated old target
                # while changing visibility to the lesson's anatomy.
                framing = sorted(set(cut + focus)) if cut else (focus or show)
                if not framing:
                    framing = np.flatnonzero(st.visible_mask()).tolist()
                if framing:
                    vp.frame_structures(framing, view=want_view)
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

        if step.get("slice_only") is True and sum(vp.clip_on) == 1:
            st.clear_ghost()
            vp.set_radiology_slice(True)
            if step.get("frame", True) and not step.get("camera") and not step.get("frame_on"):
                vp.frame_section(view=step.get("view"))

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
            "system_alpha": st.system_alpha.tolist(),
            "subsystem_on": st.subsystem_on.tolist(),
            "region_on": st.region_on.tolist(),
            "selected": list(st.selected),
            "clip": [list(vp.clip_on), list(vp.clip_pos), list(vp.clip_flip)],
            "radiology_slice": bool(getattr(vp, "radiology_slice", False)),
            "dissection": [st.depth_cut, st.depth_band],
            "custom_colors": {str(k): list(v) for k, v in st.custom_colors.items()},
        }

    def open_saved_view(self, data):
        """A saved view is an atlas view: show Explore first, or it is restored behind another workspace."""
        self._studio_explore()
        self.apply_view(data)

    def apply_view(self, data, animate=True):
        st = self.state
        n = self.ds.n
        try:
            if not isinstance(data, dict):
                raise ValueError("saved view must be an object")
            def mask(idxs):
                if not isinstance(idxs, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in idxs):
                    raise ValueError("structure IDs must be a list of integers")
                m = np.zeros(n, dtype=bool)
                m[[i for i in idxs if 0 <= i < n]] = True
                return m
            hidden = mask(data.get("hidden", []))
            forced = mask(data.get("forced", []))
            isolated = None if data.get("isolated") is None else mask(data["isolated"])
            ghost = None if data.get("ghost") is None else mask(data["ghost"])
            selected = data.get("selected", [])
            mask(selected)
            sel = [sid for sid in selected if 0 <= sid < n]
            toggles = {}
            for field in ("system_on", "subsystem_on", "region_on"):
                values = data.get(field, [])
                if not isinstance(values, list) or any(v not in (False, True) for v in values):
                    raise ValueError(f"{field} must be a list of toggles")
                if len(values) == len(getattr(st, field)):
                    toggles[field] = values
            alpha = data.get("system_alpha", st.system_alpha.tolist())
            if not isinstance(alpha, list) or len(alpha) != len(st.system_alpha) or \
                    any(type(value) not in (int, float) for value in alpha):
                raise ValueError("system opacity must have one number per system")
            alpha = np.asarray(alpha, dtype=np.float32)
            if not np.isfinite(alpha).all() or ((alpha < 0) | (alpha > 1)).any():
                raise ValueError("system opacity must be between zero and one")
            colors = {}
            raw_colors = data.get("custom_colors", {})
            if not isinstance(raw_colors, dict):
                raise ValueError("custom colors must be an object")
            for key, value in raw_colors.items():
                sid = int(key)
                if not 0 <= sid < n:
                    continue
                rgb = np.asarray(value, dtype=float)
                if rgb.shape != (3,) or not np.isfinite(rgb).all() or ((rgb < 0) | (rgb > 1)).any():
                    raise ValueError("custom colors must have three components between zero and one")
                colors[sid] = tuple(rgb)
            clip = data.get("clip")
            slice_only = data.get("radiology_slice", False)
            if not isinstance(slice_only, bool):
                raise ValueError("radiology slice flag must be boolean")
            if clip:
                on, positions, flips = clip
                if any(not isinstance(values, list) or len(values) != 3 for values in (on, positions, flips)):
                    raise ValueError("clipping settings must contain three axes")
                if any(value not in (False, True) for value in on + flips):
                    raise ValueError("clipping toggles must be booleans")
                positions = np.asarray(positions, dtype=float)
                if positions.shape != (3,) or not np.isfinite(positions).all():
                    raise ValueError("clipping positions must be three finite coordinates")
                clip = (on, positions.tolist(), flips)
            if slice_only and (not clip or sum(bool(on) for on in clip[0]) != 1):
                raise ValueError("radiology slice requires one cutting plane")
            cut, band = map(float, data.get("dissection", [0.0, 0.0]))
            target, dist, yaw, pitch = data["camera"]
            target = np.asarray(target, dtype=float)
            dist, yaw, pitch = float(dist), float(yaw), float(pitch)
            if target.shape != (3,) or not np.isfinite(target).all() or \
                    not all(math.isfinite(v) for v in (dist, yaw, pitch, cut, band)):
                raise ValueError("camera and dissection values must be finite")
            if dist <= 0:
                raise ValueError("camera distance must be positive")
            candidate = OrbitCamera(self.viewport.camera.fov)
            candidate.target, candidate.distance, candidate.yaw, candidate.pitch = target, dist, yaw, pitch
            try:
                with np.errstate(over="raise", invalid="raise", divide="raise"):
                    view_matrix = np.asarray(candidate.view(), dtype=np.float32)
                    projection = np.asarray(candidate.proj(max(self.viewport.width(), 1) /
                                                           max(self.viewport.height(), 1)), dtype=np.float32)
                if not np.isfinite(view_matrix).all() or not np.isfinite(projection).all() or \
                        not np.isclose(abs(float(np.linalg.det(view_matrix[:3, :3]))), 1.0, atol=1e-4):
                    raise ValueError("camera must produce finite, invertible render matrices")
            except FloatingPointError as exc:
                raise ValueError("camera must produce finite, invertible render matrices") from exc
            st.push_undo()
            st.hidden, st.forced, st.isolated, st.ghost_focus = hidden, forced, isolated, ghost
            for field, values in toggles.items():
                getattr(st, field)[:] = values
            st.system_alpha[:] = alpha
            st.custom_colors = colors
            st._vis_dirty()
            st.select(sel)
            self.viewport.landmark_hosts = sel if len(sel) <= 2 else []
            self.info.show_structures(sel)
            if clip:
                self.view_panel.set_clips(*clip)
            self.viewport.set_radiology_slice(slice_only)
            self.view_panel.set_depth(cut, bool(band))
            cam = self.viewport.camera
            if animate:
                cam.animate_to(target, dist, yaw, pitch, self.viewport.duration())
            else:
                cam._anim = None
                cam.target, cam.distance, cam.yaw, cam.pitch = target, dist, yaw, pitch
            self.viewport.update()
            self._update_counts()
        except (KeyError, ValueError, TypeError, OverflowError) as e:
            self.statusBar().showMessage(f"Could not restore view: {e}", 5000)

    def _saved_views(self):
        try:
            views = json.loads(self.qsettings.value("saved_views", "[]"))
            if not isinstance(views, list):
                return []
            return [v for v in views if isinstance(v, dict) and isinstance(v.get("name"), str)
                    and isinstance(v.get("data"), dict)]
        except (TypeError, ValueError):
            return []

    def _store_views(self, views):
        self.qsettings.setValue("saved_views", json.dumps(views))

    def save_view_dialog(self):
        default = ""
        if self.state.selected:
            default = self.ds.structures[self.state.selected[0]]["base"]
        label = "Name:"
        while True:
            name, ok = QInputDialog.getText(self, "Save view", label, text=default)
            if not ok:
                return
            name = name.strip()
            if not name:
                label = "Name (a saved view needs a name):"
                continue
            existing = self._saved_views()
            if any(v["name"] == name for v in existing):
                answer = QMessageBox.question(self, "Save view", f"A saved view named “{name}” already exists. Replace it?",
                                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    default, label = name, "Name:"
                    continue
            break
        views = [v for v in existing if v["name"] != name]
        views.append({"name": name, "created": datetime.now().isoformat(timespec="minutes"),
                      "data": self.capture_view()})
        self._store_views(views)
        self.statusBar().showMessage(f"Saved view “{name}”", 3000)

    def _fill_views_menu(self):
        m = self.views_menu
        m.clear()
        m.addAction(self.cmds.actions["save_view"])
        views = self._saved_views()
        if views:
            m.addSeparator()
            for v in sorted(views, key=lambda v: v["name"].lower()):
                m.addAction(v["name"], lambda data=v["data"]: self.open_saved_view(data))
            m.addSeparator()
        m.addAction("Manage saved views…", self.manage_views)

    def manage_views(self):
        from .ui.saved_views import SavedViewsDialog
        SavedViewsDialog(self).exec()

    def restore_session(self):
        try:
            data = json.loads(self.qsettings.value("last_session", "null"))
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict) and data:
            # Session continuity restores the view, not a previous lesson's
            # transient multi-selection. Explicit saved views still use apply_view.
            data = dict(data, selected=[])
            self.apply_view(data, animate=False)
            self.right_dock.hide()

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
        vp = self._measurement_viewport()
        if vp is None:
            return
        on = not vp.measure_mode
        for other in (self.viewport, vp):
            other.set_measure(on if other is vp else False)

    def _measurement_viewport(self):
        w = self.center.currentWidget()
        vp = getattr(w, "gl_widget", w)
        return vp if hasattr(vp, "measure_mode") else None

    def _on_measure_changed(self, viewport, text):
        """Keep the shared measurement controls tied to the visible 3D view."""
        if viewport is not self._measurement_viewport():
            return
        self.measure_action.setEnabled(viewport is not None)
        self.measure_action.setChecked(bool(viewport is not None and viewport.measure_mode))
        if text:
            self.statusBar().showMessage(text, 0)
        else:
            self.statusBar().clearMessage()

    def toggle_xray(self):
        mv = self.active_model_view()
        if mv is not None:
            self.xray_action.setChecked(mv.toggle_xray())
            return
        if self.state.ghost_focus is not None:
            self.state.clear_ghost()
        elif self.state.selected:
            self.state.set_ghost_focus(self.state.selected)
        self._update_counts()

    def show_all(self):
        self.state.show_all()
        self.view_panel.set_depth(0.0, False)      # snapshot the dissection before putting it back

    def reset_visibility(self):
        self.state.reset_visibility()
        self.view_panel.set_depth(0.0, False)

    def undo(self):
        if self.state.undo():
            self.view_panel.set_depth(self.state.depth_cut, bool(self.state.depth_band))

    def escape(self):
        if self.search.edit.hasFocus() and self.search.edit.text():
            self.search.edit.clear()
            return
        if self.clear_attachment_colours():
            return
        vp = self.active_viewport()
        if vp.measure_points:
            vp.clear_measure()
            return
        if vp.measure_mode:        # nothing measured: Esc leaves measure mode, like any other tool
            vp.set_measure(False)  # this view's own mode, even when the page in front is not a 3D view
            self.measure_action.setChecked(False)
            return
        mv = self.active_model_view()
        if mv is not None and not (self.quiz is not None and self.quiz.active):
            if mv.escape():
                self.xray_action.setChecked(mv.state.ghost_focus is not None)
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

    def _capture_widget(self):
        """What a screenshot or figure shows: the atlas tab (with a radiology film beside it when one is open), or
        a model tab's 3D view with its labels, without the tab's parts list and buttons."""
        mv = self.active_model_view()
        return mv.gl_widget if mv is not None else self.center.currentWidget()

    def screenshot(self, path=None):
        widget = self._capture_widget()
        img = widget.grab()
        if not path:
            pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
            default = str(Path(pics) / f"anatomy_{datetime.now():%Y%m%d_%H%M%S}.png")
            path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", default, "PNG image (*.png)")
            if not path:
                return
        if not img.save(path):
            self.statusBar().showMessage(f"Could not save screenshot: {path}", 6000)
            return
        self.statusBar().showMessage(f"Saved {path}", 4000)

    def _figure_caption(self):
        """(title, caption parts, credit line) for export_figure: the model tab in front describes itself."""
        mv = self.active_model_view()
        if mv is not None:
            return mv.figure_caption()
        from .ui.histology import HistologyViewer
        current = self.center.currentWidget()
        if isinstance(current, HistologyViewer):
            return current.figure_caption()
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
        return title, bits, "Anatomy Explorer · BodyParts3D / Z-Anatomy, CC BY-SA"

    def export_figure(self, path=None):
        """Save the current view as a captioned plate, retaining its physical pixels."""
        from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter

        widget = self._capture_widget()
        shot = widget.grab().toImage()
        dpr = shot.devicePixelRatio() or 1.0
        title, bits, credit = self._figure_caption()

        # Work entirely in physical pixels. Setting a painter device's DPR before
        # drawing also scales its coordinates, which would push the footer outside
        # the image at high display scales. Restore DPR metadata after painting.
        shot.setDevicePixelRatio(1.0)
        pad = min(round(18 * dpr), max(0, (shot.width() - 1) // 2))
        font_body = QFont(self.font())
        size = font_body.pointSizeF() if font_body.pointSizeF() > 0 else theme.FS_BODY
        font_body.setPointSizeF(size * dpr)
        font_title = QFont(font_body)
        font_title.setPointSizeF(size * 1.7 * dpr)
        font_title.setBold(True)
        fm_t, fm_b = QFontMetrics(font_title), QFontMetrics(font_body)
        width = shot.width()
        text_w = max(1, width - 2 * pad)
        caption = "  ·  ".join(bits)
        flags = int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        title_h = fm_t.boundingRect(0, 0, text_w, 10000, flags, title).height()
        caption_h = fm_b.boundingRect(0, 0, text_w, 10000, flags, caption).height() if caption else 0
        credit_h = fm_b.boundingRect(0, 0, text_w, 10000, flags, credit).height()
        head_h = title_h + 2 * pad
        foot_h = caption_h + credit_h + (3 * pad if caption else 2 * pad)
        out = QImage(width, shot.height() + head_h + foot_h, QImage.Format_RGB32)
        dark = bool(self.settings.get("dark_background", True))
        bg = QColor(theme.CANVAS) if dark else QColor("#f3f5f8")
        fg = QColor(theme.TEXT_STRONG) if dark else QColor("#1b1f26")
        muted = QColor(theme.TEXT_2) if dark else QColor("#57606d")
        out.fill(bg)
        p = QPainter(out)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(font_title)
        p.setPen(fg)
        p.drawText(pad, pad, text_w, title_h, flags, title)
        p.drawImage(0, head_h, shot)
        p.setFont(font_body)
        p.setPen(muted)
        y = shot.height() + head_h + pad
        if caption:
            p.drawText(pad, y, text_w, caption_h, flags, caption)
            y += caption_h + pad
        p.drawText(pad, y, text_w, credit_h, flags, credit)
        p.end()
        out.setDevicePixelRatio(dpr)

        if not path:
            pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
            default = str(Path(pics) / f"anatomy_figure_{datetime.now():%Y%m%d_%H%M%S}.png")
            path, _ = QFileDialog.getSaveFileName(self, "Export figure", default, "PNG image (*.png)")
            if not path:
                return
        if not out.save(path):
            self.statusBar().showMessage(f"Could not export figure: {path}", 6000)
            return
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
        elif name == "shottop":
            # whatever dialog is up (progress, notes, a modal the script opened)
            top = QApplication.activeModalWidget() or QApplication.activeWindow()
            if top is not None:
                top.grab().save(arg)
        elif name == "eval":
            exec(arg, {"w": self, "np": np})
        elif name == "quit":
            self.close()
            return
        QTimer.singleShot(delay, self._run_script)

    def _discard_model_loads(self):
        """Abandon CPU work without touching a possibly destroyed QObject."""
        self._closing = True
        self._model_loader.queue.close()
        for pending in self._loading_models.values():
            pending.callbacks.clear()
        self._loading_models.clear()
        self._reference_loads.clear()

    def closeEvent(self, e):
        for pending in self._loading_models.values():
            prepared = getattr(pending, "prepared_view", None)
            session = getattr(prepared, "runtime_session", None)
            if session is not None:
                session.close()
        self._model_loader.close()
        self._discard_model_loads()
        for view in self.micro_tabs.values():
            session = getattr(view, "runtime_session", None)
            if session is not None:
                session.close()
        practice = getattr(self.lessons_panel, "practice", None)
        if practice is not None:
            practice.stop()
        if self.quiz is not None:
            self.quiz.stop()
        self.study_layout.leave()
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
