"""Responsive native scene instruments around an unchanged OpenGL viewport."""
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QComboBox,QLabel,QPushButton,QScrollArea,QSizePolicy

class StudioScene(QWidget):
    partsChanged=Signal(bool)
    isolateRequested=Signal()
    detailsRequested=Signal()
    def __init__(self,viewport,parts,reveal,sections,teaching,parent=None):
        super().__init__(parent)
        self.setObjectName('studioScene')
        self.viewport=viewport;viewport.setParent(self)
        self.parts=parts;self._practice=False;self._initializing=True
        from .studio_style import display_css
        self.breadcrumb=QLabel('Collection  /  3D models',self);self.breadcrumb.setObjectName('studioSceneBreadcrumb')
        self.subject=QLabel(self);self.subject.setObjectName('studioSceneTitle');self.subject.setTextFormat(Qt.PlainText);self.subject.setStyleSheet(display_css(42,'#eef3f6'))
        self.summary=QLabel(self);self.summary.setObjectName('studioSceneSummary');self.summary.setTextFormat(Qt.PlainText);self.summary.setWordWrap(True)
        self.status=QLabel(self);self.status.setObjectName('studioSceneStatus')
        # Explicit local colors survive the light application's generic QLabel rules.
        self.breadcrumb.setStyleSheet('QLabel { color: #c7d5df; background: transparent; }')
        self.summary.setStyleSheet('QLabel { color: #c7d5df; background: transparent; }')
        self.status.setStyleSheet('QLabel { color: #eef3f6; background: #263544; border-radius: 8px; padding: 4px 10px; }')
        self.cards={};self.tools={};self._active=None;self._laying_out=False;self.instrument_side="right";self._building=True
        self.cards['parts']=self._card('Model contents',parts,'studioCard',key='parts')
        self.cards['reveal']=self._card('Reveal',reveal,'studioInstrument')
        self.cards['section']=self._card('Section',sections,'studioInstrument')
        self.reveal_content=reveal
        self.selection=QFrame(self);self.selection.setObjectName('selectionSurface')
        selection_layout=QHBoxLayout(self.selection);selection_layout.setContentsMargins(20,13,16,13)
        self.selection_text=QWidget();self.selection_text.setStyleSheet('background: transparent;')
        text=QVBoxLayout(self.selection_text);text.setContentsMargins(0,0,0,0);text.setSpacing(6)
        self.selection_title=QLabel();self.selection_title.setObjectName('studioSelectionTitle');self.selection_title.setTextFormat(Qt.PlainText);self.selection_title.setWordWrap(True)
        self.selection_description=QLabel();self.selection_description.setObjectName('studioSelectionDescription');self.selection_description.setTextFormat(Qt.PlainText);self.selection_description.setWordWrap(True)
        text.addWidget(self.selection_title);text.addWidget(self.selection_description)
        self.selection_scroll=QScrollArea();self.selection_scroll.setWidgetResizable(True);self.selection_scroll.setFrameShape(QFrame.NoFrame);self.selection_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.selection_scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }');self.selection_scroll.viewport().setStyleSheet('background: transparent;');self.selection_scroll.setWidget(self.selection_text)
        selection_layout.addWidget(self.selection_scroll,1)
        self.selection_actions=QWidget();self.selection_actions.setObjectName('selectionActions');self.selection_actions.setStyleSheet('QWidget#selectionActions { background: transparent; }');actions=QVBoxLayout(self.selection_actions);actions.setContentsMargins(0,0,0,0);actions.setSpacing(8);actions.addStretch()
        isolate=QPushButton('Isolate');isolate.setProperty('variant','paperAction');isolate.clicked.connect(self.isolateRequested);actions.addWidget(isolate)
        details=QPushButton('Details');details.clicked.connect(self.detailsRequested);actions.addWidget(details);actions.addStretch();selection_layout.addWidget(self.selection_actions);self.selection.hide()
        self.teaching=teaching;teaching.setParent(self);teaching.setObjectName('studioTeaching')
        teaching.installEventFilter(self)
        self.dock=QFrame(self);self.dock.setObjectName('studioDock')
        self.dock_layout=QGridLayout(self.dock);self.dock_layout.setContentsMargins(9,7,9,7);self.dock_layout.setSpacing(4)
        self.select=self.add_tool('select','Select',checkable=True);self.select.setChecked(True)
        for key,title in [('parts','Parts'),('reveal','Reveal'),('section','Section')]:
            button=self.add_tool(key,title,checkable=True)
            button.toggled.connect(lambda on,k=key:self.show_card(k,on))
        self.measure=self.add_tool('measure','Measure',checkable=True)
        self.labels=self.add_tool('labels','Labels',checkable=True)
        self.reset=self.add_tool('reset','Reset')
        self.function=self.add_tool('function','Function',checkable=True);self.function.hide()
        self.function.setToolTip('Show optional function steps')
        self.function.toggled.connect(lambda on:(self.teaching.setVisible(on),self.arrange()))
        self.parts.installEventFilter(self)
        self.tools['parts'].setChecked(True)
        self.tools['reveal'].setChecked(True)
        self._building=False
        self._initializing=False
        self.loading_cover=QFrame(self)
        self.loading_cover.setObjectName('studioLoadingCover')
        self.loading_cover.setStyleSheet('QFrame#studioLoadingCover { background: rgba(20,27,34,245); } QLabel { color: #eef3f6; background: transparent; }')
        loading_layout=QVBoxLayout(self.loading_cover);loading_layout.setContentsMargins(40,40,40,40);loading_layout.addStretch()
        self.loading_title=QLabel('Preparing model…');self.loading_title.setWordWrap(True);self.loading_title.setStyleSheet('color: #eef3f6; font-size: 26px; font-weight: 600;')
        self.loading_note=QLabel('Preparing the 3D view and labels. You can keep using other tabs.');self.loading_note.setWordWrap(True)
        loading_layout.addWidget(self.loading_title);loading_layout.addWidget(self.loading_note);loading_layout.addStretch()
        self.loading_cover.hide()
        self.setMinimumSize(340,240)

    def set_loading(self,on,error=''):
        for widget in [self.viewport,self.dock,self.teaching,*self.cards.values(),self.selection]:widget.setEnabled(not on)
        self.loading_title.setText('Could not prepare the 3D view' if error else 'Preparing model…')
        self.loading_note.setText((str(error)+'\n\nClose this tab and try again.') if error else 'Preparing the 3D view and labels. You can keep using other tabs.')
        self.loading_cover.setVisible(on)
        self.arrange()

    def _card(self,title,content,name,key=None):
        card=QFrame(self);card.setObjectName(name);card.setProperty('studioRole','surface');card.setAccessibleName(title+' instrument')
        layout=QVBoxLayout(card);layout.setContentsMargins(10,8,10,10);layout.setSpacing(5)
        header=QHBoxLayout();label=QLabel(title);label.setObjectName('studioCardTitle');header.addWidget(label);header.addStretch()
        if title=='Reveal':
            position=QComboBox();position.setAccessibleName('Reveal panel position');position.addItem('Right edge','right');position.addItem('Below contents','left')
            position.currentIndexChanged.connect(lambda _:self.set_instrument_side(position.currentData()));header.addWidget(position)
        close=QPushButton('\u00d7');close.setObjectName('headerClose');close.setAccessibleName('Close '+title);close.clicked.connect(lambda:self.tools[key or title.lower()].setChecked(False));header.addWidget(close);layout.addLayout(header)
        if key=='parts':
            # The tree owns its scrollbar; an outer scroll area traps wheel input
            # and produces a second, competing scrollbar around the same list.
            layout.addWidget(content,1)
        else:
            scroll=QScrollArea(card);scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);scroll.setWidget(content)
            layout.addWidget(scroll,1)
        card.hide();return card

    def add_tool(self,key,title,checkable=False):
        button=QPushButton(title,self.dock);button.setObjectName('studioTool');button.setCheckable(checkable)
        from .studio_style import icon
        button.setIcon(icon(key))
        button.setAccessibleName(title);button.setMinimumHeight(34);button.setFocusPolicy(Qt.StrongFocus)
        self.dock_layout.addWidget(button,0,len(self.tools));self.tools[key]=button;return button

    def show_card(self,key,on=True):
        if key=='parts' and self._practice:on=False
        if on and not self._building:
            self._active=key
            # Compact scenes use one instrument at a time, retaining its restore tool.
            for other in self.cards:
                if not self._initializing and other!=key and (self.width()<1000 or (key!='parts' and other!='parts')):
                    self.tools[other].setChecked(False)
        self.cards[key].setVisible(on)
        if key=='parts':self.parts.setVisible(on);self.partsChanged.emit(on)
        button=self.tools[key]
        if button.isChecked()!=on:
            button.blockSignals(True);button.setChecked(on);button.blockSignals(False)
        self.arrange()

    def set_instrument_side(self,side):
        self.instrument_side=side;self.arrange()

    def set_subject(self,name,summary="",category="3D models",count=None):
        self.subject.setText(name);self.summary.setText(summary);self.breadcrumb.setText("Collection  /  "+category)
        self.status.setText(f"{count} parts" if count is not None else "")
        self.arrange()

    def set_selection(self,title,description=""):
        self.selection_title.setText(title);self.selection_description.setText(description)
        self.selection.setVisible(bool(title) and not self._practice);self.arrange()

    def set_practice(self,on):
        self._practice=on;self.tools['parts'].setEnabled(not on);self.labels.setEnabled(not on)
        if on:self.show_card('parts',False);self.selection.hide()
        else:self.show_card('parts',not self.parts.isHidden())

    def eventFilter(self,obj,event):
        if event.type() in (QEvent.Show,QEvent.Hide,QEvent.ShowToParent,QEvent.HideToParent,QEvent.LayoutRequest):
            if obj is self.parts and hasattr(self,'tools') and 'parts' in self.tools:
                visible=not self.parts.isHidden() and not self._practice
                if self.cards['parts'].isHidden()==visible:self.show_card('parts',visible)
            elif obj is self.teaching:
                if event.type() in (QEvent.Show,QEvent.ShowToParent) and hasattr(self,'function'):
                    self.function.show()
                    if not self.function.isChecked():self.teaching.hide()
                self.arrange()
        return super().eventFilter(obj,event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.width()<1000:
            visible=[key for key,card in self.cards.items() if not card.isHidden()]
            keep=self._active if self._active in visible else (visible[0] if visible else None)
            for key in visible:
                if key!=keep:self.show_card(key,False)
        self.arrange()

    def arrange(self):
        if self._laying_out or not hasattr(self,'dock'):return
        self._laying_out=True
        try:
            w,h=self.width(),self.height();gap=16;narrow=w<620
            self.breadcrumb.setGeometry(34,18,max(1,w-100),24)
            self.subject.setGeometry(34,49,max(1,min(680,w-68)),56)
            self.summary.setGeometry(34,108,max(1,min(610,w-68)),48)
            self.status.setGeometry(max(16,w-190),18,155,28)
            for index,button in enumerate(self.tools.values()):
                button.setMinimumWidth(0);self.dock_layout.removeWidget(button)
                self.dock_layout.addWidget(button,index//4 if narrow else 0,index%4 if narrow else index)
            dock_h=90 if narrow else 56
            dock_w=min(max(self.dock.sizeHint().width(),570 if not narrow else 300),max(1,w-2*gap))
            self.dock.setGeometry((w-dock_w)//2,max(0,h-dock_h-gap),dock_w,dock_h)
            selection_w=min(844,max(1,w-2*gap))
            # Measure the real wrapped labels, reserving the button column and
            # scrollbar width. Long descriptions scroll only after the cap.
            self.selection.ensurePolished()
            text_w=max(60,selection_w-36-self.selection_actions.sizeHint().width()-self.selection.layout().spacing()-18)
            text_h=6
            for label in (self.selection_title,self.selection_description):
                label.ensurePolished()
                height=max(label.fontMetrics().height(),label.heightForWidth(text_w))
                label.setMinimumHeight(height)
                text_h+=height
            self.selection_text.setMinimumHeight(text_h)
            desired_h=max(110,text_h+26,self.selection_actions.minimumSizeHint().height()+26)
            available_h=max(70,self.dock.y()-gap-12)
            selection_h=min(desired_h,max(110,min(320,int(h*.45))),available_h)
            self.selection.setGeometry((w-selection_w)//2,max(gap,self.dock.y()-selection_h-12),selection_w,selection_h)
            parts=self.cards['parts'];parts_w=min(312,max(1,w-2*gap))
            parts_bottom=self.selection.y()-gap if not self.selection.isHidden() else self.dock.y()-gap
            parts_top=176
            parts_h=min(550,max(100,parts_bottom-parts_top))
            if self.instrument_side=="left" and not self.cards["reveal"].isHidden():parts_h=max(100,parts_h-172)
            parts.setGeometry(34,parts_top,parts_w,parts_h)
            instrument_w=min(440,max(1,w-2*gap));instrument_x=max(gap,w-instrument_w-gap)
            instrument_y=54
            if self.instrument_side=='left' and w>=760:
                instrument_x=34
                instrument_y=parts.geometry().bottom()+12 if not parts.isHidden() else 176
            reveal_h=max(360 if self.reveal_content.property('expanded') else 174,self.reveal_content.minimumSizeHint().height()+62)
            self.cards['reveal'].setGeometry(instrument_x,min(instrument_y,max(16,self.dock.y()-reveal_h-12)),instrument_w,min(reveal_h,max(100,h-2*gap-dock_h)))
            self.cards['section'].setGeometry(instrument_x,54,instrument_w,min(270,max(100,h-2*gap-dock_h)))
            if w<760:
                # A compact temporary sheet still floats over the continuous scene.
                for card in self.cards.values():
                    if not card.isHidden():card.setGeometry(gap,160,w-2*gap,min(card.height(),max(80,h-160-dock_h-2*gap)))
            if not self.teaching.isHidden():
                th=min(140,max(70,self.teaching.sizeHint().height()))
                self.teaching.setGeometry(max(gap,w-360-gap),220 if not self.cards["reveal"].isHidden() else 54,min(360,w-2*gap),th)
            # The renderer always owns the full canvas. Tools are sibling overlays.
            self.viewport.setGeometry(self.rect());self.viewport.lower()
            self.breadcrumb.raise_();self.subject.raise_();self.summary.raise_();self.status.raise_()
            for card in self.cards.values():card.raise_()
            self.teaching.raise_();self.selection.raise_();self.dock.raise_()
            if hasattr(self,"loading_cover"):
                self.loading_cover.setGeometry(self.rect());self.loading_cover.raise_()
        finally:self._laying_out=False
