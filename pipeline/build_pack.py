"""Write the data pack the web app reads, then check it with validate_pack.

Run after crop_layers.py, terrain.py, routes.py and geology.py. Writes into
web/data/jezero_v1/:
    manifest.json       site, grid, layers (with sources and methods), methods of the routes
    stops.json          stops with grid position, ground slope, rock unit and photos
    routes.json         shortest and gentlest route per leg (copied from data/work)
    layers/slope.png    slope in DEFAULT_SLOPE_BANDS["band_deg"] bands (display choice only)
    photos/*.jpg        stop photos, longest side DEFAULT_PHOTOS["max_side_px"]

The 25 cm tiles and the geology images were written by crop_layers.py and geology.py.

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
from pipeline.terrain import SLOPE_PATH

PACK_ID = "jezero_v1"
PACK_VERSION = "1.0.0"
SITE_NAME = "Jezero Crater"
PHOTO_CREDIT = "NASA/JPL-Caltech"

# Display choices only (no meaning of safe or unsafe).
DEFAULT_SLOPE_BANDS = {"band_deg": 5, "colormap": "viridis", "alpha": 170}
DEFAULT_PHOTOS = {"max_side_px": 1600, "jpeg_quality": 85}

HIRISE_SOURCE = (
    "HiRISE orthomosaic, 25 cm/pixel (Mars 2020 Terrain Relative Navigation). "
    "MRO, NASA/JPL-Caltech/University of Arizona; mosaic by USGS Astrogeology Science Center"
)
DTM_SOURCE = (
    "HiRISE DTM mosaic, ~1 m/pixel (Mars 2020 Terrain Relative Navigation). "
    "MRO, NASA/JPL-Caltech/University of Arizona; mosaic by USGS Astrogeology Science Center"
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


def build_manifest(grid, slope_legend, geology, tile_zooms):
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
                "as_of": None,
                "label": "NASA DATA",
            },
            {
                "id": "slope",
                "kind": "raster-continuous",
                "file": "layers/slope.png",
                "units": "degrees",
                "legend": slope_legend,
                "source": DTM_SOURCE,
                "product_id": "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40",
                "as_of": None,
                "label": "CALCULATED",
                "method": SLOPE_METHOD,
            },
            {
                "id": "geology",
                "kind": "raster-categorical",
                "file": "layers/geology.png",
                "lookup": "layers/geology_ids.png",
                "units": None,
                "legend": geology_legend,
                "source": GEOLOGY_SOURCE,
                "product_id": "SIM 3464, layer GeoUnits_v1",
                "as_of": "2020",
                "label": "NASA DATA",
            },
        ],
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

    os.makedirs(os.path.join(PACK_DIR, "layers"), exist_ok=True)
    slope_image, slope_legend = slope_band_image(
        slope, DEFAULT_SLOPE_BANDS["band_deg"], DEFAULT_SLOPE_BANDS["colormap"], DEFAULT_SLOPE_BANDS["alpha"]
    )
    Image.fromarray(slope_image, mode="RGBA").save(os.path.join(PACK_DIR, "layers", "slope.png"), optimize=True)

    stops = load_stops()
    with rasterio.open(CROPPED_DTM_PATH) as dtm:
        pack_stops = build_stops(stops, slope, geology, dtm)

    shutil.copyfile(ROUTES_PATH, os.path.join(PACK_DIR, "routes.json"))
    with open(os.path.join(PACK_DIR, "stops.json"), "w", encoding="utf-8") as stops_file:
        json.dump(pack_stops, stops_file, ensure_ascii=False, indent=2)
    manifest = build_manifest(grid, slope_legend, geology, tile_zoom_levels())
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
