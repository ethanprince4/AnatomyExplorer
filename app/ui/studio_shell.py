"""Production navigation for the approved canvas-led Study-02 shell.

Every command routes to the existing application owner; no demo scenes or data.
"""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,
                               QLineEdit,QToolButton,QLabel,QMenu,QDockWidget,QScrollArea,QFrame,QSplitter,QStackedWidget)
from . import theme
from .shell import ElidingLabel
from .studio_style import icon


class StudioHeader(QWidget):
    exploreRequested=Signal()
    learnRequested=Signal()
    collectionRequested=Signal()
    radiologyRequested=Signal()
    histologyRequested=Signal()
    practiceRequested=Signal()
    settingsRequested=Signal()
    searchRequested=Signal(str)
    backRequested=Signal()
    forwardRequested=Signal()

    def __init__(self,window):
        super().__init__()
        self._owner = window
        self.setObjectName('studioHeader')
        from .studio_style import RAIL_WIDTH
        self.navigation_rail=QWidget(window);self.navigation_rail.setObjectName('studioRail')
        self.navigation_rail.setFixedWidth(RAIL_WIDTH)
        self.rail=self.navigation_rail
        rail_layout=QVBoxLayout(self.navigation_rail);rail_layout.setContentsMargins(8,14,8,12);rail_layout.setSpacing(5)
        mark=QLabel(self.navigation_rail);mark.setObjectName('studioRailMark');mark.setAlignment(Qt.AlignCenter)
        mark.setPixmap(icon('brand').pixmap(34,34));mark.setAccessibleName('Layered Human')
        rail_layout.addWidget(mark);rail_layout.addSpacing(13)
        self.navigation={}
        rooms=(('Atlas','atlas',self.exploreRequested),('Lessons','lessons',self.learnRequested),
               ('Models','models',self.collectionRequested),('Radiology','radiology',self.radiologyRequested),
               ('Histology','histology',self.histologyRequested),('Practice','practice',self.practiceRequested))
        for label,key,signal in rooms:
            button=QToolButton(self.navigation_rail);button.setObjectName('studioRailRoom')
            button.setText(label);button.setIcon(icon(key));button.setIconSize(QSize(22,22))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);button.setCheckable(True)
            button.setAccessibleName(label+' workspace');button.setMinimumHeight(62)
            button.clicked.connect(lambda checked=False,s=signal:s.emit())
            self.navigation[key]=button
            self.navigation[{'atlas':'explore','models':'3d models'}.get(key,key)]=button
            rail_layout.addWidget(button)
        rail_layout.addStretch(1)
        self.practice_count=QLabel('',self.navigation_rail);self.practice_count.setObjectName('studioRailCount')
        self.practice_count.setAlignment(Qt.AlignCenter);rail_layout.addWidget(self.practice_count)
        self.saved_views_button=QToolButton(self.navigation_rail);self.saved_views_button.setObjectName('studioRailUtility')
        self.saved_views_button.setText('Saved');self.saved_views_button.setIcon(icon('bookmark'))
        self.saved_views_button.setIconSize(QSize(20,20));self.saved_views_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.saved_views_button.setMenu(window.views_menu);self.saved_views_button.setPopupMode(QToolButton.InstantPopup)
        self.saved_views_button.setAccessibleName('Saved views');rail_layout.addWidget(self.saved_views_button)
        self.settings_button=QToolButton(self.navigation_rail);self.settings_button.setObjectName('studioRailUtility')
        self.settings_button.setText('Settings');self.settings_button.setIcon(icon('settings'))
        self.settings_button.setIconSize(QSize(20,20));self.settings_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.settings_button.clicked.connect(self.settingsRequested);rail_layout.addWidget(self.settings_button)
        self.more_button=QToolButton(self.navigation_rail);self.more_button.setObjectName('studioRailUtility')
        self.more_button.setText('Menu');self.more_button.setIcon(icon('more'));self.more_button.setIconSize(QSize(20,20))
        self.more_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);rail_layout.addWidget(self.more_button)
        self.set_practice_due(0)
        layout=QVBoxLayout(self);layout.setContentsMargins(20,10,20,0);layout.setSpacing(12)
        self.bar=QWidget();self.bar.setObjectName('globalBar')
        self.bar.setAttribute(Qt.WA_StyledBackground,True)
        self.bar.setMinimumHeight(58)
        row=QHBoxLayout(self.bar);row.setContentsMargins(20,5,20,5);row.setSpacing(16)
        brand_icon=QLabel();brand_icon.setPixmap(icon('brand').pixmap(24,24));row.addWidget(brand_icon)
        self.brand=QLabel('Layered Human');self.brand.setObjectName('studioBrand');row.addWidget(self.brand)
        self.trail=QLabel('');self.trail.setObjectName('studioTrail');row.addWidget(self.trail,1)
        # Back returns to the place before this one, anywhere in the app; its arrow lists the recent places.
        self.back_button=QToolButton();self.back_button.setObjectName('studioPlaceButton')
        self.back_button.setText('Back');self.back_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.back_button.setIcon(icon('back'));self.back_button.setIconSize(QSize(20,20))
        self.back_button.setAccessibleName('Back to the previous place')
        self.places_menu=QMenu(self.back_button)
        self.back_button.setMenu(self.places_menu);self.back_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.back_button.clicked.connect(self.backRequested.emit)
        self.forward_button=QToolButton();self.forward_button.setObjectName('studioPlaceButton')
        self.forward_button.setText('Forward');self.forward_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.forward_button.setIcon(icon('forward'));self.forward_button.setIconSize(QSize(20,20))
        self.forward_button.setAccessibleName('Forward to the next place')
        self.forward_button.clicked.connect(self.forwardRequested.emit)
        for button in (self.back_button,self.forward_button):
            button.setEnabled(False);row.addWidget(button)
        row.addSpacing(12)
        row.addStretch()
        self.search=QLineEdit();self.search.setObjectName('globalSearch')
        self.search.setPlaceholderText('Search anatomy');self.search.setAccessibleName('Search all anatomy and study material')
        self.search.setClearButtonEnabled(True);self.search.setMinimumWidth(150);self.search.setMaximumWidth(330)
        self.search.addAction(icon('search'),QLineEdit.LeadingPosition)
        self.search.returnPressed.connect(lambda:self.searchRequested.emit(self.search.text()))
        row.addWidget(self.search,1)
        self.commands_menu=QMenu(self.more_button);self.commands_menu.aboutToShow.connect(self._populate_commands)
        self.more_button.setMenu(self.commands_menu);self.more_button.setPopupMode(QToolButton.InstantPopup)
        layout.addWidget(self.bar)
        self.subject=QWidget();self.subject.setObjectName("studioSubject");self.subject.setAttribute(Qt.WA_StyledBackground,True);subject=QHBoxLayout(self.subject);subject.setContentsMargins(6,0,6,0)
        column=QVBoxLayout();column.setSpacing(7)
        self.title=ElidingLabel('3D Anatomy');self.title.setObjectName('studioDisplay')
        self.context=ElidingLabel('Explore the atlas or choose a model');self.context.setObjectName('studioEyebrow')
        column.addWidget(self.title);column.addWidget(self.context);subject.addLayout(column,1)
        layout.addWidget(self.subject)
        self.set_workspace('explore')

    def _populate_commands(self):
        menu=self.commands_menu;menu.clear();window=self._owner
        action=window.cmds.actions.get('settings')
        if action is not None:menu.addAction(action)
        workspaces=menu.addMenu('Open workspaces')
        for index in range(window.center.count()):
            action=workspaces.addAction(window.center.tabText(index))
            action.setCheckable(True);action.setChecked(index==window.center.currentIndex())
            action.triggered.connect(lambda checked=False,i=index:window.center.setCurrentIndex(i))
        close=workspaces.addAction('Close current workspace')
        close.triggered.connect(lambda:window._close_center_tab(window.center.currentIndex()))
        menu.addAction('Find a command…',window.show_command_palette)
        menu.addSeparator()
        for action in window.menuBar().actions():
            if action.menu() is not None:menu.addMenu(action.menu())

    def set_places(self,back_label,forward_label):
        """Enable Back and Forward and name where each goes."""
        for button,label,verb in ((self.back_button,back_label,'Back'),(self.forward_button,forward_label,'Forward')):
            button.setEnabled(bool(label))
            button.setToolTip(f'{verb} to {label}' if label else f'Nothing to go {verb.lower()} to yet')

    def set_workspace(self,name):
        key={'explore':'atlas','3d models':'models','collection':'models','learn':'lessons'}.get(str(name).lower(),str(name).lower())
        for room in ('atlas','lessons','models','radiology','histology','practice'):
            self.navigation[room].setChecked(room==key)

    def set_practice_due(self,count):
        count=max(0,int(count or 0))
        self.practice_count.setText(f'{count} due' if count else '')
        self.practice_count.setVisible(bool(count))
        self.navigation['practice'].setAccessibleDescription(f'{count} practice items due' if count else 'Practice workspace')

    def mousePressEvent(self,event):
        # A borderless window has no title bar, and the menu bar is hidden (on a Mac it is the system's, outside
        # the window): the empty part of this header is where it is dragged. Buttons and the search box keep
        # their clicks; presses on the bar and the brand reach here.
        handle=self._owner.windowHandle()
        if (getattr(self._owner,'_borderless',False) and event.button()==Qt.LeftButton and handle is not None
                and handle.startSystemMove()):
            event.accept()
            return
        super().mousePressEvent(event)

    def resizeEvent(self,event):
        # Font scaling and the active stylesheet can change after construction.
        # Reserve padding using the final font instead of the startup font.
        for key in ('atlas','lessons','models','radiology','histology','practice'):
            self.navigation[key].setMinimumWidth(0)
        self.brand.setVisible(self.width()>=1040)
        self.search.setMaximumWidth(300 if self.width()>=1200 else 220)
        super().resizeEvent(event)


