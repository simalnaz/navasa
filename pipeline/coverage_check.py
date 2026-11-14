"""Print a YES/NO table: which data exists at each stop.

For each raster, YES means the stop lies inside the file and the file's own
mask says the pixel there holds data. Geology is not checked yet because no
approved library can read the SIM 3464 geodatabase.

Usage:
    python -m pipeline.coverage_check
"""

import os
import sys

import rasterio
from rasterio.windows import Window

from pipeline.stops import PROJECT_ROOT, StopsFileError, load_stops, lonlat_to_pixel

RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
RASTER_FILES = (
    ("25cm image", "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first.tif"),
    ("6m image", "JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0.tif"),
    ("1m DTM", "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif"),
)
GEOLOGY_NOT_CHECKED = "not checked (no reader)"


def raster_has_data(dataset, lon, lat):
    """True if (lon, lat) is inside the raster and its mask marks the pixel as data."""
    col, row = lonlat_to_pixel(dataset, lon, lat)
    if col < 0 or col >= dataset.width or row < 0 or row >= dataset.height:
        return False
    mask = dataset.read_masks(1, window=Window(col, row, 1, 1))
    return bool(mask[0, 0] > 0)


def photos_present(stop):
    for photo in stop["photos"]:
        if not os.path.isfile(os.path.join(PROJECT_ROOT, photo["file"])):
            return False
    return True


def yes_no(value):
    if value:
        return "YES"
    return "NO"


def main():
    try:
        stops = load_stops()
    except StopsFileError as error:
        print("Cannot check coverage, data/stops.json has problems:")
        for problem in error.problems:
            print(f"  - {problem}")
        return 1

    headers = ["stop"]
    for raster_name, _ in RASTER_FILES:
        headers.append(raster_name)
    headers.append("geology unit")
    headers.append("photos")

    rows = []
    datasets = []
    try:
        for _, file_name in RASTER_FILES:
            datasets.append(rasterio.open(os.path.join(RAW_DIR, file_name)))
        for stop in stops:
            row = [f"{stop['id']} {stop['label']}"]
            for dataset in datasets:
                row.append(yes_no(raster_has_data(dataset, stop["lon"], stop["lat"])))
            row.append(GEOLOGY_NOT_CHECKED)
            row.append(yes_no(photos_present(stop)))
            rows.append(row)
    finally:
        for dataset in datasets:
            dataset.close()

    column_widths = []
    for column_index, header in enumerate(headers):
        width = len(header)
        for row in rows:
            width = max(width, len(row[column_index]))
        column_widths.append(width)

    def format_line(cells):
        padded_cells = []
        for column_index, cell in enumerate(cells):
            padded_cells.append(cell.ljust(column_widths[column_index]))
        return " | ".join(padded_cells)

    print(format_line(headers))
    print("-+-".join("-" * width for width in column_widths))
    for row in rows:
        print(format_line(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
