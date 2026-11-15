"""Rock units from USGS SIM 3464 on the walk-area grid.

The unit outlines (layer GeoUnits_v1 of the SIM 3464 geodatabase) were converted
once with GDAL to GeoJSON in the grid's coordinate system:

    ogr2ogr -f GeoJSON data/raw/sim3464_geounits.geojson \\
      data/raw/sim3464_database/sim3464_JezeroNili_FINAL/Geodatabase/Nili.gdb GeoUnits_v1 \\
      -select unit,name,symbol \\
      -t_srs "+proj=eqc +lat_ts=0 +lon_0=0 +R=3396190 +units=m +no_defs"

Each unit gets a number (1, 2, ... in symbol order; 0 = no unit). Unit names come
from the database, with one spelling correction (NAME_CORRECTIONS). Unit
descriptions come from data/unit_descriptions.json, copied word for word from
the map's Description of Map Units; units without one get null. The GeoJSON and
the descriptions file are named in the mission file.

Outputs (in data/work/<pack>/):
    data/work/geology_overlay.png  overlay: colour fill, a hatch pattern per unit and
                                   unit outlines, so units are told apart without
                                   colour alone (build_pack.py cuts it into tiles)
    data/work/geology_ids.png      unit number of every cell (build_pack.py samples it
                                   for the cursor readout)
    data/work/geology.json         units (number, symbol, name, description, colour,
                                   pattern), unit at each stop

Usage:
    python -m pipeline.geology [data/missions/<mission>.json]
"""

import json
import os
import sys

import numpy
import rasterio
from matplotlib import colormaps
from PIL import Image
from rasterio.features import rasterize

from pipeline.mission import MissionPaths, load_mission, mission_path_from_arguments
from pipeline.stops import lonlat_to_pixel

NO_UNIT = 0
NAME_CORRECTIONS = {"Crater riim unit": "Crater rim unit"}  # spelling error in the source database
PATTERNS = ("diagonal", "back-diagonal", "horizontal", "vertical", "cross", "dots")
# Display choices only (no meaning beyond telling units apart).
DEFAULT_DISPLAY = {"fill_alpha": 90, "pattern_spacing_px": 12, "colormap": "tab20"}


def corrected_name(name):
    if name in NAME_CORRECTIONS:
        return NAME_CORRECTIONS[name]
    return name


def load_unit_features(geojson_path):
    """List of (geometry, symbol, name) from the converted GeoJSON."""
    with open(geojson_path, "r", encoding="utf-8") as geojson_file:
        collection = json.load(geojson_file)
    features = []
    for feature in collection["features"]:
        properties = feature["properties"]
        if feature["geometry"] is None or properties.get("symbol") is None:
            continue
        features.append((feature["geometry"], properties["symbol"], corrected_name(properties["name"])))
    return features


def number_units(features):
    """Map symbol -> unit number (1, 2, ... in symbol order) and symbol -> name.

    Raises if one symbol has two different names after corrections.
    """
    names_by_symbol = {}
    for _, symbol, name in features:
        if symbol in names_by_symbol and names_by_symbol[symbol] != name:
            raise ValueError(f"unit {symbol!r} has two names: {names_by_symbol[symbol]!r} and {name!r}")
        names_by_symbol[symbol] = name
    numbers_by_symbol = {}
    for index, symbol in enumerate(sorted(names_by_symbol)):
        numbers_by_symbol[symbol] = index + 1
    if len(numbers_by_symbol) > 255:
        raise ValueError("more than 255 units do not fit in the 8-bit lookup image")
    return numbers_by_symbol, names_by_symbol


def unit_grid(features, numbers_by_symbol, out_shape, grid_transform):
    """Unit number for every grid cell (cell centre inside the outline); NO_UNIT elsewhere."""
    shapes = []
    for geometry, symbol, _ in features:
        shapes.append((geometry, numbers_by_symbol[symbol]))
    return rasterize(
        shapes, out_shape=out_shape, transform=grid_transform, fill=NO_UNIT, dtype="uint8"
    )


def pattern_mask(pattern, out_shape, spacing):
    """True where the hatch pattern draws a line."""
    rows, cols = numpy.indices(out_shape)
    if pattern == "diagonal":
        return (rows + cols) % spacing == 0
    if pattern == "back-diagonal":
        return (rows - cols) % spacing == 0
    if pattern == "horizontal":
        return rows % spacing == 0
    if pattern == "vertical":
        return cols % spacing == 0
    if pattern == "cross":
        return (rows % spacing == 0) | (cols % spacing == 0)
    if pattern == "dots":
        return (rows % spacing == 0) & (cols % spacing == 0)
    raise ValueError(f"unknown pattern {pattern!r}")


