"""Checks the browser's radio line-of-sight maths (web/los.js) with node."""

import json
import math
import os
import shutil
import subprocess
import unittest

from pipeline.stops import PROJECT_ROOT

NODE = shutil.which("node")
RADIUS_M = 3396190.0


def run_node(script):
    result = subprocess.run(
        [NODE, "-e", "globalThis.L = undefined; " + script],
        cwd=os.path.join(PROJECT_ROOT, "web"), capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(result.stdout)


@unittest.skipIf(NODE is None, "node is not installed")
class LineOfSightTest(unittest.TestCase):
    def check(self, heights, length_m, antenna_a, antenna_b):
        return run_node(
            "const S = require('./los.js');"
            f"console.log(JSON.stringify(S.check({json.dumps(heights)}, {length_m}, {antenna_a}, {antenna_b})));"
        )

    def test_flat_short_line_is_clear(self):
        result = self.check([0.0] * 101, 400.0, 2.0, 2.0)
        self.assertTrue(result["clear"])
        self.assertAlmostEqual(result["minClearance"], 2.0 - 200.0 * 200.0 / (2 * RADIUS_M), places=4)

    def test_wall_blocks_and_gives_the_first_block(self):
        heights = [0.0] * 11
        heights[4] = 5.0
        heights[5] = 5.0
        result = self.check(heights, 100.0, 2.0, 2.0)
        self.assertFalse(result["clear"])
        self.assertEqual(result["firstBlock"], 4)

    def test_mars_curvature_hides_far_antennas(self):
        # Two 2 m antennas on flat ground: each sees sqrt(2 R h) = 3.69 km to the horizon.
        horizon_m = 2 * math.sqrt(2 * RADIUS_M * 2.0)
        near = self.check([0.0] * 201, horizon_m * 0.95, 2.0, 2.0)
        far = self.check([0.0] * 201, horizon_m * 1.05, 2.0, 2.0)
        self.assertTrue(near["clear"])
        self.assertFalse(far["clear"])

    def test_missing_data_is_not_called_clear(self):
        result = self.check([0.0, None, 0.0], 10.0, 2.0, 2.0)
        self.assertIsNone(result["clear"])
        self.assertEqual(result["missing"], 1)

    def test_antenna_input(self):
        values = run_node(
            "const S = require('./los.js');"
            "console.log(JSON.stringify(['', ' 1,5 ', '2', '-1', 'abc', '5000'].map(S.parseAntenna)));"
        )
        self.assertEqual(values, [None, 1.5, 2, None, None, None])


if __name__ == "__main__":
    unittest.main()
