"""Write the data pack the web app reads, then check it with validate_pack.

Run after crop_layers.py, terrain.py, routes.py and geology.py. Writes into
web/data/jezero_v1/:
    manifest.json       site, grid, layers (with sources and methods), methods of the routes
    stops.json          stops with grid position, ground slope, rock unit and photos
    routes.json         shortest and gentlest route per leg (copied from data/work)
    tiles/slope/        slope in DEFAULT_SLOPE_BANDS["band_deg"] bands (display choice only), PNG tiles
    tiles/geology/      geology overlay from geology.py, PNG tiles
    layers/elevation_readout.png, layers/slope_readout.png, layers/unit_readout.png
                        cursor readout values, sampled every DEFAULT_READOUT["sample_every_px"]
                        cells (see encode_readout)
    photos/*.jpg        stop photos, longest side DEFAULT_PHOTOS["max_side_px"]

Overlay tiles: zoom 0 shows one grid cell (1 m) per tile pixel; each lower zoom
halves the size (every second pixel, so unit colours never mix), down to the
zoom where the whole area fits in one tile. The browser enlarges zoom 0 tiles
when zoomed in further.

The 25 cm tiles were written by crop_layers.py.

Usage:
    python -m pipeline.build_pack
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

from pipeline.crop_layers import CROPPED_DTM_PATH, GRID_PATH, PACK_DIR, PROJECT_ROOT
from pipeline.geology import GEOLOGY_JSON_PATH, LOOKUP_PATH, OVERLAY_PATH
from pipeline.pack_format import validate_pack
from pipeline.routes import ROUTES_PATH
from pipeline.stops import load_stops, lonlat_to_pixel
from pipeline.terrain import SLOPE_PATH, read_heights

PACK_ID = "jezero_v1"
PACK_VERSION = "1.0.0"
SITE_NAME = "Jezero Crater"
PHOTO_CREDIT = "NASA/JPL-Caltech"

# Display choices only (no meaning of safe or unsafe).
DEFAULT_SLOPE_BANDS = {"band_deg": 5, "colormap": "viridis", "alpha": 170}
DEFAULT_PHOTOS = {"max_side_px": 1600, "jpeg_quality": 85}
# Owner's choice: readout values every 4 cells keep the files small (about 8 MB instead of 94 MB).
DEFAULT_READOUT = {"sample_every_px": 4, "elevation_step_m": 0.1, "slope_step_deg": 0.01}
READOUT_NO_DATA_CODE = 65535
TILE_SIZE = 256

HIRISE_SOURCE = (
    "HiRISE orthomosaic, 25 cm/pixel (Mars 2020 Terrain Relative Navigation). "
    "MRO, NASA/JPL-Caltech/University of Arizona; mosaic by USGS Astrogeology Science Center "
    "(Fergason and others, 2020, doi:10.5066/P9QJDP48)"
)
DTM_SOURCE = (
    "HiRISE DTM mosaic, ~1 m/pixel (Mars 2020 Terrain Relative Navigation). "
    "MRO, NASA/JPL-Caltech/University of Arizona; mosaic by USGS Astrogeology Science Center "
    "(Fergason and others, 2020, doi:10.5066/P9REJ9JN)"
)
GEOLOGY_SOURCE = (
    "Sun, V.Z., and Stack, K.M., 2020, Geologic Map of Jezero Crater and the "
    "Nili Planum Region, Mars: USGS Scientific Investigations Map 3464"
)
SLOPE_METHOD = (
    "Angle of the steepest rise at each 1 m cell, from the height differences "
    "to the neighbouring cells of the HiRISE DTM (central differences)."
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
    "distance": "Horizontal length along the route.",
    "climb_descent": "Sum of all height rises / drops from cell to cell along the route (HiRISE DTM).",
    "steepest": "Steepest 1 m cell on the route, the two stops not counted.",
    "ground_slope": "Slope of the 1 m cell at the stop position.",
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


def save_overlay_tiles(image, tiles_dir, tile_size):
    """Cut an RGBA image into PNG tiles, zoom 0 down to one tile. Returns {zoom: tile count}."""
    if os.path.isdir(tiles_dir):
        shutil.rmtree(tiles_dir)
    tile_counts = {}
    zoom = 0
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


def write_readouts(heights, slope, unit_ids):
    """Write the readout images; return their manifest entries."""
    every = DEFAULT_READOUT["sample_every_px"]
    elevation_base = float(math.floor(numpy.nanmin(heights)))
    entries = []
    for readout_id, values, base, step, units, label, source in (
        ("elevation", heights, elevation_base, DEFAULT_READOUT["elevation_step_m"], "m", "NASA DATA", DTM_SOURCE),
        ("slope", slope, 0.0, DEFAULT_READOUT["slope_step_deg"], "degrees", "CALCULATED", DTM_SOURCE),
        ("unit", unit_ids.astype(numpy.float64), 0.0, 1.0, None, "NASA DATA", GEOLOGY_SOURCE),
    ):
        file_name = f"layers/{readout_id}_readout.png"
        image = encode_readout(values, base, step, every)
        Image.fromarray(image, mode="RGB").save(os.path.join(PACK_DIR, file_name), optimize=True)
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


def build_stops(stops, slope, geology, dtm):
    photos_dir = os.path.join(PACK_DIR, "photos")
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


def build_manifest(grid, slope_legend, geology, tile_zooms, readouts, slope_tiles, geology_tiles):
    geology_legend = []
    for unit in geology["units"]:
        geology_legend.append(
            {"id": unit["id"], "symbol": unit["symbol"], "name": unit["name"],
             "color": unit["color"], "pattern": unit["pattern"]}
        )
    return {
        "id": PACK_ID,
        "version": PACK_VERSION,
        "created": datetime.date.today().isoformat(),
        "site": {
            "name": SITE_NAME,
            "bounds_px": [0, 0, grid["width"], grid["height"]],
            "bounds_lonlat": grid["bounds_lonlat"],
        },
        "grid": {
            "width": grid["width"],
            "height": grid["height"],
            "metres_per_pixel": grid["metres_per_pixel"],
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
                "source": HIRISE_SOURCE,
                "product_id": "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first",
                "as_of": "2020",
                "label": "NASA DATA",
            },
            {
                "id": "slope",
                "kind": "raster-continuous",
                "tiles": slope_tiles,
                "units": "degrees",
                "legend": slope_legend,
                "source": DTM_SOURCE,
                "product_id": "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40",
                "as_of": "2020",
                "label": "CALCULATED",
                "method": SLOPE_METHOD,
            },
            {
                "id": "geology",
                "kind": "raster-categorical",
                "tiles": geology_tiles,
                "units": None,
                "legend": geology_legend,
                "source": GEOLOGY_SOURCE,
                "product_id": "SIM 3464, layer GeoUnits_v1",
                "as_of": "2020",
                "label": "NASA DATA",
            },
        ],
        "readouts": readouts,
        "methods": METHODS,
    }


def tile_zoom_levels():
    tiles_dir = os.path.join(PACK_DIR, "tiles", "hirise")
    zooms = []
    for name in os.listdir(tiles_dir):
        if re.fullmatch(r"-?\d+", name):
            zooms.append(int(name))
    if len(zooms) == 0:
        raise FileNotFoundError(f"no tiles in {tiles_dir}; run crop_layers.py first")
    return zooms


def main():
    for needed_path in (GRID_PATH, CROPPED_DTM_PATH, SLOPE_PATH, ROUTES_PATH, GEOLOGY_JSON_PATH, OVERLAY_PATH, LOOKUP_PATH):
        if not os.path.isfile(needed_path):
            raise FileNotFoundError(f"{needed_path} is missing; run the earlier pipeline steps first")

    with open(GRID_PATH, "r", encoding="utf-8") as grid_file:
        grid = json.load(grid_file)
    with open(GEOLOGY_JSON_PATH, "r", encoding="utf-8") as geology_file:
        geology = json.load(geology_file)
    with rasterio.open(SLOPE_PATH) as slope_file:
        slope = slope_file.read(1)
    with rasterio.open(CROPPED_DTM_PATH) as dtm:
        heights = read_heights(dtm)

    layers_dir = os.path.join(PACK_DIR, "layers")
    if os.path.isdir(layers_dir):
        shutil.rmtree(layers_dir)
    os.makedirs(layers_dir)
    slope_image, slope_legend = slope_band_image(
        slope, DEFAULT_SLOPE_BANDS["band_deg"], DEFAULT_SLOPE_BANDS["colormap"], DEFAULT_SLOPE_BANDS["alpha"]
    )
    slope_tile_counts = save_overlay_tiles(slope_image, os.path.join(PACK_DIR, "tiles", "slope"), TILE_SIZE)
    del slope_image
    Image.MAX_IMAGE_PIXELS = None  # our own 54 MP images from geology.py
    with Image.open(OVERLAY_PATH) as overlay_file:
        geology_overlay = numpy.array(overlay_file.convert("RGBA"))
    geology_tile_counts = save_overlay_tiles(geology_overlay, os.path.join(PACK_DIR, "tiles", "geology"), TILE_SIZE)
    del geology_overlay
    with Image.open(LOOKUP_PATH) as lookup_file:
        unit_ids = numpy.array(lookup_file)
    readouts = write_readouts(heights, slope, unit_ids)

    stops = load_stops()
    with rasterio.open(CROPPED_DTM_PATH) as dtm:
        pack_stops = build_stops(stops, slope, geology, dtm)

    shutil.copyfile(ROUTES_PATH, os.path.join(PACK_DIR, "routes.json"))
    with open(os.path.join(PACK_DIR, "stops.json"), "w", encoding="utf-8") as stops_file:
        json.dump(pack_stops, stops_file, ensure_ascii=False, indent=2)
    manifest = build_manifest(
        grid,
        slope_legend,
        geology,
        tile_zoom_levels(),
        readouts,
        overlay_tiles_entry("slope", slope_tile_counts),
        overlay_tiles_entry("geology", geology_tile_counts),
    )
    with open(os.path.join(PACK_DIR, "manifest.json"), "w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)

    errors = validate_pack(PACK_DIR)
    if len(errors) > 0:
        print(f"INVALID pack {PACK_DIR}:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"VALID pack {PACK_DIR}")
    for stop in pack_stops:
        unit_text = "no data"
        if stop["unit"] is not None:
            unit_text = f"{stop['unit']['symbol']} {stop['unit']['name']}"
        print(f"  stop {stop['id']} {stop['label']}: {stop['position']}, slope {stop['ground_slope_deg']} deg, "
              f"{unit_text}, {len(stop['photos'])} photos")
    total_bytes = 0
    for folder, _, files in os.walk(PACK_DIR):
        for name in files:
            total_bytes += os.path.getsize(os.path.join(folder, name))
    print(f"Pack size: {total_bytes / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
