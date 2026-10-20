"""Production navigation for the approved canvas-led Study-02 shell.

Every command routes to the existing application owner; no demo scenes or data.
"""
from PySide6.QtCore import Qt, Signal, QSize, QEvent, QRectF
from PySide6.QtGui import QPainter, QPen, QIcon, QColor, QImage, QLinearGradient
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,
                               QLineEdit,QToolButton,QLabel,QMenu,QDockWidget,QScrollArea,QFrame,QSplitter,QStackedWidget,QSizePolicy)
from . import theme
from .shell import ElidingLabel
from .studio_style import icon


class RailButton(QToolButton):
    """Keep the reference's icon, seven-pixel gap and word-length active rule."""

    def sizeHint(self):
        return QSize(83, self.iconSize().height()+7+max(16,self.fontMetrics().height())+24)

    def minimumSizeHint(self):
        return QSize(0, self.iconSize().height()+7+max(16,self.fontMetrics().height())+6)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:
            rail=self.parentWidget()
            while rail is not None and not isinstance(rail,NavigationRail):
                rail=rail.parentWidget()
            if rail is not None:
                rail.fit_contents()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        colors = theme.palette()
        if self.underMouse() and self.isEnabled():
            p.fillRect(self.rect(), theme.qc(colors['spot']))
        color = colors['text'] if self.isChecked() else colors['text_2']
        if not self.isEnabled():
            color = colors['text_3']
        fm = p.fontMetrics()
        icon_size = self.iconSize()
        content_height = icon_size.height() + 7 + fm.height()
        offset = 0 if self.objectName() == 'studioRailUtility' else 2
        top = max(2, (self.height() - content_height) // 2 - offset)
        mode = QIcon.Disabled if not self.isEnabled() else QIcon.Active if self.isChecked() or self.underMouse() else QIcon.Normal
        pixmap = self.icon().pixmap(icon_size,mode,QIcon.On if self.isChecked() else QIcon.Off)
        p.drawPixmap((self.width() - icon_size.width()) // 2, top, pixmap)
        text_rect = QRectF(2, top + icon_size.height() + 7, self.width() - 4, fm.height())
        p.setPen(theme.qc(color))
        p.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.text())
        if self.isChecked():
            half = fm.horizontalAdvance(self.text()) / 2
            y = text_rect.bottom() + 5
            p.setPen(QPen(theme.qc(colors['accent']), 2))
            p.drawLine(int(self.width()/2-half), int(y), int(self.width()/2+half), int(y))
        if self.hasFocus():
            p.setPen(QPen(theme.qc(colors['text']), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(3, 3, -3, -3))


class NavigationRail(QWidget):
    """A content-sized rail keeps every caption readable without a wide gutter."""

    def __init__(self, parent):
        super().__init__(parent)
        from .studio_style import RAIL_WIDTH
        self.setObjectName('studioRail')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(RAIL_WIDTH)
        self.room_buttons = []
        self.utility_buttons = []
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 18, 1, 0)
        self.column.setSpacing(0)
        self.mark = QLabel(self)
        self.mark.setObjectName('studioRailMark')
        self.mark.setAlignment(Qt.AlignCenter)
        self.mark.setPixmap(icon('brand').pixmap(44, 44))
        self.mark.setAccessibleName('Layered Human')
        self.mark.setFixedHeight(44)
        self.column.addWidget(self.mark)
        self.mark_gap = 46
        self.column.addSpacing(self.mark_gap)
        self.rooms = QWidget(self)
        self.rooms.setObjectName('studioRailRooms')
        self.room_layout = QVBoxLayout(self.rooms)
        self.room_layout.setContentsMargins(0, 0, 0, 0)
        self.room_layout.setSpacing(10)
        self.column.addWidget(self.rooms)
        self.column.addStretch(1)
        self.foot = QWidget(self)
        self.foot.setObjectName('studioRailFoot')
        self.foot_layout = QVBoxLayout(self.foot)
        self.foot_layout.setContentsMargins(0, 19, 0, 19)
        self.foot_layout.setSpacing(2)
        self.column.addWidget(self.foot)

    def fit_contents(self):
        if not self.room_buttons or not self.utility_buttons:
            return
        room_text = max(16,max(button.fontMetrics().height() for button in self.room_buttons))
        foot_text = max(16,max(button.fontMetrics().height() for button in self.utility_buttons))
        self.setFixedWidth(max(84,max(button.fontMetrics().horizontalAdvance(button.text())+12
                                      for button in self.room_buttons+self.utility_buttons)))
        room_full, room_compact = 24 + 7 + room_text + 24, 24 + 7 + room_text + 8
        foot_full, foot_compact = 20 + 7 + foot_text + 18, 20 + 7 + foot_text + 6
        count_height = 20 if any(w.isVisible() for w in self.foot.findChildren(QLabel)) else 0
        full = 18 + 44 + 46 + 6*room_full + 5*10 + 12 + 3*foot_full + 4 + 26 + count_height
        compact = 12 + 44 + 10 + 6*room_compact + 5*2 + 12 + 3*foot_compact + 4 + 12 + count_height
        amount = max(0.0, min(1.0, (self.height() - compact) / max(1, full - compact)))
        blend = lambda small, large: round(small + (large-small)*amount)
        self.column.setContentsMargins(0, blend(12,18), 1, 0)
        foot_space = 12 + blend(12,26)
        self.foot_layout.setContentsMargins(0, foot_space//2, 0, foot_space-foot_space//2)
        self.column.itemAt(1).spacerItem().changeSize(0, blend(10,46), QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.room_layout.setSpacing(blend(2,10))
        for button in self.room_buttons:
            button.setFixedHeight(blend(room_compact, room_full))
        for button in self.utility_buttons:
            button.setFixedHeight(blend(foot_compact, foot_full))
        self.column.invalidate()

    def minimumSizeHint(self):
        if not self.room_buttons or not self.utility_buttons:
            return QSize(84,600)
        room_text=max(16,max(button.fontMetrics().height() for button in self.room_buttons))
        foot_text=max(16,max(button.fontMetrics().height() for button in self.utility_buttons))
        height=12+44+10+6*(24+7+room_text+8)+5*2+12+3*(20+7+foot_text+6)+4+12
        return QSize(self.width(),height)

    def resizeEvent(self, event):
        self.fit_contents()
        super().resizeEvent(event)

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange) and hasattr(self, 'room_buttons'):
            self.fit_contents()
            self.update()
        return result


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
        self.navigation_rail=NavigationRail(window)
        self.rail=self.navigation_rail
        rail_layout=self.navigation_rail.room_layout
        self.navigation={}
        rooms=(('Atlas','atlas',self.exploreRequested),('Lessons','lessons',self.learnRequested),
               ('Models','models',self.collectionRequested),('Radiology','radiology',self.radiologyRequested),
               ('Histology','histology',self.histologyRequested),('Practice','practice',self.practiceRequested))
        for label,key,signal in rooms:
            button=RailButton(self.navigation_rail);button.setObjectName('studioRailRoom')
            button.setText(label);button.setIcon(icon(key));button.setIconSize(QSize(24,24))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);button.setCheckable(True)
            button.setAccessibleName(label+' workspace')
            button.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False,s=signal:s.emit())
            self.navigation[key]=button
            self.navigation[{'atlas':'explore','models':'3d models'}.get(key,key)]=button
            rail_layout.addWidget(button)
            self.navigation_rail.room_buttons.append(button)
        rail_layout=self.navigation_rail.foot_layout
        self.practice_count=QLabel('',self.navigation_rail);self.practice_count.setObjectName('studioRailCount')
        self.practice_count.setAlignment(Qt.AlignCenter);rail_layout.addWidget(self.practice_count)
        self.saved_views_button=RailButton(self.navigation_rail);self.saved_views_button.setObjectName('studioRailUtility')
        self.saved_views_button.setText('Saved views');self.saved_views_button.setIcon(icon('bookmark'))
        self.saved_views_button.setIconSize(QSize(20,20));self.saved_views_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.saved_views_button.setMenu(window.views_menu);self.saved_views_button.setPopupMode(QToolButton.InstantPopup)
        self.saved_views_button.setAccessibleName('Saved views');rail_layout.addWidget(self.saved_views_button)
        self.settings_button=RailButton(self.navigation_rail);self.settings_button.setObjectName('studioRailUtility')
        self.settings_button.setText('Settings');self.settings_button.setIcon(icon('settings'))
        self.settings_button.setIconSize(QSize(20,20));self.settings_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.settings_button.clicked.connect(self.settingsRequested);rail_layout.addWidget(self.settings_button)
        self.more_button=RailButton(self.navigation_rail);self.more_button.setObjectName('studioRailUtility')
        self.more_button.setText('Menu');self.more_button.setIcon(icon('more'));self.more_button.setIconSize(QSize(20,20))
        self.more_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);rail_layout.addWidget(self.more_button)
        for button in (self.saved_views_button,self.settings_button,self.more_button):
            button.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            self.navigation_rail.utility_buttons.append(button)
        self.set_practice_due(0)
        layout=QVBoxLayout(self);layout.setContentsMargins(34,0,40,0);layout.setSpacing(0)
        self.bar=QWidget();self.bar.setObjectName('globalBar')
        self.bar.setAttribute(Qt.WA_StyledBackground,True)
        self.bar.setFixedHeight(80)
        row=QHBoxLayout(self.bar);row.setContentsMargins(0,0,0,0);row.setSpacing(26)
        # Keep the compatibility attribute; option 2 carries the identity in the rail.
        self.brand=QLabel('Layered Human',self.bar);self.brand.setObjectName('studioBrand');self.brand.hide()
        self.history=QWidget(self.bar);self.history.setObjectName('studioHistory')
        history_row=QHBoxLayout(self.history);history_row.setContentsMargins(0,0,0,0);history_row.setSpacing(4)
        self._place_labels=(None,None)
        # Back returns to the place before this one, anywhere in the app; its arrow lists the recent places.
        self.back_button=QToolButton();self.back_button.setObjectName('studioPlaceButton')
        self.back_button.setText('Back');self.back_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.back_button.setIcon(icon('back'));self.back_button.setIconSize(QSize(20,20))
        self.back_button.setAccessibleName('Back to the previous place')
        self.places_menu=QMenu(self.back_button)
        self.back_button.setMenu(self.places_menu);self.back_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.back_button.clicked.connect(self.backRequested.emit)
        self.forward_button=QToolButton();self.forward_button.setObjectName('studioPlaceButton')
        self.forward_button.setProperty('historyForward',True)
        self.forward_button.setText('Forward');self.forward_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.forward_button.setIcon(icon('forward'));self.forward_button.setIconSize(QSize(20,20))
        self.forward_button.setAccessibleName('Forward to the next place')
        self.forward_button.clicked.connect(self.forwardRequested.emit)
        for button in (self.back_button,self.forward_button):
            button.setEnabled(False);history_row.addWidget(button)
        self.back_button.installEventFilter(self)
        row.addWidget(self.history)
        self.trail=ElidingLabel('');self.trail.setObjectName('studioTrail');row.addWidget(self.trail)
        row.addStretch()
        self.search=QLineEdit();self.search.setObjectName('globalSearch')
        self.search.setPlaceholderText('Search the atlas, lessons, cases');self.search.setAccessibleName('Search all anatomy and study material')
        self.search.setClearButtonEnabled(True);self.search.setMinimumWidth(150);self.search.setMaximumWidth(330)
        self.search.addAction(icon('search'),QLineEdit.LeadingPosition)
        self.search.returnPressed.connect(lambda:self.searchRequested.emit(self.search.text()))
        row.addWidget(self.search)
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
        self._place_labels=(back_label,forward_label)
        for button,label,verb in ((self.back_button,back_label,'Back'),(self.forward_button,forward_label,'Forward')):
            button.setEnabled(bool(label))
            button.setToolTip(f'{verb} to {label}' if label else f'Nothing to go {verb.lower()} to yet')
            button.setAccessibleName(f'{verb} to {label}' if label else verb)
        self._fit_history()

    def _fit_history(self):
        scale=max(.8,self.back_button.fontMetrics().height()/18)
        label=self._place_labels[0]
        text=f'Back to {label}' if label else 'Back'
        natural=self.back_button.fontMetrics().horizontalAdvance(text)+round(88*scale)
        slot=min(max(round(300*scale),natural),max(240,round(self.width()*.48)))
        forward=round(32*scale)
        self.history.setFixedWidth(slot)
        self.forward_button.setFixedWidth(forward)
        self.back_button.setFixedWidth(slot-forward-4)
        available=self.back_button.width()-self.back_button.iconSize().width()-32
        self.back_button.setText(self.back_button.fontMetrics().elidedText(text,Qt.ElideRight,max(20,available)))

    def eventFilter(self, watched, event):
        if watched is self.back_button and event.type() in (QEvent.FontChange,QEvent.StyleChange):
            self._fit_history()
        return super().eventFilter(watched,event)

    def set_workspace(self,name):
        key={'explore':'atlas','3d models':'models','collection':'models','learn':'lessons'}.get(str(name).lower(),str(name).lower())
        for room in ('atlas','lessons','models','radiology','histology','practice'):
            self.navigation[room].setChecked(room==key)

    def set_practice_due(self,count):
        count=max(0,int(count or 0))
        self.practice_count.setText(f'{count} due' if count else '')
        self.practice_count.setVisible(bool(count))
        self.navigation['practice'].setAccessibleDescription(f'{count} practice items due' if count else 'Practice workspace')
        self.navigation_rail.fit_contents()

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
        self.brand.hide()
        self._fit_history()
        self.search.setFixedWidth(300 if self.width()>=1200 else 220)
        self.search.setPlaceholderText('Search the atlas, lessons, cases' if self.width()>=1200 else 'Search')
        self.trail.setMaximumWidth(max(120,self.width()-self.history.width()-self.search.width()-160))
        super().resizeEvent(event)


