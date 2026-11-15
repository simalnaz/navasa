"""Terrain horizon angles for sun and shadow: how high the terrain rises around each cell.

For every cell of a coarse grid over the walk area (DEFAULT_HORIZON["cell_m"] cells) and
every direction (DEFAULT_HORIZON["direction_step_deg"] apart, clockwise from north), the
horizon angle is the highest angle at which the terrain is seen in that direction:

    horizon = max over distances d of  arctan( (h(d) - h0 - d^2 / (2 R)) / d )

    h0      height of the cell, h(d) height of the terrain d metres away (bilinear between cells)
    R       Mars radius of the DTM's map projection (curvature: far terrain sits lower)
    d       every cell_m metres, up to DEFAULT_HORIZON["max_distance_m"], inside the DTM only

A cell is in the shadow of the terrain when the sun is lower than its horizon in the sun's
direction (the app does this per time). Heights: the full HiRISE DTM averaged into cell_m
cells, so features smaller than a cell do not cast shadows here. Terrain outside the DTM
(for example the far crater rim) is not included.

Ground distances: the DTM is equirectangular with true scale at the equator, so one map metre
east-west is cos(latitude) metres on the ground at the site; this step corrects for that.

Outputs (data/work/<pack>/):
    horizon.npy     uint8 [direction, row, col]: angle / angle_step_deg; NO_DATA = 255.
                    Angles below 0 are stored as 0 (the app counts the sun as up only above 0).
    horizon.json    grid, directions, encoding, distances to the DTM edges, method

Usage:
    python -m pipeline.horizon [data/missions/<mission>.json]
"""

import json
import math
import os
import sys

import numpy
import rasterio
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject

from pipeline.mission import MissionPaths, load_mission, mission_path_from_arguments

NO_DATA = 255
DEFAULT_HORIZON = {"cell_m": 16, "direction_step_deg": 10, "max_distance_m": 10000, "angle_step_deg": 0.25}

METHOD = (
    "Horizon angle per 16 m cell in 36 directions (every 10°): the highest angle to the terrain, "
    "searched every 16 m up to 10 km inside the HiRISE DTM, with Mars curvature (d² / 2R). "
    "In shadow when the sun is lower than the horizon in the sun's direction (interpolated "
    "between the two nearest directions). Terrain outside the DTM is not included."
)


def horizon_paths(paths):
    return os.path.join(paths.work_dir, "horizon.npy"), os.path.join(paths.work_dir, "horizon.json")


def bilinear_shift(padded, row_shift, col_shift, row_start, col_start, rows, cols):
    """Heights of padded[row_start + i + row_shift, col_start + j + col_shift] for all i < rows, j < cols.

    The shift is the same for every cell, so the four bilinear neighbours are four slices.
    NaN where any neighbour has no height.
    """
    row_floor = math.floor(row_shift)
    col_floor = math.floor(col_shift)
    row_fraction = row_shift - row_floor
    col_fraction = col_shift - col_floor
    top = row_start + row_floor
    left = col_start + col_floor
    top_left = padded[top : top + rows, left : left + cols]
    top_right = padded[top : top + rows, left + 1 : left + 1 + cols]
    bottom_left = padded[top + 1 : top + 1 + rows, left : left + cols]
    bottom_right = padded[top + 1 : top + 1 + rows, left + 1 : left + 1 + cols]
    upper = top_left * (1.0 - col_fraction) + top_right * col_fraction
    lower = bottom_left * (1.0 - col_fraction) + bottom_right * col_fraction
    return upper * (1.0 - row_fraction) + lower * row_fraction


