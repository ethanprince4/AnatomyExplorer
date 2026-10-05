"""Responsive native scene instruments around an unchanged OpenGL viewport."""
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QScrollArea

class StudioScene(QWidget):
    partsChanged=Signal(bool)
    isolateRequested=Signal()
    detailsRequested=Signal()
    def __init__(self,viewport,parts,reveal,sections,teaching,parent=None):
        super().__init__(parent)
        self.setObjectName('studioScene')
        self.viewport=viewport;viewport.setParent(self)
        self.parts=parts;self._practice=False
        from .studio_style import display_css
        self.breadcrumb=QLabel('Collection  /  3D models',self);self.breadcrumb.setObjectName('studioSceneBreadcrumb')
        self.subject=QLabel(self);self.subject.setObjectName('studioSceneTitle');self.subject.setTextFormat(Qt.PlainText);self.subject.setStyleSheet(display_css(42,'#eef3f6'))
        self.summary=QLabel(self);self.summary.setObjectName('studioSceneSummary');self.summary.setTextFormat(Qt.PlainText);self.summary.setWordWrap(True)
        self.status=QLabel(self);self.status.setObjectName('studioSceneStatus')
        self.cards={};self.tools={};self._active=None;self._laying_out=False;self._building=True
        self.cards['parts']=self._card('Model contents',parts,'studioCard',key='parts')
        self.cards['reveal']=self._card('Reveal',reveal,'studioInstrument')
        self.cards['section']=self._card('Section',sections,'studioInstrument')
        self.reveal_content=reveal
        self.selection=QFrame(self);self.selection.setObjectName('selectionSurface')
        selection_layout=QHBoxLayout(self.selection);selection_layout.setContentsMargins(20,13,16,13)
        text=QVBoxLayout();text.setSpacing(4)
        self.selection_title=QLabel();self.selection_title.setObjectName('studioSelectionTitle');self.selection_title.setTextFormat(Qt.PlainText)
        self.selection_description=QLabel();self.selection_description.setObjectName('studioSelectionDescription');self.selection_description.setTextFormat(Qt.PlainText);self.selection_description.setWordWrap(True)
        text.addWidget(self.selection_title);text.addWidget(self.selection_description);selection_layout.addLayout(text,1)
        isolate=QPushButton('Isolate');isolate.setProperty('variant','paperAction');isolate.clicked.connect(self.isolateRequested);selection_layout.addWidget(isolate)
        details=QPushButton('Details');details.clicked.connect(self.detailsRequested);selection_layout.addWidget(details);self.selection.hide()
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
        self.parts.installEventFilter(self)
        self.tools['parts'].setChecked(True)
        self.tools['reveal'].setChecked(True)
        self._building=False
        self.setMinimumSize(340,240)

    def _card(self,title,content,name,key=None):
        card=QFrame(self);card.setObjectName(name);card.setProperty('studioRole','surface');card.setAccessibleName(title+' instrument')
        layout=QVBoxLayout(card);layout.setContentsMargins(10,8,10,10);layout.setSpacing(5)
        header=QHBoxLayout();label=QLabel(title);label.setObjectName('studioCardTitle');header.addWidget(label);header.addStretch()
        close=QPushButton('\u00d7');close.setObjectName('headerClose');close.setAccessibleName('Close '+title);close.clicked.connect(lambda:self.tools[key or title.lower()].setChecked(False));header.addWidget(close);layout.addLayout(header)
        scroll=QScrollArea(card);scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);scroll.setWidget(content)
        layout.addWidget(scroll,1);card.hide();return card

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
                if other!=key and (self.width()<1000 or (key!='parts' and other!='parts')):
                    self.tools[other].setChecked(False)
        self.cards[key].setVisible(on)
        if key=='parts':self.parts.setVisible(on);self.partsChanged.emit(on)
        button=self.tools[key]
        if button.isChecked()!=on:
            button.blockSignals(True);button.setChecked(on);button.blockSignals(False)
        self.arrange()

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
            elif obj is self.teaching:self.arrange()
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
            selection_w=min(844,max(1,w-2*gap));selection_h=100 if w<760 else 84
            self.selection.setGeometry((w-selection_w)//2,max(gap,self.dock.y()-selection_h-12),selection_w,selection_h)
            parts=self.cards['parts'];parts_w=min(260,max(1,w-2*gap))
            parts_bottom=self.selection.y()-gap if not self.selection.isHidden() else self.dock.y()-gap
            parts_top=176
            parts_h=min(550,max(100,parts_bottom-parts_top))
            parts.setGeometry(34,parts_top,parts_w,parts_h)
            instrument_w=min(440,max(1,w-2*gap));instrument_x=(w-instrument_w)//2
            if w>=1000:instrument_x=max(parts.geometry().right()+gap if not parts.isHidden() else gap,instrument_x)
            instrument_x=min(instrument_x,max(gap,w-instrument_w-gap))
            reveal_h=360 if self.reveal_content.property('expanded') else 150
            self.cards['reveal'].setGeometry(instrument_x,54,instrument_w,min(reveal_h,max(100,h-2*gap-dock_h)))
            self.cards['section'].setGeometry(instrument_x,54,instrument_w,min(270,max(100,h-2*gap-dock_h)))
            if w<760:
                # A compact temporary sheet still floats over the continuous scene.
                for card in self.cards.values():
                    if not card.isHidden():card.setGeometry(gap,160,w-2*gap,min(card.height(),max(80,h-160-dock_h-2*gap)))
            if not self.teaching.isHidden():
                th=min(140,max(70,self.teaching.sizeHint().height()))
                self.teaching.setGeometry(max(gap,w-360-gap),gap,min(360,w-2*gap),th)
            # The renderer always owns the full canvas. Tools are sibling overlays.
            self.viewport.setGeometry(self.rect());self.viewport.lower()
            self.breadcrumb.raise_();self.subject.raise_();self.summary.raise_();self.status.raise_()
            for card in self.cards.values():card.raise_()
            self.teaching.raise_();self.selection.raise_();self.dock.raise_()
        finally:self._laying_out=False