class CollectionWorkspace(QWidget):
    """Give the existing catalog a full workspace instead of a narrow dock."""
    def __init__(self,catalog,window):
        super().__init__();self.setObjectName('studioCollection');self.setAttribute(Qt.WA_StyledBackground,True)
        outer=QHBoxLayout(self);outer.setContentsMargins(40,112,40,24)
        self.card=QWidget(self);self.card.setObjectName('studioCollectionCard');self.card.setAttribute(Qt.WA_StyledBackground,True)
        outer.addWidget(self.card,1)
        layout=QVBoxLayout(self.card);layout.setContentsMargins(0,0,0,0)
        self.pages=QStackedWidget(self.card)
        self.navigation_mode='collection'
        self.buttons={}
        for title,page in (('3D models',catalog),('Histology',window.histology_panel),
                           ('Radiology',window.radiology_browser),('Lessons',window.lessons_panel)):
            if page is not None and self.pages.indexOf(page)<0:self.pages.addWidget(page)
        layout.addWidget(self.pages,1)
        self.window_owner=window
        # The catalogue owns its specimen grid and wall-label columns.
        self.catalog_splitter = None
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
    holder=QHBoxLayout(host);holder.setContentsMargins(0,0,0,4);holder.addStretch()
    dock=QWidget(host);dock.setObjectName('studioAtlasDock');dock.setAttribute(Qt.WA_StyledBackground,True);row=QHBoxLayout(dock)
    row.setContentsMargins(2,4,2,0);row.setSpacing(4)
    section=QToolButton();section.setObjectName('studioAtlasTool');section.setText('Section')
    section.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);section.setIcon(icon('section'));section.setIconSize(QSize(18,18))
    section.setMinimumHeight(36)
    section.setAccessibleName('Section controls')
    section.setToolTip('Open cross-section controls')
    section.setMenu(window.section_menu);section.setPopupMode(QToolButton.InstantPopup);row.addWidget(section)
    host.general_tools=[section]
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
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setAccessibleName(label);button.setToolTip(hint)
            button.setMinimumHeight(36)
            row.addWidget(button)
            host.general_tools.append(button)
    from .dock_pair import LabelDockPair
    labels=LabelDockPair(dock);labels.setObjectName('atlasLabelPair')
    host.label_pair=labels
    labels.setToolTip('Show numbered labels on visible anatomy')
    labels.setAccessibleName('Anatomy label controls')
    labels.labels.setMinimumWidth(68)
    labels.labels.setToolButtonStyle(Qt.ToolButtonTextOnly);labels.labels.setMinimumHeight(36)
    labels.labels.setToolTip('Show or hide numbered anatomy labels')
    labels.show_all.setMinimumWidth(76)
    labels.show_all.setToolButtonStyle(Qt.ToolButtonTextOnly);labels.show_all.setMinimumHeight(36)
    labels.set_labels_on(bool(window.cmds.actions['structure_labels'].isChecked()))
    structure_action=window.cmds.actions['structure_labels']
    def update_atlas_labels(enabled):
        enabled=bool(enabled)
        viewport=window.viewport
        setting_handler=getattr(window,'on_setting',None)
        if (getattr(viewport,'_radiology_label_groups',None) is not None
                or getattr(viewport,'lesson_label_mode_active',False)):
            pass  # Authored scenes do not change Atlas preferences.
        elif callable(setting_handler):
            setting_handler('show_structure_labels',enabled)
        elif structure_action.isChecked()!=enabled:
            structure_action.setChecked(enabled)
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
    labels_mode_changed=getattr(window.viewport,'labelsModeChanged',None)
    if labels_mode_changed is not None:
        labels_mode_changed.connect(labels.set_labels_on)
    def toggle_all_captions():
        viewport=window.viewport
        show=getattr(viewport,'show_all_labels',None);all_open=getattr(viewport,'labels_all_open',None)
        if callable(show) and callable(all_open):
            show(not all_open());labels.set_all_open(all_open())
    labels.showAllClicked.connect(toggle_all_captions)
    row.addWidget(labels)
    row.addSpacing(6)
    separator=QFrame(dock);separator.setObjectName('studioAtlasSeparator');separator.setFixedSize(1,22)
    row.addWidget(separator,0,Qt.AlignVCenter);row.addSpacing(6)
    host.general_tools.append(separator)
    reset=window.cmds.actions.get('reset_view')
    if reset is not None:
        reset.setIconText('Reset view')
        button=QToolButton();button.setObjectName('studioAtlasTool');button.setDefaultAction(reset)
        if reset.icon().isNull():button.setIcon(icon('reset'))
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setAccessibleName('Reset view');button.setToolTip('Reset camera view')
        button.setMinimumHeight(36)
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
    tools.setToolButtonStyle(Qt.ToolButtonIconOnly);tools.setFixedSize(32,36)
    tools.setAccessibleName('More atlas tools');tools.setToolTip('More tools and controls')
    row.addWidget(tools)
    host.general_tools.append(tools)
    holder.addWidget(dock);holder.addStretch();return host

