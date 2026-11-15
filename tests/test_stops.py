import math
import os
import tempfile
import unittest

import numpy
import rasterio
from rasterio.transform import from_origin

from pipeline.stops import StopsFileError, lonlat_to_pixel, validate_stops

TEST_SPHERE_RADIUS_M = 1000.0


def valid_stop(stop_id, photo_file):
    return {
        "id": stop_id,
        "label": f"Stop {stop_id}",
        "lat": 18.0,
        "lon": 77.0,
        "position_source": "test",
        "photos": [{"file": photo_file, "sol": 2, "camera": "test", "image_id": None}],
    }


class LoadStopsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = self.temp_dir.name
        self.photos_dir = os.path.join(self.project_root, "data", "raw", "photos")
        os.makedirs(self.photos_dir)
        with open(os.path.join(self.photos_dir, "photo.png"), "wb") as photo_file:
            photo_file.write(b"test")
        self.stops_path = os.path.join(self.project_root, "data", "stops.json")
        self.stops = [
            valid_stop(1, "data/raw/photos/photo.png"),
            valid_stop(2, "data/raw/photos/photo.png"),
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def load(self):
        return validate_stops(self.stops, self.project_root, self.photos_dir)

    def assert_rejected(self, expected_text):
        with self.assertRaises(StopsFileError) as raised:
            self.load()
        matching_problems = []
        for problem in raised.exception.problems:
            if expected_text in problem:
                matching_problems.append(problem)
        self.assertTrue(
            len(matching_problems) > 0,
            f"no problem mentions {expected_text!r}: {raised.exception.problems}",
        )

    def test_valid_stops_load(self):
        self.assertEqual(len(self.load()), 2)

    def test_empty_lat_is_rejected(self):
        self.stops[0]["lat"] = None
        self.assert_rejected("lat is empty")

    def test_text_lon_is_rejected(self):
        self.stops[1]["lon"] = "77 E"
        self.assert_rejected("lon must be a number")

    def test_missing_field_is_rejected(self):
        del self.stops[0]["label"]
        self.assert_rejected("missing field 'label'")

    def test_duplicate_id_is_rejected(self):
        self.stops[1]["id"] = 1
        self.assert_rejected("duplicate id")

    def test_missing_photo_file_is_rejected(self):
        self.stops[0]["photos"][0]["file"] = "data/raw/photos/missing.png"
        self.assert_rejected("does not exist")

    def test_photo_outside_photos_folder_is_rejected(self):
        self.stops[0]["photos"][0]["file"] = "data/stops.json"
        self.assert_rejected("is not inside")

    def test_photo_sol_must_be_integer(self):
        self.stops[0]["photos"][0]["sol"] = "two"
        self.assert_rejected("sol must be an integer")

    def test_stop_without_photos_is_accepted(self):
        self.stops[0]["photos"] = []
        self.load()  # raises StopsFileError if rejected

    def test_not_a_list_is_rejected(self):
        self.stops = {"id": 1}
        self.assert_rejected("non-empty list")


class LonLatToPixelTest(unittest.TestCase):
    """A tiny raster in the same kind of projection as the real files (equirectangular on a sphere)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.raster_path = os.path.join(self.temp_dir.name, "test.tif")
        crs = rasterio.crs.CRS.from_dict({"proj": "eqc", "R": TEST_SPHERE_RADIUS_M, "units": "m"})
        pixel_size_m = 1.0
        with rasterio.open(
            self.raster_path,
            "w",
            driver="GTiff",
            width=20,
            height=20,
            count=1,
            dtype="uint8",
            crs=crs,
            transform=from_origin(0.0, 0.0, pixel_size_m, pixel_size_m),
        ) as raster:
            raster.write(numpy.zeros((1, 20, 20), dtype="uint8"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_known_point(self):
        # The point is 10.5 m east and 3.5 m south of the top-left corner -> col 10, row 3.
        lon = math.degrees(10.5 / TEST_SPHERE_RADIUS_M)
        lat = -math.degrees(3.5 / TEST_SPHERE_RADIUS_M)
        with rasterio.open(self.raster_path) as raster:
            self.assertEqual(lonlat_to_pixel(raster, lon, lat), [10, 3])


if __name__ == "__main__":
    unittest.main()
