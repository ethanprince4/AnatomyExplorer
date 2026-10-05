"""Production navigation for the approved canvas-led Study-02 shell.

Every command routes to the existing application owner; no demo scenes or data.
"""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,
                               QLineEdit,QToolButton,QLabel,QMenu)
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
        self.subject=QWidget();subject=QHBoxLayout(self.subject);subject.setContentsMargins(6,0,6,0)
        column=QVBoxLayout();column.setSpacing(7)
        self.title=ElidingLabel('3D Anatomy');self.title.setObjectName('studioDisplay')
        self.context=ElidingLabel('Explore the atlas or choose a model');self.context.setObjectName('studioEyebrow')
        column.addWidget(self.title);column.addWidget(self.context);subject.addLayout(column,1)
        for dock,label in ((window.left_dock,'Browse'),(window.right_dock,'Details')):
            button=QToolButton();button.setDefaultAction(dock.toggleViewAction());button.setText(label)
            button.setAccessibleName('Show or hide '+label.lower());subject.addWidget(button)
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
        super().__init__();self.setObjectName('studioCollection')
        layout=QVBoxLayout(self);layout.setContentsMargins(20,10,20,18)
        row=QHBoxLayout()
        for title,callback in (('3D models',catalog.focus_search),('Histology',lambda:window._show_nav_page(window.histology_panel)),
                               ('Radiology',lambda:window._show_nav_page(window.radiology_browser)),('Lessons',window.show_lessons)):
            b=QPushButton(title);b.clicked.connect(callback)
            if title=='Histology':b.setEnabled(window.histology_panel is not None)
            if title=='Radiology':b.setEnabled(window.radiology_browser is not None)
            row.addWidget(b)
        row.addStretch();layout.addLayout(row);layout.addWidget(catalog,1)


def atlas_dock(window):
    dock=QWidget();dock.setObjectName('dock');row=QHBoxLayout(dock)
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
    row.addStretch();return dock
