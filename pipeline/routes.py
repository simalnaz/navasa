"""Shortest and gentlest route for each leg between stops, with facts measured along them.

Grid: the 1 m walk-area grid from crop_layers.py. A route moves from a cell to
any of its 8 neighbours (straight step = 1 cell, diagonal step = sqrt(2) cells)
and only over cells that have a height and a slope.

Shortest route:  least horizontal distance (scikit-image MCP_Geometric, cost 1 per metre).
Gentlest route:  the lowest slope S for which the two stops are still connected using
                 only cells with slope <= S (found by binary search over the slope
                 values), then the shortest route through those cells.
                 Its steepest point is S.

Measured along each route (CALCULATED from the DTM):
    distance_m      horizontal length of the path
    climb_m         sum of all height rises between consecutive cells
    descent_m       sum of all height drops between consecutive cells
    max_slope_deg   steepest slope of any cell on the path
    max_slope_at    [col, row] of that cell

Input:  data/work/dtm_1m.tif, data/work/slope_deg.tif, data/stops.json
Output: data/work/routes.json  (format of the pack's routes.json)

Usage:
    python -m pipeline.routes
"""

import json
import math
import os
import sys

import numpy
import rasterio
from skimage.graph import MCP_Geometric
from skimage.measure import label

from pipeline.crop_layers import CROPPED_DTM_PATH, WORK_DIR
from pipeline.stops import load_stops, lonlat_to_pixel
from pipeline.terrain import SLOPE_PATH, read_heights

ROUTES_PATH = os.path.join(WORK_DIR, "routes.json")
IMPASSABLE_COST = -1.0  # MCP treats negative costs as impassable


def shortest_path(passable, start, end):
    """Least-distance 8-neighbour path over passable cells. start/end are (row, col).

    Returns the list of (row, col) cells, or None if end cannot be reached.
    """
    if not passable[start] or not passable[end]:
        return None
    costs = numpy.where(passable, 1.0, IMPASSABLE_COST)
    graph = MCP_Geometric(costs, fully_connected=True)
    cumulative_costs, _ = graph.find_costs([start], [end])
    if not numpy.isfinite(cumulative_costs[end]):
        return None
    return graph.traceback(end)


def are_connected(passable, start, end):
    """True if start and end are in the same 8-connected group of passable cells."""
    if not passable[start] or not passable[end]:
        return False
    groups = label(passable, connectivity=2)
    return bool(groups[start] == groups[end])


def lowest_connecting_slope(slope, start, end):
    """The lowest slope S for which start and end are connected through cells with slope <= S.

    Binary search over the sorted distinct slope values. Returns None if they are
    never connected.
    """
    has_slope = numpy.isfinite(slope)
    if not has_slope[start] or not has_slope[end]:
        return None
    candidates = numpy.unique(slope[has_slope])
    lowest_possible = max(slope[start], slope[end])
    low_index = int(numpy.searchsorted(candidates, lowest_possible))
    high_index = len(candidates) - 1
    if not are_connected(has_slope & (slope <= candidates[high_index]), start, end):
        return None
    while low_index < high_index:
        middle_index = (low_index + high_index) // 2
        if are_connected(has_slope & (slope <= candidates[middle_index]), start, end):
            high_index = middle_index
        else:
            low_index = middle_index + 1
    return float(candidates[low_index])


def measure_path(path, heights, slope, cell_size_m):
    """Distance, climb, descent and steepest point along a path of (row, col) cells."""
    distance_cells = 0.0
    climb_m = 0.0
    descent_m = 0.0
    max_slope = -1.0
    max_slope_cell = path[0]
    for index, cell in enumerate(path):
        if slope[cell] > max_slope:
            max_slope = float(slope[cell])
            max_slope_cell = cell
        if index == 0:
            continue
        previous = path[index - 1]
        is_diagonal = previous[0] != cell[0] and previous[1] != cell[1]
        if is_diagonal:
            distance_cells += math.sqrt(2.0)
        else:
            distance_cells += 1.0
        height_change = float(heights[cell] - heights[previous])
        if height_change > 0:
            climb_m += height_change
        else:
            descent_m -= height_change
    return {
        "points": [[int(col), int(row)] for row, col in path],
        "distance_m": round(distance_cells * cell_size_m, 1),
        "climb_m": round(climb_m, 1),
        "descent_m": round(descent_m, 1),
        "max_slope_deg": round(max_slope, 2),
        "max_slope_at": [int(max_slope_cell[1]), int(max_slope_cell[0])],
    }


def plan_leg(heights, slope, cell_size_m, start, end):
    """Shortest and gentlest route between two (row, col) cells; a route is None if impossible."""
    has_slope = numpy.isfinite(slope)

    path = shortest_path(has_slope, start, end)
    shortest = None
    if path is not None:
        shortest = measure_path(path, heights, slope, cell_size_m)

    gentlest = None
    gentlest_limit = lowest_connecting_slope(slope, start, end)
    if gentlest_limit is not None:
        path = shortest_path(has_slope & (slope <= gentlest_limit), start, end)
        if path is not None:
            gentlest = measure_path(path, heights, slope, cell_size_m)
    return shortest, gentlest


def describe(route):
    if route is None:
        return "no route (no data)"
    return (
        f"{route['distance_m']} m, climb {route['climb_m']} m, descent {route['descent_m']} m, "
        f"steepest {route['max_slope_deg']} deg at {route['max_slope_at']}"
    )


def main():
    stops = load_stops()
    with rasterio.open(CROPPED_DTM_PATH) as dtm:
        cell_size_m = dtm.res[0]
        heights = read_heights(dtm)
        stop_cells = []
        for stop in stops:
            col, row = lonlat_to_pixel(dtm, stop["lon"], stop["lat"])
            stop_cells.append((row, col))
    with rasterio.open(SLOPE_PATH) as slope_file:
        slope = slope_file.read(1).astype(numpy.float64)

    legs = []
    for index in range(len(stops) - 1):
        from_stop = stops[index]
        to_stop = stops[index + 1]
        print(f"Leg {from_stop['id']} -> {to_stop['id']} ...")
        shortest, gentlest = plan_leg(
            heights, slope, cell_size_m, stop_cells[index], stop_cells[index + 1]
        )
        print(f"  shortest: {describe(shortest)}")
        print(f"  gentlest: {describe(gentlest)}")
        legs.append({"from": from_stop["id"], "to": to_stop["id"], "shortest": shortest, "gentlest": gentlest})

    with open(ROUTES_PATH, "w", encoding="utf-8") as routes_file:
        json.dump(legs, routes_file)
    print(f"Routes written to {ROUTES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
