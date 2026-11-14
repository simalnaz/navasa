import os
import tempfile
import unittest

import numpy
from PIL import Image

from pipeline.build_pack import photo_file_name, shrink_photo, slope_band_image


class SlopeBandImageTest(unittest.TestCase):
    def test_bands_and_legend(self):
        slope = numpy.array([[0.0, 4.9, 5.0, 12.0], [numpy.nan, 1.0, 1.0, 1.0]])
        image, legend = slope_band_image(slope, 5, "viridis", 170)
        self.assertEqual([band["from_deg"] for band in legend], [0, 5, 10])
        self.assertEqual(legend[-1]["to_deg"], 15)
        self.assertEqual(image[0, 0, 0:3].tolist(), image[0, 1, 0:3].tolist())  # same band 0-5
        self.assertNotEqual(image[0, 1, 0:3].tolist(), image[0, 2, 0:3].tolist())  # 4.9 vs 5.0
        self.assertEqual(image[0, 3, 0:3].tolist(), legend[2]["color"])
        self.assertEqual(image[1, 0, 3], 0)  # no slope is transparent
        self.assertEqual(image[0, 0, 3], 170)


class PhotoTest(unittest.TestCase):
    def test_shrink_keeps_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "big.png")
            target = os.path.join(temp_dir, "small.jpg")
            Image.new("RGB", (3200, 1600), (120, 80, 40)).save(source)
            shrink_photo(source, target, 1600, 85)
            with Image.open(target) as small:
                self.assertEqual(small.size, (1600, 800))
                self.assertEqual(small.format, "JPEG")

    def test_small_photo_is_not_enlarged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "small.png")
            target = os.path.join(temp_dir, "out.jpg")
            Image.new("L", (800, 600), 100).save(source)
            shrink_photo(source, target, 1600, 85)
            with Image.open(target) as out:
                self.assertEqual(out.size, (800, 600))

    def test_photo_file_name(self):
        name = photo_file_name(2, {"sol": 425, "camera": "Left Mastcam-Z Camera"})
        self.assertEqual(name, "stop2_sol425_left-mastcam-z-camera.jpg")


if __name__ == "__main__":
    unittest.main()
