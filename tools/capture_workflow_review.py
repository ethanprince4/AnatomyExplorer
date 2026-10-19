"""Exercise reviewed native workflows with real GPU scenes in a hidden window."""
from pathlib import Path
import json
import os
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ['AE_LOCAL_MODEL_LIBRARY'] = str(ROOT/'data/local_model_library')
from app.__main__ import configure_qt
configure_qt()
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication
from app import config

scratch = tempfile.TemporaryDirectory(prefix='anatomy-workflow-review-')
config.USER_DIR = Path(scratch.name)/'user'
config.USER_DIR.mkdir()
config.LOG_DIR = Path(scratch.name)/'logs'
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, scratch.name)
app = QApplication([])
from app.data import Dataset
from app.main_window import MainWindow
import numpy as np

out = ROOT/'Reports/checkpoint3-alignment/workflow-review'
out.mkdir(parents=True, exist_ok=True)
errors, evidence = [], {}
def exception(kind, error, tb):
    errors.append(''.join(traceback.format_exception(kind, error, tb)))
    traceback.print_exception(kind, error, tb)
sys.excepthook = exception
win = MainWindow(Dataset(config.DATA_DIR), restore=False)
win.settings['restore_session'] = False
win.setAttribute(Qt.WA_DontShowOnScreen, True)
win.setAttribute(Qt.WA_ShowWithoutActivating, True)
win.resize(1920, 1080)
if '--interactive-review' in sys.argv:
    win.setWindowTitle('Layered Human — background review')
    win.move(-5000, 100)
win.show()
case = next(c for c in win.radiology_cases if c.id == 'mammo_normal')
baseline = None
current_model = None
reader_place = None
done = False


def reference():
    return getattr(win, '_radiology_model_view', None)


def ready_reference():
    view = reference()
    return view is not None and getattr(view, '_radiology_ready', False) and view.gl_widget.renderer.frame_ok


def save(name):
    app.processEvents()
    win.grab().save(str(out/(name+'.png')))
    view = reference() if win.center.currentWidget() is win.anatomy_tab and not win.radiology_panel.isHidden() else win.active_model_view()
    viewport = view.gl_widget if view is not None else win.viewport
    evidence[name] = {
        'window': [win.width(), win.height()], 'viewport': [viewport.x(),viewport.y(),viewport.width(),viewport.height()],
        'reader': not win.lesson_reader.isHidden(), 'atlas_wall': not win.atlas_wall.isHidden(),
        'atlas_depth': not win.atlas_depth.isHidden(), 'atlas_dock': not win.studio_tools.isHidden(),
        'labels': len(getattr(viewport,'_label_dot_rects',getattr(viewport,'_structure_label_dot_rects',[]))),
        'captions': len(getattr(viewport,'_label_rects',getattr(viewport,'_structure_label_rects',[]))),
        'frame_ok': bool(getattr(viewport.renderer,'frame_ok',False)),
    }
    print('CAPTURE', name, evidence[name], flush=True)
    if viewport is win.viewport and viewport.active_section() is not None and viewport.labels_on:
        viewport.makeCurrent()
        pixels=viewport.renderer.read_id_image(1)
        checks=[]
        if pixels is not None:
            pixels=pixels[::-1,:]
            for key,x,y in viewport._structure_labels:
                sid,caption,number=viewport._structure_label_metadata[key]
                px=min(pixels.shape[1]-1,max(0,int(x/viewport.width()*pixels.shape[1])))
                py=min(pixels.shape[0]-1,max(0,int(y/viewport.height()*pixels.shape[0])))
                checks.append({'caption':caption,'number':number,'sid':sid,'pixel_sid':int(pixels[py,px])-1})
        viewport.doneCurrent()
        evidence[name]['anchor_pixels']=checks


def check_reader():
    assert not win.lesson_reader.isHidden()
    for widget in (win.atlas_wall,win.atlas_depth,win.studio_tools,win.studio_header.subject):
        assert widget.isHidden(), 'Atlas overlay leaked into lesson: '+widget.objectName()
    assert not win.cmds.actions['peel_in'].isEnabled()


def lesson(lesson_id):
    win.show_lessons(lesson_id)
    win.viewport.set_labels_on(True)
    win.viewport.show_all_labels(True)
    check_reader()


def history_leave():
    global reader_place
    panel = win.lessons_panel
    reader_place = (('atlas', tuple(win.state.selected)), (panel.lesson.id,panel.index))
    win._show_catalog()
    win.studio_header.navigation['lessons'].click()
    assert win.lesson_reader.isHidden()
    assert win.lessons_panel.lesson is None
    assert win.center.currentWidget() is win.collection_workspace


def history_return():
    win._restore_place(reader_place)
    check_reader()


