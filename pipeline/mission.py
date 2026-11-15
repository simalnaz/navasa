"""A mission: one file that holds everything site- and walk-specific.

data/missions/<mission>.json
    id, name, status, objective      what the mission is for (set by the mission planner)
    objective_sources                where the objective's facts come from [{text, url?}]
    pack_id, pack_version            the data pack this mission builds (web/data/<pack_id>/)
    site                             name, the raw files (in data/raw/) and their credits:
                                       dtm_file, image_file, geology_file, unit_descriptions_file,
                                       image_source, image_product_id, dtm_source, dtm_product_id,
                                       geology_source, geology_product_id, as_of;
                                     optional thermal {...}, habitat {label, lat, lon, source} and
                                     surface_radius {radius_m, source} (for local gravity) and
                                     meda {source, product_id, url, as_of, sols: [{sol, stop_id,
                                     note, ats_file, tirs_file}]} (measured temperatures)
                                     (the habitat is the fixed end of the radio line-of-sight check)
    stops                            the stops in walking order: id, label, lat, lon,
                                     position_source, question, photos

Every pipeline step takes the mission file, so a new mission needs a new
mission file and its raw data, not code changes:

    python -m pipeline.run_mission data/missions/<mission>.json
"""

import json
import os
import sys

from pipeline.pack_format import is_text
from pipeline.stops import PROJECT_ROOT, StopsFileError, validate_stops

DEFAULT_MISSION_PATH = os.path.join(PROJECT_ROOT, "data", "missions", "jezero-biosignature.json")
PHOTOS_DIR = os.path.join(PROJECT_ROOT, "data", "raw", "photos")
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

REQUIRED_MISSION_FIELDS = (
    "id",
    "name",
    "status",
    "objective",
    "objective_sources",
    "pack_id",
    "pack_version",
    "site",
    "stops",
)
REQUIRED_SITE_FIELDS = (
    "name",
    "dtm_file",
    "image_file",
    "geology_file",
    "unit_descriptions_file",
    "image_source",
    "image_product_id",
    "dtm_source",
    "dtm_product_id",
    "geology_source",
    "geology_product_id",
    "as_of",
)
MISSION_STATUSES = ("ACTIVE", "PLANNED", "COMPLETE")


