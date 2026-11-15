"""Write the data pack the web app reads, then check it with validate_pack.

Run after crop_layers.py, terrain.py, routes.py and geology.py (or use
run_mission.py). Writes into web/data/<pack>/:
    mission.json        the mission: name, status, objective and its sources, stop questions
    manifest.json       site, grid, layers (with sources and methods), methods of the routes
    stops.json          stops with grid position, ground slope, rock unit and photos
    routes.json         shortest and gentlest route per leg (copied from data/work)
    tiles/slope/        slope in DEFAULT_SLOPE_BANDS["band_deg"] bands (display choice only), PNG tiles
    tiles/geology/      geology overlay from geology.py, PNG tiles
    layers/horizon_NN.png  terrain horizon angles from horizon.py, three directions per RGB image
    layers/elevation_readout.png, layers/slope_readout.png, layers/unit_readout.png
                        cursor readout values, sampled every DEFAULT_READOUT["sample_every_px"]
                        cells (see encode_readout)
    photos/*.jpg        stop photos, longest side DEFAULT_PHOTOS["max_side_px"]
    offline.json        files the app saves for offline use, in two stages:
                        "core" (data, photos, readouts, the coarse zoom levels) and
                        "route_detail" (the detailed tiles within DEFAULT_OFFLINE["corridor_m"]
                        of every route and stop)

Overlay tiles: zoom 0 shows one grid cell (1 m) per tile pixel; each lower zoom
halves the size (every second pixel, so unit colours never mix), down to the
zoom where the whole area fits in one tile. The browser enlarges zoom 0 tiles
when zoomed in further.

The 25 cm tiles were written by crop_layers.py.

Usage:
    python -m pipeline.build_pack [data/missions/<mission>.json]

Also rewrites web/missions.json, the list of all built missions the app offers.
"""

import datetime
import json
import math
import os
import re
import shutil
import sys

import numpy
import rasterio
from matplotlib import colormaps
from PIL import Image

from pipeline.mission import MissionPaths, load_mission, mission_path_from_arguments
from pipeline.pack_format import validate_pack
from pipeline.stops import PROJECT_ROOT, lonlat_to_pixel
from pipeline.terrain import read_heights

WEB_DIR = os.path.join(PROJECT_ROOT, "web")
MISSIONS_INDEX_PATH = os.path.join(WEB_DIR, "missions.json")
PHOTO_CREDIT = "NASA/JPL-Caltech"

# Display choices only (no meaning of safe or unsafe).
DEFAULT_SLOPE_BANDS = {"band_deg": 5, "colormap": "viridis", "alpha": 170}
DEFAULT_PHOTOS = {"max_side_px": 1600, "jpeg_quality": 85}
# Owner's choice: readout values every 4 cells keep the files small (about 8 MB instead of 94 MB).
DEFAULT_READOUT = {"sample_every_px": 4, "elevation_step_m": 0.1, "slope_step_deg": 0.01}
READOUT_NO_DATA_CODE = 65535
TILE_SIZE = 256
# Offline saving (choices): coarse zooms of the whole area, full detail only near the routes.
DEFAULT_OFFLINE = {"corridor_m": 250, "core_max_zoom": {"hirise": -1, "slope": -2, "geology": -1}, "sample_step_m": 10}

SLOPE_METHOD = (
    "Angle of the steepest rise at each cell, from the height differences "
    "to the neighbouring cells of the HiRISE DTM (central differences), in ground metres: "
    "cells are 1 m north-south and cos(latitude) m east-west (equirectangular map, true scale at the equator)."
)
METHODS = {
    "shortest": (
        "Least horizontal distance over cells with terrain data: 8-neighbour grid path "
        "(scikit-image), then straightened wherever a straight line crosses only such cells."
    ),
    "gentlest": (
        "The lowest slope S for which the two stops are still connected through cells "
        "with slope <= S (the stops' own cells not counted), then the shortest route "
        "through those cells. Its steepest point is S."
    ),
    "distance": "Horizontal ground length along the route (east-west map metres x cos(latitude)).",
    "climb_descent": "Sum of all height rises / drops from cell to cell along the route (HiRISE DTM).",
    "steepest": "Steepest 1 m cell on the route, the two stops not counted.",
    "ground_slope": "Slope of the 1 m cell at the stop position.",
    "bearing": "Direction from one stop to the next on the ground, in degrees clockwise from north (map up), from the two grid positions with east-west map metres x cos(latitude).",
    "straight_distance": "Straight-line horizontal ground distance between two stops, from the two grid positions (east-west map metres x cos(latitude)).",
    "ground_scale": "The grid is equirectangular with true scale at the equator: one cell is 1 m north-south and cos(latitude) m east-west on the ground (grid.east_scale). Slope, distances, bearings, the scale bar and shadows use ground metres.",
    "readout": "Cursor readout of elevation, slope and rock unit: value of the nearest 1 m cell sampled every 4 m.",
}


