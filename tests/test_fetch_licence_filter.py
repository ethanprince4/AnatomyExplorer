"""The Commons fetch tools take in only the licences tools/check_licenses.py accepts (CC0, public domain, CC BY).
No network: the licence tests are plain calls, and the radiology download is run with its Commons calls replaced."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import check_licenses  # noqa: E402
import fetch_histology  # noqa: E402
import fetch_radiology  # noqa: E402

REFUSED = ("CC BY-SA 4.0", "CC BY-SA 3.0", "GFDL", "No restrictions", "CC BY-NC 4.0", "CC BY-ND 4.0", "", None)
ACCEPTED = ("CC BY 4.0", "CC0", "Public domain", "CC BY 3.0 de")


class LicenceFilterTest(unittest.TestCase):
    def test_each_filter_matches_the_checker(self):
        for name, rule in (("check_licenses", check_licenses.image_licence_ok),
                           ("fetch_histology", fetch_histology.licence_ok),
                           ("fetch_radiology", fetch_radiology.licence_ok)):
            for lic in REFUSED:
                self.assertFalse(rule(lic), f"{name} accepted {lic!r}")
            for lic in ACCEPTED:
                self.assertTrue(rule(lic), f"{name} refused {lic!r}")

    def test_tools_use_the_checker_function(self):
        self.assertIs(fetch_histology.licence_ok, check_licenses.image_licence_ok)
        self.assertIs(fetch_radiology.licence_ok, check_licenses.image_licence_ok)

    def test_radiology_download_skips_a_refused_licence(self):
        def meta(lic):
            return {"title": "File:X.jpg", "thumb": "https://example.invalid/x.jpg", "width": 800, "height": 800,
                    "mime": "image/jpeg", "page": "https://commons.wikimedia.org/wiki/File:X.jpg", "licence": lic,
                    "author": "A", "credit": "", "description": ""}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "images").mkdir()
            saved = (fetch_radiology.OUT, fetch_radiology.IMAGES, fetch_radiology.file_info, fetch_radiology.get)
            fetched = []
            try:
                fetch_radiology.OUT, fetch_radiology.IMAGES = out, out / "images"
                fetch_radiology.get = lambda *a, **k: fetched.append(a) or None
                for lic in ("CC BY-SA 4.0", "GFDL"):
                    fetch_radiology.file_info = lambda titles, lic=lic: {"File:X.jpg": meta(lic)}
                    fetch_radiology.fetch({"case_x": "File:X.jpg"})
            finally:
                fetch_radiology.OUT, fetch_radiology.IMAGES, fetch_radiology.file_info, fetch_radiology.get = saved
            self.assertEqual(fetched, [], "a refused licence must not be downloaded")
            self.assertEqual(json.loads((out / "sources.json").read_text(encoding="utf-8")), {})
            self.assertEqual(list((out / "images").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
