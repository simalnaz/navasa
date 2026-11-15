"""Checks the browser's gravity panel maths (web/gravity.js, web/marstime.js) with node, against Python."""

import json
import os
import shutil
import subprocess
import unittest

from pipeline.mars_time import mars_gravity_m_s2
from pipeline.stops import PROJECT_ROOT

NODE = shutil.which("node")


def run_node(script):
    result = subprocess.run([NODE, "-e", script], cwd=os.path.join(PROJECT_ROOT, "web"), capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


@unittest.skipIf(NODE is None, "node is not installed")
class GravityPanelTest(unittest.TestCase):
    def test_values(self):
        values = run_node(
            "const G = require('./gravity.js'); const M = require('./marstime.js');"
            "const g = M.gravity(18.47, 0);"
            "console.log(JSON.stringify([g, G.weightNewtons(100, g), G.earthEquivalentKg(100, g, 9.82), G.climbWorkJoules(100, g, 92.6),"
            " ['', '80', ' 72,5 ', '0', '-3', 'x', '2000'].map(G.parseMass)]));"
        )
        g, weight, equivalent, work, masses = values
        self.assertAlmostEqual(g, mars_gravity_m_s2(18.47), places=6)
        self.assertAlmostEqual(weight, 100 * g)
        self.assertAlmostEqual(equivalent, 100 * g / 9.82)
        self.assertAlmostEqual(work, 100 * g * 92.6)
        self.assertEqual(masses, [None, 80, 72.5, None, None, None, None])

    def test_site_height_from_nasa_radius(self):
        g = run_node(
            "const M = require('./marstime.js');"
            "console.log(JSON.stringify(M.gravity(18.47, 3391936.53 - M.ellipsoidRadius(18.47))));"
        )
        from pipeline.mars_time import ellipsoid_radius_m

        self.assertAlmostEqual(g, mars_gravity_m_s2(18.47, 3391936.53 - ellipsoid_radius_m(18.47)), places=6)


if __name__ == "__main__":
    unittest.main()
