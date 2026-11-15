"""Slope in degrees from the cropped DTM.

Method: at each cell, the height change per ground metre towards east (dz/dx)
and towards north (dz/dy) is taken from the neighbouring cells (numpy.gradient:
central differences inside the grid, one-sided differences on its edges).

Ground cell size: the DTM is equirectangular with true scale at the equator, so
a cell is res metres north-south but res * cos(latitude) ground metres east-west
(0.948 m at Jezero, 18.47 N). ground_cell_size_m gives both; the latitude is the
walk area's centre (cos changes by under 0.1 % across it).
Slope is the angle of the steepest rise:

    slope = arctan( sqrt( (dz/dx)^2 + (dz/dy)^2 ) ), in degrees

A cell with no height, or next to one, has no slope (NaN). No limit or mask
is applied.

Input:  data/work/<pack>/dtm_1m.tif   (from crop_layers.py)
Output: data/work/<pack>/slope_deg.tif

Usage:
    python -m pipeline.terrain [data/missions/<mission>.json]
"""

import math
import sys

import numpy
import rasterio
from rasterio.warp import transform as transform_points

from pipeline.mission import MissionPaths, load_mission, mission_path_from_arguments


def ground_cell_size_m(dtm):
    """(north_m, east_m): ground size of one DTM cell, for an equirectangular sphere with lat_ts 0."""
    projection = dtm.crs.to_dict()
    if projection.get("proj") != "eqc" or projection.get("lat_ts", 0) != 0 or "R" not in projection:
        raise ValueError(f"expected an equirectangular sphere with lat_ts 0, got {projection}")
    if dtm.res[0] != dtm.res[1]:
        raise ValueError("DTM pixels are not square")
    centre_x = (dtm.bounds.left + dtm.bounds.right) / 2.0
    centre_y = (dtm.bounds.bottom + dtm.bounds.top) / 2.0
    _, latitudes = transform_points(dtm.crs, {"proj": "longlat", "R": projection["R"], "no_defs": True}, [centre_x], [centre_y])
    return dtm.res[1], dtm.res[0] * math.cos(math.radians(latitudes[0]))


def slope_degrees(heights, cell_size_m, cell_east_m=None):
    """Slope in degrees for a 2-D array of heights (metres). NaN heights give NaN slope.

    cell_size_m is the north-south cell size; cell_east_m the east-west one (same if None).
    """
    if cell_east_m is None:
        cell_east_m = cell_size_m
    rise_per_row, rise_per_col = numpy.gradient(heights.astype(numpy.float64), cell_size_m, cell_east_m)
    steepest_rise = numpy.hypot(rise_per_col, rise_per_row)
    slope = numpy.degrees(numpy.arctan(steepest_rise)).astype(numpy.float32)
    # Central differences skip the cell itself, so a cell without a height needs its own check.
    slope[numpy.isnan(heights)] = numpy.nan
    return slope


def read_heights(dtm):
    """Heights as float64 with the file's no-data cells set to NaN."""
    heights = dtm.read(1).astype(numpy.float64)
    if dtm.nodata is not None:
        heights[heights == dtm.nodata] = numpy.nan
    return heights


def main(mission_path):
    paths = MissionPaths(load_mission(mission_path))
    with rasterio.open(paths.cropped_dtm) as dtm:
        cell_north_m, cell_east_m = ground_cell_size_m(dtm)
        heights = read_heights(dtm)
        slope = slope_degrees(heights, cell_north_m, cell_east_m)
        profile = dtm.profile.copy()
        profile.update(dtype="float32", nodata=numpy.nan)

    with rasterio.open(paths.slope, "w", **profile) as slope_file:
        slope_file.write(slope, 1)

    cells_with_slope = int(numpy.isfinite(slope).sum())
    print(f"Ground cell size: {cell_north_m:.4f} m north-south, {cell_east_m:.4f} m east-west")
    print(f"Slope written to {paths.slope}")
    print(f"Cells with a slope: {cells_with_slope} of {slope.size}")
    print(f"Slope min {numpy.nanmin(slope):.2f} deg, max {numpy.nanmax(slope):.2f} deg, "
          f"mean {numpy.nanmean(slope):.2f} deg")
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
