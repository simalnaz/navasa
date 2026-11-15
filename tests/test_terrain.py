import math
import unittest

import numpy

from pipeline.terrain import slope_degrees


class SlopeDegreesTest(unittest.TestCase):
    def test_flat_ground_is_zero(self):
        heights = numpy.full((5, 5), 100.0)
        self.assertTrue(numpy.allclose(slope_degrees(heights, 1.0), 0.0))

    def test_tilted_plane_rising_east(self):
        # Rises 1 m per 1 m cell towards east -> 45 degrees everywhere.
        cols = numpy.arange(6, dtype=float)
        heights = numpy.tile(cols, (4, 1))
        self.assertTrue(numpy.allclose(slope_degrees(heights, 1.0), 45.0, atol=1e-4))

    def test_tilted_plane_known_angle_with_cell_size(self):
        # Rises 0.5 m per row on 2 m cells -> arctan(0.25).
        rows = numpy.arange(5, dtype=float).reshape(5, 1) * 0.5
        heights = numpy.tile(rows, (1, 4))
        expected = math.degrees(math.atan(0.25))
        self.assertTrue(numpy.allclose(slope_degrees(heights, 2.0), expected, atol=1e-4))

    def test_diagonal_plane(self):
        # 3 m per cell east and 4 m per cell north -> rise 5 per metre.
        row_index, col_index = numpy.mgrid[0:5, 0:5].astype(float)
        heights = 3.0 * col_index + 4.0 * row_index
        expected = math.degrees(math.atan(5.0))
        self.assertTrue(numpy.allclose(slope_degrees(heights, 1.0), expected, atol=1e-4))

    def test_no_height_gives_no_slope(self):
        heights = numpy.full((5, 5), 10.0)
        heights[2, 2] = numpy.nan
        slope = slope_degrees(heights, 1.0)
        self.assertTrue(numpy.isnan(slope[2, 2]))
        self.assertTrue(numpy.isnan(slope[2, 1]))  # neighbour uses the missing height
        self.assertFalse(numpy.isnan(slope[0, 0]))

    def test_east_west_cells_shorter_on_the_ground(self):
        # Rises 1 m per map cell towards east; east cells are 0.5 m on the ground: 2 m per ground metre.
        heights = numpy.tile(numpy.arange(6, dtype=numpy.float64), (6, 1))
        slope = slope_degrees(heights, 1.0, 0.5)
        self.assertTrue(numpy.allclose(slope, math.degrees(math.atan(2.0)), atol=1e-4))


if __name__ == "__main__":
    unittest.main()
