"""THEMIS thermal infrared on the walk-area grid.

Source (named in the mission file, site.thermal): THEMIS Night IR and Day IR controlled
mosaics, 100 m/pixel, 8-bit qualitative (brighter = warmer surface when observed),
2001 Mars Odyssey (NASA/JPL/Arizona State University), mosaics by USGS Astrogeology,
as included in the USGS SIM 3464 database.

Each mosaic is re-projected (nearest pixel, no blending) onto a coarse grid of
DEFAULT_THERMAL["cell_px"] x DEFAULT_THERMAL["cell_px"] walk-area cells: the source
pixels are 100 m, so no detail is lost. Cells outside the mosaic get NO_DATA.

Outputs (data/work/<pack>/): thermal_night.tif, thermal_day.tif (uint16, NO_DATA = 65535)

Usage:
    python -m pipeline.thermal [data/missions/<mission>.json]
"""

import os
import sys

import numpy
import rasterio
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject

from pipeline.mission import RAW_DIR, MissionPaths, load_mission, mission_path_from_arguments

NO_DATA = 65535
DEFAULT_THERMAL = {"cell_px": 8}
THERMAL_KINDS = ("night", "day")


def thermal_paths(paths):
    result = {}
    for kind in THERMAL_KINDS:
        result[kind] = os.path.join(paths.work_dir, f"thermal_{kind}.tif")
    return result


def reproject_to_grid(source_path, grid_transform, grid_crs, out_shape):
    """Source mosaic values on the coarse grid; NO_DATA outside the mosaic."""
    destination = numpy.full(out_shape, NO_DATA, dtype=numpy.uint16)
    with rasterio.open(source_path) as source:
        values = source.read(1).astype(numpy.uint16)
        reproject(
            source=values,
            destination=destination,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=source.nodata,
            dst_transform=grid_transform,
            dst_crs=grid_crs,
            dst_nodata=NO_DATA,
            resampling=Resampling.nearest,
        )
    return destination


def main(mission_path):
    mission = load_mission(mission_path)
    thermal = mission["site"].get("thermal")
    if thermal is None:
        print("Mission has no thermal data (site.thermal): skipped")
        return 0
    paths = MissionPaths(mission)
    cell = DEFAULT_THERMAL["cell_px"]
    with rasterio.open(paths.cropped_dtm) as dtm:
        grid_crs = dtm.crs
        coarse_transform = dtm.transform * Affine.scale(cell)
        out_shape = (-(-dtm.height // cell), -(-dtm.width // cell))
        profile = dtm.profile.copy()
    profile.update(
        width=out_shape[1], height=out_shape[0], transform=coarse_transform, dtype="uint16", nodata=NO_DATA, count=1
    )
    outputs = thermal_paths(paths)
    for kind in THERMAL_KINDS:
        source_path = os.path.join(RAW_DIR, thermal[f"{kind}_file"])
        values = reproject_to_grid(source_path, coarse_transform, grid_crs, out_shape)
        with rasterio.open(outputs[kind], "w", **profile) as output:
            output.write(values, 1)
        has_data = values != NO_DATA
        print(
            f"THEMIS {kind}: {out_shape[1]} x {out_shape[0]} cells of {cell} m, "
            f"{int((~has_data).sum())} without data, values {int(values[has_data].min())}-{int(values[has_data].max())}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
