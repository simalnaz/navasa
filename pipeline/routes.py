"""Shortest and gentlest route for each leg between stops, with facts measured along them.

Grid: the 1 m walk-area grid from crop_layers.py. Only cells that have a slope
(and so a height) can be walked on.

1. Grid path: scikit-image MCP_Geometric finds the least-distance path in
   ground metres, moving to any of the 8 neighbouring cells. Cells are
   cell_north_m x cell_east_m on the ground (terrain.ground_cell_size_m: the map
   is equirectangular, so east-west cells are cos(latitude) shorter).
2. Line-of-sight smoothing: grid paths can only turn at 0 or 45 degrees, which
   makes them longer than the real shortest way. From each corner, the path
   goes straight to the farthest later point of the grid path that can be
   reached in a straight line over allowed cells only. A straight segment is
   allowed when every cell under it (sampled every DEFAULT_ROUTES["sample_step_cells"]
   cells) is allowed.

Shortest route:  allowed cells = all cells with a slope.
Gentlest route:  S = the lowest slope for which the two stops are still connected
                 through cells with slope <= S (binary search over the slope
                 values); allowed cells = cells with slope <= S. The two stop
                 cells are always allowed and do not count towards S: the route
                 is the gentlest way between the stops. The ground slope at
                 each stop is a separate fact shown with the stop.

Measured along each route (CALCULATED from the DTM), over the cells under its
straight segments:
    points          corners of the route, [col, row]
    distance_m      horizontal ground length (sum of straight segment lengths)
    climb_m         sum of all height rises from cell to cell
    descent_m       sum of all height drops from cell to cell
    max_slope_deg   steepest cell on the route, not counting the two stop cells
    max_slope_at    [col, row] of that cell

Input:  data/work/<pack>/dtm_1m.tif, data/work/<pack>/slope_deg.tif, the mission's stops
Output: data/work/<pack>/routes.json  (format of the pack's routes.json)

Usage:
    python -m pipeline.routes [data/missions/<mission>.json]
"""

import json
import math
import sys

import numpy
import rasterio
from skimage.graph import MCP_Geometric
from skimage.measure import label

from pipeline.mission import MissionPaths, load_mission, mission_path_from_arguments
from pipeline.stops import lonlat_to_pixel
from pipeline.terrain import ground_cell_size_m, read_heights

IMPASSABLE_COST = -1.0  # MCP treats negative costs as impassable
DEFAULT_ROUTES = {"sample_step_cells": 0.25}


def with_stops_allowed(allowed, start, end):
    """Copy of the allowed-cells mask with the two stop cells always allowed."""
    allowed = allowed.copy()
    allowed[start] = True
    allowed[end] = True
    return allowed


def cell_sizes(cell_size_m):
    """(north_m, east_m) from one number (square cells) or a pair."""
    if isinstance(cell_size_m, (tuple, list)):
        return float(cell_size_m[0]), float(cell_size_m[1])
    return float(cell_size_m), float(cell_size_m)


def grid_path(allowed, start, end, cell_size_m=1.0):
    """Least ground-distance 8-neighbour path over allowed cells. start/end are (row, col).

    cell_size_m: one number for square cells, or (north_m, east_m).
    Returns the list of (row, col) cells, or None if end cannot be reached.
    """
    if not allowed[start] or not allowed[end]:
        return None
    costs = numpy.where(allowed, 1.0, IMPASSABLE_COST)
    graph = MCP_Geometric(costs, fully_connected=True, sampling=cell_sizes(cell_size_m))
    cumulative_costs, _ = graph.find_costs([start], [end])
    if not numpy.isfinite(cumulative_costs[end]):
        return None
    path = []
    for cell in graph.traceback(end):
        path.append((int(cell[0]), int(cell[1])))
    return path


def segment_cells(start, end):
    """The cells under the straight segment from start to end, in order, without repeats."""
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    sample_count = int(math.ceil(length / DEFAULT_ROUTES["sample_step_cells"])) + 1
    fractions = numpy.linspace(0.0, 1.0, sample_count)
    exact_rows = start[0] + fractions * (end[0] - start[0])
    exact_cols = start[1] + fractions * (end[1] - start[1])
    # A sample exactly on a cell corner touches four cells but crosses none of them; skip it.
    on_row_edge = numpy.isclose(exact_rows - numpy.floor(exact_rows), 0.5)
    on_col_edge = numpy.isclose(exact_cols - numpy.floor(exact_cols), 0.5)
    on_corner = on_row_edge & on_col_edge
    rows = numpy.rint(exact_rows[~on_corner]).astype(int)
    cols = numpy.rint(exact_cols[~on_corner]).astype(int)
    keep = numpy.ones(len(rows), dtype=bool)
    keep[1:] = (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])
    return rows[keep], cols[keep]


def in_line_of_sight(allowed, start, end):
    rows, cols = segment_cells(start, end)
    return bool(allowed[rows, cols].all())


def smooth_path(path, allowed):
    """Corners of the path after line-of-sight smoothing (always keeps the first and last cell)."""
    corners = [path[0]]
    anchor_index = 0
    last_index = len(path) - 1
    while anchor_index < last_index:
        reach_index = anchor_index + 1
        while reach_index < last_index and in_line_of_sight(
            allowed, path[anchor_index], path[reach_index + 1]
        ):
            reach_index += 1
        corners.append(path[reach_index])
        anchor_index = reach_index
    return corners


def are_connected(allowed, start, end):
    """True if start and end are in the same 8-connected group of allowed cells."""
    groups = label(allowed, connectivity=2)
    return bool(groups[start] == groups[end])


