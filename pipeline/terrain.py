"""Slope in degrees from the cropped DTM.

Method: at each cell, the height change per metre towards east (dz/dx) and
towards north (dz/dy) is taken from the neighbouring cells (numpy.gradient:
central differences inside the grid, one-sided differences on its edges).
Slope is the angle of the steepest rise:

    slope = arctan( sqrt( (dz/dx)^2 + (dz/dy)^2 ) ), in degrees

A cell with no height, or next to one, has no slope (NaN). No limit or mask
is applied.

Input:  data/work/<pack>/dtm_1m.tif   (from crop_layers.py)
Output: data/work/<pack>/slope_deg.tif

Usage:
    python -m pipeline.terrain [data/missions/<mission>.json]
"""

import sys

import numpy
import rasterio

from pipeline.mission import MissionPaths, load_mission, mission_path_from_arguments


def slope_degrees(heights, cell_size_m):
    """Slope in degrees for a 2-D array of heights (metres). NaN heights give NaN slope."""
    rise_per_row, rise_per_col = numpy.gradient(heights.astype(numpy.float64), cell_size_m)
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
        if dtm.res[0] != dtm.res[1]:
            raise ValueError("DTM pixels are not square")
        cell_size_m = dtm.res[0]
        heights = read_heights(dtm)
        slope = slope_degrees(heights, cell_size_m)
        profile = dtm.profile.copy()
        profile.update(dtype="float32", nodata=numpy.nan)

    with rasterio.open(paths.slope, "w", **profile) as slope_file:
        slope_file.write(slope, 1)

    cells_with_slope = int(numpy.isfinite(slope).sum())
    print(f"Slope written to {paths.slope}")
    print(f"Cells with a slope: {cells_with_slope} of {slope.size}")
    print(f"Slope min {numpy.nanmin(slope):.2f} deg, max {numpy.nanmax(slope):.2f} deg, "
          f"mean {numpy.nanmean(slope):.2f} deg")
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