def initial_reference():
    global baseline
    view = reference()
    baseline = view.state.visible_mask().copy()
    assert baseline.any() and not baseline.all(), 'Case did not restrict its model'
    assert win.studio_tools.isHidden(), 'Duplicate atlas toolbar in model reference'
    assert view.width() > win.anatomy_tab.width()*.45, 'Reference starts squashed'
    assert len(view._radiology_labels) == 4, view._radiology_labels
    assert len(view.gl_widget._label_dot_rects) == 4, 'Missing authored scan label'
    view.gl_widget.show_all_labels(True)


def select_reference():
    for label in case.labels:
        win.on_radiology_pick(label.structures, side=label.side)
    win.on_radiology_pick(['Adipose tissue of breast'], side='Right')
    reference().studio.selection_expand.setChecked(True)


def isolate_reference():
    view = reference()
    view.state.isolate(list(view.state.selected))
    assert np.all(~view.state.visible_mask() | baseline)


def restore_reference():
    view = reference()
    view.show_all()
    assert np.array_equal(view.state.visible_mask(), baseline), 'Show all escaped the case anatomy'
    view.gl_widget.camera.distance *= .55
    view.reset_view(animate=False)
    assert np.array_equal(view.state.visible_mask(), baseline), 'Reset escaped the case anatomy'
    assert not view.state.selected
    win._show_radiology_labels(False)
    assert not view.gl_widget.labels_on
    win._show_radiology_labels(True)
    view.gl_widget.show_all_labels(True)


def load_model(model_id,all_labels=True):
    global current_model
    current_model = None
    win._show_catalog()
    def ready(view):
        global current_model
        current_model = view
        if view is not None:
            view.labels.setChecked(True)
            view.gl_widget.show_all_labels(all_labels)
    win.open_micro(model_id, on_ready=ready)


def catalogue_search(text):
    win._show_catalog()
    win.catalog.edit.setText(text)


def ready_model():
    return current_model is not None and current_model.gl_widget.renderer.frame_ok


def zoom_model():
    current_model.gl_widget.camera.distance *= .45
    current_model.gl_widget.update()
    assert current_model.gl_widget.geometry() == current_model.studio.rect(), 'Model viewport is still cropped'


def atlas():
    win._studio_explore()
    win.view_panel.set_depth(.26)
    win.viewport.set_labels_on(True)
    win.viewport.show_all_labels(True)
    assert abs(win.atlas_depth.geometry().center().y()-win.workspace.rect().center().y()) <= 1
    assert win.workspace_layout.indexOf(win.studio_header) < 0


steps = [
    ('atlas',atlas,None), ('lessons',win._studio_learn,None),
    ('vertebral-lesson',lambda:lesson('vertebral-column'),None),
    ('pectoral-lesson',lambda:lesson('pectoral-girdle'),None),
    ('lesson-library-return',history_leave,None), ('lesson-history-return',history_return,None),
    ('breast-initial',lambda:win.open_radiology(case.id),ready_reference),
    ('breast-labels',initial_reference,None), ('breast-selected',select_reference,None),
    ('breast-isolated',isolate_reference,None), ('breast-restored',restore_reference,None),
    ('models',win._show_catalog,None),
    ('pancreas-catalogue',lambda:catalogue_search('pancreas'),None),
    ('neuron-catalogue',lambda:catalogue_search('neuron'),None),
    ('cardiac',lambda:load_model('cardiac_muscle'),ready_model), ('cardiac-close',zoom_model,None),
    ('kidney',lambda:load_model('kidney_nephron'),ready_model),
    ('kidney-1280',lambda:win.resize(1280,800),None),
    ('lessons-1280',win._studio_learn,None),
]

if '--model-confirm' in sys.argv or '--final-confirm' in sys.argv:
    steps = [
        ('cardiac',lambda:load_model('cardiac_muscle'),ready_model), ('cardiac-close',zoom_model,None),
        ('kidney',lambda:load_model('kidney_nephron'),ready_model),
        ('kidney-1280',lambda:win.resize(1280,800),None),
    ]
    if '--final-confirm' in sys.argv:
        steps = [
            ('pancreas-catalogue',lambda:catalogue_search('pancreas'),None),
            ('neuron-catalogue',lambda:catalogue_search('neuron'),None),
            ('lesson-default-labels',lambda:default_lesson(),None),
        ] + steps

if '--compact-confirm' in sys.argv:
    steps = [
        ('kidney',lambda:load_model('kidney_nephron'),ready_model),
        ('kidney-1280',lambda:win.resize(1280,800),None),
    ]

