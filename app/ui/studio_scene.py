"""Responsive native scene instruments around an unchanged OpenGL viewport."""
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QScrollArea

class StudioScene(QWidget):
    partsChanged=Signal(bool)
    def __init__(self,viewport,parts,reveal,sections,teaching,parent=None):
        super().__init__(parent)
        self.setObjectName('studioScene')
        self.viewport=viewport;viewport.setParent(self)
        self.parts=parts;self._practice=False
        self.cards={};self.tools={};self._active=None;self._laying_out=False
        self.cards['parts']=self._card('Parts',parts,'studioCard')
        self.cards['reveal']=self._card('Reveal',reveal,'studioInstrument')
        self.cards['section']=self._card('Section',sections,'studioInstrument')
        self.teaching=teaching;teaching.setParent(self);teaching.setObjectName('studioTeaching')
        teaching.installEventFilter(self)
        self.dock=QFrame(self);self.dock.setObjectName('studioDock')
        self.dock_layout=QGridLayout(self.dock);self.dock_layout.setContentsMargins(9,7,9,7);self.dock_layout.setSpacing(4)
        for key,title in [('parts','Parts'),('reveal','Reveal'),('section','Section')]:
            button=self.add_tool(key,title,checkable=True)
            button.toggled.connect(lambda on,k=key:self.show_card(k,on))
        self.measure=self.add_tool('measure','Measure',checkable=True)
        self.labels=self.add_tool('labels','Labels',checkable=True)
        self.reset=self.add_tool('reset','Reset')
        self.parts.installEventFilter(self)
        self.tools['parts'].setChecked(True)
        self.setMinimumSize(340,240)

    def _card(self,title,content,name):
        card=QFrame(self);card.setObjectName(name);card.setProperty('studioRole','surface');card.setAccessibleName(title+' instrument')
        layout=QVBoxLayout(card);layout.setContentsMargins(10,8,10,10);layout.setSpacing(5)
        header=QHBoxLayout();label=QLabel(title);label.setObjectName('studioCardTitle');header.addWidget(label);header.addStretch()
        close=QPushButton('Close');close.setAccessibleName('Close '+title);close.clicked.connect(lambda:self.tools[title.lower()].setChecked(False));header.addWidget(close);layout.addLayout(header)
        scroll=QScrollArea(card);scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);scroll.setWidget(content)
        layout.addWidget(scroll,1);card.hide();return card

    def add_tool(self,key,title,checkable=False):
        button=QPushButton(title,self.dock);button.setObjectName('studioTool');button.setCheckable(checkable)
        button.setAccessibleName(title);button.setMinimumHeight(34);button.setFocusPolicy(Qt.StrongFocus)
        self.dock_layout.addWidget(button,0,len(self.tools));self.tools[key]=button;return button

    def show_card(self,key,on=True):
        if key=='parts' and self._practice:on=False
        if on:
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

    def set_practice(self,on):
        self._practice=on;self.tools['parts'].setEnabled(not on);self.labels.setEnabled(not on)
        if on:self.show_card('parts',False)
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
            w,h=self.width(),self.height();gap=12
            # Two-row dock on narrow windows; every action remains reachable.
            narrow=w<620
            for index,button in enumerate(self.tools.values()):
                button.setMinimumWidth(0);button.setMaximumWidth(16777215)
                self.dock_layout.removeWidget(button)
                self.dock_layout.addWidget(button,index//3 if narrow else 0,index%3 if narrow else index)
            self.dock_layout.setSpacing(2 if narrow else 4)
            dock_h=90 if narrow else 52;dock_w=min(max(self.dock.sizeHint().width(),330),max(1,w-2*gap))
            self.dock.setGeometry((w-dock_w)//2,max(0,h-dock_h-gap),dock_w,dock_h)
            top=gap
            if not self.teaching.isHidden():
                height=min(max(70,self.teaching.sizeHint().height()),max(70,h//4))
                self.teaching.setGeometry(gap,top,max(1,w-2*gap),height);top+=height+gap
            bottom=self.dock.y()-gap
            left=gap;right=w-gap
            parts=self.cards['parts'];instrument=next((self.cards[k] for k in ('reveal','section') if not self.cards[k].isHidden()),None)
            if w>=760:
                if not parts.isHidden():
                    width=min(320,max(250,w//4));parts.setGeometry(gap,top,width,max(1,bottom-top));left=gap+width+gap
                if instrument is not None:
                    width=min(370,max(290,w//3));instrument.setGeometry(w-gap-width,top,width,max(1,bottom-top));right=w-gap-width-gap
            else:
                # Instruments become lower cards so at least half the scene remains usable.
                card=parts if not parts.isHidden() else instrument
                if card is not None:
                    height=max(100,min(300,(bottom-top)//2));card.setGeometry(gap,bottom-height,max(1,w-2*gap),height);bottom-=height+gap
            self.viewport.setGeometry(left,top,max(1,right-left),max(1,bottom-top))
            self.viewport.lower()
            for card in self.cards.values():card.raise_()
            self.teaching.raise_();self.dock.raise_()
        finally:self._laying_out=False
