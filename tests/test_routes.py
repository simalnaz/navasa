import math
import unittest

import numpy

from pipeline.routes import lowest_connecting_slope, measure_path, plan_leg, shortest_path


def ridge_grid():
    """7 x 9 grid of 1 degree slope with a 30 degree wall in column 4,
    except one 10 degree gap at the bottom row (row 6)."""
    slope = numpy.full((7, 9), 1.0)
    slope[:, 4] = 30.0
    slope[6, 4] = 10.0
    heights = numpy.zeros((7, 9))
    return slope, heights


class ShortestPathTest(unittest.TestCase):
    def test_straight_line_length(self):
        passable = numpy.ones((3, 6), dtype=bool)
        path = shortest_path(passable, (1, 0), (1, 5))
        self.assertEqual(len(path), 6)
        route = measure_path(path, numpy.zeros((3, 6)), numpy.zeros((3, 6)), 1.0)
        self.assertAlmostEqual(route["distance_m"], 5.0)

    def test_diagonal_length_uses_square_root_of_two(self):
        passable = numpy.ones((4, 4), dtype=bool)
        path = shortest_path(passable, (0, 0), (3, 3))
        route = measure_path(path, numpy.zeros((4, 4)), numpy.zeros((4, 4)), 2.0)
        self.assertAlmostEqual(route["distance_m"], round(3 * math.sqrt(2) * 2.0, 1))

    def test_blocked_cells_are_avoided(self):
        passable = numpy.ones((3, 5), dtype=bool)
        passable[0:2, 2] = False
        path = shortest_path(passable, (0, 0), (0, 4))
        self.assertIn((2, 2), [tuple(cell) for cell in path])

    def test_unreachable_returns_none(self):
        passable = numpy.ones((3, 5), dtype=bool)
        passable[:, 2] = False
        self.assertIsNone(shortest_path(passable, (1, 0), (1, 4)))


class GentlestRouteTest(unittest.TestCase):
    def test_lowest_connecting_slope_is_the_gap(self):
        slope, _ = ridge_grid()
        self.assertEqual(lowest_connecting_slope(slope, (0, 0), (0, 8)), 10.0)

    def test_gentlest_goes_through_gap_and_shortest_crosses_wall(self):
        slope, heights = ridge_grid()
        shortest, gentlest = plan_leg(heights, slope, 1.0, (0, 0), (0, 8))
        self.assertEqual(shortest["max_slope_deg"], 30.0)
        self.assertEqual(gentlest["max_slope_deg"], 10.0)
        self.assertEqual(gentlest["max_slope_at"], [4, 6])  # [col, row] of the gap
        self.assertGreater(gentlest["distance_m"], shortest["distance_m"])

    def test_missing_slope_blocks_both_routes(self):
        slope, heights = ridge_grid()
        slope[:, 4] = numpy.nan
        shortest, gentlest = plan_leg(heights, slope, 1.0, (0, 0), (0, 8))
        self.assertIsNone(shortest)
        self.assertIsNone(gentlest)


class MeasurePathTest(unittest.TestCase):
    def test_climb_and_descent(self):
        heights = numpy.array([[0.0, 2.0, 5.0, 4.0, 1.0]])
        slope = numpy.array([[1.0, 2.0, 9.0, 3.0, 1.0]])
        path = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
        route = measure_path(path, heights, slope, 1.0)
        self.assertEqual(route["climb_m"], 5.0)
        self.assertEqual(route["descent_m"], 4.0)
        self.assertEqual(route["max_slope_deg"], 9.0)
        self.assertEqual(route["max_slope_at"], [2, 0])
        self.assertEqual(route["points"][0], [0, 0])


if __name__ == "__main__":
    unittest.main()
