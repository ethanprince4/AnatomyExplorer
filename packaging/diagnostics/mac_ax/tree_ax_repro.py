"""Synthetic Qt tree/accessibility diagnostic. No anatomy data, GL or app imports."""
import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

import PySide6
from PySide6.QtCore import QLibraryInfo, QTimer, Qt, qVersion
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QTextBrowser, QTreeWidget,
                              QTreeWidgetItem, QVBoxLayout, QWidget)


class Repro(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.started = time.monotonic()
        self.sequence = 0
        self.log = args.report.open('w', encoding='utf-8') if args.report else None
        self.items = []
        self.setWindowTitle('Qt Cocoa tree accessibility diagnostic')
        self.resize(760, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Synthetic tree. Click a leaf in either text column. Native probe can crash this diagnostic.'))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Synthetic filter')
        self.filter.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setAccessibleName('Synthetic diagnostic tree')
        self.tree.setObjectName('mac_ax_diagnostic_tree')
        self.tree.setColumnCount(args.columns)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setIndentation(14)
        layout.addWidget(self.tree)
        self.details = QTextBrowser()
        self.details.setMaximumHeight(100)
        layout.addWidget(self.details)
        controls = QHBoxLayout()
        for text, action in (('No selection', self.clear_selection), ('Select leaf', self.select_leaf),
                             ('Expand', self.tree.expandAll), ('Collapse', self.tree.collapseAll),
                             ('Filter leaf', lambda:self.filter.setText('Leaf 1')),
                             ('Clear filter', lambda:self.filter.setText('')),
                             ('Reset items', self.reset_items), ('Probe', lambda:self.probe('manual'))):
            button = QPushButton(text)
            button.clicked.connect(action)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.build()
        self.tree.itemClicked.connect(self.clicked)
        self.tree.itemSelectionChanged.connect(lambda:self.emit('selection', qt_selected_count=len(self.tree.selectedItems())))
        self.native = None
        if args.native_probe:
            from mac_native_probe import NativeProbe
            self.native = NativeProbe(self, self.tree, self.emit, args.probe_order)
        self.emit('environment', python=platform.python_version(), pyside=PySide6.__version__,
                  qt=qVersion(), qt_library_version=QLibraryInfo.version().toString(),
                  platform=platform.system(), os_release=platform.release(), machine=platform.machine(),
                  qpa=QApplication.platformName(), columns=args.columns, mode=args.mode,
                  native_probe=args.native_probe, probe_order=args.probe_order,
                  qt_mouse_simulation=args.auto)
        if sys.platform == 'darwin':
            from runtime_binary import loaded_qcocoa_identity
            self.emit('loaded_qcocoa', **loaded_qcocoa_identity())
            if os.environ.get('QT_OWNERSHIP_PLUGIN_SHA256'):
                from runtime_binary import ownership_runtime_identity
                self.emit('ownership_runtime', **ownership_runtime_identity())

    def emit(self, event, **fields):
        self.sequence += 1
        row = {'seq':self.sequence, 'elapsed_ms':round((time.monotonic()-self.started)*1000),
               'event':event, **fields}
        line = json.dumps(row, separators=(',', ':'))
        print(line, flush=True)
        if self.log:
            self.log.write(line+'\n')
            self.log.flush()

    def build(self):
        for group_number in range(3):
            group = QTreeWidgetItem(self.tree, [f'Group {group_number}', '4'][:self.args.columns])
            group.setFlags(group.flags() | Qt.ItemIsUserCheckable)
            group.setCheckState(0, Qt.Checked)
            self.items.append(group)
            for leaf_number in range(4):
                leaf = QTreeWidgetItem(group, [f'Leaf {leaf_number} in group {group_number}', ''][:self.args.columns])
                leaf.setFlags(leaf.flags() | Qt.ItemIsUserCheckable)
                leaf.setCheckState(0, Qt.Checked)
                self.items.append(leaf)

    def clicked(self, item, column):
        self.emit('item_clicked', column=column, leaf=item.childCount()==0)
        self.on_selection(item)
        if self.args.probe_on_click:
            self.probe('inside-click-slot')
        QTimer.singleShot(0, lambda:self.probe('after-click-event')) if self.args.native_probe else None

    def on_selection(self, item):
        # Reproduce only the retained-item selection follow-up operations.
        # No reset/deletion occurs in this ordinary click path.
        if self.args.mode in ('reveal', 'combined'):
            blocked = self.tree.blockSignals(True)
            try:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
            finally:
                self.tree.blockSignals(blocked)
        if self.args.mode in ('details', 'combined'):
            self.details.setHtml('<h3>Synthetic details</h3><p>Selection refresh diagnostic.</p>')

    def clear_selection(self):
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self.emit('phase', name='no-selection')

    def select_leaf(self):
        self.tree.expandAll()
        self.tree.setCurrentItem(self.items[1])
        self.on_selection(self.items[1])
        self.emit('phase', name='selected-row')

    def apply_filter(self, text):
        term = text.casefold().strip()
        self.tree.setUpdatesEnabled(False)
        try:
            for i in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(i)
                any_visible = False
                for j in range(group.childCount()):
                    child = group.child(j)
                    visible = not term or term in child.text(0).casefold()
                    child.setHidden(not visible)
                    any_visible |= visible
                group.setHidden(not any_visible)
                if term and any_visible:
                    group.setExpanded(True)
            if not term:
                self.tree.collapseAll()
        finally:
            self.tree.setUpdatesEnabled(True)
        self.emit('phase', name='filter' if term else 'clear-filter')

    def single_branches(self):
        # v4.0.4 aborted here on macOS: with cell interfaces cached by an accessibility client, opening ONE branch
        # (QTreeViewPrivate::expand, the path of a click on a branch arrow; expandAll takes a different one) made
        # Qt describe a cell it was deleting, whose row is -1, and the Cocoa element indexed its rows with it.
        self.tree.collapseAll()
        self.probe('before-single-branches')
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(True)
            self.probe(f'after-opening-group-{i}')
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(False)
            self.probe(f'after-closing-group-{i}')
        self.emit('phase', name='single-branches')

    def reset_items(self):
        self.emit('reset_begin', note='deliberate structural-control; absent from ordinary click')
        self.items.clear()
        self.tree.clear()
        self.build()
        self.tree.expandAll()
        self.emit('phase', name='reset-items')

    def probe(self, label):
        if self.native:
            self.native.snapshot(label)
        else:
            self.emit('probe_skipped', label=label, reason='native-probe-disabled')

    def auto_phase(self, number):
        from PySide6.QtTest import QTest
        stages = [self.clear_selection, self.select_leaf, self.tree.collapseAll,
                  self.tree.expandAll, self.single_branches, lambda:self.filter.setText('Leaf 1'),
                  lambda:self.filter.setText(''), self.reset_items, self.select_leaf]
        if number >= len(stages)*self.args.cycles:
            self.emit('diagnostic_complete', phases=number, native_probe_exercised=bool(self.native),
                      physical_click_validated=False, external_ax_path_validated=False)
            QApplication.instance().quit()
            return
        phase = number % len(stages)
        self.emit('auto_phase_begin', number=number, phase=phase)
        stages[phase]()
        if stages[phase] == self.select_leaf:
            rect = self.tree.visualItemRect(self.items[1])
            # Qt event simulation is a harness control, not a physical Mac click.
            point = rect.center()
            point.setX(max(rect.left()+45, point.x()))
            QTest.mouseClick(self.tree.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.probe(f'phase-{number}')
        QTimer.singleShot(self.args.interval_ms, lambda:self.auto_phase(number+1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--columns', type=int, choices=(1,2), default=2)
    ap.add_argument('--mode', choices=('plain','reveal','details','combined'), default='plain')
    ap.add_argument('--native-probe', action='store_true')
    ap.add_argument('--probe-on-click', action='store_true', help='Also query synchronously within itemClicked')
    ap.add_argument('--probe-order', choices=('selected-first','hierarchy-first'), default='selected-first')
    ap.add_argument('--auto', action='store_true', help='Bounded Qt-simulated phase sequence; no physical click claim')
    ap.add_argument('--cycles', type=int, choices=range(1,51), default=1)
    ap.add_argument('--interval-ms', type=int, default=750)
    ap.add_argument('--report', type=Path)
    args = ap.parse_args(argv)
    if not 50 <= args.interval_ms <= 10000:
        ap.error('--interval-ms must be 50..10000')
    if args.native_probe and sys.platform != 'darwin':
        ap.error('--native-probe requires macOS')
    app = QApplication(sys.argv[:1])
    window = Repro(args)
    window.show()
    previous_hook = sys.excepthook

    def callback_failed(exception_type, exception, tb):
        # Qt catches Python slot exceptions. Without this hook, an exception
        # before the next singleShot leaves the event loop idle until timeout.
        # Record no message, traceback, path, pointer or user content.
        try:
            window.emit('diagnostic_callback_error', exception_type=exception_type.__name__)
        finally:
            app.exit(2)

    sys.excepthook = callback_failed
    try:
        if args.auto:
            QTimer.singleShot(args.interval_ms, lambda:window.auto_phase(0))
        result = app.exec()
    finally:
        sys.excepthook = previous_hook
        if window.log:
            window.log.close()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