class MissionFileError(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("mission file has problems:\n  - " + "\n  - ".join(problems))


class MissionPaths:
    """Where a mission's inputs are read from and its outputs are written to."""

    def __init__(self, mission):
        site = mission["site"]
        self.dtm = os.path.join(RAW_DIR, site["dtm_file"])
        self.image = os.path.join(RAW_DIR, site["image_file"])
        self.geology_units = os.path.join(RAW_DIR, site["geology_file"])
        self.unit_descriptions = os.path.join(PROJECT_ROOT, site["unit_descriptions_file"])
        self.work_dir = os.path.join(PROJECT_ROOT, "data", "work", mission["pack_id"])
        self.pack_dir = os.path.join(PROJECT_ROOT, "web", "data", mission["pack_id"])
        self.cropped_dtm = os.path.join(self.work_dir, "dtm_1m.tif")
        self.grid = os.path.join(self.work_dir, "grid.json")
        self.slope = os.path.join(self.work_dir, "slope_deg.tif")
        self.routes = os.path.join(self.work_dir, "routes.json")
        self.geology_overlay = os.path.join(self.work_dir, "geology_overlay.png")
        self.geology_ids = os.path.join(self.work_dir, "geology_ids.png")
        self.geology_json = os.path.join(self.work_dir, "geology.json")
        self.image_tiles = os.path.join(self.pack_dir, "tiles", "hirise")


def check_mission(mission, project_root=PROJECT_ROOT, photos_dir=PHOTOS_DIR):
    """Return a list of problems; an empty list means the mission file is usable."""
    problems = []
    if not isinstance(mission, dict):
        return ["top level must be a JSON object"]
    for field_name in REQUIRED_MISSION_FIELDS:
        if field_name not in mission:
            problems.append(f"missing field {field_name!r}")
    if len(problems) > 0:
        return problems
    for text_field in ("id", "name", "objective", "pack_id", "pack_version"):
        if not is_text(mission[text_field]):
            problems.append(f"{text_field} must be text")
    if mission["status"] not in MISSION_STATUSES:
        problems.append(f"status must be one of {MISSION_STATUSES}")
    if not isinstance(mission["objective_sources"], list) or len(mission["objective_sources"]) == 0:
        problems.append("objective_sources must be a non-empty list: every objective needs a source")
    else:
        for index, source in enumerate(mission["objective_sources"]):
            if not isinstance(source, dict) or not is_text(source.get("text")):
                problems.append(f"objective source {index}: needs 'text'")
    site = mission["site"]
    if not isinstance(site, dict):
        problems.append("site must be an object")
    else:
        for field_name in REQUIRED_SITE_FIELDS:
            if not is_text(site.get(field_name)):
                problems.append(f"site {field_name!r} must be text")
    thermal = site.get("thermal") if isinstance(site, dict) else None
    if thermal is not None:
        for field_name in ("night_file", "day_file", "source", "product_id", "as_of"):
            if not isinstance(thermal, dict) or not is_text(thermal.get(field_name)):
                problems.append(f"site thermal {field_name!r} must be text")
    meda = site.get("meda") if isinstance(site, dict) else None
    if meda is not None:
        if not isinstance(meda, dict) or not all(is_text(meda.get(key)) for key in ("source", "product_id", "as_of")):
            problems.append("site meda needs 'source', 'product_id' and 'as_of' text")
        elif not isinstance(meda.get("sols"), list) or len(meda["sols"]) == 0:
            problems.append("site meda needs a non-empty 'sols' list")
        else:
            for index, entry in enumerate(meda["sols"]):
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("sol"), int)
                    or not is_text(entry.get("ats_file"))
                    or not is_text(entry.get("tirs_file"))
                ):
                    problems.append(f"site meda sol {index}: needs integer 'sol', 'ats_file' and 'tirs_file'")
                elif not os.path.isfile(os.path.join(RAW_DIR, entry["ats_file"])) or not os.path.isfile(os.path.join(RAW_DIR, entry["tirs_file"])):
                    problems.append(f"site meda sol {entry['sol']}: file not found in data/raw")
    surface = site.get("surface_radius") if isinstance(site, dict) else None
    if surface is not None and (not isinstance(surface, dict) or not isinstance(surface.get("radius_m"), (int, float)) or not is_text(surface.get("source"))):
        problems.append("site surface_radius needs numeric 'radius_m' and 'source' text")
    habitat = site.get("habitat") if isinstance(site, dict) else None
    if habitat is not None:
        if not isinstance(habitat, dict) or not is_text(habitat.get("label")) or not is_text(habitat.get("source")):
            problems.append("site habitat needs 'label' and 'source' text")
        elif not all(isinstance(habitat.get(key), (int, float)) for key in ("lat", "lon")):
            problems.append("site habitat needs numeric 'lat' and 'lon'")
    try:
        validate_stops(mission["stops"], project_root, photos_dir)
    except StopsFileError as error:
        problems.extend(error.problems)
    if isinstance(mission["stops"], list):
        for index, stop in enumerate(mission["stops"]):
            if isinstance(stop, dict) and not is_text(stop.get("question")):
                problems.append(f"stop {index + 1}: question must be text")
    return problems


def load_mission(mission_path=DEFAULT_MISSION_PATH):
    """Read and check a mission file. Return the mission or raise MissionFileError."""
    try:
        with open(mission_path, "r", encoding="utf-8") as mission_file:
            mission = json.load(mission_file)
    except (OSError, ValueError) as error:
        raise MissionFileError([f"cannot read {mission_path} ({error})"])
    problems = check_mission(mission)
    if len(problems) > 0:
        raise MissionFileError(problems)
    return mission


def mission_path_from_arguments():
    """The mission file given on the command line, or the default mission."""
    if len(sys.argv) > 1:
        return sys.argv[1]
    return DEFAULT_MISSION_PATH
