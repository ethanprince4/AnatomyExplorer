"""Systems and the selected specimen's wall label, from checkpoint three."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget, QScrollArea)
from . import theme


class AtlasWall(QScrollArea):
    def __init__(self, window):
        super().__init__(window.workspace)
        self.owner = window
        self.setObjectName('atlasWall')
        self.setFrameShape(QScrollArea.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.setWidget(self.body)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet(
            f'QWidget#atlasWall, QWidget#atlasWall QWidget {{background:transparent;}}'
            f'QWidget#atlasWall QLabel, QWidget#atlasWall QCheckBox {{border:0;'
            f'color:{theme.TEXT_2};font-family:"{theme.font_family()}";font-size:14px;}}'
            f'QWidget#atlasWall QCheckBox {{spacing:10px;}}'
            f'QWidget#atlasWall QCheckBox::indicator {{width:13px;height:13px;border-radius:0;}}'
            f'QWidget#atlasWall QPushButton {{background:transparent;color:{theme.TEXT_2};'
            f'font-family:"{theme.font_family()}";font-size:14px;border:0;outline:0;text-align:left;padding:5px 0;}}'
            f'QWidget#atlasWall QPushButton:hover {{color:{theme.TEXT};border-bottom:1px solid {theme.ACCENT};}}'
            f'QWidget#atlasWall QPushButton:focus {{border-bottom:1px solid {theme.ACCENT};}}'
            f'QWidget#atlasWall QPushButton[wallAction="true"] {{border:1px solid {theme.BORDER_STRONG};'
            f'padding:8px 12px;text-align:center;}}')
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.systems = QWidget()
        systems = QVBoxLayout(self.systems)
        systems.setContentsMargins(0, 0, 0, 0)
        systems.setSpacing(0)
        heading = QLabel('Systems')
        heading.setStyleSheet('font-weight:500;padding-bottom:14px;')
        systems.addWidget(heading)
        counts = np.bincount(window.ds.system_of, minlength=len(window.ds.systems))
        self.checks = []
        self.system_rows = []
        order = {'regions':0,'fascia':1,'muscular':2,'skeletal':3,'joints':4,
                 'cardiovascular':5,'lymphatic':6,'nervous':7,'visceral':8}
        for index, system in sorted(enumerate(window.ds.systems), key=lambda pair:order.get(pair[1]['key'],9)):
            if system['key'] in ('attachments', 'reference'):
                continue
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0,0,0,0)
            row.setSpacing(8)
            label = {'regions':'Surface landmarks', 'nervous':'Nervous system'}.get(system['key'],system['name'])
            check = QCheckBox(label.replace('&','&&'))
            check.setAccessibleName('Show '+label)
            check.toggled.connect(lambda on,i=index:window.state.set_system(i,on))
            row.addWidget(check,1)
            count = QLabel(str(int(counts[index])))
            count.setStyleSheet(f'color:{theme.MUTED};font-size:13px;')
            count.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
            row.addWidget(count)
            systems.addWidget(row_widget)
            self.system_rows.append(row_widget)
            self.checks.append((index,check))
        systems.addSpacing(24)
        quick = QLabel('Quick views')
        quick.setStyleSheet('font-weight:500;padding-bottom:10px;')
        systems.addWidget(quick)
        from .systems_panel import PRESETS
        presets = [(name,keys) for name,keys in PRESETS if name not in ('Attachments','Surface')]
        for start in (0,3):
            row = QHBoxLayout()
            row.setSpacing(20)
            for name,keys in presets[start:start+3]:
                button = QPushButton(name)
                button.clicked.connect(lambda _=False,k=keys:window.systems._preset(k))
                row.addWidget(button,1)
            systems.addLayout(row)
        layout.addWidget(self.systems,0,Qt.AlignLeft)
        layout.addStretch(1)
        self.selection = QWidget()
        selected = QVBoxLayout(self.selection)
        selected.setContentsMargins(0,22,0,0)
        selected.setSpacing(0)
        self.name = QLabel()
        self.name.setWordWrap(True)
        self.name.setStyleSheet(f'font-family:"{theme.display_font_family()}";font-size:32px;color:{theme.TEXT};')
        self.latin = QLabel()
        self.latin.setWordWrap(True)
        self.latin.setStyleSheet(f'font-family:"{theme.display_font_family()}";font-size:18px;font-style:italic;')
        selected.addWidget(self.name)
        selected.addWidget(self.latin)
        self.facts = QWidget()
        self.facts.setStyleSheet(f'QWidget#atlasFacts {{border-top:1px solid {theme.BORDER};}}')
        self.facts.setObjectName('atlasFacts')
        grid = QGridLayout(self.facts)
        grid.setContentsMargins(0,14,0,0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0,76)
        grid.setColumnStretch(1,1)
        self.fact_rows=[]
        for i,label in enumerate(('Nerve','Action','Blood','Attaches')):
            key,value=QLabel(label),QLabel()
            key.setStyleSheet(f'color:{theme.MUTED};')
            value.setWordWrap(True)
            grid.addWidget(key,i,0,Qt.AlignTop)
            grid.addWidget(value,i,1)
            self.fact_rows.append((key,value))
        selected.addSpacing(14)
        selected.addWidget(self.facts)
        self.meta=QLabel()
        self.meta.setWordWrap(True)
        self.meta.setStyleSheet(f'color:{theme.MUTED};font-size:13px;padding:14px 0 16px;')
        selected.addWidget(self.meta)
        actions=QHBoxLayout()
        actions.setSpacing(8)
        for title,key in (('Isolate','isolate'),('Hide','hide'),('X-ray','xray')):
            action=window.cmds.actions.get(key)
            if action is not None:
                button=QPushButton(title)
                button.setProperty('wallAction',True)
                button.clicked.connect(lambda _=False,a=action:a.trigger())
                actions.addWidget(button)
        more=QPushButton('Full entry  ›')
        more.setProperty('wallAction',True)
        more.clicked.connect(window.right_dock.show)
        actions.addWidget(more)
        actions.addStretch(1)
        selected.addLayout(actions)
        layout.addWidget(self.selection)
        window.state.visibility_changed.connect(self.sync)
        window.state.selection_changed.connect(self.sync)
        self.sync()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.systems.setFixedWidth(min(self.width(),270))
        for row in self.system_rows:
            row.setFixedHeight(30 if self.height()>=720 else 25)

    @staticmethod
    def _text(value):
        if isinstance(value,(list,tuple)):
            return ' · '.join(map(str,value))
        return str(value or '')

    def sync(self):
        window=self.owner
        for index,check in self.checks:
            blocked=check.blockSignals(True)
            check.setChecked(bool(window.state.system_on[index]))
            check.blockSignals(blocked)
        chosen=sorted(window.state.selected)
        self.selection.setVisible(bool(chosen))
        if not chosen:return
        structure=window.ds.structures[int(chosen[0])]
        single=len(chosen)==1
        self.name.setText(structure['base'] if single else f'{len(chosen)} selected structures')
        self.latin.setText(self._text(structure.get('latin')) if single else '')
        values=[structure.get('innervation'),structure.get('action'),structure.get('blood_supply'),
                structure.get('attachment') or structure.get('attachments')]
        for (key,label),value in zip(self.fact_rows,values):
            text=self._text(value) if single else ''
            key.setVisible(bool(text));label.setVisible(bool(text));label.setText(text)
        self.facts.setVisible(single and any(values))
        metadata=[]
        if single:
            if structure.get('ta2'):metadata.append('TA2 '+self._text(structure['ta2']))
            metadata.extend(self._text(structure.get(key)) for key in ('side','subsystem') if structure.get(key))
        else:metadata.append('Use Full entry to inspect the selected structures')
        self.meta.setText(' · '.join(metadata))