class CollectionWorkspace(QWidget):
    """Give the existing catalog a full workspace instead of a narrow dock."""
    def __init__(self,catalog,window):
        super().__init__();self.setObjectName('studioCollection');self.setAttribute(Qt.WA_StyledBackground,True)
        outer=QHBoxLayout(self);outer.setContentsMargins(28,12,28,24);outer.addStretch()
        self.card=QWidget(self);self.card.setObjectName('studioCollectionCard');self.card.setAttribute(Qt.WA_StyledBackground,True)
        self.card.setMaximumWidth(1320)
        outer.addWidget(self.card,1);outer.addStretch()
        layout=QVBoxLayout(self.card);layout.setContentsMargins(20,16,20,16)
        self.pages=QStackedWidget(self.card)
        self.navigation_mode='collection'
        self.buttons={}
        for title,page in (('3D models',catalog),('Histology',window.histology_panel),
                           ('Radiology',window.radiology_browser),('Lessons',window.lessons_panel)):
            if page is not None and self.pages.indexOf(page)<0:self.pages.addWidget(page)
        layout.addWidget(self.pages,1)
        self.window_owner=window
        # Reuse every original catalog widget and callback; change its composition only.
        original=catalog.layout();items=[]
        while original.count():items.append(original.takeAt(0))
        split=QSplitter(Qt.Horizontal,catalog);split.setChildrenCollapsible(False)
        left=QWidget(split);right=QWidget(split)
        ll=QVBoxLayout(left);ll.setContentsMargins(0,0,12,0);ll.setSpacing(8)
        rl=QVBoxLayout(right);rl.setContentsMargins(16,0,0,0);rl.setSpacing(12)
        target=ll
        for item in items:
            if item.widget() is catalog.preview:target=rl
            if item.widget() is not None:
                target.addWidget(item.widget())
            elif item.layout() is not None:
                target.addLayout(item.layout())
            else:
                target.addItem(item)
            if item.widget() is catalog.list:ll.setStretch(ll.count()-1,1)
            if item.widget() is catalog.preview:rl.setStretch(rl.count()-1,0)
        original.addWidget(split,1)
        rl.addStretch(1)
        left.setMinimumWidth(260)
        split.setStretchFactor(0,1);split.setStretchFactor(1,2);split.setSizes([340,760])
        for button in (catalog.open_button,):
            button.setMaximumWidth(max(220,button.sizeHint().width()))
        catalog.kind_filter.setMaximumWidth(360)
        self.catalog_splitter=split
        catalog.show()
        self.show_page(catalog,'3D models')

    def show_page(self,page,title=None,mode='collection'):
        if page is None:return
        self.navigation_mode=(title or '3D models').lower()
        self.pages.setCurrentWidget(page)
        for label,button in self.buttons.items():
            button.setChecked(label==title)
        if title=='Lab course':page.show_course()
        if title=='Lecture exams':page.show_lecture()
        if hasattr(self.window_owner,'collection_workspace'):
            self.window_owner.center.setCurrentWidget(self)
            self.window_owner.left_dock.hide();self.window_owner.right_dock.hide()
            self.window_owner._update_workspace_header()


