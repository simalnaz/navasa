"""Cut the terrain and the 25 cm image to the walk area, on one grid, and make map tiles.

Walk area: the box around all stops on the 1 m DTM grid, plus DEFAULT_CROP["margin_m"]
on every side. The DTM pixels of that box are the pack grid: pixel [col, row]
means the same place in every layer.

Outputs:
    data/work/dtm_1m.tif      cropped DTM (heights in metres, the file's own no-data value kept)
    data/work/grid.json       the grid: size, metres per pixel, position on Mars
    web/data/jezero_v1/tiles/hirise/{z}/{x}/{y}.jpg
                              25 cm image as 256 px JPEG tiles. At zoom z, one grid
                              pixel is 2**z tile pixels. The highest zoom shows the
                              image at its full 25 cm resolution; the lowest zoom
                              fits the whole area in one tile.

Usage:
    python -m pipeline.crop_layers
"""

import json
import math
import os
import sys

import numpy
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.warp import transform
from rasterio.windows import Window, from_bounds

from pipeline.stops import PROJECT_ROOT, load_stops, lonlat_to_pixel

RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
WORK_DIR = os.path.join(PROJECT_ROOT, "data", "work")
PACK_DIR = os.path.join(PROJECT_ROOT, "web", "data", "jezero_v1")

DTM_PATH = os.path.join(RAW_DIR, "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif")
HIRISE_PATH = os.path.join(RAW_DIR, "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first.tif")
CROPPED_DTM_PATH = os.path.join(WORK_DIR, "dtm_1m.tif")
GRID_PATH = os.path.join(WORK_DIR, "grid.json")
HIRISE_TILES_DIR = os.path.join(PACK_DIR, "tiles", "hirise")

DEFAULT_CROP = {"margin_m": 1000}
DEFAULT_TILES = {"tile_size": 256, "jpeg_quality": 75}


def walk_area_window(stop_pixels, margin_px, raster_width, raster_height):
    """Box around the stop pixels plus margin_px on every side, cut to the raster edges."""
    cols = []
    rows = []
    for col, row in stop_pixels:
        if col < 0 or col >= raster_width or row < 0 or row >= raster_height:
            raise ValueError(f"stop pixel {[col, row]} is outside the raster")
        cols.append(col)
        rows.append(row)
    col_min = max(0, min(cols) - margin_px)
    row_min = max(0, min(rows) - margin_px)
    col_max = min(raster_width - 1, max(cols) + margin_px)
    row_max = min(raster_height - 1, max(rows) + margin_px)
    return Window(col_min, row_min, col_max - col_min + 1, row_max - row_min + 1)


def aligned_window(dataset, bounds):
    """Window of dataset covering bounds; the edges must fall exactly on pixel edges."""
    window = from_bounds(*bounds, transform=dataset.transform)
    values = (window.col_off, window.row_off, window.width, window.height)
    rounded = []
    for value in values:
        if abs(value - round(value)) > 1e-6:
            raise ValueError(f"{dataset.name}: walk area does not line up with its pixels ({values})")
        rounded.append(int(round(value)))
    return Window(*rounded)