def slope_band_image(slope, band_deg, colormap_name, alpha):
    """RGBA image of slope bands and its legend [{from_deg, to_deg, color}]. No slope = transparent."""
    has_slope = numpy.isfinite(slope)
    max_slope = float(numpy.nanmax(slope))
    band_count = max(1, int(math.floor(max_slope / band_deg)) + 1)
    bands = numpy.zeros(slope.shape, dtype=numpy.int32)
    bands[has_slope] = numpy.minimum(
        numpy.floor(slope[has_slope] / band_deg).astype(numpy.int32), band_count - 1
    )
    colormap = colormaps[colormap_name]
    image = numpy.zeros(slope.shape + (4,), dtype=numpy.uint8)
    legend = []
    for band in range(band_count):
        red, green, blue, _ = colormap(band / max(1, band_count - 1))
        color = [int(red * 255), int(green * 255), int(blue * 255)]
        in_band = has_slope & (bands == band)
        image[in_band, 0:3] = color
        image[in_band, 3] = alpha
        legend.append({"from_deg": band * band_deg, "to_deg": (band + 1) * band_deg, "color": color})
    return image, legend


def save_overlay_tiles(image, tiles_dir, tile_size, start_zoom=0):
    """Cut an RGBA image into PNG tiles, start_zoom down to one tile. Returns {zoom: tile count}.

    start_zoom is the zoom at which one image pixel is one tile pixel (0 for a 1-cell grid,
    -3 for an image of 8 x 8 cells per pixel).
    """
    if os.path.isdir(tiles_dir):
        shutil.rmtree(tiles_dir)
    tile_counts = {}
    zoom = start_zoom
    while True:
        count = 0
        for tile_row in range(math.ceil(image.shape[0] / tile_size)):
            for tile_col in range(math.ceil(image.shape[1] / tile_size)):
                part = image[
                    tile_row * tile_size : (tile_row + 1) * tile_size,
                    tile_col * tile_size : (tile_col + 1) * tile_size,
                ]
                tile = numpy.zeros((tile_size, tile_size, 4), dtype=numpy.uint8)
                tile[: part.shape[0], : part.shape[1]] = part
                folder = os.path.join(tiles_dir, str(zoom), str(tile_col))
                os.makedirs(folder, exist_ok=True)
                Image.fromarray(tile, mode="RGBA").save(os.path.join(folder, f"{tile_row}.png"), optimize=True)
                count += 1
        tile_counts[zoom] = count
        if image.shape[0] <= tile_size and image.shape[1] <= tile_size:
            break
        image = image[::2, ::2]
        zoom -= 1
    return tile_counts


def overlay_tiles_entry(name, tile_counts):
    return {
        "url": f"tiles/{name}/{{z}}/{{x}}/{{y}}.png",
        "min_zoom": min(tile_counts),
        "max_zoom": max(tile_counts),
        "tile_size": TILE_SIZE,
    }


def encode_readout(values, base, step, sample_every_px):
    """Sample every n-th cell and store each value as a 16-bit code in red (high byte) and green (low byte).

    value = base + code * step. Cells without a value get READOUT_NO_DATA_CODE.
    The cell at grid [col, row] is read from readout pixel
    [round(col / n), round(row / n)] (clipped to the image).
    Returns an RGB image array.
    """
    sampled = values[::sample_every_px, ::sample_every_px].astype(numpy.float64)
    has_value = numpy.isfinite(sampled)
    codes = numpy.full(sampled.shape, READOUT_NO_DATA_CODE, dtype=numpy.uint32)
    codes[has_value] = numpy.rint((sampled[has_value] - base) / step).astype(numpy.uint32)
    if codes[has_value].size > 0 and codes[has_value].max() >= READOUT_NO_DATA_CODE:
        raise ValueError("readout values do not fit in 16 bits with this step")
    image = numpy.zeros(sampled.shape + (3,), dtype=numpy.uint8)
    image[..., 0] = codes >> 8
    image[..., 1] = codes & 255
    return image


