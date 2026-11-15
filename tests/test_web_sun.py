"""Checks the browser's sun and shadow maths (web/marstime.js, web/sun.js) with node, against Python."""

import json
import os
import shutil
import subprocess
import unittest

from pipeline.mars_time import earth_mars_light_time_s, m20_sol, mars_sun
from pipeline.stops import PROJECT_ROOT

WEB_DIR = os.path.join(PROJECT_ROOT, "web")
NODE = shutil.which("node")


def run_node(script):
    result = subprocess.run([NODE, "-e", script], cwd=WEB_DIR, capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


@unittest.skipIf(NODE is None, "node is not installed")
class WebSunTest(unittest.TestCase):
    def test_sols_and_sun_match_python(self):
        moments = [1613681700000.0, 1702361522816.0, 1763164800000.0, 1790000000000.0]
        values = run_node(
            "const M = require('./marstime.js');"
            f"const moments = {json.dumps(moments)};"
            "console.log(JSON.stringify(moments.map(t => [M.m20Sol(t), M.sun(t, 77.38, 18.47).elevation, M.sun(t, 77.38, 18.47).lmst])));"
        )
        for moment, (sol, elevation, lmst) in zip(moments, values):
            python_sun = mars_sun(moment, 77.38, 18.47)
            self.assertEqual(sol, m20_sol(moment))
            self.assertAlmostEqual(elevation, python_sun["elevation"], places=4)
            self.assertAlmostEqual(lmst, python_sun["lmst"], places=6)

    def test_local_time_round_trip_and_sunset(self):
        values = run_node(
            "const M = require('./marstime.js');"
            "const t = M.unixMsAtLocalTime(2040, 13.5, 77.38);"
            "const times = M.sunriseSunset(2040, 77.38, 18.47);"
            "console.log(JSON.stringify([M.m20Sol(t), M.sun(t, 77.38, 18.47).lmst, M.sun(times.sunrise, 77.38, 18.47).elevation,"
            " M.sun(times.sunset, 77.38, 18.47).elevation, times.sunrise < t, t < times.sunset]));"
        )
        sol, lmst, sunrise_elevation, sunset_elevation, rise_before, set_after = values
        self.assertEqual(sol, 2040)
        self.assertAlmostEqual(lmst, 13.5, places=5)
        self.assertAlmostEqual(sunrise_elevation, 0.0, places=3)
        self.assertAlmostEqual(sunset_elevation, 0.0, places=3)
        self.assertTrue(rise_before and set_after)

    def test_shadow_rules(self):
        values = run_node(
            "const S = require('./sun.js');"
            "const h = {directions_deg: [0, 90, 180, 270], angle_step_deg: 0.25, no_data_code: 255, cell_px: 16, width: 2, height: 1};"
            "const codes = [new Uint8Array([40, 255]), new Uint8Array([80, 0]), new Uint8Array([0, 0]), new Uint8Array([0, 0])];"
            "console.log(JSON.stringify(["
            " S.horizonAt(h, codes, 0, 45),"  # halfway between 10 and 20 degrees
            " S.inShadow(h, codes, 0, 45, 14.9), S.inShadow(h, codes, 0, 45, 15.1),"
            " S.inShadow(h, codes, 0, 180, -0.5),"  # night
            " S.inShadow(h, codes, 1, 0, 30),"  # no data
            " S.routeShadow(h, codes, [[0, 8], [31, 8]], 90, 10).shadow,"  # half the samples on each cell
            " S.mapAngle(90, 0.95), S.mapAngle(45, 1)"
            "]));"
        )
        self.assertAlmostEqual(values[0], 15.0)
        self.assertEqual(values[1:5], [True, False, True, None])
        # Sun east at 10°: cell 0 has a 20° horizon there (shadow), cell 1 has 0° (lit): half the route.
        self.assertAlmostEqual(values[5], 0.5)
        self.assertAlmostEqual(values[6], 90.0)
        self.assertAlmostEqual(values[7], 45.0)


    def test_earth_link_matches_python(self):
        moments = [1763164800000.0, 1790000000000.0, 1830000000000.0]
        values = run_node(
            "const M = require('./marstime.js');"
            f"console.log(JSON.stringify({json.dumps(moments)}.map(t => [M.earthLink(t).oneWaySeconds, M.earthLink(t).distanceAu])));"
        )
        for moment, (one_way, distance) in zip(moments, values):
            python_one_way, python_distance = earth_mars_light_time_s(moment)
            self.assertAlmostEqual(one_way, python_one_way, delta=0.01)
            self.assertAlmostEqual(distance, python_distance, places=8)

    def test_message_timeline(self):
        values = run_node(
            "const C = require('./comms.js');"
            "const t = C.messageTimeline(1000, 600);"
            "console.log(JSON.stringify([t.arrivesEarth, t.earliestReply, C.messageState(t, 301000), C.messageState(t, 901000).phase,"
            " C.messageState(t, 1300000).phase, C.formatDuration(754.4)]));"
        )
        self.assertEqual(values[0], 601000)
        self.assertEqual(values[1], 1201000)
        self.assertEqual(values[2], {"phase": "to-earth", "fraction": 0.5})
        self.assertEqual(values[3:6], ["to-mars", "done", "12 min 34 s"])


if __name__ == "__main__":
    unittest.main()
