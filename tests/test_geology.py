import unittest

import numpy
from rasterio.transform import from_origin

from pipeline.geology import (
    NO_UNIT,
    corrected_name,
    number_units,
    overlay_image,
    unit_grid,
    unit_outlines,
)


def square(x_min, y_min, x_max, y_max):
    return {
        "type": "Polygon",
        "coordinates": [[[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max], [x_min, y_min]]],
    }


class NamesTest(unittest.TestCase):
    def test_spelling_correction(self):
        self.assertEqual(corrected_name("Crater riim unit"), "Crater rim unit")
        self.assertEqual(corrected_name("Jezero fan 2 unit"), "Jezero fan 2 unit")

    def test_units_are_numbered_in_symbol_order(self):
        features = [(None, "b", "B unit"), (None, "a", "A unit"), (None, "b", "B unit")]
        numbers, names = number_units(features)
        self.assertEqual(numbers, {"a": 1, "b": 2})
        self.assertEqual(names["b"], "B unit")

    def test_one_symbol_with_two_names_is_refused(self):
        with self.assertRaises(ValueError):
            number_units([(None, "cr", "Crater rim unit"), (None, "cr", "Other name")])


class UnitGridTest(unittest.TestCase):
    def test_squares_land_on_the_right_cells(self):
        # 10 x 10 grid of 1 m cells, top-left corner at x=0, y=10.
        grid_transform = from_origin(0.0, 10.0, 1.0, 1.0)
        features = [(square(0, 5, 5, 10), "a", "A unit"), (square(5, 0, 10, 5), "b", "B unit")]
        numbers, _ = number_units(features)
        units = unit_grid(features, numbers, (10, 10), grid_transform)
        self.assertEqual(units[0, 0], 1)  # top-left quarter = a
        self.assertEqual(units[9, 9], 2)  # bottom-right quarter = b
        self.assertEqual(units[0, 9], NO_UNIT)  # top-right quarter has no unit
        self.assertEqual(int((units == 1).sum()), 25)


class OverlayTest(unittest.TestCase):
    def test_no_unit_is_transparent_and_units_are_visible(self):
        units = numpy.zeros((20, 20), dtype=numpy.uint8)
        units[:, 10:] = 1
        styles = {1: {"color": [200, 0, 0], "pattern": "diagonal"}}
        overlay = overlay_image(units, styles)
        self.assertEqual(overlay[5, 2, 3], 0)  # no unit
        self.assertGreater(overlay[5, 15, 3], 0)  # unit
        self.assertTrue((overlay[:, 10:, 3] == 255).any())  # hatch lines drawn

    def test_outlines_mark_unit_edges(self):
        units = numpy.zeros((4, 4), dtype=numpy.uint8)
        units[:, 2:] = 1
        outlines = unit_outlines(units)
        self.assertTrue(outlines[0, 1])
        self.assertFalse(outlines[0, 0])


if __name__ == "__main__":
    unittest.main()
