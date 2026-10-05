"""Production navigation for the approved canvas-led Study-02 shell.

Every command routes to the existing application owner; no demo scenes or data.
"""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,
                               QLineEdit,QToolButton,QLabel,QMenu,QDockWidget,QScrollArea,QFrame,QSplitter)
from .shell import ElidingLabel
from .studio_style import icon


class StudioHeader(QWidget):
    exploreRequested=Signal()
    learnRequested=Signal()
    collectionRequested=Signal()
    searchRequested=Signal(str)

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
        row.addSpacing(28)
        self.navigation={}
        for label,signal in (('Explore',self.exploreRequested),('Learn',self.learnRequested),('Collection',self.collectionRequested)):
            button=QPushButton(label);button.setCheckable(True);button.setAccessibleName(label+' workspace')
            button.setProperty('variant','quiet');button.setMinimumHeight(36)
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

    def set_workspace(self,name):
        for key,button in self.navigation.items():
            button.setChecked(key==name)

    def resizeEvent(self,event):
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
        row=QHBoxLayout()
        for title,callback in (('3D models',catalog.focus_search),('Histology',lambda:window._show_nav_page(window.histology_panel)),
                               ('Radiology',lambda:window._show_nav_page(window.radiology_browser)),('Lessons',window.show_lessons)):
            b=QPushButton(title);b.clicked.connect(callback)
            if title=='Histology':b.setEnabled(window.histology_panel is not None)
            if title=='Radiology':b.setEnabled(window.radiology_browser is not None)
            row.addWidget(b)
        row.addStretch();layout.addLayout(row);layout.addWidget(catalog,1)
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
            if item.widget() is catalog.preview:rl.setStretch(rl.count()-1,1)
        original.addWidget(split,1)
        split.setStretchFactor(0,3);split.setStretchFactor(1,2);split.setSizes([660,440])
        for button in (catalog.verify_models,catalog.cancel_verification,catalog.open_button):
            button.setMaximumWidth(max(220,button.sizeHint().width()))
        catalog.kind_filter.setMaximumWidth(360)
        self.catalog_splitter=split
        catalog.show()


def atlas_dock(window):
    host=QWidget();host.setObjectName('studioAtlasTools');host.setAttribute(Qt.WA_StyledBackground,True)
    holder=QHBoxLayout(host);holder.setContentsMargins(20,10,20,16);holder.addStretch()
    dock=QWidget(host);dock.setObjectName('dock');dock.setAttribute(Qt.WA_StyledBackground,True);row=QHBoxLayout(dock)
    row.setContentsMargins(14,8,14,8);row.addStretch()
    for label,callback in (('Parts',lambda:window._show_nav_page(window.tree)),
                           ('Reveal',lambda:window._show_nav_page(window.view_panel))):
        button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
    section=QToolButton();section.setText('Section');section.setMenu(window.section_menu)
    section.setPopupMode(QToolButton.InstantPopup);row.addWidget(section)
    for label,key in (('Measure','measure'),('Reset','reset_view')):
        action=window.cmds.actions.get(key)
        if action is not None:
            button=QToolButton();button.setDefaultAction(action);button.setText(label);row.addWidget(button)
    tools=QToolButton();tools.setText('More tools');tools.setMenu(window.tools_menu)
    tools.setPopupMode(QToolButton.InstantPopup);row.addWidget(tools)
    row.addStretch();holder.addWidget(dock);holder.addStretch();return host

class FloatingPanels:
    """Keep legacy dock APIs while presenting ordinary in-workspace cards."""
    def __init__(self, window):
        self.window = window
        self.host = window.workspace
        self.panels = (window.left_dock, window.right_dock)
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
        for panel in self.panels:
            was_visible=not panel.isHidden()
            window.removeDockWidget(panel)
            panel.setParent(self.host,Qt.Widget)
            panel.installEventFilter(self.filter)
            panel.setAllowedAreas(Qt.NoDockWidgetArea)
            panel.setFeatures(QDockWidget.DockWidgetClosable)
            panel.setAttribute(Qt.WA_StyledBackground,True)
            panel.setStyleSheet('QDockWidget {background:#f8fafb;border:1px solid #94a6b1;border-radius:14px;}')
            title=QWidget(panel);title.setAttribute(Qt.WA_StyledBackground,True)
            title.setStyleSheet('background:#f8fafb;border:none;border-top-left-radius:14px;border-top-right-radius:14px;')
            row=QHBoxLayout(title);row.setContentsMargins(14,10,10,8)
            label=QLabel(panel.windowTitle());label.setStyleSheet('color:#24343d;font-size:16px;font-weight:600;');row.addWidget(label);row.addStretch()
            close=QPushButton('Close');close.setAccessibleName('Close '+panel.windowTitle());close.clicked.connect(panel.hide);row.addWidget(close)
            panel.setTitleBarWidget(title)
            content=panel.widget()
            scroll=QScrollArea(panel);scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setWidget(content);panel.setWidget(scroll)
            panel.visibilityChanged.connect(lambda visible,p=panel: self.shown(p,visible))
            panel.setVisible(was_visible)
        self.layout()
    def clip(self,panel):
        # QWidget masks clip descendant scroll viewports too, unlike QSS radius.
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath,QRegion
        path=QPainterPath();path.addRoundedRect(QRectF(panel.rect()),14,14)
        panel.setMask(QRegion(path.toFillPolygon().toPolygon()))
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
            top += 100
        available=max(120,h-top-20)
        for index,panel in enumerate(self.panels):
            content=panel.widget().widget()
            minimum=content.minimumSizeHint().width() + 26
            preferred=max(400 if index else 450, minimum)
            width=min(preferred,max(240,w-40))
            x=max(20,w-width-20) if index else 20
            panel.setGeometry(x,top,width,min(760,available))
            if panel.mask().isEmpty():self.clip(panel)
            if not panel.isHidden():panel.raise_()
