"""Production navigation for the approved canvas-led Study-02 shell.

Every command routes to the existing application owner; no demo scenes or data.
"""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,
                               QLineEdit,QToolButton,QLabel,QMenu,QDockWidget,QScrollArea,QFrame,QSplitter,QStackedWidget)
from .shell import ElidingLabel
from .studio_style import icon


class StudioHeader(QWidget):
    exploreRequested=Signal()
    learnRequested=Signal()
    collectionRequested=Signal()
    radiologyRequested=Signal()
    histologyRequested=Signal()
    searchRequested=Signal(str)
    backRequested=Signal()
    forwardRequested=Signal()

    def __init__(self,window):
        super().__init__()
        self._owner = window
        self.setObjectName('studioHeader')
        layout=QVBoxLayout(self);layout.setContentsMargins(28,20,28,0);layout.setSpacing(18)
        self.bar=QWidget();self.bar.setObjectName('globalBar')
        self.bar.setAttribute(Qt.WA_StyledBackground,True)
        self.bar.setMinimumHeight(58)
        row=QHBoxLayout(self.bar);row.setContentsMargins(20,5,20,5);row.setSpacing(16)
        brand_icon=QLabel();brand_icon.setPixmap(icon('brand').pixmap(26,26));row.addWidget(brand_icon)
        self.brand=QLabel('Anatomy Explorer');self.brand.setObjectName('studioBrand');row.addWidget(self.brand)
        row.addSpacing(16)
        # Back returns to the place before this one, anywhere in the app; its arrow lists the recent places.
        self.back_button=QToolButton();self.back_button.setIcon(icon('back'));self.back_button.setIconSize(QSize(22,22))
        self.back_button.setAccessibleName('Back to the previous place')
        self.places_menu=QMenu(self.back_button)
        self.back_button.setMenu(self.places_menu);self.back_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.back_button.clicked.connect(self.backRequested.emit)
        self.forward_button=QToolButton();self.forward_button.setIcon(icon('forward'));self.forward_button.setIconSize(QSize(22,22))
        self.forward_button.setAccessibleName('Forward to the next place')
        self.forward_button.clicked.connect(self.forwardRequested.emit)
        for button in (self.back_button,self.forward_button):
            button.setEnabled(False);row.addWidget(button)
        row.addSpacing(12)
        self.navigation={}
        for label,signal in (('Explore',self.exploreRequested),('Lessons',self.learnRequested),('3D Models',self.collectionRequested),
                             ('Radiology',self.radiologyRequested),('Histology',self.histologyRequested)):
            button=QPushButton(label);button.setCheckable(True);button.setAccessibleName(label+' workspace')
            button.setObjectName('studioNavButton')
            button.setProperty('variant','quiet');button.setMinimumHeight(40)
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(label)+48)
            button.clicked.connect(lambda checked=False,s=signal:s.emit())
            self.navigation[label.lower()]=button;row.addWidget(button)
        row.addStretch()
        self.search=QLineEdit();self.search.setObjectName('globalSearch')
        self.search.setPlaceholderText('Search anatomy');self.search.setAccessibleName('Search all anatomy and study material')
        self.search.setClearButtonEnabled(True);self.search.setMinimumWidth(150);self.search.setMaximumWidth(330)
        self.search.addAction(icon('search'),QLineEdit.LeadingPosition)
        self.search.returnPressed.connect(lambda:self.searchRequested.emit(self.search.text()))
        row.addWidget(self.search,1)
        saved=QToolButton();saved.setText('Saved views');saved.setMenu(window.views_menu)
        saved.setPopupMode(QToolButton.InstantPopup);row.addWidget(saved)
        settings=QToolButton();settings.setIcon(icon('settings'));settings.setIconSize(QSize(22,22))
        settings.setToolTip('Settings and application commands');settings.setAccessibleName('Settings and application commands')
        self.commands_menu=QMenu(settings);self.commands_menu.aboutToShow.connect(self._populate_commands)
        settings.setMenu(self.commands_menu);settings.setPopupMode(QToolButton.InstantPopup);row.addWidget(settings)
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
        for key,button in self.navigation.items():
            button.setChecked(key==name)

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
        for button in self.navigation.values():
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(button.text())+48)
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
    dock=QWidget(host);dock.setObjectName('dock');dock.setAttribute(Qt.WA_StyledBackground,True);row=QHBoxLayout(dock)
    row.setContentsMargins(14,8,14,8);row.addStretch()
    for label,key in (('Measure','measure'),('Show all','show_all'),('Reset','reset_view')):
        action=window.cmds.actions.get(key)
        if action is not None:
            # A tool button re-reads its action's iconText whenever the action changes (checked, enabled), so a
            # short label set only with setText reverted to the long one ("Measure distances") and shifted the bar.
            action.setIconText(label)
            button=QToolButton();button.setDefaultAction(action);button.setText(label)
            if key=='structure_labels':button.setToolTip('Show names of visible structures')
            elif key=='show_all':button.setToolTip('Show every structure again and leave isolation')
            elif key=='reset_view':button.setToolTip('Reset the camera view')
            row.addWidget(button)
    menu=QMenu(window)
    menu.addAction('Parts',lambda:window._show_nav_page(window.tree))
    menu.addAction('Reveal controls',lambda:window._show_nav_page(window.view_panel))
    # Details has its own Close button; this is the way back to it without knowing the panels shortcut.
    menu.addAction('Details',lambda:(window.right_dock.show(),window.right_dock.raise_()))
    menu.addMenu(window.section_menu)
    menu.addSeparator()
    menu.addActions(window.tools_menu.actions())
    tools=QToolButton();tools.setText('More tools');tools.setMenu(menu)
    tools.setPopupMode(QToolButton.InstantPopup);row.addWidget(tools)
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
        panel.setAttribute(Qt.WA_StyledBackground,True)
        panel.setStyleSheet('QDockWidget {background:#f8fafb;border:1px solid #94a6b1;border-radius:14px;}')
        title=QWidget(panel);title.setAttribute(Qt.WA_StyledBackground,True)
        title.setStyleSheet('background:#f8fafb;border:none;border-top-left-radius:14px;border-top-right-radius:14px;')
        row=QHBoxLayout(title);row.setContentsMargins(14,10,10,8)
        label=QLabel(panel.windowTitle());panel._studio_title=label;label.setStyleSheet('color:#24343d;font-size:16px;font-weight:600;');row.addWidget(label);row.addStretch()
        close=QPushButton('Close');close.setAccessibleName('Close '+panel.windowTitle());close.clicked.connect(panel.hide);row.addWidget(close)
        panel.setTitleBarWidget(title)
        content=panel.widget();panel._studio_content=content
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
        # Alpha clipping keeps descendant viewports inside smooth corners.
        # QRegion masks have a binary pixel edge and look jagged on round cards.
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter,QPainterPath,QImage,QPixmap,QBrush
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        ratio=panel.devicePixelRatioF()
        image=QImage(max(1,int(panel.width()*ratio)),max(1,int(panel.height()*ratio)),QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio);image.fill(Qt.transparent)
        painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
        path=QPainterPath();path.addRoundedRect(QRectF(panel.rect()),14,14)
        painter.fillPath(path,Qt.white);painter.end()
        effect=getattr(panel,'_studio_corner_effect',None)
        if effect is None:
            effect=QGraphicsOpacityEffect(panel);effect.setOpacity(1.0)
            panel._studio_corner_effect=effect;panel.setGraphicsEffect(effect)
        panel.clearMask();effect.setOpacityMask(QBrush(QPixmap.fromImage(image)))
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
            preferred=panel._studio_width or max(400 if index else 450, minimum)
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
