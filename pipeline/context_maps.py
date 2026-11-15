"""The rest of Mars around the walk area: whole planet -> region -> crater -> walk area.

Source: Mars Viking MDIM 2.1 Colorized Global Mosaic (USGS Astrogeology; NASA Viking
Orbiter images), the same layer in three sizes:
  planet  web/data/globe/mars_viking_colour.jpg (2048 x 1024, from make_globe.py)
  region  NASA Mars Trek tiles, level 5 (16384 px around Mars, about 1.3 km/px)
  crater  NASA Mars Trek tiles, level 7 (65536 px around Mars, about 330 m/px)
Trek tiles: https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/...
level z has 2^(z+1) x 2^z tiles of 256 px, longitude -180..180, latitude 90..-90.
Downloaded tiles are kept in data/raw/trek/.

The walk-area grid and these images all use plain longitude/latitude (equirectangular),
so grid column and row are straight-line functions of longitude and latitude. Each
image is cut into 256 px map tiles in grid coordinates (nearest pixel, transparent
outside the image) for the zoom levels where it is the sharpest layer.

Region and crater boxes around the site centre (DEFAULT_CONTEXT) are display choices.

Outputs: web/data/<pack>/tiles/context-planet|context-region|context-crater/{z}/{x}/{y}.png
         data/work/<pack>/context.json  (layers, zooms, bounds, sources) for build_pack.py

Usage:
    python -m pipeline.context_maps [data/missions/<mission>.json]
"""

import io
import json
import math
import os
import sys
import subprocess
import time

import numpy
from PIL import Image

from pipeline.mission import RAW_DIR, MissionPaths, load_mission, mission_path_from_arguments
from pipeline.stops import PROJECT_ROOT

TREK_URL = (
    "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/"
    "default/default028mm/{level}/{row}/{col}.jpg"
)
TREK_CACHE_DIR = os.path.join(RAW_DIR, "trek")
PLANET_IMAGE_PATH = os.path.join(PROJECT_ROOT, "web", "data", "globe", "mars_viking_colour.jpg")
TILE_SIZE = 256
SOURCE_TEXT = (
    "Mars Viking MDIM 2.1 Colorized Global Mosaic (USGS Astrogeology Science Center; "
    "NASA Viking Orbiter images), via NASA Mars Trek"
)
DEFAULT_CONTEXT = {
    "region_half_size_deg": (15.0, 12.5),  # longitude, latitude
    "crater_half_size_deg": (2.0, 1.5),
    "region_trek_level": 5,
    "crater_trek_level": 7,
}


class GridMapping:
    """Grid column/row <-> longitude/latitude (both linear in an equirectangular grid)."""

    def __init__(self, bounds_lonlat, width, height):
        self.west, self.south, self.east, self.north = bounds_lonlat
        self.width = width
        self.height = height

    def col(self, lon):
        return (lon - self.west) / (self.east - self.west) * self.width

    def row(self, lat):
        return (self.north - lat) / (self.north - self.south) * self.height

    def lon(self, col):
        return self.west + col / self.width * (self.east - self.west)

    def lat(self, row):
        return self.north - row / self.height * (self.north - self.south)


def trek_tile_range(level, west, south, east, north):
    """Rows and columns of the Trek tiles covering a box."""
    columns = 2 ** (level + 1)
    rows = 2**level
    col_first = int(math.floor((west + 180.0) / 360.0 * columns))
    col_last = int(math.ceil((east + 180.0) / 360.0 * columns)) - 1
    row_first = int(math.floor((90.0 - north) / 180.0 * rows))
    row_last = int(math.ceil((90.0 - south) / 180.0 * rows)) - 1
    return range(max(0, row_first), min(rows - 1, row_last) + 1), range(max(0, col_first), min(columns - 1, col_last) + 1)


def fetch_trek_tile(level, row, col):
    path = os.path.join(TREK_CACHE_DIR, str(level), str(row), f"{col}.jpg")
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        url = TREK_URL.format(level=level, row=row, col=col)
        # curl checks the HTTPS certificate with the operating system's certificate store.
        result = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "60", url],
            capture_output=True,
            check=True,
        )
        data = result.stdout
        Image.open(io.BytesIO(data)).verify()  # refuse anything that is not an image
        with open(path, "wb") as tile_file:
            tile_file.write(data)
        time.sleep(0.1)  # be gentle with the public service
    with Image.open(path) as tile:
        return numpy.array(tile.convert("RGB"))


def trek_mosaic(level, west, south, east, north):
    """Stitched Trek tiles and their exact (tile-aligned) longitude/latitude bounds."""
    rows, cols = trek_tile_range(level, west, south, east, north)
    image = numpy.zeros((len(rows) * TILE_SIZE, len(cols) * TILE_SIZE, 3), dtype=numpy.uint8)
    for row_index, row in enumerate(rows):
        for col_index, col in enumerate(cols):
            image[row_index * TILE_SIZE : (row_index + 1) * TILE_SIZE, col_index * TILE_SIZE : (col_index + 1) * TILE_SIZE] = fetch_trek_tile(level, row, col)
    degrees_per_tile = 360.0 / 2 ** (level + 1)
    bounds = (
        -180.0 + cols.start * degrees_per_tile,
        90.0 - (rows.stop) * degrees_per_tile,
        -180.0 + cols.stop * degrees_per_tile,
        90.0 - rows.start * degrees_per_tile,
    )
    return image, bounds