def downsample_by_two(image, nodata):
    """Halve width and height; each new pixel is the mean of its valid 2x2 source pixels."""
    height, width = image.shape
    padded = numpy.full((height + height % 2, width + width % 2), nodata, dtype=image.dtype)
    padded[:height, :width] = image
    blocks = padded.reshape(padded.shape[0] // 2, 2, padded.shape[1] // 2, 2)
    valid = blocks != nodata
    total = numpy.where(valid, blocks, 0).astype(numpy.uint32).sum(axis=(1, 3))
    count = valid.sum(axis=(1, 3))
    result = numpy.full(total.shape, nodata, dtype=image.dtype)
    has_data = count > 0
    result[has_data] = numpy.round(total[has_data] / count[has_data]).astype(image.dtype)
    return result


def save_tile(tile_pixels, path, tile_size, nodata, jpeg_quality):
    """Save one tile; tiles at the right and bottom edge are padded with the no-data value."""
    tile = numpy.full((tile_size, tile_size), nodata, dtype=numpy.uint8)
    tile[: tile_pixels.shape[0], : tile_pixels.shape[1]] = tile_pixels
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(tile, mode="L").save(path, "JPEG", quality=jpeg_quality)


def save_tile_row(image_rows, zoom, tile_row, tiles_dir, tile_size, nodata, jpeg_quality):
    """Save all tiles of one row of tiles. Return how many were written."""
    tile_count = 0
    for tile_col in range(math.ceil(image_rows.shape[1] / tile_size)):
        col_start = tile_col * tile_size
        tile_pixels = image_rows[:, col_start : col_start + tile_size]
        path = os.path.join(tiles_dir, str(zoom), str(tile_col), f"{tile_row}.jpg")
        save_tile(tile_pixels, path, tile_size, nodata, jpeg_quality)
        tile_count += 1
    return tile_count


def save_all_tiles(image, zoom, tiles_dir, tile_size, nodata, jpeg_quality):
    tile_count = 0
    for tile_row in range(math.ceil(image.shape[0] / tile_size)):
        row_start = tile_row * tile_size
        image_rows = image[row_start : row_start + tile_size, :]
        tile_count += save_tile_row(image_rows, zoom, tile_row, tiles_dir, tile_size, nodata, jpeg_quality)
    return tile_count


def make_hirise_tiles(hirise, window, max_zoom, tiles_dir, tile_size, jpeg_quality):
    """Tile the cropped 25 cm image, reading it one row of tiles at a time.

    The full-resolution zoom is written while reading; a half-size copy is kept
    in memory and halved again for every lower zoom.
    """
    nodata = int(hirise.nodata)
    half_size = numpy.full(
        (math.ceil(window.height / 2), math.ceil(window.width / 2)), nodata, dtype=numpy.uint8
    )
    tile_counts = {max_zoom: 0}
    for tile_row in range(math.ceil(window.height / tile_size)):
        row_start = tile_row * tile_size
        rows_to_read = min(tile_size, window.height - row_start)
        strip = hirise.read(
            1, window=Window(window.col_off, window.row_off + row_start, window.width, rows_to_read)
        )
        tile_counts[max_zoom] += save_tile_row(
            strip, max_zoom, tile_row, tiles_dir, tile_size, nodata, jpeg_quality
        )
        half_strip = downsample_by_two(strip, nodata)
        half_size[row_start // 2 : row_start // 2 + half_strip.shape[0], :] = half_strip
        print(f"  zoom {max_zoom}: tile row {tile_row + 1} of {math.ceil(window.height / tile_size)}", end="\r")
    print()

    zoom = max_zoom - 1
    image = half_size
    while True:
        tile_counts[zoom] = save_all_tiles(image, zoom, tiles_dir, tile_size, nodata, jpeg_quality)
        if image.shape[0] <= tile_size and image.shape[1] <= tile_size:
            break
        image = downsample_by_two(image, nodata)
        zoom -= 1
    return tile_counts


def lonlat_bounds(dataset, map_bounds):
    """[west, south, east, north] in degrees, from the dataset's own sphere radius."""
    lonlat_crs = CRS.from_dict({"proj": "longlat", "R": dataset.crs.to_dict()["R"], "no_defs": True})
    lons, lats = transform(
        dataset.crs, lonlat_crs, [map_bounds[0], map_bounds[2]], [map_bounds[1], map_bounds[3]]
    )
    return [lons[0], lats[0], lons[1], lats[1]]


def main():
    stops = load_stops()
    os.makedirs(WORK_DIR, exist_ok=True)

    with rasterio.open(DTM_PATH) as dtm:
        metres_per_pixel = dtm.res[0]
        if dtm.res[0] != dtm.res[1]:
            raise ValueError("DTM pixels are not square")
        stop_pixels = []
        for stop in stops:
            stop_pixels.append(lonlat_to_pixel(dtm, stop["lon"], stop["lat"]))
        margin_px = int(round(DEFAULT_CROP["margin_m"] / metres_per_pixel))
        window = walk_area_window(stop_pixels, margin_px, dtm.width, dtm.height)
        window_transform = dtm.window_transform(window)
        map_bounds = rasterio.windows.bounds(window, dtm.transform)

        profile = dtm.profile.copy()
        profile.update(width=window.width, height=window.height, transform=window_transform)
        heights = dtm.read(1, window=window)
        with rasterio.open(CROPPED_DTM_PATH, "w", **profile) as cropped:
            cropped.write(heights, 1)
        no_data_cells = int((heights == dtm.nodata).sum())
        grid = {
            "width": window.width,
            "height": window.height,
            "metres_per_pixel": metres_per_pixel,
            "window_in_dtm": [window.col_off, window.row_off, window.width, window.height],
            "map_bounds_m": list(map_bounds),
            "bounds_lonlat": lonlat_bounds(dtm, map_bounds),
            "crs": dtm.crs.to_string(),
            "margin_m": DEFAULT_CROP["margin_m"],
        }

    with open(GRID_PATH, "w", encoding="utf-8") as grid_file:
        json.dump(grid, grid_file, indent=2)
    print(f"Grid: {grid['width']} x {grid['height']} pixels at {metres_per_pixel} m")
    print(f"Bounds (lon/lat): {grid['bounds_lonlat']}")
    print(f"DTM cells without data in the walk area: {no_data_cells}")

    with rasterio.open(HIRISE_PATH) as hirise:
        hirise_window = aligned_window(hirise, map_bounds)
        pixels_per_grid_pixel = hirise_window.width / window.width
        max_zoom = int(round(math.log2(pixels_per_grid_pixel)))
        if 2**max_zoom != pixels_per_grid_pixel:
            raise ValueError(f"25 cm image is {pixels_per_grid_pixel} x the grid, not a power of two")
        print(f"25 cm image window: {hirise_window.width} x {hirise_window.height} pixels")
        tile_counts = make_hirise_tiles(
            hirise,
            hirise_window,
            max_zoom,
            HIRISE_TILES_DIR,
            DEFAULT_TILES["tile_size"],
            DEFAULT_TILES["jpeg_quality"],
        )
    for zoom in sorted(tile_counts):
        print(f"  zoom {zoom}: {tile_counts[zoom]} tiles")
    print(f"Tiles in {HIRISE_TILES_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
