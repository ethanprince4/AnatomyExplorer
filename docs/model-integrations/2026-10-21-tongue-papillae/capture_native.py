"""Exercise the actual Windows model widget without displaying/focusing a window."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.environ['QT_QPA_PLATFORM'] = 'windows'
os.environ['AE_LOCAL_MODEL_LIBRARY'] = str(ROOT/'data/local_model_library')
os.environ['ANATOMY_PREPARED_CACHE'] = 'off'
os.environ['ANATOMY_RENDERER'] = 'opengl'
from app.__main__ import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app.viewer.catalog import load_catalog
from app.viewer.model_loading import LoadToken
from app.ui.model_view import ModelView
from app.ui import theme
from app.config import DEFAULT_SETTINGS


def main():
    app = QApplication([])
    theme.apply_theme(app)
    catalog = load_catalog()
    entry = catalog['tongue_papillae']
    model = entry.prepare_cpu(LoadToken())
    view = ModelView(entry, SimpleNamespace(micro_models=catalog,tissues={}),
        dict(DEFAULT_SETTINGS, renderer_backend='opengl'),
        prepared=SimpleNamespace(model=model, seconds=0))
    view.setAttribute(Qt.WA_DontShowOnScreen, True)
    view.setAttribute(Qt.WA_ShowWithoutActivating, True)
    view.resize(1500, 950)
    view.show()

    def settle():
        for _ in range(8):
            app.processEvents()
            view.gl_widget.repaint()
        assert view.gl_widget.isValid()
        assert view.gl_widget.renderer.frame_ok

    settle()
    assert view.grab().save(str(OUT/'native-overview.png'))
    represented = set(view.part_items)
    for ids in view.family_sids.values():
        represented.update(ids)
    assert represented == set(range(29))
    checks = []
    for file in ['lessons_course_lab08.json','lessons_digestive_upper.json']:
        for lesson in json.loads((ROOT/'data/content'/file).read_text(encoding='utf-8')):
            for index, step in enumerate(lesson['steps']):
                if step.get('micro') != 'tongue_papillae':
                    continue
                missing = view.show_lesson_parts(step['micro_focus'],view_name=step['micro_view'])
                assert not missing, (lesson['id'], index, missing)
                expected, missing = view.part_ids(step['micro_focus'])
                assert not missing
                assert set(view.state.selected) == set(expected)
                assert not any(view.state.hidden[i] for i in expected)
                settle()
                if lesson['id']=='lab08-03-tongue-papillae-taste' and index < 2:
                    assert view.grab().save(str(OUT/f'native-lesson-{index:02d}.webp'))
                checks.append(dict(lesson=lesson['id'],step=index,view=step['micro_view'],
                    selected=[model.items[i].key for i in expected],frame_ok=True))
    report = dict(platform='Windows Qt windows plugin', widget='ModelView',
        hidden_window=True, shown_on_desktop=False, focus_taken=False,
        renderer='Application QOpenGLWidget / OpenGL',
        valid_context=view.gl_widget.isValid(), frame_ok=view.gl_widget.renderer.frame_ok,
        parts_tree_indices=sorted(represented),
        native_view_names=model.camera_order,
        opening_note='The standard catalog installs its additional Full teaching model overview and cutaway.',
        lesson_checks=checks,
        limitations=['Standalone native viewer widget; no packaged build or macOS validation.'])
    (OUT/'native.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    view.close()
    view.deleteLater()
    app.processEvents()
    print(json.dumps(dict(native_frame_ok=True, tree_parts=len(represented),
                          actual_lesson_steps=len(checks))))


if __name__=='__main__':
    main()