if '--menu-audit' in sys.argv:
    out = ROOT/'Reports/checkpoint3-alignment/menu-audit'
    out.mkdir(parents=True, exist_ok=True)
    samples = []
    def sample_layout():
        grid = win.lessons_panel.unit_grid
        samples.append((grid.width(),grid.viewport().width(),grid.viewport().height(),
                        grid.gridSize().width(),grid.gridSize().height(),
                        grid.verticalScrollBar().maximum(),
                        tuple((grid.visualItemRect(grid.item(i)).x(),grid.visualItemRect(grid.item(i)).y())
                              for i in range(min(4,grid.count())))))
    sampler=QTimer(win);sampler.setInterval(30);sampler.timeout.connect(sample_layout)
    def sample_start():
        samples.clear();win._studio_learn();sampler.start()
    def sample_end():
        sampler.stop();print('LAYOUT_SAMPLES',len(samples),'UNIQUE',len(set(samples)),list(dict.fromkeys(samples)),flush=True)
    def ct_case():
        target=next(c for c in win.radiology_cases if 'liver and spleen' in c.title.lower())
        print('CASE',target.id,flush=True);win.open_radiology(target.id)
    def ct_labels():
        win.viewport.show_all_labels(True)
        print('SECTION',win.viewport.active_section(),'ANCHORS',
              [(str(a[0]),win.ds.structures[a[0]]['name'],list(map(float,a[1]))) for a in win.viewport.section_anchors],flush=True)
    def pharynx():
        target=next(l for l in win.lessons_panel.lessons if 'pharynx and larynx' in l.title.lower())
        win.show_lessons(target.id);win.viewport.show_all_labels(True)
    def histology():
        target=next(t for t in win.content.histology['tissues'] if 'simple cuboidal' in t['name'].lower())
        win.open_histology(target['id'])
    steps=[('lessons-motion',sample_start,None),('lessons-settled',sample_end,None),
           ('ct-abdomen',ct_case,None),('ct-labels',ct_labels,None),('pharynx',pharynx,None),
           ('ear',lambda:load_model('ear'),ready_model),('histology-slide',histology,None)]

if '--broad-review' in sys.argv:
    out=ROOT/'Reports/checkpoint3-alignment/broad-review'
    out.mkdir(parents=True,exist_ok=True)
    def atlas_large():
        win.resize(2560,1424);atlas()
    def stored_view():
        tiles=current_model.studio.view_tiles
        list(tiles.values())[1].click()
    def labels_on():current_model.gl_widget.show_all_labels(True)
    def ct_case():win.open_radiology('ct_abdo_kidney')
    def ct_labels():win.viewport.show_all_labels(True)
    def histology():
        target=next(t for t in win.content.histology['tissues'] if 'simple cuboidal' in t['name'].lower())
        win.open_histology(target['id'])
    steps=[
        ('lessons',win._studio_learn,None),
        ('pharynx',lambda:lesson('lab06-02-pharynx-larynx'),None),
        ('lesson-library-return',history_leave,None),('lesson-history-return',history_return,None),
        ('pectoral',lambda:lesson('pectoral-girdle'),None),
        ('ct-initial',ct_case,None),('ct-labels',ct_labels,None),
        ('breast-initial',lambda:win.open_radiology(case.id),ready_reference),
        ('breast-labels',initial_reference,None),('breast-selected',select_reference,None),
        ('breast-isolated',isolate_reference,None),('breast-restored',restore_reference,None),
        ('jejunum-catalogue',lambda:catalogue_search('jejunum'),None),
        ('duodenum-catalogue',lambda:catalogue_search('duodenum'),None),
        ('colon-catalogue',lambda:catalogue_search('colon wall'),None),
        ('ear-controls',lambda:load_model('ear',False),ready_model),
        ('ear-stored-view',stored_view,None),('ear-labels',labels_on,None),
        ('kidney-controls',lambda:load_model('kidney_nephron',False),ready_model),
        ('kidney-labels',labels_on,None),
        ('kidney-1280',lambda:win.resize(1280,800),None),
        ('cardiac-controls',lambda:(win.resize(1920,1080),load_model('cardiac_muscle',False)),ready_model),
        ('histology-slide',histology,None),
        ('atlas-large',atlas_large,None),
    ]
    if '--label-confirm' in sys.argv:
        out=ROOT/'Reports/checkpoint3-alignment/label-confirm';out.mkdir(parents=True,exist_ok=True)
        steps=[('pharynx',lambda:lesson('lab06-02-pharynx-larynx'),None),
               ('pectoral',lambda:lesson('pectoral-girdle'),None),
               ('ct-initial',ct_case,None),('ct-labels',ct_labels,None)]


def default_lesson():
    win.viewport.set_labels_on(False)
    win.show_lessons('vertebral-column')
    check_reader()
    assert win.viewport.labels_on, 'Authored lesson labels depend on Atlas preference'
    assert not win.settings['show_structure_labels'], 'Lesson changed Atlas label preference'


