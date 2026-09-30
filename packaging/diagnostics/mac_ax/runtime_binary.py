"""Report the Cocoa plugin actually loaded in this process, without path/device data."""
import ctypes
import hashlib
import os
from pathlib import Path
import struct
import sys
import uuid


def ownership_runtime_identity():
    """Candidate-only loaded-file checks; report no filesystem paths."""
    expected = os.environ.get('QT_OWNERSHIP_PLUGIN_SHA256')
    wheel_root = os.environ.get('QT_OWNERSHIP_WHEEL_ROOT')
    if not expected or not wheel_root or sys.platform != 'darwin':
        return {'candidate_plugin_loaded': False, 'all_qt_frameworks_from_wheel': False}
    wheel = Path(wheel_root).resolve()
    dyld = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    dyld._dyld_image_count.argtypes = []
    dyld._dyld_image_count.restype = ctypes.c_uint32
    dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    dyld._dyld_get_image_name.restype = ctypes.c_char_p
    frameworks, plugins = [], []
    for i in range(dyld._dyld_image_count()):
        raw = dyld._dyld_get_image_name(i)
        if not raw:
            continue
        path = Path(os.fsdecode(raw)).resolve()
        if path.name == 'libqcocoa.dylib':
            plugins.append({'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'from_isolated_wheel': path.is_relative_to(wheel)})
        elif '.framework/' in str(path) and path.name.startswith('Qt'):
            frameworks.append({'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                               'from_isolated_wheel': path.is_relative_to(wheel)})
        elif path.name.startswith('libQt') and path.suffix == '.dylib':
            frameworks.append({'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                               'from_isolated_wheel': path.is_relative_to(wheel)})
    names = {row['name'] for row in frameworks}
    return {'candidate_plugin_loaded': len(plugins) == 1 and plugins[0]['sha256'] == expected
                                      and plugins[0]['from_isolated_wheel'],
            'all_qt_frameworks_from_wheel': {'QtCore', 'QtGui', 'QtWidgets'}.issubset(names)
                                           and all(row['from_isolated_wheel'] for row in frameworks),
            'frameworks': frameworks, 'plugins': plugins,
            'frozen': bool(getattr(sys, 'frozen', False))}


def loaded_qcocoa_identity():
    if sys.platform != 'darwin':
        return {'supported':False, 'reason':'macOS-only'}
    dyld = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    dyld._dyld_image_count.argtypes = []
    dyld._dyld_image_count.restype = ctypes.c_uint32
    dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    dyld._dyld_get_image_name.restype = ctypes.c_char_p
    dyld._dyld_get_image_header.argtypes = [ctypes.c_uint32]
    dyld._dyld_get_image_header.restype = ctypes.c_void_p
    matches = []
    for i in range(dyld._dyld_image_count()):
        path = dyld._dyld_get_image_name(i)
        if not path or path.rsplit(b'/',1)[-1] != b'libqcocoa.dylib':
            continue
        header = dyld._dyld_get_image_header(i)
        raw_header = ctypes.string_at(header, 32)
        magic, cpu, subtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack('<8I', raw_header)
        if magic != 0xFEEDFACF or sizeofcmds > 1024*1024:
            raise RuntimeError('Unexpected loaded Cocoa plugin Mach-O header')
        commands = ctypes.string_at(header+32, sizeofcmds)
        offset = 0
        identity = {'basename':'libqcocoa.dylib', 'cpu_type':hex(cpu)}
        for _ in range(ncmds):
            cmd, size = struct.unpack_from('<II', commands, offset)
            if size < 8 or offset+size > len(commands):
                raise RuntimeError('Invalid loaded Mach-O command bounds')
            if cmd == 0x1B:
                identity['uuid'] = str(uuid.UUID(bytes=commands[offset+8:offset+24]))
            offset += size
        matches.append(identity)
    return {'supported':True, 'images':matches,
            'exact_crash_plugin_loaded':any(m.get('uuid')=='f2e95bb5-d6a7-3098-8ae3-89a4387c7f4e' for m in matches)}
