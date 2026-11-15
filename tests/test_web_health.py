"""Checks the health panel's simulation maths (web/health.js) with node."""

import json
import os
import shutil
import subprocess
import unittest

from pipeline.stops import PROJECT_ROOT

NODE = shutil.which("node")


def run_node(script):
    result = subprocess.run([NODE, "-e", script], cwd=os.path.join(PROJECT_ROOT, "web"), capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


@unittest.skipIf(NODE is None, "node is not installed")
class HealthSimulationTest(unittest.TestCase):
    def test_simulation_and_inputs(self):
        values = run_node(
            "const H = require('./health.js');"
            "console.log(JSON.stringify([H.simulate(100, 20, 2), H.simulate(100, 20, 9), H.formatHms(3725000),"
            " ['', '5', '0', '-1', 'x', '2,5'].map(t => H.parseAmount(t, false)), H.parseAmount('0', true)]));"
        )
        self.assertEqual(values[0], {"remaining": 60, "fraction": 0.6, "hoursLeft": 3, "emptyAfterHours": 5})
        self.assertEqual(values[1]["remaining"], 0)
        self.assertEqual(values[2], "1:02:05")
        self.assertEqual(values[3], [None, 5, 0, None, None, 2.5])
        self.assertIsNone(values[4])


if __name__ == "__main__":
    unittest.main()
