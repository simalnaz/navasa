import os
import tempfile
import unittest

import numpy
from PIL import Image

from pipeline.build_pack import (
    decode_readout,
    encode_readout,
    photo_file_name,
    save_overlay_tiles,
    shrink_photo,
    slope_band_image,
    tiles_near_points,
)


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


class OverlayTilesTest(unittest.TestCase):
    def test_zoom_levels_and_tile_count(self):
        with tempfile.TemporaryDirectory() as tiles_dir:
            image = numpy.zeros((300, 600, 4), dtype=numpy.uint8)
            image[:, :, 3] = 200
            counts = save_overlay_tiles(image, tiles_dir, 256)
            self.assertEqual(counts, {0: 6, -1: 2, -2: 1})  # 3x2, then 2x1, then 1x1
            with Image.open(os.path.join(tiles_dir, "0", "2", "1.png")) as edge_tile:
                self.assertEqual(edge_tile.getpixel((10, 10))[3], 200)  # image part
                self.assertEqual(edge_tile.getpixel((200, 200))[3], 0)  # padding is transparent


class TilesNearPointsTest(unittest.TestCase):
    def test_buffer_and_zoom(self):
        # point at grid (400, 10), 50 px buffer, 256 px tiles: 350-450 stays in tile 1
        self.assertEqual(tiles_near_points([(400.0, 10.0)], 0, 50, 256), {(1, 0)})
        self.assertEqual(tiles_near_points([(260.0, 10.0)], 0, 50, 256), {(0, 0), (1, 0)})
        # zoom 2: 4 tile pixels per grid pixel
        self.assertEqual(tiles_near_points([(300.0, 10.0)], 2, 0, 256), {(4, 0)})


class ReadoutTest(unittest.TestCase):
    def test_round_trip_and_sampling(self):
        heights = numpy.arange(64, dtype=float).reshape(8, 8) * 1.5 - 2600.0
        heights[4, 4] = numpy.nan
        image = encode_readout(heights, -2600.0, 0.1, 4)
        self.assertEqual(image.shape, (2, 2, 3))
        values = decode_readout(image, -2600.0, 0.1)
        self.assertAlmostEqual(values[0, 1], heights[0, 4], places=6)
        self.assertAlmostEqual(values[1, 0], heights[4, 0], places=6)
        self.assertTrue(numpy.isnan(values[1, 1]))  # no data stays no data

    def test_too_large_range_is_refused(self):
        with self.assertRaises(ValueError):
            encode_readout(numpy.array([[0.0, 10000.0]]), 0.0, 0.1, 1)


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