def decode_readout(image, base, step):
    """Inverse of encode_readout, for checks: values with NaN where there is no data."""
    codes = image[..., 0].astype(numpy.uint32) * 256 + image[..., 1].astype(numpy.uint32)
    values = base + codes.astype(numpy.float64) * step
    values[codes == READOUT_NO_DATA_CODE] = numpy.nan
    return values


def write_readouts(pack_dir, site, heights, slope, unit_ids):
    """Write the readout images; return their manifest entries."""
    every = DEFAULT_READOUT["sample_every_px"]
    elevation_base = float(math.floor(numpy.nanmin(heights)))
    entries = []
    for readout_id, values, base, step, units, label, source in (
        ("elevation", heights, elevation_base, DEFAULT_READOUT["elevation_step_m"], "m", "NASA DATA", site["dtm_source"]),
        ("slope", slope, 0.0, DEFAULT_READOUT["slope_step_deg"], "degrees", "CALCULATED", site["dtm_source"]),
        ("unit", unit_ids.astype(numpy.float64), 0.0, 1.0, None, "NASA DATA", site["geology_source"]),
    ):
        file_name = f"layers/{readout_id}_readout.png"
        image = encode_readout(values, base, step, every)
        Image.fromarray(image, mode="RGB").save(os.path.join(pack_dir, file_name), optimize=True)
        entries.append(
            {
                "id": readout_id,
                "file": file_name,
                "units": units,
                "base": base,
                "step": step,
                "sample_every_px": every,
                "no_data_code": READOUT_NO_DATA_CODE,
                "label": label,
                "source": source,
            }
        )
    return entries


def shrink_photo(source_path, target_path, max_side_px, jpeg_quality):
    """Save a JPEG copy whose longest side is at most max_side_px (aspect ratio kept)."""
    with Image.open(source_path) as photo:
        rgb_photo = photo.convert("RGB")
        rgb_photo.thumbnail((max_side_px, max_side_px), Image.LANCZOS)
        rgb_photo.save(target_path, "JPEG", quality=jpeg_quality)


def photo_file_name(stop_id, photo):
    camera_slug = re.sub(r"[^a-z0-9]+", "-", photo["camera"].lower()).strip("-")
    return f"stop{stop_id}_sol{photo['sol']}_{camera_slug}.jpg"


def build_stops(pack_dir, stops, slope, geology, dtm):
    photos_dir = os.path.join(pack_dir, "photos")
    if os.path.isdir(photos_dir):
        shutil.rmtree(photos_dir)
    os.makedirs(photos_dir)

    units_by_id = {}
    for unit in geology["units"]:
        units_by_id[unit["id"]] = unit

    pack_stops = []
    for stop in stops:
        col, row = lonlat_to_pixel(dtm, stop["lon"], stop["lat"])
        ground_slope = None
        if numpy.isfinite(slope[row, col]):
            ground_slope = round(float(slope[row, col]), 2)
        unit = None
        unit_id = geology["stop_units"].get(str(stop["id"]))
        if unit_id is not None and unit_id in units_by_id:
            found = units_by_id[unit_id]
            unit = {"symbol": found["symbol"], "name": found["name"], "description": found["description"]}

        pack_photos = []
        for photo in stop["photos"]:
            file_name = photo_file_name(stop["id"], photo)
            shrink_photo(
                os.path.join(PROJECT_ROOT, photo["file"]),
                os.path.join(photos_dir, file_name),
                DEFAULT_PHOTOS["max_side_px"],
                DEFAULT_PHOTOS["jpeg_quality"],
            )
            pack_photos.append(
                {
                    "file": f"photos/{file_name}",
                    "sol": photo["sol"],
                    "camera": photo["camera"],
                    "image_id": photo["image_id"],
                    "credit": PHOTO_CREDIT,
                }
            )
        pack_stops.append(
            {
                "id": stop["id"],
                "label": stop["label"],
                "position": [col, row],
                "position_source": stop["position_source"],
                "ground_slope_deg": ground_slope,
                "unit": unit,
                "photos": pack_photos,
            }
        )
    return pack_stops


