"""Re-signing may change metadata; changed executable sections must fail identity."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from app.macho_sections import section_identity


class MachOSectionTests(unittest.TestCase):
    def binary(self, text=b"code", metadata=b"sign"):
        header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 6, 1, 152, 0, 0)
        segment = struct.pack("<II16s4Q4I", 0x19, 152, b"__TEXT", 0, 4096, 0, 188, 7, 5, 1, 0)
        section = struct.pack("<16s16sQQ8I", b"__text", b"__TEXT", 0, 4, 184, 0, 0, 0, 0, 0, 0, 0)
        return header + segment + section + text + metadata

    def identity(self, raw):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.dylib"
            path.write_bytes(raw)
            return section_identity(path)

    def test_code_sections_are_independent_of_signature_metadata(self):
        self.assertEqual(self.identity(self.binary(metadata=b"old")),
                         self.identity(self.binary(metadata=b"different signature")))

    def test_changed_code_is_rejected(self):
        self.assertNotEqual(self.identity(self.binary()), self.identity(self.binary(text=b"edit")))

    def test_invalid_section_range_is_rejected(self):
        raw = bytearray(self.binary())
        struct.pack_into("<I", raw, 32 + 72 + 48, 999999)
        with self.assertRaises(ValueError):
            self.identity(raw)

    def test_duplicate_or_unknown_architecture_is_rejected(self):
        raw = bytearray(self.binary())
        struct.pack_into("<I", raw, 4, 0)
        with self.assertRaises(ValueError):
            self.identity(raw)

    def test_accepted_binary_matches_pinned_sections_and_architecture(self):
        root = Path(__file__).resolve().parents[1] / "packaging/qt-cocoa"
        actual = section_identity(root / "libqcocoa.dylib")
        self.assertEqual(set(actual), {"arm64"})
        self.assertEqual(actual, json.loads((root / "PROVENANCE.json").read_text())["file_backed_sections"])
