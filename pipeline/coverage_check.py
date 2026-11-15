"""Print a YES/NO table: which data exists at each stop.

For each raster named in the mission file (orthoimage, DTM), YES means the stop
lies inside the file and the file's own mask says the pixel there holds data.
The geology column shows the unit found by geology.py (run it first).

Usage:
    python -m pipeline.coverage_check [data/missions/<mission>.json]
"""

import json
import os
import sys

import rasterio
from rasterio.windows import Window

from pipeline.mission import MissionFileError, MissionPaths, load_mission, mission_path_from_arguments
from pipeline.stops import PROJECT_ROOT, lonlat_to_pixel

GEOLOGY_NOT_RUN = "not checked (run geology.py)"


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


def geology_by_stop(paths):
    """Unit symbol at each stop from geology.py's output, or None if it has not run."""
    if not os.path.isfile(paths.geology_json):
        return None
    with open(paths.geology_json, "r", encoding="utf-8") as geology_file:
        geology = json.load(geology_file)
    symbols = {}
    for unit in geology["units"]:
        symbols[unit["id"]] = unit["symbol"]
    result = {}
    for stop_id, unit_id in geology["stop_units"].items():
        result[stop_id] = symbols.get(unit_id, "NO")
    return result


def main(mission_path):
    try:
        mission = load_mission(mission_path)
    except MissionFileError as error:
        print("Cannot check coverage, the mission file has problems:")
        for problem in error.problems:
            print(f"  - {problem}")
        return 1
    paths = MissionPaths(mission)
    stops = mission["stops"]
    raster_files = (("image", paths.image), ("DTM", paths.dtm))
    units = geology_by_stop(paths)

    headers = ["stop"]
    for raster_name, _ in raster_files:
        headers.append(raster_name)
    headers.append("geology unit")
    headers.append("photos")

    rows = []
    datasets = []
    try:
        for _, raster_path in raster_files:
            datasets.append(rasterio.open(raster_path))
        for stop in stops:
            row = [f"{stop['id']} {stop['label']}"]
            for dataset in datasets:
                row.append(yes_no(raster_has_data(dataset, stop["lon"], stop["lat"])))
            if units is None:
                row.append(GEOLOGY_NOT_RUN)
            else:
                row.append(units.get(str(stop["id"]), "NO"))
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
    sys.exit(main(mission_path_from_arguments()))