def build_manifest(mission, grid, slope_legend, geology, tile_zooms, readouts, slope_tiles, geology_tiles):
    site = mission["site"]
    geology_legend = []
    for unit in geology["units"]:
        geology_legend.append(
            {"id": unit["id"], "symbol": unit["symbol"], "name": unit["name"],
             "color": unit["color"], "pattern": unit["pattern"]}
        )
    return {
        "id": mission["pack_id"],
        "version": mission["pack_version"],
        "created": datetime.date.today().isoformat(),
        "site": {
            "name": site["name"],
            "bounds_px": [0, 0, grid["width"], grid["height"]],
            "bounds_lonlat": grid["bounds_lonlat"],
        },
        "grid": {
            "width": grid["width"],
            "height": grid["height"],
            "metres_per_pixel": grid["metres_per_pixel"],
            # ground metres per grid metre east-west (equirectangular, true scale at the equator)
            "east_scale": math.cos(math.radians((grid["bounds_lonlat"][1] + grid["bounds_lonlat"][3]) / 2.0)),
        },
        "layers": [
            {
                "id": "hirise",
                "kind": "imagery",
                "tiles": {
                    "url": "tiles/hirise/{z}/{x}/{y}.jpg",
                    "min_zoom": min(tile_zooms),
                    "max_zoom": max(tile_zooms),
                    "tile_size": 256,
                },
                "units": None,
                "legend": None,
                "source": site["image_source"],
                "product_id": site["image_product_id"],
                "as_of": site["as_of"],
                "label": "NASA DATA",
            },
            {
                "id": "slope",
                "kind": "raster-continuous",
                "tiles": slope_tiles,
                "units": "degrees",
                "legend": slope_legend,
                "source": site["dtm_source"],
                "product_id": site["dtm_product_id"],
                "as_of": site["as_of"],
                "label": "CALCULATED",
                "method": SLOPE_METHOD,
            },
            {
                "id": "geology",
                "kind": "raster-categorical",
                "tiles": geology_tiles,
                "units": None,
                "legend": geology_legend,
                "source": site["geology_source"],
                "product_id": site["geology_product_id"],
                "as_of": site["as_of"],
                "label": "NASA DATA",
            },
        ],
        "readouts": readouts,
        "methods": METHODS,
    }


