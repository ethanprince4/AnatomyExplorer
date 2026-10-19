"""Regressions for the approved ruler and On the body search interaction."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
from app.ui import theme
from app.ui.depth_gauge import DepthGauge
from app.ui.view_panel import DISSECTION_STOPS
from app.ui.search_panel import SearchPanel, ROLE_ENTRY
from app.ui.wall_search import fold, MoreResults, ROLE_RANK
from app.search import SearchEntry
from app.viewport import Viewport

APP=QApplication.instance() or QApplication([])

class PaintGauge(DepthGauge):
    def paintEvent(self,event):
        self.last_region=event.region().boundingRect()
        super().paintEvent(event)

class SearchViewport(QWidget):
    frameTimed=Signal(float)
    searchMarkerHovered=Signal(int)
    on_body_search_markers=[]
    def set_search_active(self,rank,target=None):self.active=(rank,target)

class CheckpointControls(unittest.TestCase):
    def setUp(self):
        theme.apply_theme(APP,scale=1.0)
        self.widgets=[]
    def keep(self,w):self.widgets.append(w);return w
    def tearDown(self):
        for w in self.widgets:w.close();w.deleteLater()
        APP.processEvents()

    def test_ruler_repaints_old_handle_and_programmatic_layer_position(self):
        gauge=self.keep(PaintGauge(DISSECTION_STOPS));gauge.resize(310,800);gauge.show()
        APP.processEvents();gauge.setFocus();QTest.keyClick(gauge,Qt.Key_BracketRight)
        self.assertEqual(gauge.value(),80)
        gauge.setValue(260);APP.processEvents()
        old_y=gauge.only_layer.y()
        gauge.blockSignals(True);gauge.setValue(400);gauge.blockSignals(False);APP.processEvents()
        self.assertGreater(gauge.only_layer.y(),old_y)
        self.assertTrue(gauge.last_region.contains(QPoint(round(gauge._rule()[0]),round(gauge._point_y(.26)))))
        self.assertTrue(gauge.last_region.contains(QPoint(round(gauge._rule()[0]),round(gauge._point_y(.40)))))
        changes=[];gauge.onlyLayerToggled.connect(changes.append)
        gauge.only_layer.click();self.assertEqual(changes,[True])
        gauge.set_only_layer(False);self.assertEqual(changes,[True])
        QTest.keyClick(gauge,Qt.Key_End);self.assertEqual(gauge.value(),1000)

    def test_wall_search_retains_stable_rows_and_opens_more_without_activation(self):
        entries=[SearchEntry('structure',f'Muscle {i}','Muscular system',[i],alt=f'Musculus {i}') for i in range(12)]
        ds=SimpleNamespace(n=12,nodes={},structures=[{'base':e.title} for e in entries])
        index=SimpleNamespace(entries=entries,search=Mock(return_value=entries))
        viewport=self.keep(SearchViewport())
        panel=self.keep(SearchPanel(ds,index));panel.set_wall_mode(viewport);panel.resize(580,700);panel.show()
        opened=[];panel.activated.connect(opened.append)
        panel.edit.setText('muscle');panel._timer.stop();panel._run();APP.processEvents()
        stable=[panel.list.item(i) for i in range(panel.list.count())]
        more=next(panel.list.item(i) for i in range(panel.shown) if isinstance(panel.list.item(i).data(ROLE_ENTRY),MoreResults))
        panel._activate_item(more)
        self.assertEqual(opened,[]);self.assertEqual(panel.shown,12)
        self.assertTrue(all(panel.list.item(i) is item for i,item in enumerate(stable)))
        panel._activate_item(panel.list.item(2));self.assertEqual(opened,[entries[2]])
        self.assertEqual(panel.list.item(2).data(ROLE_RANK),3)
        panel.edit.clear();self.assertEqual(panel.shown,0)

    def test_body_search_samples_real_bounds_and_keeps_display_rank_for_hidden_results(self):
        fake=SimpleNamespace()
        fake.ds=SimpleNamespace(n=2,nodes={},centroid=np.array([[0,0,0],[0,0,0]]),
            bbox_min=np.array([[-.5,-.5,0],[-.5,-.5,0]]),bbox_max=np.array([[.5,.5,0],[.5,.5,0]]),
            structures=[{'name':'Hidden'},{'name':'Visible'}])
        fake.state=SimpleNamespace(visible_mask=lambda:np.array([False,True]))
        samples=[]
        def pick(points):samples.extend(points);return [1 for _ in points]
        fake.renderer=SimpleNamespace(frame_ok=True,last_vp=np.eye(4),size=(800,600),pick_many=pick)
        fake.width=lambda:800;fake.height=lambda:600
        fake._gl_xy=lambda p:(p.x(),p.y())
        fake._on_body_search_entries=[SearchEntry('structure','Hidden','',[0]),SearchEntry('structure','Visible','',[1])]
        fake._on_body_search_key=None
        Viewport._update_on_body_search(fake)
        self.assertGreater(len(set(x for x,y in samples)),1)
        self.assertGreater(len(set(y for x,y in samples)),1)
        self.assertTrue(fake.on_body_search_markers)
        self.assertEqual(fake.on_body_search_markers[0][0],2)

    def test_attachment_group_folds_into_actual_muscle_without_mutating_index(self):
        muscle=SearchEntry('group','Biceps brachii muscle','4 parts',None,'muscular',node='m')
        attachment=SearchEntry('group','Biceps brachii muscle','2 attachments',None,'attachments',node='a')
        part=SearchEntry('structure','Long head of biceps brachii','Muscle',[0],'muscular')
        ds=SimpleNamespace(nodes={'m':{},'a':{}},node_structures=lambda n:[0,1] if n=='m' else [2],
                           structures=[{'base':'Long head of biceps brachii'},{'base':'Short head of biceps brachii'},{'base':'Biceps brachii muscle'}])
        self.assertEqual(fold([muscle,attachment,part],ds),[muscle])
        self.assertEqual(attachment.node,'a')

if __name__=='__main__':unittest.main()
