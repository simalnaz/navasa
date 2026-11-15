"""Check the stops of a mission, and convert stop positions to map pixels.

Each stop (in the mission file, see mission.py) has its label, latitude/longitude,
where the position came from (position_source), and the Perseverance photos for
that stop. A missing value is an error that says what to add; nothing is filled in.
"""

import os

from rasterio.crs import CRS
from rasterio.warp import transform

from pipeline.pack_format import is_integer, is_number, is_text, resolve_inside_folder

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PHOTOS_DIR = os.path.join(PROJECT_ROOT, "data", "raw", "photos")

REQUIRED_STOP_FIELDS = ("id", "label", "lat", "lon", "position_source", "photos")
REQUIRED_PHOTO_FIELDS = ("file", "sol", "camera", "image_id")


class StopsFileError(Exception):
    """The stops are missing, unreadable or has invalid entries."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("stops file has problems:\n  - " + "\n  - ".join(problems))


def check_photo(photo, project_root, photos_dir, where, problems):
    if not isinstance(photo, dict):
        problems.append(f"{where}: must be an object")
        return
    missing_field = False
    for field_name in REQUIRED_PHOTO_FIELDS:
        if field_name not in photo:
            problems.append(f"{where}: missing field {field_name!r}")
            missing_field = True
    if missing_field:
        return
    photo_path = resolve_inside_folder(project_root, photo["file"])
    photos_root = os.path.realpath(photos_dir)
    if photo_path is None or not photo_path.startswith(photos_root + os.sep):
        problems.append(f"{where}: file {photo['file']!r} is not inside {photos_dir}")
    elif not os.path.isfile(photo_path):
        problems.append(f"{where}: file {photo['file']!r} does not exist")
    if not is_integer(photo["sol"]):
        problems.append(f"{where}: sol must be an integer")
    if not is_text(photo["camera"]):
        problems.append(f"{where}: camera must be text")
    if photo["image_id"] is not None and not is_text(photo["image_id"]):
        problems.append(f"{where}: image_id must be text or null")


def check_stop(stop, project_root, photos_dir, where, problems):
    if not isinstance(stop, dict):
        problems.append(f"{where}: must be an object")
        return
    missing_field = False
    for field_name in REQUIRED_STOP_FIELDS:
        if field_name not in stop:
            problems.append(f"{where}: missing field {field_name!r}")
            missing_field = True
    if missing_field:
        return
    if not is_integer(stop["id"]):
        problems.append(f"{where}: id must be an integer")
    if not is_text(stop["label"]):
        problems.append(f"{where}: label must be text")
    for coordinate_field in ("lat", "lon"):
        coordinate = stop[coordinate_field]
        if coordinate is None:
            problems.append(f"{where}: {coordinate_field} is empty - fill it in")
        elif not is_number(coordinate):
            problems.append(f"{where}: {coordinate_field} must be a number")
    if not is_text(stop["position_source"]):
        problems.append(f"{where}: position_source must be text")
    photos = stop["photos"]
    if not isinstance(photos, list) or len(photos) == 0:
        problems.append(f"{where}: photos must be a non-empty list")
        return
    for photo_index, photo in enumerate(photos):
        check_photo(photo, project_root, photos_dir, f"{where} photo {photo_index}", problems)


def validate_stops(stops, project_root=PROJECT_ROOT, photos_dir=DEFAULT_PHOTOS_DIR):
    """Check a list of stops (from a mission file). Return it or raise StopsFileError."""
    if not isinstance(stops, list) or len(stops) == 0:
        raise StopsFileError(["stops must be a non-empty list"])
    problems = []
    seen_ids = set()
    for index, stop in enumerate(stops):
        where = f"stop {index + 1}"
        check_stop(stop, project_root, photos_dir, where, problems)
        if isinstance(stop, dict) and "id" in stop:
            if stop["id"] in seen_ids:
                problems.append(f"{where}: duplicate id {stop['id']!r}")
            seen_ids.add(stop["id"])
    if len(problems) > 0:
        raise StopsFileError(problems)
    return stops


def lonlat_to_pixel(dataset, lon, lat):
    """Convert longitude/latitude (degrees) to pixel [col, row] of an open raster.

    The latitude/longitude system is built from the raster's own coordinate
    system (its sphere radius), so no outside value is used.
    """
    crs_parameters = dataset.crs.to_dict()
    if "R" not in crs_parameters:
        raise ValueError(f"{dataset.name}: coordinate system has no sphere radius 'R'")
    lonlat_crs = CRS.from_dict({"proj": "longlat", "R": crs_parameters["R"], "no_defs": True})
    map_xs, map_ys = transform(lonlat_crs, dataset.crs, [lon], [lat])
    row, col = dataset.index(map_xs[0], map_ys[0])
    return [int(col), int(row)]


