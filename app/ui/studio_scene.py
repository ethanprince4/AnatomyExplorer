"""Floating model instruments over a continuous, full-size anatomy canvas."""
from math import ceil
from pathlib import Path
import re
from PySide6.QtGui import QTextDocument, QIcon, QColor, QImage, QLinearGradient, QPainter
from PySide6.QtCore import Qt, Signal, QEvent, QSize
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QComboBox,QLabel,QPushButton,QToolButton,QScrollArea,QSizePolicy,QMenu,QLayout
from .outline import Outline


class WallLetteringFade(QWidget):
    """Softly return anatomy to the shared wall behind instrument zones.

    This is one cached transparent overlay, never a cropped render target or an
    opaque panel. The centre remains clear and mouse input reaches the model.
    """
    def __init__(self,parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents,True)
        self.setAttribute(Qt.WA_NoSystemBackground,True)
        self.zones=(0,0,0,0)
        self._key=None;self._image=None

    def set_zones(self,zones):
        self.zones=tuple(zones);self.update()

    def paintEvent(self,event):
        from . import theme
        p=theme.palette();w,h=self.width(),self.height()
        key=(w,h,self.zones,p['stage_top'],p['stage_bottom'])
        if key!=self._key and w>0 and h>0:
            layer=QImage(w,h,QImage.Format_ARGB32_Premultiplied);layer.fill(Qt.transparent)
            painter=QPainter(layer)
            wall=QLinearGradient(0,0,0,h)
            wall.setColorAt(0,QColor(p['stage_top']));wall.setColorAt(1,QColor(p['stage_bottom']))
            painter.fillRect(layer.rect(),wall)
            mask=QImage(w,h,QImage.Format_ARGB32_Premultiplied);mask.fill(Qt.transparent)
            mp=QPainter(mask)
            left,top,right,bottom=self.zones
            for start,end,extent in [((0,0),(left,0),left),((0,0),(0,top),top),
                                     ((w,0),(w-right,0),right),((0,h),(0,h-bottom),bottom)]:
                if extent<=0:continue
                fade=QLinearGradient(*start,*end)
                fade.setColorAt(0,QColor(255,255,255,235))
                fade.setColorAt(.58,QColor(255,255,255,218))
                fade.setColorAt(1,QColor(255,255,255,0))
                mp.fillRect(mask.rect(),fade)
            mp.end()
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.drawImage(0,0,mask);painter.end()
            self._image=layer;self._key=key
        if self._image is not None:
            painter=QPainter(self);painter.drawImage(0,0,self._image)


