"""Checks the mission editor's rules (web/editor.js) with node, and that its export passes the pipeline's own check."""

import json
import os
import shutil
import subprocess
import unittest

from pipeline.mission import check_mission
from pipeline.stops import PROJECT_ROOT

NODE = shutil.which("node")
BOUNDS = [77.2883, 18.4277, 77.4678, 18.5144]
GRID = {"width": 10637, "height": 5134}
SITE = "Jezero Crater"


def run_node(script):
    result = subprocess.run([NODE, "-e", script], cwd=os.path.join(PROJECT_ROOT, "web"), capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


def user_mission():
    return {
        "id": "delta-walk-a1b2c3",
        "name": "Delta walk",
        "status": "PLANNED",
        "objective": "Look at the delta front layers.",
        "objective_sources": [{"text": "Set by you in the NAVASA mission editor"}],
        "site": SITE,
        "stops": [
            {"id": 1, "label": "Start", "lat": 18.44, "lon": 77.45, "position_source": "Placed on the map", "question": "What is here?", "photos": []},
            {"id": 2, "label": "Front", "lat": 18.45, "lon": 77.40, "position_source": "Placed on the map", "question": "Layers?", "photos": []},
        ],
    }


@unittest.skipIf(NODE is None, "node is not installed")
class MissionEditorTest(unittest.TestCase):
    def check(self, mission):
        return run_node(
            "const E = require('./editor.js');"
            f"console.log(JSON.stringify(E.check({json.dumps(mission)}, {json.dumps(SITE)}, {json.dumps(BOUNDS)})));"
        )

    def test_valid_mission(self):
        self.assertEqual(self.check(user_mission()), [])

    def test_problems(self):
        mission = user_mission()
        mission["status"] = "DONE"
        mission["objective_sources"] = []
        mission["stops"][1]["lon"] = 80.0
        mission["stops"][1]["id"] = 1
        mission["stops"][0]["question"] = ""
        problems = " | ".join(self.check(mission))
        for expected in ("status", "objective_sources", "outside", "different for every stop", "question"):
            self.assertIn(expected, problems)

    def test_other_site_and_bad_url(self):
        mission = user_mission()
        mission["site"] = "Gale Crater"
        mission["objective_sources"] = [{"text": "x", "url": "javascript:alert(1)"}]
        problems = " | ".join(self.check(mission))
        self.assertIn("another site", problems)
        self.assertIn("https://", problems)

    def test_grid_round_trip_and_line_facts(self):
        values = run_node(
            "const E = require('./editor.js');"
            f"const b = {json.dumps(BOUNDS)}, g = {json.dumps(GRID)};"
            "const p = E.gridFromLonLat(b, g, 77.4, 18.45); const back = E.lonLatFromGrid(b, g, p[0], p[1]);"
            "console.log(JSON.stringify([back, E.lineFacts([10, 12, null, 11, 15], [5, 30, 8, null, 40]),"
            " E.parseSources('A paper | https://doi.org/x\\n\\nMy note'), E.slug('Delta Walk #2!')]));"
        )
        self.assertAlmostEqual(values[0][0], 77.4)
        self.assertAlmostEqual(values[0][1], 18.45)
        self.assertEqual(values[1], {"climb": 6, "descent": 1, "steepest": 30, "missing": 1})
        self.assertEqual(values[2], [{"text": "A paper", "url": "https://doi.org/x"}, {"text": "My note"}])
        self.assertEqual(values[3], "delta-walk-2")

    def test_export_passes_the_pipeline_check(self):
        with open(os.path.join(PROJECT_ROOT, "data", "missions", "jezero-biosignature.json"), encoding="utf-8") as mission_file:
            site_template = json.load(mission_file)["site"]
        exported = run_node(
            "const E = require('./editor.js');"
            f"console.log(JSON.stringify(E.toMissionFile({json.dumps(user_mission())}, {json.dumps(site_template)})));"
        )
        self.assertEqual(exported["pack_id"], "delta_walk_a1b2c3_v1")
        self.assertEqual(check_mission(exported), [])


if __name__ == "__main__":
    unittest.main()