def finish():
    global done
    if done:return
    done = True
    result = {'errors':errors,'screens':evidence,'remaining':[step[0] for step in steps], 'gl':win.viewport.gl_info}
    report = ('compact-confirm.json' if '--compact-confirm' in sys.argv else
              'final-confirm.json' if '--final-confirm' in sys.argv else
              'model-confirm.json' if '--model-confirm' in sys.argv else 'capture.json')
    (out/report).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    win.close()
    QTimer.singleShot(500,app.quit)


def next_step():
    if errors or not steps:
        finish();return
    name, action, ready = steps.pop(0)
    started = time.monotonic()
    def settled():
        try:
            if ready is not None and not ready():
                if time.monotonic()-started > 45:raise RuntimeError('Timed out: '+name)
                QTimer.singleShot(200,settled);return
            def capture():
                try:
                    save(name)
                    next_step()
                except BaseException:
                    exception(*sys.exc_info());finish()
            QTimer.singleShot(1400,capture)
        except BaseException:
            exception(*sys.exc_info());finish()
    try:
        action()
        QTimer.singleShot(500,settled)
    except BaseException:
        exception(*sys.exc_info());finish()


if '--interactive-review' in sys.argv:
    out=ROOT/'Reports/checkpoint3-alignment/background-review'
    out.mkdir(parents=True,exist_ok=True)
    command_file=out/'command.json'
    command_seen=None
    def poll_command():
        global command_seen
        if not command_file.exists():return
        raw=command_file.read_text(encoding='utf-8-sig')
        if raw==command_seen:return
        command_seen=raw
        try:
            command=json.loads(raw)
            action=command['action']
            if action=='lessons':win.studio_header.navigation['lessons'].click()
            elif action=='lesson':win.show_lessons(command['id'])
            elif action=='radiology':win.open_radiology(command['id'])
            elif action=='model':load_model(command['id'])
            elif action=='catalogue':catalogue_search(command.get('query',''))
            elif action=='histology':win.open_histology(command['id'])
            elif action=='atlas':win._studio_explore()
            elif action=='resize':win.resize(*command['size'])
            elif action=='labels':
                view=win.active_model_view();vp=view.gl_widget if view else win.viewport
                vp.set_labels_on(True);vp.show_all_labels(command.get('all',True))
            elif action=='sample-lessons':
                win.studio_header.navigation['lessons'].click()
                win.resize(*command['size'])
                samples=[]
                def sample():
                    grid=win.lessons_panel.unit_grid
                    samples.append((grid.width(),grid.viewport().width(),grid.viewport().height(),
                        grid.gridSize().width(),grid.gridSize().height(),grid.verticalScrollBar().maximum(),
                        grid.verticalScrollBar().value(),tuple((grid.visualItemRect(grid.item(i)).x(),grid.visualItemRect(grid.item(i)).y()) for i in range(grid.count()))))
                    if len(samples)<80:QTimer.singleShot(30,sample)
                    else:
                        result={'size':[win.width(),win.height()],'samples':len(samples),'settled_layouts':len(set(samples[15:])), 'layouts':list(dict.fromkeys(samples[15:]))}
                        (out/('motion-'+str(win.width())+'.json')).write_text(json.dumps(result,indent=2))
                        print('LESSON_MOTION',result,flush=True);save('lessons-'+str(win.width()))
                QTimer.singleShot(250,sample)
            elif action=='inspect-labels':
                vp=win.viewport
                vp.makeCurrent()
                ids=vp.renderer.read_id_image(1)[::-1,:]
                rows=[]
                for key,x,y in vp._structure_labels:
                    sid,caption,number=vp._structure_label_metadata[key]
                    px=min(ids.shape[1]-1,max(0,int(x/vp.width()*ids.shape[1])))
                    py=min(ids.shape[0]-1,max(0,int(y/vp.height()*ids.shape[0])))
                    hit=int(ids[py,px])-1
                    rows.append({'caption':caption,'number':number,'sid':sid,'pixel_sid':hit,'matches':sid==hit})
                vp.doneCurrent()
                (out/(command['name']+'.json')).write_text(json.dumps(rows,indent=2))
                print('LABEL_PIXELS',rows,flush=True)
            elif action=='capture':save(command['name'])
            elif action=='stop':win.close();app.quit()
            else:raise ValueError(action)
            print('COMMAND',command,flush=True)
        except BaseException:exception(*sys.exc_info())
    poller=QTimer(win);poller.setInterval(250);poller.timeout.connect(poll_command);poller.start()
    steps=[]
    print('BACKGROUND_REVIEW_READY',flush=True)
else:
    QTimer.singleShot(6000,next_step)
    QTimer.singleShot(210000,lambda:(errors.append('Workflow capture timed out'),finish()))
app.exec()
sys.exit(1 if errors or steps else 0)