def horizon_angles(heights, target_origin, target_shape, cell_m, east_scale, radius_m, directions_deg, max_distance_m):
    """Horizon angle in degrees, shape [direction, rows, cols]; NaN where the cell has no height.

    heights        2-D heights (metres, NaN = no data) on cell_m map cells, covering the targets and around them
    target_origin  (row, col) of the first target cell inside heights
    target_shape   (rows, cols) of the target cells
    east_scale     ground metres per map metre east-west (cos of the latitude for this projection)
    """
    rows, cols = target_shape
    step_count = int(max_distance_m // cell_m)
    max_shift = int(math.ceil(step_count / max(east_scale, 1e-6))) + 2
    padded = numpy.pad(heights.astype(numpy.float32), max_shift, constant_values=numpy.nan)
    row_start = target_origin[0] + max_shift
    col_start = target_origin[1] + max_shift
    own_height = padded[row_start : row_start + rows, col_start : col_start + cols]
    result = numpy.full((len(directions_deg), rows, cols), numpy.nan, dtype=numpy.float32)
    for index, direction in enumerate(directions_deg):
        ground_east = math.sin(math.radians(direction))
        ground_north = math.cos(math.radians(direction))
        best_tangent = numpy.full((rows, cols), -numpy.inf, dtype=numpy.float32)
        for step in range(1, step_count + 1):
            distance = step * cell_m
            col_shift = distance * ground_east / east_scale / cell_m
            row_shift = -distance * ground_north / cell_m
            far_height = bilinear_shift(padded, row_shift, col_shift, row_start, col_start, rows, cols)
            tangent = (far_height - own_height - distance * distance / (2.0 * radius_m)) / distance
            numpy.fmax(best_tangent, tangent, out=best_tangent)  # fmax ignores NaN (no terrain there)
        angle = numpy.degrees(numpy.arctan(best_tangent))
        angle[~numpy.isfinite(own_height)] = numpy.nan
        result[index] = angle
    return result


def encode_horizon(angles, angle_step_deg):
    """uint8 codes: round(angle / step), angles below 0 as 0, NaN as NO_DATA."""
    codes = numpy.full(angles.shape, NO_DATA, dtype=numpy.uint8)
    has_value = numpy.isfinite(angles)
    clipped = numpy.clip(angles[has_value], 0.0, (NO_DATA - 1) * angle_step_deg)
    codes[has_value] = numpy.rint(clipped / angle_step_deg).astype(numpy.uint8)
    return codes


def coarse_heights(raw_dtm_path, walk_transform, cell_m):
    """The full raw DTM averaged into cell_m cells aligned with the walk-area grid.

    Returns heights, (row, col) of the walk-area origin inside them, and the coarse transform.
    """
    with rasterio.open(raw_dtm_path) as raw:
        walk_left = walk_transform.c
        walk_top = walk_transform.f
        cells_west = int((walk_left - raw.bounds.left) // cell_m)
        cells_north = int((raw.bounds.top - walk_top) // cell_m)
        left = walk_left - cells_west * cell_m
        top = walk_top + cells_north * cell_m
        width = int((raw.bounds.right - left) // cell_m)
        height = int((top - raw.bounds.bottom) // cell_m)
        transform = Affine(cell_m, 0.0, left, 0.0, -cell_m, top)
        heights = numpy.full((height, width), numpy.nan, dtype=numpy.float32)
        reproject(
            source=rasterio.band(raw, 1),
            destination=heights,
            src_transform=raw.transform,
            src_crs=raw.crs,
            src_nodata=raw.nodata,
            dst_transform=transform,
            dst_crs=raw.crs,
            dst_nodata=numpy.nan,
            resampling=Resampling.average,
        )
        raw_bounds = raw.bounds
    return heights, (cells_north, cells_west), raw_bounds


def main(mission_path):
    mission = load_mission(mission_path)
    paths = MissionPaths(mission)
    settings = DEFAULT_HORIZON
    cell_m = settings["cell_m"]
    with rasterio.open(paths.cropped_dtm) as dtm:
        walk_transform = dtm.transform
        walk_width, walk_height = dtm.width, dtm.height
        projection = dtm.crs.to_dict()
        walk_bounds = dtm.bounds
    if projection.get("proj") != "eqc" or projection.get("lat_ts", 0) != 0 or "R" not in projection:
        raise ValueError(f"horizon.py expects an equirectangular sphere with lat_ts 0, got {projection}")
    if abs(walk_transform.a - 1.0) > 1e-9 or abs(walk_transform.e + 1.0) > 1e-9:
        raise ValueError("horizon.py expects the 1 m walk-area grid")
    radius_m = float(projection["R"])
    with open(paths.grid, "r", encoding="utf-8") as grid_file:
        bounds_lonlat = json.load(grid_file)["bounds_lonlat"]
    centre_latitude = (bounds_lonlat[1] + bounds_lonlat[3]) / 2.0
    east_scale = math.cos(math.radians(centre_latitude))

    heights, origin, raw_bounds = coarse_heights(paths.dtm, walk_transform, cell_m)
    target_shape = (-(-walk_height // cell_m), -(-walk_width // cell_m))
    directions = list(range(0, 360, settings["direction_step_deg"]))
    print(f"Heights: {heights.shape[1]} x {heights.shape[0]} cells of {cell_m} m; "
          f"targets {target_shape[1]} x {target_shape[0]}; {len(directions)} directions")
    angles = horizon_angles(
        heights, origin, target_shape, cell_m, east_scale, radius_m, directions, settings["max_distance_m"]
    )
    codes = encode_horizon(angles, settings["angle_step_deg"])

    margins_m = {  # ground metres from the walk-area edge to the DTM edge
        "west": round((walk_bounds.left - raw_bounds.left) * east_scale),
        "east": round((raw_bounds.right - walk_bounds.right) * east_scale),
        "north": round(raw_bounds.top - walk_bounds.top),
        "south": round(walk_bounds.bottom - raw_bounds.bottom),
    }
    horizon_file, info_file = horizon_paths(paths)
    numpy.save(horizon_file, codes)
    info = {
        "cell_px": cell_m,  # walk-area grid cells (1 m) per horizon cell
        "width": target_shape[1],
        "height": target_shape[0],
        "directions_deg": directions,
        "angle_step_deg": settings["angle_step_deg"],
        "no_data_code": NO_DATA,
        "max_distance_m": settings["max_distance_m"],
        "radius_m": radius_m,
        "east_scale": east_scale,
        "dtm_margin_m": margins_m,
        "method": METHOD,
    }
    with open(info_file, "w", encoding="utf-8") as output:
        json.dump(info, output, indent=2)
    has_value = numpy.isfinite(angles)
    print(f"Horizon angles: max {float(numpy.nanmax(angles)):.2f} deg, mean {float(numpy.nanmean(numpy.maximum(angles, 0))):.2f} deg, "
          f"{int((~has_value[0]).sum())} cells without height")
    print(f"DTM reaches beyond the walk area (ground m): {margins_m}")
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
