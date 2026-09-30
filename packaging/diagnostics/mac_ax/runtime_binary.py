"""Report the Cocoa plugin actually loaded in this process, without path/device data."""
import ctypes
import struct
import sys
import uuid


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
