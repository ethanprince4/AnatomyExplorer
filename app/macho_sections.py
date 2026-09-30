"""Bounded Mach-O file-backed section identity, independent of signing/link edits."""
import hashlib
from pathlib import Path
import struct


def section_identity(path):
    data = Path(path).read_bytes()
    if data[:4] == b"\xca\xfe\xba\xbe":
        count = struct.unpack_from(">I", data, 4)[0]
        if not 1 <= count <= 16 or 8 + count * 20 > len(data):
            raise ValueError("Invalid universal Mach-O bounds")
        slices = [struct.unpack_from(">5I", data, 8 + i * 20)[2:4] for i in range(count)]
    else:
        slices = [(0, len(data))]
    result = {}
    for start, length in slices:
        if length < 32 or start + length > len(data):
            raise ValueError("Invalid Mach-O slice bounds")
        raw = memoryview(data)[start:start + length]
        magic, cpu, _, _, count, command_size, _, _ = struct.unpack_from("<8I", raw)
        if magic != 0xFEEDFACF or command_size > length - 32 or count > 10000:
            raise ValueError("Expected bounded 64-bit little-endian Mach-O")
        architecture = {0x0100000C: "arm64", 0x01000007: "x86_64"}.get(cpu)
        if architecture is None or architecture in result:
            raise ValueError("Unexpected or duplicate Mach-O architecture")
        sections, offset = {}, 32
        for _ in range(count):
            if offset + 8 > 32 + command_size:
                raise ValueError("Invalid load command bounds")
            command, size = struct.unpack_from("<II", raw, offset)
            if size < 8 or offset + size > 32 + command_size:
                raise ValueError("Invalid load command size")
            if command == 0x19:  # LC_SEGMENT_64
                if size < 72:
                    raise ValueError("Invalid segment command")
                nsections = struct.unpack_from("<I", raw, offset + 64)[0]
                if 72 + nsections * 80 > size:
                    raise ValueError("Invalid section table")
                for index in range(nsections):
                    fields = struct.unpack_from("<16s16sQQ8I", raw, offset + 72 + index * 80)
                    name, segment, _, byte_count, file_offset, _, _, _, flags, _, _, _ = fields
                    # S_ZEROFILL, S_GB_ZEROFILL, S_THREAD_LOCAL_ZEROFILL have no file bytes.
                    if flags & 0xFF in (1, 0xC, 0x12) or byte_count == 0:
                        continue
                    if file_offset + byte_count > length:
                        raise ValueError("Invalid file-backed section bounds")
                    key = segment.rstrip(b"\0").decode("ascii") + "/" + name.rstrip(b"\0").decode("ascii")
                    if key in sections:
                        raise ValueError("Duplicate Mach-O section")
                    sections[key] = {"size": byte_count, "sha256": hashlib.sha256(
                        raw[file_offset:file_offset + byte_count]).hexdigest()}
            offset += size
        if offset != 32 + command_size or not sections or "__TEXT/__text" not in sections:
            raise ValueError("Incomplete Mach-O section identity")
        result[architecture] = sections
    return result
