"""Data pack format and validation.

A data pack is a folder of static files that the web app reads. The pipeline
writes it; the app only displays it. Every pack has this layout:

    <pack>/
      manifest.json   table of contents (described below)
      stops.json      the stops
      routes.json     the routes between stops
      ...             layer images, map tiles and photos referenced above

manifest.json
    id, version      pack name and version, e.g. "jezero_v1", "1.0.0"
    created          date the pack was built, "YYYY-MM-DD"
    site             name, bounds_px [col_min, row_min, col_max, row_max],
                     bounds_lonlat [west, south, east, north]
    grid             width, height (pixels), metres_per_pixel (north-south), optional
                     east_scale (ground metres per grid metre east-west, 0-1]
    layers           list of layers (below)

Each layer has: id, kind (LAYER_KINDS), units, legend, source, product_id,
as_of, label (VALUE_LABELS), and exactly one of:
    file    a path inside the pack
    tiles   imagery and raster layers: url ("tiles/<name>/{z}/{x}/{y}.png"),
            min_zoom, max_zoom, tile_size. At zoom z, one grid pixel is 2**z
            tile pixels.
A CALCULATED layer also has "method": how it was calculated.
Optional manifest field "methods": {name: text} for calculations that are not
layers (for example the routes).
Optional manifest field "readouts": [{"id", "file", "units", "base", "step",
"sample_every_px", "no_data_code", "label", "source"}]: images holding cursor
readout values as 16-bit codes (value = base + code * step).
Optional manifest field "horizon": terrain horizon angles for sun and shadow
(pipeline/horizon.py): cell_px, width, height, directions_deg, angle_step_deg,
no_data_code, method, label, source and files [{"file", "directions_deg"}]:
RGB images, one direction per colour channel, angle = code * angle_step_deg.

Positions are pixel [col, row] on the grid, counted from the top-left corner.

stops.json   [{"id", "label", "position", "position_source", "ground_slope_deg",
               "unit": {"symbol", "name", "description"},
               "photos": [{"file", "sol", "camera", "image_id", "credit"}]}]
             photo file is a path inside the pack; ground_slope_deg, unit,
             unit description and image_id may be null (no data).
mission.json (optional) {"id", "name", "status", "objective", "objective_sources",
             "site", "questions": [{"stop_id", "question"}]}
routes.json  [{"from", "to", "shortest": route, "gentlest": route}]
             route: {"points": [[col, row], ...], "distance_m", "climb_m",
                     "descent_m", "max_slope_deg", "max_slope_at": [col, row]}
             A route is null when there is no terrain data for it.

Usage:
    python -m pipeline.pack_format web/data/jezero_v1
"""

import json
import os
import sys

MANIFEST_FILE_NAME = "manifest.json"
STOPS_FILE_NAME = "stops.json"
ROUTES_FILE_NAME = "routes.json"

LAYER_KINDS = (
    "imagery",
    "raster-continuous",
    "raster-categorical",
    "vector",
    "points",
)
TILED_KINDS = ("imagery", "raster-continuous", "raster-categorical")
VALUE_LABELS = ("NASA DATA", "CALCULATED")
CALCULATED_LABEL = "CALCULATED"
ROUTE_TYPES = ("shortest", "gentlest")

REQUIRED_PACK_FIELDS = ("id", "version", "created", "site", "grid", "layers")
REQUIRED_SITE_FIELDS = ("name", "bounds_px", "bounds_lonlat")
REQUIRED_GRID_FIELDS = ("width", "height", "metres_per_pixel")
REQUIRED_LAYER_FIELDS = (
    "id",
    "kind",
    "units",
    "legend",
    "source",
    "product_id",
    "as_of",
    "label",
)
REQUIRED_READOUT_FIELDS = (
    "id",
    "file",
    "units",
    "base",
    "step",
    "sample_every_px",
    "no_data_code",
    "label",
    "source",
)
REQUIRED_TILES_FIELDS = ("url", "min_zoom", "max_zoom", "tile_size")
REQUIRED_TILE_PLACEHOLDERS = ("{z}", "{x}", "{y}")
REQUIRED_STOP_FIELDS = (
    "id",
    "label",
    "position",
    "position_source",
    "ground_slope_deg",
    "unit",
    "photos",
)
REQUIRED_UNIT_FIELDS = ("symbol", "name", "description")
REQUIRED_PHOTO_FIELDS = ("file", "sol", "camera", "image_id", "credit")
REQUIRED_LEG_FIELDS = ("from", "to") + ROUTE_TYPES
REQUIRED_ROUTE_FIELDS = (
    "points",
    "distance_m",
    "climb_m",
    "descent_m",
    "max_slope_deg",
    "max_slope_at",
)
ROUTE_NUMBER_FIELDS = ("distance_m", "climb_m", "descent_m", "max_slope_deg")