def lowest_connecting_slope(slope, start, end):
    """The lowest slope S for which start and end are connected through cells with slope <= S.

    The two stop cells are always allowed. Binary search over the sorted distinct
    slope values. Returns None if the stops are never connected.
    """
    has_slope = numpy.isfinite(slope)
    candidates = numpy.unique(slope[has_slope])
    low_index = 0
    high_index = len(candidates) - 1
    if not are_connected(with_stops_allowed(has_slope, start, end), start, end):
        return None
    while low_index < high_index:
        middle_index = (low_index + high_index) // 2
        allowed = with_stops_allowed(has_slope & (slope <= candidates[middle_index]), start, end)
        if are_connected(allowed, start, end):
            high_index = middle_index
        else:
            low_index = middle_index + 1
    return float(candidates[low_index])


def measure_route(corners, heights, slope, cell_size_m):
    """Distance, climb, descent and steepest point along the straight segments between corners.

    cell_size_m: one number for square cells, or (north_m, east_m).
    """
    cell_north_m, cell_east_m = cell_sizes(cell_size_m)
    distance_m = 0.0
    route_rows = [corners[0][0]]
    route_cols = [corners[0][1]]
    for index in range(1, len(corners)):
        previous = corners[index - 1]
        corner = corners[index]
        distance_m += math.hypot((corner[0] - previous[0]) * cell_north_m, (corner[1] - previous[1]) * cell_east_m)
        rows, cols = segment_cells(previous, corner)
        route_rows.extend(rows[1:].tolist())
        route_cols.extend(cols[1:].tolist())

    route_heights = heights[route_rows, route_cols]
    height_changes = numpy.diff(route_heights)
    climb_m = float(height_changes[height_changes > 0].sum())
    descent_m = float(-height_changes[height_changes < 0].sum())

    # The steepest point between the stops: leave out the first and last cell (the stops).
    if len(route_rows) > 2:
        inner_rows = route_rows[1:-1]
        inner_cols = route_cols[1:-1]
    else:
        inner_rows = route_rows
        inner_cols = route_cols
    inner_slopes = slope[inner_rows, inner_cols]
    steepest_index = int(numpy.argmax(inner_slopes))

    points = []
    for row, col in corners:
        points.append([int(col), int(row)])
    return {
        "points": points,
        "distance_m": round(distance_m, 1),
        "climb_m": round(climb_m, 1),
        "descent_m": round(descent_m, 1),
        "max_slope_deg": round(float(inner_slopes[steepest_index]), 2),
        "max_slope_at": [int(inner_cols[steepest_index]), int(inner_rows[steepest_index])],
    }


def best_route(allowed, heights, slope, cell_size_m, start, end):
    """Grid path, smoothed, and measured; None if the stops cannot be connected."""
    path = grid_path(allowed, start, end, cell_size_m)
    if path is None:
        return None
    corners = smooth_path(path, allowed)
    return measure_route(corners, heights, slope, cell_size_m)


def plan_leg(heights, slope, cell_size_m, start, end):
    """Shortest and gentlest route between two (row, col) cells; a route is None if impossible."""
    has_slope = numpy.isfinite(slope)
    if not has_slope[start] or not has_slope[end]:
        return None, None
    shortest = best_route(has_slope, heights, slope, cell_size_m, start, end)

    gentlest = None
    gentlest_limit = lowest_connecting_slope(slope, start, end)
    if gentlest_limit is not None:
        allowed = with_stops_allowed(has_slope & (slope <= gentlest_limit), start, end)
        gentlest = best_route(allowed, heights, slope, cell_size_m, start, end)
    return shortest, gentlest


def describe(route):
    if route is None:
        return "no route (no data)"
    return (
        f"{route['distance_m']} m, climb {route['climb_m']} m, descent {route['descent_m']} m, "
        f"steepest {route['max_slope_deg']} deg at {route['max_slope_at']}, {len(route['points'])} corners"
    )


def main(mission_path):
    mission = load_mission(mission_path)
    paths = MissionPaths(mission)
    stops = mission["stops"]
    with rasterio.open(paths.cropped_dtm) as dtm:
        cell_size_m = ground_cell_size_m(dtm)  # (north_m, east_m)
        heights = read_heights(dtm)
        stop_cells = []
        for stop in stops:
            col, row = lonlat_to_pixel(dtm, stop["lon"], stop["lat"])
            stop_cells.append((row, col))
    with rasterio.open(paths.slope) as slope_file:
        slope = slope_file.read(1).astype(numpy.float64)

    for stop, cell in zip(stops, stop_cells):
        print(f"Stop {stop['id']} ground slope: {slope[cell]:.2f} deg")

    legs = []
    for index in range(len(stops) - 1):
        from_stop = stops[index]
        to_stop = stops[index + 1]
        start = stop_cells[index]
        end = stop_cells[index + 1]
        straight_m = math.hypot((end[0] - start[0]) * cell_size_m[0], (end[1] - start[1]) * cell_size_m[1])
        print(f"Leg {from_stop['id']} -> {to_stop['id']} (straight line {straight_m:.1f} m) ...")
        shortest, gentlest = plan_leg(heights, slope, cell_size_m, start, end)
        print(f"  shortest: {describe(shortest)}")
        print(f"  gentlest: {describe(gentlest)}")
        legs.append({"from": from_stop["id"], "to": to_stop["id"], "shortest": shortest, "gentlest": gentlest})

    with open(paths.routes, "w", encoding="utf-8") as routes_file:
        json.dump(legs, routes_file)
    print(f"Routes written to {paths.routes}")
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
