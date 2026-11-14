import os
import tempfile
import unittest

import numpy
from PIL import Image

from pipeline.crop_layers import downsample_by_two, save_all_tiles, walk_area_window


class WalkAreaWindowTest(unittest.TestCase):
    def test_box_with_margin(self):
        window = walk_area_window([[10, 20], [30, 25]], 5, 100, 100)
        self.assertEqual((window.col_off, window.row_off, window.width, window.height), (5, 15, 31, 16))

    def test_box_is_cut_at_raster_edges(self):
        window = walk_area_window([[2, 3], [97, 98]], 10, 100, 100)
        self.assertEqual((window.col_off, window.row_off, window.width, window.height), (0, 0, 100, 100))

    def test_stop_outside_raster_is_refused(self):
        with self.assertRaises(ValueError):
            walk_area_window([[150, 20]], 5, 100, 100)


class DownsampleByTwoTest(unittest.TestCase):
    def test_mean_of_each_block(self):
        image = numpy.array([[10, 20, 30, 30], [30, 40, 30, 30]], dtype=numpy.uint8)
        self.assertEqual(downsample_by_two(image, 0).tolist(), [[25, 30]])

    def test_no_data_is_ignored(self):
        image = numpy.array([[0, 0], [0, 40]], dtype=numpy.uint8)
        self.assertEqual(downsample_by_two(image, 0).tolist(), [[40]])

    def test_all_no_data_stays_no_data(self):
        image = numpy.zeros((2, 2), dtype=numpy.uint8)
        self.assertEqual(downsample_by_two(image, 0).tolist(), [[0]])

    def test_odd_size(self):
        image = numpy.full((3, 3), 50, dtype=numpy.uint8)
        self.assertEqual(downsample_by_two(image, 0).shape, (2, 2))


class SaveAllTilesTest(unittest.TestCase):
    def test_tile_grid_and_padding(self):
        with tempfile.TemporaryDirectory() as tiles_dir:
            image = numpy.full((300, 600), 100, dtype=numpy.uint8)
            count = save_all_tiles(image, 2, tiles_dir, 256, 0, 75)
            self.assertEqual(count, 6)  # 3 columns x 2 rows
            corner_tile_path = os.path.join(tiles_dir, "2", "2", "1.jpg")
            self.assertTrue(os.path.isfile(corner_tile_path))
            with Image.open(corner_tile_path) as tile:
                self.assertEqual(tile.size, (256, 256))
                self.assertGreater(tile.getpixel((10, 10)), 50)  # image part
                self.assertLess(tile.getpixel((200, 200)), 50)  # padding


if __name__ == "__main__":
    unittest.main()