class StudioScene(QWidget):
    partsChanged=Signal(bool)
    isolateRequested=Signal()
    hideRequested=Signal()
    detailsRequested=Signal()
    def __init__(self,viewport,parts,reveal,sections,teaching,parent=None):
        super().__init__(parent)
        self.setObjectName('studioScene')
        self.setAttribute(Qt.WA_StyledBackground,True)
        self.viewport=viewport;viewport.setParent(self)
        # Fade the anatomy, then paint its labels. A sibling above the viewport
        # would dim the caption layer along with the tissue beneath it.
        self.wall_fade=WallLetteringFade(viewport)
        self.parts=parts;self._practice=False;self._initializing=True;self._lesson_mode=False;self._reference_mode=False
        self._annotation_mode=False;self._annotation_restore=None
        from .studio_style import display_css
        from . import theme
        self.breadcrumb=QLabel('Collection  /  3D models',self);self.breadcrumb.setObjectName('studioSceneBreadcrumb')
        self.subject=QLabel(self);self.subject.setObjectName('studioSceneTitle');self.subject.setTextFormat(Qt.PlainText);self.subject.setStyleSheet(display_css(44))
        self.subject.setFont(theme.font_for('display',size=44,weight=400,optical_size=72))
        self.summary=QLabel(self);self.summary.setObjectName('studioSceneSummary');self.summary.setTextFormat(Qt.PlainText);self.summary.setWordWrap(True)
        self.status=QLabel(self);self.status.setObjectName('studioSceneStatus')
        self.status.hide()
        self.summary.hide()
        # Keep every instrument wall-lettered; the active palette owns the text and focus colors.
        self.cards={};self.tools={};self._active=None;self._laying_out=False;self.instrument_side="right";self._building=True
        self.cards['parts']=self._card('Parts',parts,'studioCard',key='parts')
        self.cards['reveal']=self._card('Reveal',reveal,'studioInstrument')
        self.cards['section']=self._card('Section',sections,'studioInstrument')
        self.reveal_content=reveal
        self.selection=QFrame(self);self.selection.setObjectName('selectionSurface')
        selection_layout=QVBoxLayout(self.selection);selection_layout.setContentsMargins(0,0,0,0);selection_layout.setSpacing(12)
        self.selection_text=QWidget();self.selection_text.setStyleSheet('background: transparent;')
        text=QVBoxLayout(self.selection_text);text.setContentsMargins(0,0,0,0);text.setSpacing(6);text.setAlignment(Qt.AlignTop)
        self.selection_title=QLabel();self.selection_title.setObjectName('studioSelectionTitle');self.selection_title.setTextFormat(Qt.PlainText);self.selection_title.setWordWrap(True)
        self.selection_expand=QToolButton();self.selection_expand.setText('Read description');self.selection_expand.setCheckable(True)
        self.selection_expand.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);self.selection_expand.setArrowType(Qt.RightArrow)
        self.selection_expand.setAccessibleName('Read selected structure description');self.selection_expand.hide()
        self.selection_expand.toggled.connect(self._expand_selection)
        self.selection_description=QLabel();self.selection_description.setObjectName('studioSelectionDescription');self.selection_description.setTextFormat(Qt.PlainText);self.selection_description.setWordWrap(True)
        text.addWidget(self.selection_title);text.addWidget(self.selection_expand);text.addWidget(self.selection_description)
        self.selection_scroll=QScrollArea();self.selection_scroll.setWidgetResizable(True);self.selection_scroll.setFrameShape(QFrame.NoFrame);self.selection_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.selection_scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }');self.selection_scroll.viewport().setStyleSheet('background: transparent;');self.selection_scroll.setWidget(self.selection_text)
        selection_layout.addWidget(self.selection_scroll,1)
        self.selection_actions=QWidget();self.selection_actions.setObjectName('selectionActions');self.selection_actions.setStyleSheet('QWidget#selectionActions { background: transparent; }');actions=QHBoxLayout(self.selection_actions);actions.setContentsMargins(0,0,0,0);actions.setSpacing(8)
        isolate=QPushButton('Isolate');isolate.setProperty('variant','primary');isolate.clicked.connect(self.isolateRequested);actions.addWidget(isolate)
        hide=QPushButton('Hide');hide.setProperty('variant','primary');hide.clicked.connect(self.hideRequested);actions.addWidget(hide)
        details=QPushButton('Details');details.clicked.connect(self.detailsRequested);actions.addWidget(details);actions.addStretch();selection_layout.addWidget(self.selection_actions);self.selection.hide()
        self.selection_details=details
        self.stored_views=QScrollArea(self);self.stored_views.setObjectName('studioStoredViews');self.stored_views.setFrameShape(QFrame.NoFrame)
        self.stored_views.setWidgetResizable(True);self.stored_views.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded);self.stored_views.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stored_views.setAccessibleName('Stored model views');self.stored_views.hide();self.view_tiles={}
        self.teaching=teaching;teaching.setParent(self);teaching.setObjectName('studioTeaching')
        teaching.installEventFilter(self)
        self.dock=QFrame(self);self.dock.setObjectName('studioModelDock')
        self.dock_layout=QGridLayout(self.dock);self.dock_layout.setContentsMargins(2,4,2,0);self.dock_layout.setSpacing(4)
        self.select=self.add_tool('select','Select',checkable=True);self.select.setChecked(True)
        for key,title in [('parts','Parts'),('reveal','Reveal'),('section','Section')]:
            button=self.add_tool(key,title,checkable=True)
            button.toggled.connect(lambda on,k=key:self.show_card(k,on))
        self.measure=self.add_tool('measure','Measure',checkable=True)
        self.xray=self.add_tool('xray','X-ray')
        self.isolate=self.add_tool('isolate','Isolate')
        self.hide_selected=self.add_tool('hide','Hide')
        self.section=QToolButton(self.dock);self.section.setObjectName('studioAtlasTool');self.section.setText('Section');self.section.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        from .studio_style import icon
        self.section.setIcon(icon('section'));self.section.setIconSize(QSize(18,18));self.section.setPopupMode(QToolButton.InstantPopup)
        self.section.setAccessibleName('Model section controls');self.section.setMinimumHeight(36);self.tools['section_menu']=self.section
        from .dock_pair import LabelDockPair
        self.label_pair=LabelDockPair(self.dock)
        self.labels=self.label_pair.labels
        self.tools['labels']=self.label_pair
        self.dock_layout.addWidget(self.label_pair,0,len(self.tools)-1)
        self.label_pair.labelsToggled.connect(lambda on:self.label_pair.set_labels_on(on))
        self.label_pair.layoutChanged.connect(self.arrange)
        self.show_all=self.add_tool('show_all','Show all')
        self.show_all.setToolTip('Show every part again and leave isolation')
        self.reset=self.add_tool('reset','Reset view')
        self.reset.setToolTip('Reset the camera view')
        self.function=self.add_tool('function','Function',checkable=True);self.function.hide()
        self.function.setToolTip('Show optional function steps')
        self.function.toggled.connect(self.show_function)
        more_menu=QMenu(self)
        more_menu.addAction('Show every part',self.show_all.click)
        self.show_all.hide()
        for key,title in [('parts','Parts'),('reveal','Reveal controls'),('section','Cross-section')]:
            button=self.tools[key]
            action=more_menu.addAction(title);action.setCheckable(True)
            action.setChecked(key in ('parts','reveal'))
            action.toggled.connect(button.setChecked)
            button.toggled.connect(action.setChecked)
        for key in ('select','parts','reveal','section'):self.tools[key].hide()
        more=self.add_tool('more','');more.setIcon(icon('more'));more.setAccessibleName('More model tools');more.setMenu(more_menu)
        self.parts.installEventFilter(self)
        self.tools['parts'].setChecked(True)
        self.tools['reveal'].setChecked(True)
        self._building=False
        self._initializing=False
        self.loading_cover=QFrame(self)
        self.loading_cover.setObjectName('studioLoadingCover')
        loading_layout=QVBoxLayout(self.loading_cover);loading_layout.setContentsMargins(40,40,40,40);loading_layout.addStretch()
        self.loading_title=QLabel('Preparing model…');self.loading_title.setWordWrap(True);self.loading_title.setFont(theme.font_for('display',size=26,weight=500))
        self.loading_note=QLabel('Preparing the 3D view and labels. You can keep using other tabs.');self.loading_note.setWordWrap(True)
        for label in (self.loading_title,self.loading_note):
            label.setAlignment(Qt.AlignCenter);label.setMaximumWidth(560)
        loading_layout.addWidget(self.loading_title,0,Qt.AlignHCenter);loading_layout.addWidget(self.loading_note,0,Qt.AlignHCenter);loading_layout.addStretch()
        self.loading_cover.hide()
        self.setMinimumSize(340,240)

    def set_lesson_mode(self, on):
        """Use only the model canvas in a lesson; restore library instruments on exit."""
        on = bool(on)
        if self._lesson_mode == on:
            return
        overlays = [self.breadcrumb, self.subject, self.summary, self.status, self.dock,self.stored_views,
                    self.selection, self.teaching, *self.cards.values()]
        if on:
            self._lesson_restore = [(widget, not widget.isHidden()) for widget in overlays]
            self._lesson_mode = True
            for widget in overlays:
                widget.hide()
        else:
            self._lesson_mode = False
            for widget, visible in self._lesson_restore:
                widget.setVisible(visible)
        self.arrange()

    def set_reference_mode(self,on=True):
        """A comparison scene has one purpose-specific toolbar, not library instruments."""
        on=bool(on)
        if self._reference_mode==on:return
        self._reference_mode=on
        if on:
            self._reference_restore=[(widget,not widget.isHidden()) for widget in
                [self.subject,self.summary,self.stored_views,self.teaching,*self.cards.values(),*self.tools.values()]]
            for key in self.cards:self.show_card(key,False)
            for widget in [self.subject,self.summary,self.stored_views,self.teaching,*self.tools.values()]:widget.hide()
            for key in ('labels','show_all','reset'):self.tools[key].show()
            self.show_all.setText('Restore anatomy');self.show_all.setToolTip('Restore the anatomy chosen for this case')
            self.selection_details.hide()
        else:
            for widget,visible in self._reference_restore:widget.setVisible(visible)
            self.show_all.setText('Show all');self.show_all.setToolTip('Show every part again and leave isolation')
            self.selection_details.show()
        self.selection_expand.setChecked(False)
        self.selection_expand.setVisible(on and bool(self.selection_description.text()))
        self.selection_description.setVisible(not on)
        self.arrange()

    def _expand_selection(self,on):
        self.selection_expand.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.selection_expand.setText('Hide description' if on else 'Read description')
        self.selection_description.setVisible(bool(on) or not self._reference_mode)
        self.arrange()

    def set_annotation_mode(self,on):
        """Give open captions the outer walls without overlapping instruments."""
        if on and not self._annotation_mode:
            from .label_rails import reserve_caption_space
            reserve_caption_space(self.viewport)
        self._annotation_mode=bool(on)
        if not self._reference_mode:
            self.selection.setVisible(bool(self.selection_title.text()) and not self._annotation_mode
                                      and not self._practice and not self._lesson_mode)
        self.arrange()

    def _arrange_annotation_instruments(self):
        if self._lesson_mode or self._reference_mode:return
        tuck=self._annotation_mode
        self.stored_views.setVisible(bool(self.view_tiles) and not tuck)
        if tuck and self._annotation_restore is None:
            self._annotation_restore={
                'cards':{key:not self.cards[key].isHidden() for key in ('parts','reveal','section')},
                'function':self.function.isChecked(),
            }
            for key in ('parts','reveal','section'):self.show_card(key,False)
            self.function.setChecked(False);self.teaching.hide()
        elif not tuck and self._annotation_restore is not None:
            saved=self._annotation_restore;self._annotation_restore=None
            for key,visible in saved['cards'].items():self.show_card(key,visible)
            self.function.setChecked(saved['function'])

    def set_loading(self,on,error=''):
        for widget in [self.viewport,self.dock,self.teaching,*self.cards.values(),self.selection]:widget.setEnabled(not on)
        self.loading_title.setText('Could not prepare the 3D view' if error else 'Preparing model…')
        self.loading_note.setText((str(error)+'\n\nClose this tab and try again.') if error else 'Preparing the 3D view and labels. You can keep using other tabs.')
        self.loading_cover.setVisible(on)
        self.arrange()

    def _card(self,title,content,name,key=None):
        card=QFrame(self);card.setObjectName(name);card.setProperty('studioRole','surface');card.setAccessibleName(title+' instrument')
        layout=QVBoxLayout(card);layout.setContentsMargins(0,0,0,0);layout.setSpacing(14)
        header=QHBoxLayout();label=QLabel(title);label.setObjectName('studioViewerHeading');header.addWidget(label);header.addStretch()
        close=QPushButton('\u00d7');close.setObjectName('headerClose');close.setAccessibleName('Close '+title);close.clicked.connect(lambda:self.tools[key or title.lower()].setChecked(False));header.addWidget(close)
        close.hide();layout.addLayout(header)
        if title=='Reveal':
            layout.setSizeConstraint(QLayout.SetNoConstraint)
            content.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred)
        if key=='parts' or title=='Reveal':
            # The tree owns its scrollbar; an outer scroll area traps wheel input
            # and produces a second, competing scrollbar around the same list.
            layout.addWidget(content,1)
        else:
            scroll=QScrollArea(card);scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);scroll.setWidget(content)
            layout.addWidget(scroll,1)
        card.hide();return card

    def add_tool(self,key,title,checkable=False):
        button=QPushButton(title,self.dock);button.setObjectName('studioModelTool');button.setCheckable(checkable)
        button.setAccessibleName(title);button.setMinimumHeight(36);button.setFocusPolicy(Qt.StrongFocus)
        self.dock_layout.addWidget(button,0,len(self.tools));self.tools[key]=button;return button

    def set_stored_views(self,names,cameras,activate,model_id):
        body=QWidget();body.setObjectName('studioStoredViewBody');row=QVBoxLayout(body);row.setContentsMargins(0,0,8,0);row.setSpacing(12)
        heading=QLabel('Views');heading.setObjectName('studioViewerHeading');row.addWidget(heading)
        groups={};self.view_tiles={}
        kidney_groups={'Family overview (nephron 15x)':'Overview','Kidney':'Whole kidney','Lobe opened':'Whole kidney','Renal vessels':'Whole kidney','Lobe':'Whole kidney','Nephron (15x schematic)':'Nephron, 15×','Corpuscle':'Nephron, 15×','Juxtaglomerular apparatus':'Nephron, 15×','Podocytes':'Nephron, 15×','Loop of Henle':'Nephron, 15×'}
        thumbnails={'Kidney':'kidney_v_kidney','Lobe':'kidney_v_lobe','Nephron (15x schematic)':'kidney_v_nephron','Corpuscle':'kidney_v_corpuscle','Juxtaglomerular apparatus':'kidney_v_jga','Podocytes':'kidney_v_podocytes'}
        for name in names:
            record=cameras.get(name,{})
            title=str(record.get('title') or record.get('label') or name).strip()
            if re.fullmatch(r'(?:v(?:iew)?\s*)?\d+',title,re.IGNORECASE):
                title=str(record.get('note') or '').strip()
            if not title or re.fullmatch(r'(?:v(?:iew)?\s*)?\d+',title,re.IGNORECASE):continue
            group=record.get('group','')
            if model_id=='kidney_nephron':group=kidney_groups.get(name,'Section diagram')
            if group not in groups:
                box=QWidget();column=QVBoxLayout(box);column.setContentsMargins(0,0,0,0);column.setSpacing(6)
                if group:
                    label=QLabel(group);label.setObjectName('studioStoredViewGroup');column.addWidget(label)
                tiles=QVBoxLayout();tiles.setSpacing(6);tiles.setContentsMargins(0,0,0,0);column.addLayout(tiles);row.addWidget(box);groups[group]=tiles
            tile=QToolButton();tile.setObjectName('studioStoredView');tile.setIconSize(QSize(42,32));tile.setCheckable(True)
            tile.setAccessibleName(title);tile.setToolTip(title)
            tile.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            tile_layout=QHBoxLayout(tile);tile_layout.setContentsMargins(10,6,10,6);tile_layout.setSpacing(10)
            thumbnail=record.get('thumbnail')
            if model_id=='kidney_nephron' and name in thumbnails:
                thumbnail=Path(__file__).parent/'resources/studio/stored-views'/(thumbnails[name]+'.webp')
            if thumbnail and Path(thumbnail).is_file():
                preview=QLabel();preview.setPixmap(QIcon(str(thumbnail)).pixmap(QSize(42,32)));preview.setAttribute(Qt.WA_TransparentForMouseEvents);tile_layout.addWidget(preview)
            caption=QLabel(title);caption.setWordWrap(True);caption.setAttribute(Qt.WA_TransparentForMouseEvents);tile_layout.addWidget(caption,1)
            tile.setMinimumHeight(44)
            tile.clicked.connect(lambda checked=False,name=name:activate(name));groups[group].addWidget(tile);self.view_tiles[name]=tile
        row.addStretch();self.stored_views.setWidget(body);self.stored_views.setVisible(bool(self.view_tiles) and not self._reference_mode and not self._lesson_mode);self.arrange()

    def set_current_view(self,name,caption=''):
        for key,tile in self.view_tiles.items():tile.setChecked(key==name)
        self.summary.setText(caption);self.summary.setVisible(bool(caption) and not self._lesson_mode and not self._reference_mode)

    def show_function(self,on):
        if self._lesson_mode or self._reference_mode:on=False
        if on:
            for key in ('reveal','section'):
                self.show_card(key,False)
            if self.width()<820:
                self.tools['parts'].setChecked(False)
                self.selection.hide()
        self.teaching.setVisible(on)
        self.arrange()

    def show_card(self,key,on=True):
        if self._lesson_mode or self._reference_mode:on=False
        if on and self.width()<820:self.selection.hide()
        if on and (key in ('reveal','section') or self.width()<820) and hasattr(self,'function'):
            self.function.setChecked(False)
        if key=='parts' and self._practice:on=False
        if on and not self._building:
            self._active=key
            # Compact scenes use one instrument at a time, retaining its restore tool.
            for other in self.cards:
                if not self._initializing and other!=key and (self.width()<1000 or (key!='parts' and other!='parts')):
                    self.tools[other].setChecked(False)
        self._changing_card=True
        try:
            self.cards[key].setVisible(on)
            if key=='parts':self.parts.setVisible(on)
        finally:self._changing_card=False
        if key=='parts':self.partsChanged.emit(on)
        button=self.tools[key]
        if button.isChecked()!=on:
            button.blockSignals(True);button.setChecked(on);button.blockSignals(False)
        self.arrange()

    def set_instrument_side(self,side):
        self.instrument_side=side;self.arrange()

    def set_subject(self,name,summary="",category="3D models",count=None):
        self.subject.setText(name);self.summary.setText(summary);self.breadcrumb.clear();self.breadcrumb.hide()
        self.arrange()

    def set_selection(self,title,description=""):
        changed=title!=self.selection_title.text()
        self.selection_title.setText(title);self.selection_description.setText(description)
        if self._reference_mode:
            if changed:self.selection_expand.setChecked(False)
            self.selection_expand.setVisible(bool(description))
            self.selection_description.setVisible(self.selection_expand.isChecked())
        show=bool(title) and not self._practice and not self._lesson_mode and (
            self._reference_mode or not self._annotation_mode)
        if show and self.width()<820:
            self.function.setChecked(False)
            for key in self.cards:self.tools[key].setChecked(False)
        self.selection.setVisible(show);self.arrange()

    def set_practice(self,on):
        self._practice=on;self.tools['parts'].setEnabled(not on);self.labels.setEnabled(not on)
        if on:self.show_card('parts',False);self.selection.hide()
        else:self.show_card('parts',not self.parts.isHidden())

    def eventFilter(self,obj,event):
        if self._lesson_mode:
            return super().eventFilter(obj,event)
        if event.type() in (QEvent.Show,QEvent.Hide,QEvent.ShowToParent,QEvent.HideToParent,QEvent.LayoutRequest):
            if obj is self.parts and hasattr(self,'tools') and 'parts' in self.tools and not getattr(self,'_changing_card',False):
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
            if self.width()<820 and (not self.selection.isHidden() or not self.teaching.isHidden()):
                for key in self.cards:self.tools[key].setChecked(False)
                if not self.selection.isHidden():self.function.setChecked(False)
            visible=[key for key,card in self.cards.items() if not card.isHidden()]
            keep=self._active if self._active in visible else (visible[0] if visible else None)
            for key in visible:
                if key!=keep:self.show_card(key,False)
        self.arrange()

    def arrange(self):
        if self._laying_out or not hasattr(self,'dock'):return
        self._laying_out=True
        try:
            self._arrange_annotation_instruments()
            w,h=self.width(),self.height()
            self.viewport.setGeometry(self.rect());self.viewport.lower()
            self.wall_fade.setGeometry(self.rect());self.wall_fade.raise_()
            if self._lesson_mode:
                self.wall_fade.hide()
                self.viewport.label_stage_insets=(16,24,16,24)
                self.viewport.label_caption_zones={}
                for widget in [self.breadcrumb,self.subject,self.summary,self.status,self.dock,
                               self.stored_views,self.selection,self.teaching,*self.cards.values()]:widget.hide()
            elif self._reference_mode:
                self.wall_fade.show()
                for widget in [self.breadcrumb,self.subject,self.summary,self.status,self.stored_views,
                               self.teaching,*self.cards.values()]:widget.hide()
                for button in self.tools.values():self.dock_layout.removeWidget(button)
                for column,key in enumerate(('labels','show_all','reset')):
                    self.dock_layout.addWidget(self.tools[key],0,column)
                self.dock_layout.invalidate();self.dock_layout.activate()
                dock_w=min(self.dock.sizeHint().width(),max(1,w-32))
                self.dock.setGeometry((w-dock_w)//2,max(0,h-60),dock_w,44)
                width=min(460,max(120,w-56));text_width=max(80,width-10);text_height=0
                for label in (self.selection_title,self.selection_description):
                    label.setFixedWidth(text_width);label.setAlignment(Qt.AlignTop|Qt.AlignLeft)
                    document=QTextDocument();document.setDocumentMargin(0);document.setDefaultFont(label.font())
                    document.setPlainText(label.text());document.setTextWidth(text_width)
                    height=ceil(document.size().height())+4 if label.text() and not label.isHidden() else 0
                    label.setFixedHeight(height);text_height+=height
                if not self.selection_expand.isHidden():text_height+=self.selection_expand.sizeHint().height()+6
                self.selection_text.setFixedHeight(text_height+12)
                self.selection_actions.setMaximumWidth(width)
                available=max(80,self.dock.y()-132)
                desired=text_height+self.selection_actions.sizeHint().height()+32
                selection_h=min(desired,available)
                self.selection.setGeometry(28,max(112,self.dock.y()-selection_h-20),width,selection_h)
                bottom=h-self.dock.y()+100
                if not self.selection.isHidden():bottom=max(bottom,h-self.selection.y()+100)
                self.wall_fade.set_zones((0,0,0,bottom))
                self.viewport.label_stage_insets=(20,104,20,84)
                self.viewport.label_caption_zones={}
                self.selection.raise_();self.dock.raise_()
            else:
                self.wall_fade.show()
                margin=40 if w>=1300 else 28
                top=232 if h>=930 else 212
                compact=w<820
                side=min(320,max(240,int(w*.26)))
                right=w-margin-side
                self.subject.setGeometry(margin,104,max(1,w-margin*2),62)
                self.summary.setGeometry(margin,167,max(1,w-margin*2),40)
                self.status.hide();self.breadcrumb.hide()
                order=['section_menu','xray','isolate','hide','measure','labels','reset','more','function']
                for button in self.tools.values():self.dock_layout.removeWidget(button)
                column=0
                for key in order:
                    button=self.tools.get(key)
                    if button is None or button.isHidden():continue
                    self.dock_layout.addWidget(button,0,column);column+=1
                self.dock_layout.invalidate();self.dock_layout.activate()
                dock_w=min(self.dock.sizeHint().width(),max(1,w-32))
                self.dock.setGeometry((w-dock_w)//2,max(0,h-60),dock_w,44)
                instrument_bottom=self.dock.y()-20
                instruments=[*self.cards.values(),self.selection,self.teaching]
                if compact and any(not widget.isHidden() for widget in instruments):
                    top+=max(80,int((instrument_bottom-top)*.48))+20
                parts=self.cards['parts']
                parts_h=max(100,self.dock.y()-top-22)
                parts.setGeometry(margin,top,side,parts_h)
                tree=self.parts.findChild(Outline)
                if tree is not None:
                    # The existing vertical stretch gives the tree all remaining
                    # space. A fixed height fed its old size back into the next
                    # resize and also imposed a library minimum on other rooms.
                    tree.setMinimumHeight(0);tree.setMaximumHeight(16777215)
                    tree.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
                reveal=self.cards['reveal'];reveal.ensurePolished();reveal.layout().invalidate()
                reveal_h=max(100,reveal.layout().heightForWidth(side) if reveal.layout().hasHeightForWidth() else reveal.layout().sizeHint().height())
                reveal_h=min(reveal_h,max(100,self.dock.y()-top-24))
                reveal_x=margin if self.instrument_side=='left' else right
                reveal_y=(parts.geometry().bottom()+16 if self.instrument_side=='left' and not parts.isHidden() else top)
                reveal.setGeometry(reveal_x,min(reveal_y,max(top,self.dock.y()-reveal_h-20)),side,reveal_h)
                # Section and selected-part prose share the right wall. Budget
                # their height together, leaving usable room for stored views.
                has_selection=not self.selection.isHidden()
                views_reserve=144 if not self.stored_views.isHidden() else 0
                selection_reserve=164 if has_selection else 0
                control_budget=max(100,instrument_bottom-top-views_reserve-selection_reserve)
                if not reveal.isHidden() and self.instrument_side!='left':
                    reveal.setGeometry(right,top,side,min(reveal_h,control_budget))
                section=self.cards['section']
                section.setGeometry(right,top,side,min(240,control_budget))
                selection_y=top
                for control in (reveal,section):
                    if not control.isHidden() and control.x()>=right-4:
                        selection_y=max(selection_y,control.geometry().bottom()+24)
                selection_h=max(80,min(330,instrument_bottom-selection_y-views_reserve))
                self.selection.setGeometry(right,selection_y,side,selection_h)
                self.selection_actions.setMaximumWidth(side)
                text_width=max(80,side-10);text_height=0
                for label in (self.selection_title,self.selection_description):
                    label.setFixedWidth(text_width);label.setAlignment(Qt.AlignTop|Qt.AlignLeft)
                    document=QTextDocument();document.setDocumentMargin(0);document.setDefaultFont(label.font())
                    document.setPlainText(label.text());document.setTextWidth(text_width)
                    height=ceil(document.size().height())+4 if label.text() else 0
                    label.setFixedHeight(height);text_height+=height
                self.selection_text.setFixedHeight(text_height+self.selection_text.layout().spacing())
                if w<1000:
                    for card in self.cards.values():
                        if not card.isHidden():card.setGeometry(margin,top,side,min(card.height(),max(100,self.dock.y()-top-20)))
                    self.selection.setGeometry(right,max(top,self.dock.y()-selection_h-16),side,selection_h)
                if not self.teaching.isHidden():
                    tw=min(360,w-56);layout=self.teaching.layout()
                    th=layout.heightForWidth(tw) if layout.hasHeightForWidth() else layout.sizeHint().height()
                    self.teaching.setGeometry(w-margin-tw,max(top,self.dock.y()-th-12),tw,th)
                views_y=top
                for widget in (reveal,self.cards['section'],self.selection,self.teaching):
                    if not widget.isHidden() and widget.x()>=right-4:
                        views_y=max(views_y,widget.geometry().bottom()+24)
                self.stored_views.setGeometry(right,views_y,side,max(80,instrument_bottom-views_y))
                if not self.stored_views.isHidden():instruments.append(self.stored_views)
                inset_left,inset_right=16,16
                compact_y=top
                for widget in instruments:
                    if widget.isHidden():continue
                    if compact:
                        reserve=104 if widget is not self.stored_views and not self.stored_views.isHidden() else 0
                        height=max(60,min(widget.height(),instrument_bottom-compact_y-reserve))
                        widget.setGeometry(margin,compact_y,max(1,w-2*margin),height)
                        compact_y=widget.geometry().bottom()+24
                    elif widget.geometry().center().x()<w/2:
                        inset_left=max(inset_left,widget.geometry().right()+25)
                    else:
                        inset_right=max(inset_right,w-widget.x()+24)
                bottom=h-self.dock.y()+100
                if compact and any(not widget.isHidden() for widget in instruments):bottom=max(bottom,h-top+80)
                caption_top=212
                for widget in instruments:
                    if not widget.isHidden() and widget.x()>=right-4:
                        caption_top=max(caption_top,widget.geometry().bottom()+24)
                self.viewport.label_caption_zones={1:(right,caption_top,side,max(1,h-80-caption_top))}
                if self._annotation_mode:
                    self.viewport.label_caption_zones[-1]=(margin,212,side,max(1,h-292))
                left_fade=max(inset_left,margin+side+24) if self._annotation_mode else inset_left
                right_fade=max(inset_right,w-right+24) if self._annotation_mode else inset_right
                self.wall_fade.set_zones((left_fade+150 if left_fade>16 else 0,260,
                                          right_fade+150 if right_fade>16 else 0,bottom))
                self.viewport.label_stage_insets=(inset_left,212,inset_right,80)
                for widget in [self.subject,self.summary,*self.cards.values(),self.teaching,
                               self.selection,self.stored_views,self.dock]:widget.raise_()
            overlay=getattr(self.viewport,'overlay',None)
            if overlay is not None:
                overlay.raise_()
                overlay.update()
            if hasattr(self,'loading_cover'):
                self.loading_cover.setGeometry(self.rect());self.loading_cover.raise_()
        finally:self._laying_out=False