def unit_outlines(units):
    """True on cells whose right or lower neighbour belongs to a different unit."""
    outlines = numpy.zeros(units.shape, dtype=bool)
    outlines[:, :-1] |= units[:, :-1] != units[:, 1:]
    outlines[:-1, :] |= units[:-1, :] != units[1:, :]
    return outlines


def unit_styles(numbers_by_symbol):
    """Colour (r, g, b) and pattern for each unit number."""
    colormap = colormaps[DEFAULT_DISPLAY["colormap"]]
    styles = {}
    for symbol, number in numbers_by_symbol.items():
        red, green, blue, _ = colormap((number - 1) % colormap.N)
        styles[number] = {
            "color": [int(red * 255), int(green * 255), int(blue * 255)],
            "pattern": PATTERNS[(number - 1) % len(PATTERNS)],
        }
    return styles


def overlay_image(units, styles):
    """RGBA overlay: see-through fill, solid hatch lines and outlines; no unit = transparent."""
    overlay = numpy.zeros(units.shape + (4,), dtype=numpy.uint8)
    spacing = DEFAULT_DISPLAY["pattern_spacing_px"]
    for number, style in styles.items():
        in_unit = units == number
        if not in_unit.any():
            continue
        overlay[in_unit, 0:3] = style["color"]
        overlay[in_unit, 3] = DEFAULT_DISPLAY["fill_alpha"]
        hatch = in_unit & pattern_mask(style["pattern"], units.shape, spacing)
        overlay[hatch, 3] = 255
    outlines = unit_outlines(units)
    overlay[outlines, 0:3] = 0
    overlay[outlines, 3] = 255
    return overlay


def main(mission_path):
    mission = load_mission(mission_path)
    paths = MissionPaths(mission)
    with open(paths.unit_descriptions, "r", encoding="utf-8") as descriptions_file:
        descriptions = json.load(descriptions_file)

    features = load_unit_features(paths.geology_units)
    numbers_by_symbol, names_by_symbol = number_units(features)
    stops = mission["stops"]
    with rasterio.open(paths.cropped_dtm) as dtm:
        units = unit_grid(features, numbers_by_symbol, (dtm.height, dtm.width), dtm.transform)
        stop_units = {}
        for stop in stops:
            col, row = lonlat_to_pixel(dtm, stop["lon"], stop["lat"])
            stop_units[stop["id"]] = int(units[row, col])

    present_numbers = set(numpy.unique(units).tolist())
    styles = unit_styles(numbers_by_symbol)
    unit_list = []
    for symbol, number in sorted(numbers_by_symbol.items(), key=lambda item: item[1]):
        if number not in present_numbers:
            continue
        unit_list.append(
            {
                "id": number,
                "symbol": symbol,
                "name": names_by_symbol[symbol],
                "description": descriptions.get(symbol),
                "color": styles[number]["color"],
                "pattern": styles[number]["pattern"],
            }
        )

    os.makedirs(paths.work_dir, exist_ok=True)
    Image.fromarray(overlay_image(units, styles), mode="RGBA").save(paths.geology_overlay, optimize=True)
    Image.fromarray(units, mode="L").save(paths.geology_ids, optimize=True)
    with open(paths.geology_json, "w", encoding="utf-8") as geology_file:
        json.dump({"units": unit_list, "stop_units": stop_units}, geology_file, ensure_ascii=False, indent=2)

    no_unit_cells = int((units == NO_UNIT).sum())
    print(f"Units in the walk area: {len(unit_list)}; cells without a unit: {no_unit_cells} of {units.size}")
    for unit in unit_list:
        cell_count = int((units == unit["id"]).sum())
        has_description = "description" if unit["description"] is not None else "no description"
        print(f"  {unit['id']:>2} {unit['symbol']:<6} {unit['name']:<26} {cell_count:>10} cells  {has_description}")
    for stop in stops:
        number = stop_units[stop["id"]]
        symbol = "no unit"
        for unit in unit_list:
            if unit["id"] == number:
                symbol = f"{unit['symbol']} {unit['name']}"
        print(f"Stop {stop['id']} {stop['label']}: {symbol}")
    for path in (paths.geology_overlay, paths.geology_ids):
        print(f"{path}: {os.path.getsize(path) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
