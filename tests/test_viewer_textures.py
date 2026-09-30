"""glTF UV(0,0) samples the original image's upper-left texel."""
import io
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image
from app.viewer.renderer import Renderer


class TextureOrientationTests(unittest.TestCase):
    def test_uploaded_image_preserves_gltf_top_left_and_alpha(self):
        pixels = np.array([[[255, 0, 0, 255], [0, 255, 0, 128]],
                           [[0, 0, 255, 64], [255, 255, 0, 0]]], dtype=np.uint8)
        source = io.BytesIO()
        Image.fromarray(pixels, "RGBA").save(source, format="PNG")
        uploaded = []

        def upload(size, channels, data, **options):
            uploaded.append((size, channels, data, options))
            return SimpleNamespace(build_mipmaps=lambda: None)

        renderer = Renderer.__new__(Renderer)
        renderer.model = SimpleNamespace(doc=SimpleNamespace(images=[source.getvalue()]))
        renderer.textures = {}
        renderer.ctx = SimpleNamespace(texture=upload)
        renderer.white = object()
        texture = renderer._texture(0)
        self.assertIsNot(texture, renderer.white)
        self.assertEqual(uploaded[0][:2], ((2, 2), 4))
        self.assertEqual(uploaded[0][3]["internal_format"], 0x8C43)
        actual = np.frombuffer(uploaded[0][2], dtype=np.uint8).reshape(2, 2, 4)
        np.testing.assert_array_equal(actual, pixels)
        self.assertIs(renderer._texture(0), texture)
        self.assertEqual(len(uploaded), 1)


if __name__ == "__main__":
    unittest.main()