def atlas_dock(window):
    host=QWidget();host.setObjectName('studioAtlasTools');host.setAttribute(Qt.WA_StyledBackground,True)
    host.setStyleSheet('QWidget#studioAtlasTools {background:transparent;border:none;}')
    holder=QHBoxLayout(host);holder.setContentsMargins(20,10,20,16);holder.addStretch()
    dock=QWidget(host);dock.setObjectName('studioAtlasDock');dock.setAttribute(Qt.WA_StyledBackground,True);row=QHBoxLayout(dock)
    row.setContentsMargins(0,8,0,0);row.setSpacing(5);row.addStretch()
    section=QToolButton();section.setObjectName('studioAtlasTool');section.setText('Section')
    section.setAccessibleName('Section controls')
    section.setToolTip('Open cross-section controls')
    section.setMenu(window.section_menu);section.setPopupMode(QToolButton.InstantPopup);row.addWidget(section)
    compact_tools = {
        'xray': ('X-ray', 'reveal', 'Toggle the X-ray view'),
        'isolate': ('Isolate', 'select', 'Isolate the selected structure'),
        'hide': ('Hide', 'labels', 'Hide the selected structure'),
        'measure': ('Measure', 'measure', 'Measure between points'),
    }
    for label,key in (('X-ray','xray'),('Isolate','isolate'),('Hide','hide'),('Measure','measure')):
        action=window.cmds.actions.get(key)
        if action is not None:
            action.setIconText(label)
            button=QToolButton();button.setObjectName('studioAtlasTool');button.setDefaultAction(action)
            _, icon_key, hint = compact_tools[key]
            if action.icon().isNull():button.setIcon(icon(icon_key))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setAccessibleName(label);button.setToolTip(hint)
            button.setMinimumSize(42,40)
            row.addWidget(button)
    from .dock_pair import LabelDockPair
    labels=LabelDockPair(dock);labels.setObjectName('atlasLabelPair')
    host.label_pair=labels
    labels.setToolTip('Show numbered labels on visible anatomy')
    labels.setAccessibleName('Anatomy label controls')
    labels.labels.setMinimumWidth(68)
    labels.labels.setToolTip('Show or hide numbered anatomy labels')
    labels.show_all.setMinimumWidth(76)
    labels.set_labels_on(bool(window.cmds.actions['structure_labels'].isChecked()))
    structure_action=window.cmds.actions['structure_labels']
    def update_atlas_labels(enabled):
        enabled=bool(enabled)
        setting_handler=getattr(window,'on_setting',None)
        if callable(setting_handler):
            setting_handler('show_structure_labels',enabled)
        elif structure_action.isChecked()!=enabled:
            structure_action.setChecked(enabled)
        viewport=window.viewport
        setter=getattr(viewport,'set_labels_on',None)
        if callable(setter):setter(enabled)
        all_open=getattr(viewport,'labels_all_open',None)
        labels.set_all_open(bool(all_open()) if callable(all_open) else False)
    labels.labelsToggled.connect(update_atlas_labels)
    structure_action.toggled.connect(labels.set_labels_on)
    setter=getattr(window.viewport,'set_labels_on',None)
    if callable(setter):setter(structure_action.isChecked())
    labels_open_changed=getattr(window.viewport,'labelsOpenChanged',None)
    if labels_open_changed is not None and hasattr(labels_open_changed,'connect'):
        labels_open_changed.connect(labels.set_all_open)
    def toggle_all_captions():
        viewport=window.viewport
        show=getattr(viewport,'show_all_labels',None);all_open=getattr(viewport,'labels_all_open',None)
        if callable(show) and callable(all_open):
            show(not all_open());labels.set_all_open(all_open())
    labels.showAllClicked.connect(toggle_all_captions)
    row.addWidget(labels)
    reset=window.cmds.actions.get('reset_view')
    if reset is not None:
        reset.setIconText('Reset view')
        button=QToolButton();button.setObjectName('studioAtlasTool');button.setDefaultAction(reset)
        if reset.icon().isNull():button.setIcon(icon('reset'))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAccessibleName('Reset view');button.setToolTip('Reset camera view')
        button.setMinimumSize(42,40)
        row.addWidget(button)
    menu=QMenu(window)
    menu.addAction('Parts',lambda:window._show_nav_page(window.tree))
    menu.addAction('Reveal controls',lambda:window._show_nav_page(window.view_panel))
    # Details has its own Close button; this is the way back to it without knowing the panels shortcut.
    menu.addAction('Details',lambda:(window.right_dock.show(),window.right_dock.raise_()))
    menu.addMenu(window.section_menu)
    menu.addSeparator()
    show_all=window.cmds.actions.get('show_all')
    if show_all is not None:menu.addAction(show_all)
    menu.addSeparator()
    menu.addActions(window.tools_menu.actions())
    tools=QToolButton();tools.setObjectName('studioAtlasTool');tools.setText('More tools');tools.setIcon(icon('more'));tools.setIconSize(QSize(18,18));tools.setMenu(menu)
    tools.setPopupMode(QToolButton.InstantPopup)
    tools.setAccessibleName('More atlas tools');tools.setToolTip('More tools and controls')
    row.addWidget(tools)
    row.addStretch();holder.addWidget(dock);holder.addStretch();return host

