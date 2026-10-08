import unittest

from app.viewer.viewport import msaa_samples


class MsaaTests(unittest.TestCase):
    def test_samples_by_pixel_ratio(self):
        self.assertEqual(msaa_samples(True, 1.0), 8)
        self.assertEqual(msaa_samples(True, 2.0), 4)
        self.assertEqual(msaa_samples(True, 1.5), 4)
        self.assertEqual(msaa_samples(False, 2.0), 1)


if __name__ == "__main__":
    unittest.main()
