import copy
import json
import os
import unittest

from pipeline.mission import DEFAULT_MISSION_PATH, MissionPaths, check_mission


def read_default_mission():
    with open(DEFAULT_MISSION_PATH, "r", encoding="utf-8") as mission_file:
        return json.load(mission_file)


class MissionFileTest(unittest.TestCase):
    def setUp(self):
        self.mission = read_default_mission()

    def test_default_mission_is_valid(self):
        self.assertEqual(check_mission(self.mission), [])

    def test_objective_needs_a_source(self):
        mission = copy.deepcopy(self.mission)
        mission["objective_sources"] = []
        problems = check_mission(mission)
        self.assertTrue(any("objective_sources" in problem for problem in problems))

    def test_every_stop_needs_a_question(self):
        mission = copy.deepcopy(self.mission)
        del mission["stops"][0]["question"]
        problems = check_mission(mission)
        self.assertTrue(any("question" in problem for problem in problems))

    def test_unknown_status_is_refused(self):
        mission = copy.deepcopy(self.mission)
        mission["status"] = "SECRET"
        self.assertTrue(any("status" in problem for problem in check_mission(mission)))

    def test_missing_site_file_name_is_refused(self):
        mission = copy.deepcopy(self.mission)
        del mission["site"]["dtm_file"]
        self.assertTrue(any("dtm_file" in problem for problem in check_mission(mission)))

    def test_paths_are_per_pack(self):
        paths = MissionPaths(self.mission)
        self.assertTrue(paths.pack_dir.endswith(os.path.join("web", "data", self.mission["pack_id"])))
        self.assertTrue(paths.work_dir.endswith(os.path.join("data", "work", self.mission["pack_id"])))

    def test_wording_rule_potential_biosignature(self):
        text = json.dumps(self.mission).lower()
        self.assertNotIn("life found", text)
        if "biosignature" in text:
            self.assertIn("potential biosignature", text)


if __name__ == "__main__":
    unittest.main()
