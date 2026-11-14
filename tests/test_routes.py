import math
import unittest

import numpy

from pipeline.routes import (
    grid_path,
    lowest_connecting_slope,
    measure_route,
    plan_leg,
    segment_cells,
    smooth_path,
)


def ridge_grid():
    """7 x 9 grid of 1 degree slope with a 30 degree wall in column 4,
    except one 10 degree gap at the bottom row (row 6)."""
    slope = numpy.full((7, 9), 1.0)
    slope[:, 4] = 30.0
    slope[6, 4] = 10.0
    heights = numpy.zeros((7, 9))
    return slope, heights


class GridPathTest(unittest.TestCase):
    def test_blocked_cells_are_avoided(self):
        allowed = numpy.ones((3, 5), dtype=bool)
        allowed[0:2, 2] = False
        path = grid_path(allowed, (0, 0), (0, 4))
        self.assertIn((2, 2), path)

    def test_unreachable_returns_none(self):
        allowed = numpy.ones((3, 5), dtype=bool)
        allowed[:, 2] = False
        self.assertIsNone(grid_path(allowed, (1, 0), (1, 4)))


class SmoothPathTest(unittest.TestCase):
    def test_open_ground_becomes_one_straight_segment(self):
        allowed = numpy.ones((20, 40), dtype=bool)
        path = grid_path(allowed, (2, 1), (15, 37))
        corners = smooth_path(path, allowed)
        self.assertEqual(corners, [(2, 1), (15, 37)])
        route = measure_route(corners, numpy.zeros((20, 40)), numpy.zeros((20, 40)), 1.0)
        self.assertAlmostEqual(route["distance_m"], round(math.hypot(13, 36), 1))

    def test_smoothing_never_crosses_blocked_cells(self):
        allowed = numpy.ones((11, 11), dtype=bool)
        allowed[2:11, 5] = False  # wall with an opening at the top rows 0-1
        path = grid_path(allowed, (10, 0), (10, 10))
        corners = smooth_path(path, allowed)
        self.assertGreater(len(corners), 2)
        route = measure_route(corners, numpy.zeros((11, 11)), numpy.zeros((11, 11)), 1.0)
        self.assertGreater(route["distance_m"], 10.0)
        for index in range(1, len(corners)):
            rows, cols = segment_cells(corners[index - 1], corners[index])
            self.assertTrue(allowed[rows, cols].all())

    def test_cell_size_scales_distance(self):
        allowed = numpy.ones((4, 4), dtype=bool)
        corners = smooth_path(grid_path(allowed, (0, 0), (3, 3)), allowed)
        route = measure_route(corners, numpy.zeros((4, 4)), numpy.zeros((4, 4)), 2.0)
        self.assertAlmostEqual(route["distance_m"], round(3 * math.sqrt(2) * 2.0, 1))


class SegmentCellsTest(unittest.TestCase):
    def test_diagonal_step_touches_only_its_two_cells(self):
        rows, cols = segment_cells((0, 0), (1, 1))
        self.assertEqual(list(zip(rows.tolist(), cols.tolist())), [(0, 0), (1, 1)])

    def test_diagonal_squeeze_never_reports_the_blocked_corner_cells(self):
        slope = numpy.zeros((2, 2))
        slope[0, 1] = 40.0
        slope[1, 0] = 40.0
        allowed = slope < 10.0
        corners = smooth_path(grid_path(allowed, (0, 0), (1, 1)), allowed)
        route = measure_route(corners, numpy.zeros((2, 2)), slope, 1.0)
        self.assertEqual(route["max_slope_deg"], 0.0)


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

    def test_steep_stop_cell_does_not_set_the_limit(self):
        slope, heights = ridge_grid()
        slope[0, 8] = 40.0  # the end stop stands on steep ground
        self.assertEqual(lowest_connecting_slope(slope, (0, 0), (0, 8)), 10.0)
        _, gentlest = plan_leg(heights, slope, 1.0, (0, 0), (0, 8))
        self.assertEqual(gentlest["max_slope_deg"], 10.0)

    def test_missing_slope_blocks_both_routes(self):
        slope, heights = ridge_grid()
        slope[:, 4] = numpy.nan
        shortest, gentlest = plan_leg(heights, slope, 1.0, (0, 0), (0, 8))
        self.assertIsNone(shortest)
        self.assertIsNone(gentlest)


class MeasureRouteTest(unittest.TestCase):
    def test_climb_descent_and_steepest_between_stops(self):
        heights = numpy.array([[0.0, 2.0, 5.0, 4.0, 1.0]])
        slope = numpy.array([[50.0, 2.0, 9.0, 3.0, 1.0]])  # start cell is steep, not counted
        corners = [(0, 0), (0, 4)]
        route = measure_route(corners, heights, slope, 1.0)
        self.assertEqual(route["climb_m"], 5.0)
        self.assertEqual(route["descent_m"], 4.0)
        self.assertEqual(route["max_slope_deg"], 9.0)
        self.assertEqual(route["max_slope_at"], [2, 0])
        self.assertEqual(route["points"], [[0, 0], [4, 0]])


if __name__ == "__main__":
    unittest.main()