def is_number(value):
    """True for int or float. bool is excluded although Python treats it as an int."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def is_integer(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, int)


def is_text(value):
    return isinstance(value, str) and value.strip() != ""


def resolve_inside_folder(folder, relative_path):
    """Return the absolute path of relative_path, or None if it leaves the folder."""
    if not isinstance(relative_path, str) or relative_path == "":
        return None
    if os.path.isabs(relative_path):
        return None
    folder_root = os.path.realpath(folder)
    full_path = os.path.realpath(os.path.join(folder_root, relative_path))
    if not full_path.startswith(folder_root + os.sep):
        return None
    return full_path


def check_pack_file(pack_dir, relative_path, where, errors):
    """Check that a referenced file is inside the pack and exists. Return its path or None."""
    full_path = resolve_inside_folder(pack_dir, relative_path)
    if full_path is None:
        errors.append(f"{where}: path {relative_path!r} is not inside the pack")
        return None
    if not os.path.isfile(full_path):
        errors.append(f"{where}: file {relative_path!r} does not exist")
        return None
    return full_path


def load_json_file(path, where, expected_type, errors):
    """Read JSON of expected_type (dict or list). Return None and record an error on failure."""
    if not os.path.isfile(path):
        errors.append(f"{where}: {os.path.basename(path)} not found")
        return None
    try:
        with open(path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    except (OSError, ValueError) as error:
        errors.append(f"{where}: cannot read JSON ({error})")
        return None
    if not isinstance(data, expected_type):
        errors.append(f"{where}: top level must be a JSON {expected_type.__name__}")
        return None
    return data


def check_required_fields(data, required_fields, where, errors):
    """Record an error for each required field missing from data. True if all present."""
    all_present = True
    for field_name in required_fields:
        if field_name not in data:
            errors.append(f"{where}: missing field {field_name!r}")
            all_present = False
    return all_present


def check_number_list(value, expected_length, where, errors):
    if not isinstance(value, list) or len(value) != expected_length:
        errors.append(f"{where}: must be a list of {expected_length} numbers")
        return False
    for item in value:
        if not is_number(item):
            errors.append(f"{where}: must be a list of {expected_length} numbers")
            return False
    return True


def check_position(position, grid, where, errors):
    """A position is [col, row] inside the grid."""
    if not check_number_list(position, 2, where, errors):
        return
    if grid is None:
        return
    col, row = position
    if col < 0 or col >= grid["width"] or row < 0 or row >= grid["height"]:
        errors.append(f"{where}: position {position} is outside the grid")


def check_site(site, errors):
    if not isinstance(site, dict):
        errors.append("manifest site: must be an object")
        return
    if not check_required_fields(site, REQUIRED_SITE_FIELDS, "manifest site", errors):
        return
    check_number_list(site["bounds_px"], 4, "manifest site bounds_px", errors)
    check_number_list(site["bounds_lonlat"], 4, "manifest site bounds_lonlat", errors)


def check_grid(grid, errors):
    """Return the grid if it is usable for position checks, else None."""
    if not isinstance(grid, dict):
        errors.append("manifest grid: must be an object")
        return None
    if not check_required_fields(grid, REQUIRED_GRID_FIELDS, "manifest grid", errors):
        return None
    grid_is_valid = True
    for size_field in ("width", "height"):
        size = grid[size_field]
        if not is_integer(size) or size <= 0:
            errors.append(f"manifest grid {size_field}: must be a positive integer")
            grid_is_valid = False
    metres_per_pixel = grid["metres_per_pixel"]
    if not is_number(metres_per_pixel) or metres_per_pixel <= 0:
        errors.append("manifest grid metres_per_pixel: must be a positive number")
        grid_is_valid = False
    if "east_scale" in grid and (not is_number(grid["east_scale"]) or not 0 < grid["east_scale"] <= 1):
        errors.append("manifest grid east_scale: must be a number in (0, 1]")
        grid_is_valid = False
    if not grid_is_valid:
        return None
    return grid


def check_tiles(pack_dir, tiles, where, errors):
    if not isinstance(tiles, dict):
        errors.append(f"{where} tiles: must be an object")
        return
    if not check_required_fields(tiles, REQUIRED_TILES_FIELDS, f"{where} tiles", errors):
        return
    url = tiles["url"]
    if not isinstance(url, str):
        errors.append(f"{where} tiles url: must be a string")
        return
    for placeholder in REQUIRED_TILE_PLACEHOLDERS:
        if placeholder not in url:
            errors.append(f"{where} tiles url: missing {placeholder}")
    tile_folder = url.split("{")[0]
    folder_path = resolve_inside_folder(pack_dir, tile_folder)
    if folder_path is None:
        errors.append(f"{where} tiles url: {url!r} is not inside the pack")
    elif not os.path.isdir(folder_path):
        errors.append(f"{where} tiles url: folder {tile_folder!r} does not exist")
    for integer_field in ("min_zoom", "max_zoom", "tile_size"):
        if not is_integer(tiles[integer_field]):
            errors.append(f"{where} tiles {integer_field}: must be an integer")


def check_layer(pack_dir, layer, index, errors):
    where = f"manifest layer {index}"
    if not isinstance(layer, dict):
        errors.append(f"{where}: must be an object")
        return
    if not check_required_fields(layer, REQUIRED_LAYER_FIELDS, where, errors):
        return
    where = f"manifest layer {layer['id']!r}"
    if layer["kind"] not in LAYER_KINDS:
        errors.append(f"{where}: kind {layer['kind']!r} is not one of {LAYER_KINDS}")
    if layer["label"] not in VALUE_LABELS:
        errors.append(f"{where}: label {layer['label']!r} is not one of {VALUE_LABELS}")
    if layer["label"] == CALCULATED_LABEL and not is_text(layer.get("method")):
        errors.append(f"{where}: a CALCULATED layer needs a 'method'")

    has_file = "file" in layer
    has_tiles = "tiles" in layer
    if has_file and has_tiles:
        errors.append(f"{where}: must have either 'file' or 'tiles', not both")
    elif has_file:
        check_pack_file(pack_dir, layer["file"], where, errors)
    elif has_tiles:
        if layer["kind"] not in TILED_KINDS:
            errors.append(f"{where}: only {TILED_KINDS} layers can use tiles")
        check_tiles(pack_dir, layer["tiles"], where, errors)
    else:
        errors.append(f"{where}: needs 'file' or 'tiles'")


def check_layers(pack_dir, layers, errors):
    if not isinstance(layers, list):
        errors.append("manifest layers: must be a list")
        return
    seen_layer_ids = set()
    for index, layer in enumerate(layers):
        if isinstance(layer, dict) and "id" in layer:
            if layer["id"] in seen_layer_ids:
                errors.append(f"manifest layers: duplicate id {layer['id']!r}")
            seen_layer_ids.add(layer["id"])
        check_layer(pack_dir, layer, index, errors)


def check_photo(pack_dir, photo, where, errors):
    if not isinstance(photo, dict):
        errors.append(f"{where}: must be an object")
        return
    if not check_required_fields(photo, REQUIRED_PHOTO_FIELDS, where, errors):
        return
    check_pack_file(pack_dir, photo["file"], where, errors)
    if not is_integer(photo["sol"]):
        errors.append(f"{where}: sol must be an integer")
    if not is_text(photo["camera"]):
        errors.append(f"{where}: camera must be text")
    if photo["image_id"] is not None and not is_text(photo["image_id"]):
        errors.append(f"{where}: image_id must be text or null")
    if not is_text(photo["credit"]):
        errors.append(f"{where}: credit must be text")


def check_unit(unit, where, errors):
    if unit is None:
        return
    if not isinstance(unit, dict):
        errors.append(f"{where}: must be an object or null")
        return
    if not check_required_fields(unit, REQUIRED_UNIT_FIELDS, where, errors):
        return
    if not is_text(unit["symbol"]) or not is_text(unit["name"]):
        errors.append(f"{where}: symbol and name must be text")
    if unit["description"] is not None and not is_text(unit["description"]):
        errors.append(f"{where}: description must be text or null")


def check_stops(pack_dir, stops, grid, errors):
    """Return the set of stop ids found, for checking route legs."""
    stop_ids = set()
    for index, stop in enumerate(stops):
        where = f"stop {index}"
        if not isinstance(stop, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not check_required_fields(stop, REQUIRED_STOP_FIELDS, where, errors):
            continue
        where = f"stop {stop['id']!r}"
        if not is_integer(stop["id"]):
            errors.append(f"{where}: id must be an integer")
        elif stop["id"] in stop_ids:
            errors.append(f"stops: duplicate id {stop['id']!r}")
        stop_ids.add(stop["id"])
        if not is_text(stop["label"]):
            errors.append(f"{where}: label must be text")
        if not is_text(stop["position_source"]):
            errors.append(f"{where}: position_source must be text")
        check_position(stop["position"], grid, f"{where} position", errors)
        ground_slope = stop["ground_slope_deg"]
        if ground_slope is not None and not is_number(ground_slope):
            errors.append(f"{where}: ground_slope_deg must be a number or null")
        check_unit(stop["unit"], f"{where} unit", errors)
        photos = stop["photos"]
        if not isinstance(photos, list) or len(photos) == 0:
            errors.append(f"{where}: photos must be a non-empty list")
            continue
        for photo_index, photo in enumerate(photos):
            check_photo(pack_dir, photo, f"{where} photo {photo_index}", errors)
    return stop_ids


def check_route(route, grid, where, errors):
    if route is None:
        return
    if not isinstance(route, dict):
        errors.append(f"{where}: must be an object or null")
        return
    if not check_required_fields(route, REQUIRED_ROUTE_FIELDS, where, errors):
        return
    points = route["points"]
    if not isinstance(points, list) or len(points) < 2:
        errors.append(f"{where}: points must be a list of at least 2 positions")
    else:
        for point_index, point in enumerate(points):
            check_position(point, grid, f"{where} point {point_index}", errors)
    for number_field in ROUTE_NUMBER_FIELDS:
        if not is_number(route[number_field]):
            errors.append(f"{where}: {number_field} must be a number")
    check_position(route["max_slope_at"], grid, f"{where} max_slope_at", errors)


def check_routes(legs, stop_ids, grid, errors):
    for index, leg in enumerate(legs):
        where = f"route leg {index}"
        if not isinstance(leg, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not check_required_fields(leg, REQUIRED_LEG_FIELDS, where, errors):
            continue
        for end_field in ("from", "to"):
            if leg[end_field] not in stop_ids:
                errors.append(f"{where}: {end_field} {leg[end_field]!r} is not a known stop")
        for route_type in ROUTE_TYPES:
            check_route(leg[route_type], grid, f"{where} {route_type}", errors)


def check_readouts(pack_dir, readouts, errors):
    if not isinstance(readouts, list):
        errors.append("manifest readouts: must be a list")
        return
    for index, readout in enumerate(readouts):
        where = f"manifest readout {index}"
        if not isinstance(readout, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not check_required_fields(readout, REQUIRED_READOUT_FIELDS, where, errors):
            continue
        check_pack_file(pack_dir, readout["file"], where, errors)
        if not is_number(readout["base"]) or not is_number(readout["step"]) or readout["step"] <= 0:
            errors.append(f"{where}: base must be a number and step a positive number")
        if not is_integer(readout["sample_every_px"]) or readout["sample_every_px"] <= 0:
            errors.append(f"{where}: sample_every_px must be a positive integer")
        if readout["label"] not in VALUE_LABELS:
            errors.append(f"{where}: label {readout['label']!r} is not one of {VALUE_LABELS}")


REQUIRED_HORIZON_FIELDS = (
    "cell_px", "width", "height", "directions_deg", "angle_step_deg", "no_data_code", "method", "label", "source", "files",
)


def check_horizon(pack_dir, horizon, grid, errors):
    if not isinstance(horizon, dict) or not check_required_fields(horizon, REQUIRED_HORIZON_FIELDS, "manifest horizon", errors):
        return
    for field_name in ("cell_px", "width", "height"):
        if not is_integer(horizon[field_name]) or horizon[field_name] <= 0:
            errors.append(f"manifest horizon: {field_name} must be a positive integer")
            return
    if grid is not None and (horizon["width"] * horizon["cell_px"] < grid["width"] or horizon["height"] * horizon["cell_px"] < grid["height"]):
        errors.append("manifest horizon: does not cover the grid")
    if horizon["label"] != CALCULATED_LABEL:
        errors.append("manifest horizon: label must be CALCULATED")
    listed = []
    for index, horizon_file in enumerate(horizon["files"]):
        where = f"manifest horizon file {index}"
        if not isinstance(horizon_file, dict) or not check_required_fields(horizon_file, ("file", "directions_deg"), where, errors):
            continue
        check_pack_file(pack_dir, horizon_file["file"], where, errors)
        if not isinstance(horizon_file["directions_deg"], list) or not 1 <= len(horizon_file["directions_deg"]) <= 3:
            errors.append(f"{where}: directions_deg must list 1 to 3 directions")
            continue
        listed.extend(horizon_file["directions_deg"])
    if listed != horizon["directions_deg"]:
        errors.append("manifest horizon: files must hold directions_deg in order")


REQUIRED_PACK_MISSION_FIELDS = ("id", "name", "status", "objective", "objective_sources", "site", "questions")


def check_pack_mission(pack_mission, stop_ids, errors):
    if not check_required_fields(pack_mission, REQUIRED_PACK_MISSION_FIELDS, "mission", errors):
        return
    for text_field in ("id", "name", "status", "objective", "site"):
        if not is_text(pack_mission[text_field]):
            errors.append(f"mission: {text_field} must be text")
    if not isinstance(pack_mission["objective_sources"], list) or len(pack_mission["objective_sources"]) == 0:
        errors.append("mission: objective_sources must be a non-empty list")
    if not isinstance(pack_mission["questions"], list):
        errors.append("mission: questions must be a list")
        return
    for index, question in enumerate(pack_mission["questions"]):
        if not isinstance(question, dict) or question.get("stop_id") not in stop_ids or not is_text(question.get("question")):
            errors.append(f"mission question {index}: needs a known stop_id and question text")


def validate_pack(pack_dir):
    """Check a data pack folder. Return a list of problems; an empty list means valid."""
    errors = []
    manifest_path = os.path.join(pack_dir, MANIFEST_FILE_NAME)
    manifest = load_json_file(manifest_path, "manifest", dict, errors)
    if manifest is None:
        return errors
    if not check_required_fields(manifest, REQUIRED_PACK_FIELDS, "manifest", errors):
        return errors

    check_site(manifest["site"], errors)
    grid = check_grid(manifest["grid"], errors)
    if "readouts" in manifest:
        check_readouts(pack_dir, manifest["readouts"], errors)
    if "methods" in manifest:
        methods = manifest["methods"]
        if not isinstance(methods, dict):
            errors.append("manifest methods: must be an object")
        else:
            for method_name, method_text in methods.items():
                if not is_text(method_text):
                    errors.append(f"manifest methods {method_name!r}: must be text")
    check_layers(pack_dir, manifest["layers"], errors)
    if "horizon" in manifest:
        check_horizon(pack_dir, manifest["horizon"], grid, errors)

    stop_ids = set()
    stops = load_json_file(os.path.join(pack_dir, STOPS_FILE_NAME), "stops", list, errors)
    if stops is not None:
        stop_ids = check_stops(pack_dir, stops, grid, errors)

    mission_path = os.path.join(pack_dir, "mission.json")
    if os.path.isfile(mission_path):
        pack_mission = load_json_file(mission_path, "mission", dict, errors)
        if pack_mission is not None:
            check_pack_mission(pack_mission, stop_ids, errors)

    legs = load_json_file(os.path.join(pack_dir, ROUTES_FILE_NAME), "routes", list, errors)
    if legs is not None:
        check_routes(legs, stop_ids, grid, errors)

    return errors


def main():
    if len(sys.argv) != 2:
        print("usage: python -m pipeline.pack_format <pack folder>")
        return 2
    pack_dir = sys.argv[1]
    errors = validate_pack(pack_dir)
    if len(errors) > 0:
        print(f"INVALID pack {pack_dir}: {len(errors)} problem(s)")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"VALID pack {pack_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