class DetailsBackdrop(QWidget):
    """Continue the gallery wall behind prose, with a soft edge over the scene."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._key = self._image = None

    def paintEvent(self, event):
        from .wall_background import viewport_background
        palette = theme.palette()
        colours = viewport_background(self, {'custom_background': True,
            'bg_top': palette['stage_top'], 'bg_bottom': palette['stage_bottom']})
        width, height = self.width(), self.height()
        key = (width, height, colours['bg_top'], colours['bg_bottom'])
        if key != self._key and width > 0 and height > 0:
            layer = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
            layer.fill(Qt.transparent)
            painter = QPainter(layer)
            wall = QLinearGradient(0, 0, 0, height)
            wall.setColorAt(0, QColor(colours['bg_top']))
            wall.setColorAt(1, QColor(colours['bg_bottom']))
            painter.fillRect(layer.rect(), wall)
            edge = QLinearGradient(0, 0, min(144, width), 0)
            edge.setColorAt(0, QColor(255, 255, 255, 0))
            edge.setColorAt(1, QColor(255, 255, 255, 255))
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.fillRect(layer.rect(), edge)
            painter.end()
            self._key, self._image = key, layer
        if self._image is not None:
            painter = QPainter(self)
            painter.drawImage(0, 0, self._image)


class FloatingPanels:
    """Keep legacy dock APIs for utility cards and the right-side entry reader."""
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
        self.register(window.left_dock)
        self.register(window.right_dock,wrap_content=False)
        window.tabs.currentChanged.connect(self.update_title)
        self.update_title()
        self.layout()
    def register(self,panel,*,wrap_content=True,preferred_width=None):
        if panel in self.panels:return
        self.panels.append(panel)
        panel._studio_width=preferred_width
        is_details=panel is self.window.right_dock
        was_visible=not panel.isHidden()
        self.window.removeDockWidget(panel)
        panel.setParent(self.host,Qt.Widget)
        panel.installEventFilter(self.filter)
        panel.setAllowedAreas(Qt.NoDockWidgetArea)
        panel.setFeatures(QDockWidget.DockWidgetClosable)
        panel.setObjectName('studioDetailsPanel' if is_details else 'studioFloatingPanel')
        panel.setMinimumWidth(0)
        panel.setAttribute(Qt.WA_StyledBackground,True)
        title=QWidget(panel);title.setObjectName('studioFloatingTitleBar');title.setAttribute(Qt.WA_StyledBackground,True)
        row=QHBoxLayout(title)
        row.setContentsMargins(*( (6,0,0,12) if is_details else (14,10,10,8) ))
        label=QLabel(panel.windowTitle());label.setObjectName('studioFloatingTitle');panel._studio_title=label;row.addWidget(label);row.addStretch()
        close=QPushButton('Close');close.setObjectName('studioFloatingClose');close.setProperty('variant','quiet');close.setAccessibleName('Close '+panel.windowTitle());close.clicked.connect(self.window.close_details if is_details else panel.hide);row.addWidget(close)
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
            if panel is self.window.left_dock:
                self.window.right_dock.hide()
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
            if panel is self.window.right_dock:
                continue  # Positioned over the right reading rail by the workspace.
            content=panel._studio_content
            minimum=max(340,content.minimumSizeHint().width() + 26)
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
