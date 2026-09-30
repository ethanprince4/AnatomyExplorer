"""Loaded Qt frameworks must be distinguished from PySide binding extensions."""
from pathlib import Path
import runpy
import unittest

IDENTIFY = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                            'packaging/diagnostics/mac_ax/runtime_binary.py'))['qt_framework_name']


class RuntimeIdentityTests(unittest.TestCase):
    def test_actual_framework_is_identified(self):
        for name in ('QtCore', 'QtGui', 'QtWidgets', 'QtDBus'):
            self.assertEqual(IDENTIFY(f'/wheel/PySide6/Qt/lib/{name}.framework/Versions/A/{name}'), name)
        self.assertEqual(IDENTIFY('/foreign/QtGui.framework/Versions/A/QtGui'), 'QtGui')
        self.assertEqual(IDENTIFY('/app/Contents/Frameworks/QtWidgets.framework/Versions/A/QtWidgets'), 'QtWidgets')

    def test_python_framework_parent_does_not_classify_bindings_as_qt(self):
        for name in ('QtCore', 'QtGui', 'QtWidgets'):
            path = f'/Python.framework/Versions/3.11/lib/site-packages/PySide6/{name}.abi3.so'
            self.assertIsNone(IDENTIFY(path))

    def test_foreign_framework_or_extra_qt_named_file_is_rejected(self):
        self.assertIsNone(IDENTIFY('/Python.framework/Versions/A/QtCore'))
        self.assertIsNone(IDENTIFY('/QtCore.framework/Versions/A/QtCore.abi3.so'))
        self.assertIsNone(IDENTIFY('/ordinary/QtGui.so'))

    def test_actual_framework_nested_in_python_framework_still_identifies(self):
        self.assertEqual(IDENTIFY('/Python.framework/lib/PySide6/Qt/lib/QtGui.framework/Versions/A/QtGui'),
                         'QtGui')