def corridor_points(pack_stops, legs, step_px):
    """Grid points every step_px along every route, plus the stops."""
    points = []
    for stop in pack_stops:
        points.append((float(stop["position"][0]), float(stop["position"][1])))
    for leg in legs:
        for kind in ("shortest", "gentlest"):
            route = leg[kind]
            if route is None:
                continue
            for start, end in zip(route["points"], route["points"][1:]):
                length = math.hypot(end[0] - start[0], end[1] - start[1])
                count = max(1, int(length // step_px))
                for index in range(count + 1):
                    fraction = index / count
                    points.append((start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction))
    return points


def tiles_near_points(points, zoom, buffer_px, tile_size):
    """(x, y) of every tile at this zoom that lies within buffer_px of a point (box test)."""
    scale = 2.0**zoom
    tiles = set()
    for col, row in points:
        x_min = int(math.floor((col - buffer_px) * scale / tile_size))
        x_max = int(math.floor((col + buffer_px) * scale / tile_size))
        y_min = int(math.floor((row - buffer_px) * scale / tile_size))
        y_max = int(math.floor((row + buffer_px) * scale / tile_size))
        for x in range(max(0, x_min), x_max + 1):
            for y in range(max(0, y_min), y_max + 1):
                tiles.add((x, y))
    return tiles


def write_offline_list(pack_dir, manifest, pack_stops, legs):
    """Write offline.json: "core" and "route_detail" file lists (paths inside the pack)."""
    core = ["manifest.json", "mission.json", "stops.json", "routes.json"]
    for readout in manifest["readouts"]:
        core.append(readout["file"])
    if "meda" in manifest:
        core.append(manifest["meda"]["file"])
    if "horizon" in manifest:
        for horizon_file in manifest["horizon"]["files"]:
            core.append(horizon_file["file"])
    for stop in pack_stops:
        for photo in stop["photos"]:
            core.append(photo["file"])

    metres_per_pixel = manifest["grid"]["metres_per_pixel"]
    points = corridor_points(pack_stops, legs, DEFAULT_OFFLINE["sample_step_m"] / metres_per_pixel)
    buffer_px = DEFAULT_OFFLINE["corridor_m"] / metres_per_pixel
    route_detail = []
    for layer in manifest["layers"]:
        tiles = layer.get("tiles")
        if tiles is None:
            continue
        if layer.get("context"):
            core_max = tiles["max_zoom"]  # the Mars context layers are small: save them whole
        else:
            core_max = DEFAULT_OFFLINE["core_max_zoom"].get(layer["id"], tiles["min_zoom"])
        for zoom in range(tiles["min_zoom"], tiles["max_zoom"] + 1):
            if zoom <= core_max:
                folder = os.path.join(pack_dir, tiles["url"].split("{z}")[0], str(zoom))
                for x_name in sorted(os.listdir(folder)):
                    for file_name in sorted(os.listdir(os.path.join(folder, x_name))):
                        core.append(f"{tiles['url'].split('{z}')[0]}{zoom}/{x_name}/{file_name}")
            else:
                for x, y in sorted(tiles_near_points(points, zoom, buffer_px, tiles["tile_size"])):
                    path = tiles["url"].replace("{z}", str(zoom)).replace("{x}", str(x)).replace("{y}", str(y))
                    if os.path.isfile(os.path.join(pack_dir, path)):
                        route_detail.append(path)

    offline = {"version": manifest["version"], "corridor_m": DEFAULT_OFFLINE["corridor_m"], "core": core, "route_detail": route_detail}
    with open(os.path.join(pack_dir, "offline.json"), "w", encoding="utf-8") as offline_file:
        json.dump(offline, offline_file)
    return offline


def write_mission_file(pack_dir, mission):
    """The mission as the app shows it, plus site_template: the mission file's site block (raw-file
    names and credits), so the in-app mission editor can export a complete mission file for this site."""
    questions = []
    for stop in mission["stops"]:
        questions.append({"stop_id": stop["id"], "question": stop["question"]})
    pack_mission = {
        "id": mission["id"],
        "name": mission["name"],
        "status": mission["status"],
        "objective": mission["objective"],
        "objective_sources": mission["objective_sources"],
        "site": mission["site"]["name"],
        "questions": questions,
        "pack_version": mission["pack_version"],
        "site_template": mission["site"],
    }
    with open(os.path.join(pack_dir, "mission.json"), "w", encoding="utf-8") as mission_file:
        json.dump(pack_mission, mission_file, ensure_ascii=False, indent=2)


def write_missions_index():
    """web/missions.json: every built pack that has a mission.json, for the boot screen."""
    data_dir = os.path.join(WEB_DIR, "data")
    entries = []
    for pack_name in sorted(os.listdir(data_dir)):
        mission_path = os.path.join(data_dir, pack_name, "mission.json")
        manifest_path = os.path.join(data_dir, pack_name, "manifest.json")
        if not os.path.isfile(mission_path) or not os.path.isfile(manifest_path):
            continue
        with open(mission_path, "r", encoding="utf-8") as mission_file:
            pack_mission = json.load(mission_file)
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        west, south, east, north = manifest["site"]["bounds_lonlat"]
        entries.append(
            {
                "pack": f"data/{pack_name}/",
                "id": pack_mission["id"],
                "name": pack_mission["name"],
                "status": pack_mission["status"],
                "site": pack_mission["site"],
                "stop_count": len(pack_mission["questions"]),
                "pack_version": manifest["version"],
                "centre_lonlat": [round((west + east) / 2, 4), round((south + north) / 2, 4)],
            }
        )
    with open(MISSIONS_INDEX_PATH, "w", encoding="utf-8") as index_file:
        json.dump(entries, index_file, ensure_ascii=False, indent=2)
    return entries


# Thermal display (choice only): a dark-to-bright colour scale over the 8-bit values.
DEFAULT_THERMAL_DISPLAY = {"colormap": "inferno", "alpha": 190, "legend_steps": 6}


def thermal_band_image(values, no_data, colormap_name, alpha):
    """RGBA image of 8-bit thermal values (0-255) on a colour scale; no data = transparent."""
    colormap = colormaps[colormap_name]
    lookup = (numpy.array([colormap(level / 255.0) for level in range(256)]) * 255).astype(numpy.uint8)
    has_data = values != no_data
    image = numpy.zeros(values.shape + (4,), dtype=numpy.uint8)
    image[has_data, 0:3] = lookup[values[has_data].astype(numpy.uint8), 0:3]
    image[has_data, 3] = alpha
    return image, lookup


def thermal_layers(pack_dir, thermal, work_dir):
    """Map layers + readouts for THEMIS night and day; ([], []) if thermal.py has not run."""
    layers = []
    readouts = []
    for kind, name in (("night", "THEMIS NIGHT IR"), ("day", "THEMIS DAY IR")):
        source_path = os.path.join(work_dir, f"thermal_{kind}.tif")
        if not os.path.isfile(source_path):
            return [], []
        with rasterio.open(source_path) as source:
            values = source.read(1)
            no_data = source.nodata
            metres_per_cell = source.res[0]
        with open(os.path.join(work_dir, "grid.json"), "r", encoding="utf-8") as grid_file:
            cell_px = int(round(metres_per_cell / json.load(grid_file)["metres_per_pixel"]))
        image, lookup = thermal_band_image(values, no_data, DEFAULT_THERMAL_DISPLAY["colormap"], DEFAULT_THERMAL_DISPLAY["alpha"])
        start_zoom = -int(round(math.log2(cell_px)))
        counts = save_overlay_tiles(image, os.path.join(pack_dir, "tiles", f"thermal-{kind}"), TILE_SIZE, start_zoom)
        legend = []
        steps = DEFAULT_THERMAL_DISPLAY["legend_steps"]
        for step in range(steps):
            low = round(step * 255 / steps)
            high = round((step + 1) * 255 / steps)
            middle = (low + high) // 2
            legend.append({"from_value": low, "to_value": high, "color": [int(v) for v in lookup[middle, 0:3]]})
        layers.append(
            {
                "id": f"thermal-{kind}",
                "kind": "raster-continuous",
                "tiles": {
                    "url": f"tiles/thermal-{kind}/{{z}}/{{x}}/{{y}}.png",
                    "min_zoom": min(counts),
                    "max_zoom": max(counts),
                    "tile_size": TILE_SIZE,
                },
                "units": "8-bit value (qualitative): brighter = warmer surface when observed",
                "legend": legend,
                "source": thermal["source"],
                "product_id": thermal["product_id"],
                "as_of": thermal["as_of"],
                "label": "NASA DATA",
                "display_name": name,
            }
        )
        file_name = f"layers/thermal_{kind}_readout.png"
        coded = encode_readout(values.astype(numpy.float64), 0.0, 1.0, 1)
        has_value = values != no_data
        coded[~has_value, 0] = READOUT_NO_DATA_CODE >> 8
        coded[~has_value, 1] = READOUT_NO_DATA_CODE & 255
        Image.fromarray(coded, mode="RGB").save(os.path.join(pack_dir, file_name), optimize=True)
        readouts.append(
            {
                "id": f"thermal_{kind}",
                "file": file_name,
                "units": "8-bit value",
                "base": 0.0,
                "step": 1.0,
                "sample_every_px": cell_px,
                "no_data_code": READOUT_NO_DATA_CODE,
                "label": "NASA DATA",
                "source": thermal["source"],
            }
        )
    return layers, readouts


HORIZON_DIRECTIONS_PER_IMAGE = 3  # red, green, blue


def horizon_entry(pack_dir, work_dir, dtm_source):
    """layers/horizon_NN.png (three directions per RGB image) and their manifest entry; None if horizon.py has not run."""
    codes_path = os.path.join(work_dir, "horizon.npy")
    info_path = os.path.join(work_dir, "horizon.json")
    if not os.path.isfile(codes_path) or not os.path.isfile(info_path):
        return None
    codes = numpy.load(codes_path)
    with open(info_path, "r", encoding="utf-8") as info_file:
        info = json.load(info_file)
    files = []
    directions = info["directions_deg"]
    for first in range(0, len(directions), HORIZON_DIRECTIONS_PER_IMAGE):
        image = numpy.zeros(codes.shape[1:] + (3,), dtype=numpy.uint8)
        group = directions[first : first + HORIZON_DIRECTIONS_PER_IMAGE]
        for channel in range(len(group)):
            image[..., channel] = codes[first + channel]
        file_name = f"layers/horizon_{first // HORIZON_DIRECTIONS_PER_IMAGE:02d}.png"
        Image.fromarray(image, "RGB").save(os.path.join(pack_dir, file_name), optimize=True)
        files.append({"file": file_name, "directions_deg": group})
    entry = {key: info[key] for key in ("cell_px", "width", "height", "directions_deg", "angle_step_deg", "no_data_code",
                                         "max_distance_m", "radius_m", "east_scale", "dtm_margin_m", "method")}
    entry.update({"files": files, "label": "CALCULATED", "source": dtm_source})
    return entry


def context_layers(work_dir):
    """Planet / region / crater layers from context_maps.py (empty list if it has not run)."""
    context_path = os.path.join(work_dir, "context.json")
    if not os.path.isfile(context_path):
        return []
    with open(context_path, "r", encoding="utf-8") as context_file:
        context = json.load(context_file)
    layers = []
    for entry in context["layers"]:
        layers.append(
            {
                "id": entry["id"],
                "kind": "imagery",
                "context": True,
                "tiles": {
                    "url": f"tiles/{entry['id']}/{{z}}/{{x}}/{{y}}.png",
                    "min_zoom": entry["min_zoom"],
                    "max_zoom": entry["max_zoom"],
                    "tile_size": TILE_SIZE,
                    "bounds_lonlat": entry["bounds_lonlat"],
                },
                "units": None,
                "legend": None,
                "source": entry["source"],
                "product_id": "Mars_Viking_MDIM21_ClrMosaic_global_232m",
                "as_of": None,
                "label": "NASA DATA",
            }
        )
    return layers


def tile_zoom_levels(pack_dir):
    tiles_dir = os.path.join(pack_dir, "tiles", "hirise")
    zooms = []
    for name in os.listdir(tiles_dir):
        if re.fullmatch(r"-?\d+", name):
            zooms.append(int(name))
    if len(zooms) == 0:
        raise FileNotFoundError(f"no tiles in {tiles_dir}; run crop_layers.py first")
    return zooms


def main(mission_path):
    mission = load_mission(mission_path)
    paths = MissionPaths(mission)
    pack_dir = paths.pack_dir
    for needed_path in (paths.grid, paths.cropped_dtm, paths.slope, paths.routes, paths.geology_json, paths.geology_overlay, paths.geology_ids):
        if not os.path.isfile(needed_path):
            raise FileNotFoundError(f"{needed_path} is missing; run the earlier pipeline steps first")

    with open(paths.grid, "r", encoding="utf-8") as grid_file:
        grid = json.load(grid_file)
    with open(paths.geology_json, "r", encoding="utf-8") as geology_file:
        geology = json.load(geology_file)
    with rasterio.open(paths.slope) as slope_file:
        slope = slope_file.read(1)
    with rasterio.open(paths.cropped_dtm) as dtm:
        heights = read_heights(dtm)

    layers_dir = os.path.join(pack_dir, "layers")
    if os.path.isdir(layers_dir):
        shutil.rmtree(layers_dir)
    os.makedirs(layers_dir)
    slope_image, slope_legend = slope_band_image(
        slope, DEFAULT_SLOPE_BANDS["band_deg"], DEFAULT_SLOPE_BANDS["colormap"], DEFAULT_SLOPE_BANDS["alpha"]
    )
    slope_tile_counts = save_overlay_tiles(slope_image, os.path.join(pack_dir, "tiles", "slope"), TILE_SIZE)
    del slope_image
    Image.MAX_IMAGE_PIXELS = None  # our own 54 MP images from geology.py
    with Image.open(paths.geology_overlay) as overlay_file:
        geology_overlay = numpy.array(overlay_file.convert("RGBA"))
    geology_tile_counts = save_overlay_tiles(geology_overlay, os.path.join(pack_dir, "tiles", "geology"), TILE_SIZE)
    del geology_overlay
    with Image.open(paths.geology_ids) as lookup_file:
        unit_ids = numpy.array(lookup_file)
    readouts = write_readouts(pack_dir, mission["site"], heights, slope, unit_ids)

    stops = mission["stops"]
    with rasterio.open(paths.cropped_dtm) as dtm:
        pack_stops = build_stops(pack_dir, stops, slope, geology, dtm)

    shutil.copyfile(paths.routes, os.path.join(pack_dir, "routes.json"))
    write_mission_file(pack_dir, mission)
    with open(os.path.join(pack_dir, "stops.json"), "w", encoding="utf-8") as stops_file:
        json.dump(pack_stops, stops_file, ensure_ascii=False, indent=2)
    manifest = build_manifest(
        mission,
        grid,
        slope_legend,
        geology,
        tile_zoom_levels(pack_dir),
        readouts,
        overlay_tiles_entry("slope", slope_tile_counts),
        overlay_tiles_entry("geology", geology_tile_counts),
    )
    manifest["layers"] = context_layers(paths.work_dir) + manifest["layers"]
    if mission["site"].get("thermal") is not None:
        thermal_map_layers, thermal_readouts = thermal_layers(pack_dir, mission["site"]["thermal"], paths.work_dir)
        manifest["layers"] = manifest["layers"] + thermal_map_layers
        manifest["readouts"] = manifest["readouts"] + thermal_readouts
    meda_summary = os.path.join(paths.work_dir, "meda.json")
    if mission["site"].get("meda") is not None and os.path.isfile(meda_summary):
        shutil.copyfile(meda_summary, os.path.join(pack_dir, "meda.json"))
        meda_site = mission["site"]["meda"]
        manifest["meda"] = {
            "file": "meda.json",
            "source": meda_site["source"],
            "product_id": meda_site["product_id"],
            "url": meda_site.get("url"),
            "as_of": meda_site["as_of"],
            "label": "NASA DATA",
            "method": (
                "Air: mean of the three mast air temperature sensors (ATS 1-3). Ground: TIRS ground brightness "
                "temperature, rows left out when a quality flag says the rover moved, tilted 20 degrees or more, "
                "shaded the spot or had a wheel in view. Median per Mars minute, then hourly means (LMST) and "
                "the lowest / highest minute."
            ),
        }
    if mission["site"].get("surface_radius") is not None:
        manifest["site"]["surface_radius"] = mission["site"]["surface_radius"]
    habitat = mission["site"].get("habitat")
    if habitat is not None:
        with rasterio.open(paths.cropped_dtm) as dtm:
            col, row = lonlat_to_pixel(dtm, habitat["lon"], habitat["lat"])
        manifest["habitat"] = {"label": habitat["label"], "position": [int(col), int(row)], "source": habitat["source"]}
    horizon = horizon_entry(pack_dir, paths.work_dir, mission["site"]["dtm_source"])
    if horizon is not None:
        manifest["horizon"] = horizon
    with open(os.path.join(pack_dir, "manifest.json"), "w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)

    with open(os.path.join(pack_dir, "routes.json"), "r", encoding="utf-8") as routes_file:
        legs = json.load(routes_file)
    offline = write_offline_list(pack_dir, manifest, pack_stops, legs)

    errors = validate_pack(pack_dir)
    if len(errors) > 0:
        print(f"INVALID pack {pack_dir}:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"VALID pack {pack_dir}")
    missions = write_missions_index()
    print(f"Missions in {MISSIONS_INDEX_PATH}: {len(missions)}")
    for stop in pack_stops:
        unit_text = "no data"
        if stop["unit"] is not None:
            unit_text = f"{stop['unit']['symbol']} {stop['unit']['name']}"
        print(f"  stop {stop['id']} {stop['label']}: {stop['position']}, slope {stop['ground_slope_deg']} deg, "
              f"{unit_text}, {len(stop['photos'])} photos")
    total_bytes = 0
    for folder, _, files in os.walk(pack_dir):
        for name in files:
            total_bytes += os.path.getsize(os.path.join(folder, name))
    print(f"Pack size: {total_bytes / 1e6:.1f} MB")
    for stage in ("core", "route_detail"):
        stage_bytes = 0
        for path in offline[stage]:
            stage_bytes += os.path.getsize(os.path.join(pack_dir, path))
        print(f"Offline {stage}: {len(offline[stage])} files, {stage_bytes / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
