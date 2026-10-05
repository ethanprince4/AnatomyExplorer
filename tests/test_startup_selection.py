import json
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from app.main_window import MainWindow

class StartupSelectionTests(unittest.TestCase):
    def test_session_drops_only_transient_selection(self):
        original={'camera':[[0,1,0],2,0,0], 'selected':list(range(29)),
                  'hidden':[40,41], 'systems':[True,False], 'clips':[[False,True,False],[0,1,0],[False]*3]}
        settings=Mock();settings.value.return_value=json.dumps(original)
        host=SimpleNamespace(qsettings=settings,apply_view=Mock(),right_dock=Mock())
        MainWindow.restore_session(host)
        restored=host.apply_view.call_args.args[0]
        self.assertEqual(restored,dict(original,selected=[]))
        self.assertEqual(host.apply_view.call_args.kwargs,{'animate':False})
        host.right_dock.hide.assert_called_once()
        settings.setValue.assert_not_called()
    def test_empty_or_invalid_session_does_not_change_scene(self):
        for payload in ['null','[]','broken']:
            settings=Mock();settings.value.return_value=payload
            host=SimpleNamespace(qsettings=settings,apply_view=Mock(),right_dock=Mock())
            MainWindow.restore_session(host)
            host.apply_view.assert_not_called()

if __name__=='__main__':unittest.main()
