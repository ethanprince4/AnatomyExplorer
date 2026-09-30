"""Invoke this diagnostic's own Cocoa accessibility objects on the Qt GUI thread.

No AXUIElement client, TCC prompt, remote application, or accessibility setting.
Private Qt Cocoa selectors are bounded to the pinned 6.11.2 diagnostic build.
The ctypes signatures contain only object pointers, uint32 and NSUInteger;
there are no variadic, floating-point or structure-return messages.
Native failures intentionally remain native failures for crash collection.
"""
import ctypes
import sys


class NativeProbe:
    def __init__(self, window, tree, emit, order='selected-first', max_nodes=96):
        if sys.platform != 'darwin':
            raise RuntimeError('Native Cocoa probe requires macOS and the cocoa QPA plugin')
        from PySide6.QtGui import QAccessible
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName() != 'cocoa':
            raise RuntimeError('Native Cocoa probe requires QT_QPA_PLATFORM=cocoa')
        self.window, self.tree, self.emit = window, tree, emit
        self.QAccessible = QAccessible
        self.order, self.max_nodes = order, max_nodes
        self.objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        self.objc.objc_getClass.argtypes = [ctypes.c_char_p]
        self.objc.objc_getClass.restype = ctypes.c_void_p
        self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
        self.objc.sel_registerName.restype = ctypes.c_void_p
        self.objc.object_getClassName.argtypes = [ctypes.c_void_p]
        self.objc.object_getClassName.restype = ctypes.c_char_p
        address = ctypes.cast(self.objc.objc_msgSend, ctypes.c_void_p).value
        self.send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
        self.send_u32 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32)(address)
        self.send_index = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)(address)
        self.send_count = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p)(address)
        self.send_bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
        self.send_bool0 = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(address)
        self.send_void = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(address)
        self.selectors = {}
        self.array_class = self.objc.objc_getClass(b'NSArray')
        self.element_class = self.objc.objc_getClass(b'QMacAccessibilityElement')
        if not self.element_class or not self.responds(self.element_class, 'elementWithId:'):
            raise RuntimeError('The expected Qt 6.11.2 Cocoa accessibility class is unavailable')

    def sel(self, name):
        if name not in self.selectors:
            self.selectors[name] = self.objc.sel_registerName(name.encode('ascii'))
        return self.selectors[name]

    def responds(self, obj, name):
        return bool(obj and self.send_bool(obj, self.sel('respondsToSelector:'), self.sel(name)))

    def call(self, obj, name):
        if not self.responds(obj, name):
            return None
        return self.send(obj, self.sel(name))

    def items(self, array):
        if not array:
            return []
        if not self.send_bool(array, self.sel('isKindOfClass:'), self.array_class):
            raise RuntimeError('Expected an NSArray from a Cocoa accessibility array getter')
        count = self.send_count(array, self.sel('count'))
        return [self.send_index(array, self.sel('objectAtIndex:'), i)
                for i in range(min(count, self.max_nodes))]

    def string(self, obj):
        if not obj or not self.responds(obj, 'UTF8String'):
            return None
        raw = self.send(obj, self.sel('UTF8String'))
        return ctypes.string_at(raw).decode('utf-8', 'replace') if raw else None

    def snapshot(self, label):
        # All calls execute synchronously in the GUI thread. Each pass gets its
        # own autorelease pool, matching Cocoa's normal event-boundary cleanup.
        pool_class = self.objc.objc_getClass(b'NSAutoreleasePool')
        pool = self.send(self.send(pool_class, self.sel('alloc')), self.sel('init'))
        target = None
        try:
            view = int(self.window.winId())
            class_name = self.objc.object_getClassName(view).decode('ascii', 'replace')
            if class_name != 'QNSView' or not self.responds(view, 'activateQtAccessibility'):
                raise RuntimeError('Qt top-level winId did not identify the expected QNSView')
            self.send_void(view, self.sel('activateQtAccessibility'))
            interface = self.QAccessible.queryAccessibleInterface(self.tree)
            if interface is None:
                raise RuntimeError('Qt did not expose an accessible interface for the tree')
            identifier = self.QAccessible.uniqueId(interface)
            target = self.send_u32(self.element_class, self.sel('elementWithId:'), identifier)
            if not target:
                raise RuntimeError('Qt did not expose the native tree accessibility element')
            self.send(target, self.sel('retain'))
            self.emit('native_probe_begin', label=label, order=self.order,
                      tree_class=self.objc.object_getClassName(target).decode('ascii', 'replace'))
            result = {}
            if self.order == 'hierarchy-first':
                result['hierarchy'] = self.hierarchy(target)
            self.emit('native_getter_begin', label=label, getter='accessibilitySelectedChildren')
            if not self.responds(target, 'accessibilitySelectedChildren'):
                raise RuntimeError('The native tree lacks the exact crashing accessibility getter')
            selected = self.call(target, 'accessibilitySelectedChildren')
            result['selected_children_count'] = len(self.items(selected))
            self.emit('native_getter_end', label=label, getter='accessibilitySelectedChildren',
                      count=result['selected_children_count'])
            rows = self.call(target, 'accessibilitySelectedRows')
            result['selected_rows_count'] = len(self.items(rows))
            if self.order == 'selected-first':
                result['hierarchy'] = self.hierarchy(target)
            self.emit('native_probe_end', label=label, **result)
        finally:
            if target:
                self.send_void(target, self.sel('release'))
            self.send_void(pool, self.sel('drain'))

    def hierarchy(self, root):
        result, seen = [], set()
        pending = [(root, 0)]
        while pending and len(result) < self.max_nodes:
            obj, depth = pending.pop(0)
            if not obj or obj in seen:
                continue
            seen.add(obj)
            row = {'depth': depth,
                   'class': self.objc.object_getClassName(obj).decode('ascii', 'replace'),
                   'role': self.string(self.call(obj, 'accessibilityRole')),
                   'has_parent': bool(self.call(obj, 'accessibilityParent'))}
            # The harness is synthetic, but report no title/text/pointer values.
            if self.responds(obj, 'isAccessibilityEnabled'):
                row['enabled'] = bool(self.send_bool0(obj, self.sel('isAccessibilityEnabled')))
            children = self.items(self.call(obj, 'accessibilityChildren')) if depth < 5 else []
            row['child_count_bounded'] = len(children)
            result.append(row)
            pending.extend((child, depth+1) for child in children)
        return {'nodes': result, 'truncated': bool(pending)}