class FloatingPanels:
    """Keep legacy dock APIs while presenting ordinary in-workspace cards."""
    def __init__(self, window):
        self.window = window
        self.host = window.workspace
        self.panels = []
        from PySide6.QtCore import QObject,QEvent
        owner=self
        class ResizeFilter(QObject):
            def eventFilter(self, watched, event):
                if watched in owner.panels:
                    if event.type() == QEvent.Resize: owner.clip(watched)
                elif event.type() in (QEvent.Resize,QEvent.Show): owner.layout()
                return False
        self.filter=ResizeFilter(self.host)
        self.host.installEventFilter(self.filter)
        for panel in (window.left_dock,window.right_dock):self.register(panel)
        window.tabs.currentChanged.connect(self.update_title)
        self.update_title()
        self.layout()
    def register(self,panel,*,wrap_content=True,preferred_width=None):
        if panel in self.panels:return
        self.panels.append(panel)
        panel._studio_width=preferred_width
        was_visible=not panel.isHidden()
        self.window.removeDockWidget(panel)
        panel.setParent(self.host,Qt.Widget)
        panel.installEventFilter(self.filter)
        panel.setAllowedAreas(Qt.NoDockWidgetArea)
        panel.setFeatures(QDockWidget.DockWidgetClosable)
        panel.setObjectName('studioFloatingPanel')
        panel.setAttribute(Qt.WA_StyledBackground,True)
        title=QWidget(panel);title.setObjectName('studioFloatingTitleBar');title.setAttribute(Qt.WA_StyledBackground,True)
        row=QHBoxLayout(title);row.setContentsMargins(14,10,10,8)
        label=QLabel(panel.windowTitle());label.setObjectName('studioFloatingTitle');panel._studio_title=label;row.addWidget(label);row.addStretch()
        close=QPushButton('Close');close.setObjectName('studioFloatingClose');close.setProperty('variant','quiet');close.setAccessibleName('Close '+panel.windowTitle());close.clicked.connect(panel.hide);row.addWidget(close)
        panel.setTitleBarWidget(title)
        content=panel.widget();panel._studio_content=content
        content.setProperty('studioWallSurface',True)
        content.setAttribute(Qt.WA_StyledBackground,True)
        content.style().unpolish(content);content.style().polish(content)
        if wrap_content:
            scroll=QScrollArea(panel);scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setWidget(content);panel.setWidget(scroll)
        panel.visibilityChanged.connect(lambda visible,p=panel: self.shown(p,visible))
        panel.setVisible(was_visible)
        self.layout()

    def update_title(self,*_):
        tabs=self.window.tabs
        page=tabs.tabText(tabs.currentIndex()) if tabs.currentIndex()>=0 else 'Explore'
        title={'Lessons':'Learn','View':'View tools','Tree':'Anatomy tree'}.get(page,page)
        panel=self.window.left_dock
        panel.setWindowTitle(title or 'Explore')
        panel._studio_title.setText(title or 'Explore')
        close=panel.titleBarWidget().findChild(QPushButton)
        if close is not None:close.setAccessibleName('Close '+(title or 'Explore'))
    def clip(self,panel):
        effect=getattr(panel,'_studio_corner_effect',None)
        if effect is not None:
            panel.setGraphicsEffect(None)
            panel._studio_corner_effect=None
        panel.clearMask()
    def shown(self,panel,visible):
        if visible:
            if self.host.width()<1100:
                for other in self.panels:
                    if other is not panel:other.hide()
            self.layout();panel.raise_()
    def layout(self):
        self.window._layout_studio_chrome()
        w,h=self.host.width(),self.host.height()
        header=getattr(self.window,'studio_header',None)
        top=(header.geometry().bottom()+12) if header is not None else 20
        if self.window.center.currentWidget() is self.window.anatomy_tab:
            top=self.window.studio_header.subject.geometry().bottom()+12
        available=max(120,h-top-20)
        for index,panel in enumerate(self.panels):
            content=panel._studio_content
            minimum=content.minimumSizeHint().width() + 26
            # Same share of the window as on the 2560x1440 screen the sizes were set on; never larger than that.
            today=panel._studio_width or (400 if index else 450)
            preferred=max(theme.scaled_to_window(today,w,theme.REF_WINDOW_W,minimum),minimum)
            width=min(preferred,max(240,w-40))
            x=max(20,w-width-20) if index else 20
            height=min(760,available)
            if panel._studio_width is not None:
                # Question body already scrolls; keep its footer outside that scroll.
                hint=content.sizeHint().height()+panel.titleBarWidget().sizeHint().height()
                height=min(max(440,hint),680,available)
            panel.setGeometry(x,top,width,height)
            if panel.mask().isEmpty():self.clip(panel)
            if not panel.isHidden():panel.raise_()
