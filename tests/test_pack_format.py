import json
import os
import tempfile
import unittest

from pipeline.pack_format import validate_pack


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file)


def read_json(path):
    with open(path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)


def write_empty_file(path):
    with open(path, "wb") as empty_file:
        empty_file.write(b"test")


def make_route(points):
    return {
        "points": points,
        "distance_m": 50.0,
        "climb_m": 2.0,
        "descent_m": 1.0,
        "max_slope_deg": 5.0,
        "max_slope_at": points[1],
    }


def write_small_valid_pack(pack_dir):
    """A minimal pack that follows the format: 1 layer, 2 stops, 1 leg."""
    os.makedirs(os.path.join(pack_dir, "layers"))
    os.makedirs(os.path.join(pack_dir, "photos"))
    write_empty_file(os.path.join(pack_dir, "layers", "slope.png"))
    write_empty_file(os.path.join(pack_dir, "photos", "stop1.jpg"))

    manifest = {
        "id": "test_pack",
        "version": "1.0.0",
        "created": "2026-01-01",
        "site": {
            "name": "Test site",
            "bounds_px": [0, 0, 100, 80],
            "bounds_lonlat": [0.0, 0.0, 1.0, 1.0],
        },
        "grid": {"width": 100, "height": 80, "metres_per_pixel": 1.0},
        "layers": [
            {
                "id": "slope",
                "kind": "raster-continuous",
                "file": "layers/slope.png",
                "units": "degrees",
                "legend": [],
                "source": "test",
                "product_id": "test",
                "as_of": "2026-01-01",
                "label": "CALCULATED",
                "method": "test method",
            }
        ],
    }
    stops = [
        {
            "id": 1,
            "label": "Stop 1",
            "position": [10, 10],
            "position_source": "test",
            "ground_slope_deg": 1.5,
            "unit": {"symbol": "Njf", "name": "Test unit", "description": "test"},
            "photos": [
                {"file": "photos/stop1.jpg", "sol": 2, "camera": "test", "image_id": None, "credit": "test"}
            ],
        },
        {
            "id": 2,
            "label": "Stop 2",
            "position": [50, 40],
            "position_source": "test",
            "ground_slope_deg": None,
            "unit": None,
            "photos": [
                {"file": "photos/stop1.jpg", "sol": 3, "camera": "test", "image_id": "ABC", "credit": "test"}
            ],
        },
    ]
    routes = [
        {
            "from": 1,
            "to": 2,
            "shortest": make_route([[10, 10], [30, 25], [50, 40]]),
            "gentlest": make_route([[10, 10], [20, 30], [50, 40]]),
        }
    ]
    write_json(os.path.join(pack_dir, "manifest.json"), manifest)
    write_json(os.path.join(pack_dir, "stops.json"), stops)
    write_json(os.path.join(pack_dir, "routes.json"), routes)


class PackFormatTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pack_dir = os.path.join(self.temp_dir.name, "pack")
        os.makedirs(self.pack_dir)
        write_small_valid_pack(self.pack_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def edit_json(self, file_name, change):
        """Load a pack file, apply change(data), save it back."""
        path = os.path.join(self.pack_dir, file_name)
        data = read_json(path)
        change(data)
        write_json(path, data)

    def assert_invalid(self, expected_text):
        errors = validate_pack(self.pack_dir)
        self.assertTrue(len(errors) > 0, "pack should be invalid")
        matching_errors = []
        for error in errors:
            if expected_text in error:
                matching_errors.append(error)
        self.assertTrue(len(matching_errors) > 0, f"no error mentions {expected_text!r}: {errors}")

    def test_valid_pack_has_no_errors(self):
        self.assertEqual(validate_pack(self.pack_dir), [])

    def test_missing_manifest(self):
        os.remove(os.path.join(self.pack_dir, "manifest.json"))
        self.assert_invalid("manifest.json not found")

    def test_missing_routes_file(self):
        os.remove(os.path.join(self.pack_dir, "routes.json"))
        self.assert_invalid("routes.json not found")

    def test_unknown_layer_kind(self):
        def change(manifest):
            manifest["layers"][0]["kind"] = "timeseries"
        self.edit_json("manifest.json", change)
        self.assert_invalid("kind 'timeseries'")

    def test_missing_layer_field(self):
        def change(manifest):
            del manifest["layers"][0]["source"]
        self.edit_json("manifest.json", change)
        self.assert_invalid("missing field 'source'")

    def test_estimate_label_is_refused(self):
        def change(manifest):
            manifest["layers"][0]["label"] = "ESTIMATE"
        self.edit_json("manifest.json", change)
        self.assert_invalid("label 'ESTIMATE'")

    def test_calculated_layer_needs_method(self):
        def change(manifest):
            del manifest["layers"][0]["method"]
        self.edit_json("manifest.json", change)
        self.assert_invalid("needs a 'method'")

    def test_nasa_data_layer_needs_no_method(self):
        def change(manifest):
            manifest["layers"][0]["label"] = "NASA DATA"
            del manifest["layers"][0]["method"]
        self.edit_json("manifest.json", change)
        self.assertEqual(validate_pack(self.pack_dir), [])

    def test_duplicate_layer_id(self):
        def change(manifest):
            manifest["layers"].append(dict(manifest["layers"][0]))
        self.edit_json("manifest.json", change)
        self.assert_invalid("duplicate id 'slope'")

    def test_layer_file_missing(self):
        os.remove(os.path.join(self.pack_dir, "layers", "slope.png"))
        self.assert_invalid("does not exist")

    def test_path_outside_pack_is_refused(self):
        write_empty_file(os.path.join(self.temp_dir.name, "outside.png"))

        def change(manifest):
            manifest["layers"][0]["file"] = "../outside.png"
        self.edit_json("manifest.json", change)
        self.assert_invalid("is not inside the pack")

    def test_absolute_path_is_refused(self):
        def change(manifest):
            manifest["layers"][0]["file"] = "/etc/hosts"
        self.edit_json("manifest.json", change)
        self.assert_invalid("is not inside the pack")

    def test_valid_tiled_imagery(self):
        os.makedirs(os.path.join(self.pack_dir, "tiles", "hirise"))

        def change(manifest):
            manifest["layers"].append(
                {
                    "id": "hirise",
                    "kind": "imagery",
                    "tiles": {
                        "url": "tiles/hirise/{z}/{x}/{y}.png",
                        "min_zoom": 0,
                        "max_zoom": 4,
                        "tile_size": 256,
                    },
                    "units": None,
                    "legend": None,
                    "source": "test",
                    "product_id": "test",
                    "as_of": "2026-01-01",
                    "label": "NASA DATA",
                }
            )
        self.edit_json("manifest.json", change)
        self.assertEqual(validate_pack(self.pack_dir), [])

    def test_tiles_not_for_points(self):
        os.makedirs(os.path.join(self.pack_dir, "tiles", "slope"))

        def change(manifest):
            manifest["layers"][0]["kind"] = "points"
            del manifest["layers"][0]["file"]
            manifest["layers"][0]["tiles"] = {
                "url": "tiles/slope/{z}/{x}/{y}.png",
                "min_zoom": 0,
                "max_zoom": 4,
                "tile_size": 256,
            }
        self.edit_json("manifest.json", change)
        self.assert_invalid("layers can use tiles")

    def test_stop_outside_grid(self):
        def change(stops):
            stops[1]["position"] = [500, 40]
        self.edit_json("stops.json", change)
        self.assert_invalid("outside the grid")

    def test_stop_photo_missing(self):
        def change(stops):
            stops[0]["photos"][0]["file"] = "photos/missing.jpg"
        self.edit_json("stops.json", change)
        self.assert_invalid("does not exist")

    def test_stop_without_photos(self):
        def change(stops):
            stops[0]["photos"] = []
        self.edit_json("stops.json", change)
        self.assert_invalid("photos must be a non-empty list")

    def test_unit_needs_name(self):
        def change(stops):
            del stops[0]["unit"]["name"]
        self.edit_json("stops.json", change)
        self.assert_invalid("missing field 'name'")

    def test_photo_needs_credit(self):
        def change(stops):
            del stops[0]["photos"][0]["credit"]
        self.edit_json("stops.json", change)
        self.assert_invalid("missing field 'credit'")

    def test_route_to_unknown_stop(self):
        def change(routes):
            routes[0]["to"] = 9
        self.edit_json("routes.json", change)
        self.assert_invalid("9 is not a known stop")

    def test_route_missing_number(self):
        def change(routes):
            del routes[0]["gentlest"]["descent_m"]
        self.edit_json("routes.json", change)
        self.assert_invalid("missing field 'descent_m'")

    def test_route_number_must_be_number(self):
        def change(routes):
            routes[0]["shortest"]["max_slope_deg"] = "steep"
        self.edit_json("routes.json", change)
        self.assert_invalid("max_slope_deg must be a number")

    def test_route_without_data_is_null(self):
        def change(routes):
            routes[0]["gentlest"] = None
        self.edit_json("routes.json", change)
        self.assertEqual(validate_pack(self.pack_dir), [])


if __name__ == "__main__":
    unittest.main()
