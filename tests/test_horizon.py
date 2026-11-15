import math
import unittest

import numpy

from pipeline.horizon import NO_DATA, encode_horizon, horizon_angles

RADIUS_M = 3396190.0
CELL_M = 16


def wall_terrain(wall_col, wall_height_m, size=40):
    heights = numpy.zeros((size, size), dtype=numpy.float32)
    heights[:, wall_col:] = wall_height_m
    return heights


class HorizonAnglesTest(unittest.TestCase):
    def test_flat_ground_has_a_horizon_just_below_zero(self):
        heights = numpy.zeros((20, 20), dtype=numpy.float32)
        angles = horizon_angles(heights, (10, 10), (1, 1), CELL_M, 1.0, RADIUS_M, [0, 90, 180, 270], 160)
        for angle in angles[:, 0, 0]:
            self.assertLess(angle, 0.0)
            self.assertGreater(angle, -0.01)

    def test_wall_to_the_east(self):
        # Target at column 5, wall of 50 m from column 15 on: 10 cells = 160 m away.
        angles = horizon_angles(wall_terrain(15, 50.0), (20, 5), (1, 1), CELL_M, 1.0, RADIUS_M, [90, 270], 400)
        distance = 160.0
        expected = math.degrees(math.atan((50.0 - distance**2 / (2 * RADIUS_M)) / distance))
        self.assertAlmostEqual(float(angles[0, 0, 0]), expected, places=3)
        self.assertLess(float(angles[1, 0, 0]), 0.0)  # looking west: flat

    def test_map_scale_east_west(self):
        # Half a ground metre per map metre: the same wall is half as far on the ground.
        angles = horizon_angles(wall_terrain(15, 50.0), (20, 5), (1, 1), CELL_M, 0.5, RADIUS_M, [90], 400)
        distance = 80.0
        expected = math.degrees(math.atan((50.0 - distance**2 / (2 * RADIUS_M)) / distance))
        self.assertAlmostEqual(float(angles[0, 0, 0]), expected, places=3)

    def test_terrain_outside_the_heights_is_ignored(self):
        heights = numpy.zeros((10, 10), dtype=numpy.float32)
        angles = horizon_angles(heights, (5, 5), (1, 1), CELL_M, 1.0, RADIUS_M, [0], 1000)
        self.assertTrue(numpy.isfinite(angles[0, 0, 0]))

    def test_cell_without_height(self):
        heights = numpy.zeros((10, 10), dtype=numpy.float32)
        heights[5, 5] = numpy.nan
        angles = horizon_angles(heights, (5, 5), (1, 1), CELL_M, 1.0, RADIUS_M, [0], 64)
        self.assertTrue(numpy.isnan(angles[0, 0, 0]))


class EncodeHorizonTest(unittest.TestCase):
    def test_codes(self):
        codes = encode_horizon(numpy.array([-3.0, 0.0, 10.1, 80.0, numpy.nan]), 0.25)
        self.assertEqual(codes.tolist(), [0, 0, 40, NO_DATA - 1, NO_DATA])


if __name__ == "__main__":
    unittest.main()