def native_zoom(image_width, bounds, mapping):
    """Map zoom at which one image pixel is one screen pixel (rounded down)."""
    grid_px_per_image_px = (mapping.col(bounds[2]) - mapping.col(bounds[0])) / image_width
    return int(math.floor(-math.log2(grid_px_per_image_px)))


def write_tiles(image, bounds, mapping, zooms, out_dir):
    """Cut an equirectangular image (bounds = west, south, east, north) into grid-space tiles."""
    west, south, east, north = bounds
    height, width = image.shape[:2]
    counts = {}
    for zoom in zooms:
        scale = 2.0**zoom
        x_min = mapping.col(west) * scale
        x_max = mapping.col(east) * scale
        y_min = mapping.row(north) * scale
        y_max = mapping.row(south) * scale
        count = 0
        for tile_x in range(int(math.floor(x_min / TILE_SIZE)), int(math.floor((x_max - 1e-9) / TILE_SIZE)) + 1):
            for tile_y in range(int(math.floor(y_min / TILE_SIZE)), int(math.floor((y_max - 1e-9) / TILE_SIZE)) + 1):
                pixel_x = tile_x * TILE_SIZE + numpy.arange(TILE_SIZE) + 0.5
                pixel_y = tile_y * TILE_SIZE + numpy.arange(TILE_SIZE) + 0.5
                lon = mapping.lon(pixel_x / scale)
                lat = mapping.lat(pixel_y / scale)
                source_col = numpy.floor((lon - west) / (east - west) * width).astype(int)
                source_row = numpy.floor((north - lat) / (north - south) * height).astype(int)
                inside_col = (source_col >= 0) & (source_col < width)
                inside_row = (source_row >= 0) & (source_row < height)
                tile = numpy.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=numpy.uint8)
                rows_index = numpy.clip(source_row, 0, height - 1)[:, None]
                cols_index = numpy.clip(source_col, 0, width - 1)[None, :]
                inside = inside_row[:, None] & inside_col[None, :]
                tile[..., :3] = image[rows_index, cols_index]
                tile[..., 3] = numpy.where(inside, 255, 0)
                if not inside.any():
                    continue
                folder = os.path.join(out_dir, str(zoom), str(tile_x))
                os.makedirs(folder, exist_ok=True)
                Image.fromarray(tile, mode="RGBA").save(os.path.join(folder, f"{tile_y}.png"), optimize=True)
                count += 1
        counts[zoom] = count
    return counts


def main(mission_path):
    mission = load_mission(mission_path)
    paths = MissionPaths(mission)
    with open(paths.grid, "r", encoding="utf-8") as grid_file:
        grid = json.load(grid_file)
    mapping = GridMapping(grid["bounds_lonlat"], grid["width"], grid["height"])
    centre_lon = (mapping.west + mapping.east) / 2
    centre_lat = (mapping.south + mapping.north) / 2

    with Image.open(PLANET_IMAGE_PATH) as planet_file:
        planet = numpy.array(planet_file.convert("RGB"))
    layers = [("context-planet", planet, (-180.0, -90.0, 180.0, 90.0))]
    for name, level_key, half_key in (
        ("context-region", "region_trek_level", "region_half_size_deg"),
        ("context-crater", "crater_trek_level", "crater_half_size_deg"),
    ):
        half_lon, half_lat = DEFAULT_CONTEXT[half_key]
        image, bounds = trek_mosaic(
            DEFAULT_CONTEXT[level_key], centre_lon - half_lon, centre_lat - half_lat, centre_lon + half_lon, centre_lat + half_lat
        )
        layers.append((name, image, bounds))

    entries = []
    previous_native = None
    for name, image, bounds in layers:
        native = native_zoom(image.shape[1], bounds, mapping)
        lowest = native - 2 if previous_native is None else previous_native + 1
        zooms = list(range(lowest, native + 1))
        counts = write_tiles(image, bounds, mapping, zooms, os.path.join(paths.pack_dir, "tiles", name))
        previous_native = native
        entries.append(
            {
                "id": name,
                "bounds_lonlat": [round(value, 6) for value in bounds],
                "min_zoom": min(zooms),
                "max_zoom": native,
                "source": SOURCE_TEXT,
            }
        )
        print(f"{name}: {image.shape[1]} x {image.shape[0]} px, bounds {bounds}, zooms {zooms}, tiles {sum(counts.values())}")
    with open(os.path.join(paths.work_dir, "context.json"), "w", encoding="utf-8") as context_file:
        json.dump({"layers": entries}, context_file, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
