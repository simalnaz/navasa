import os
import tempfile
import unittest

from pipeline.mars_time import m20_sol, unix_ms_at_m20_local_time
from pipeline.meda import air_samples, ground_samples, parse_lmst, summarise

TIRS_HEADER = "SCLK,LMST,LTST,GROUND_TEMP,ROVER_STILL,ROVER_LOW_TILT,TIRS_GROUND_FOOTPRINT_NOT_IN_SHADOW,WHEEL_OUTSIDE_TIRS_DOWNWARD_LOOKING_FOV\n"
ATS_HEADER = "SCLK,LMST,LTST,ATS_LOCAL_TEMP1,ATS_LOCAL_TEMP2,ATS_LOCAL_TEMP3,ATS_LOCAL_TEMP4,ATS_LOCAL_TEMP5\n"


def write_table(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as table:
        table.write(text)
    return path


class MedaTest(unittest.TestCase):
    def test_parse_lmst(self):
        sol, hours = parse_lmst("01859M13:30:36.000")
        self.assertEqual(sol, 1859)
        self.assertAlmostEqual(hours, 13.51)

    def test_ground_rows_left_out_only_by_a_zero_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_table(
                folder,
                "tirs.csv",
                TIRS_HEADER
                + "1,00426M10:00:00.0,x,250.0,1,1,1,\n"  # empty wheel flag: kept
                + "2,00426M10:00:01.0,x,300.0,0,1,1,1\n"  # rover moving: left out
                + "3,00426M10:00:02.0,x,,1,1,1,1\n"  # no value
                + "4,00425M23:59:59.0,x,200.0,1,1,1,1\n",  # other sol
            )
            samples, left_out = ground_samples(path, 426)
        self.assertEqual(samples, [(10.0, 250.0)])
        self.assertEqual(left_out, 1)

    def test_air_needs_all_three_mast_sensors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_table(folder, "ats.csv", ATS_HEADER + "1,00015M01:00:00.0,x,200,210,220,0,0\n2,00015M01:00:01.0,x,200,,220,0,0\n")
            samples = air_samples(path, 15)
        self.assertEqual(samples, [(1.0, 210.0)])

    def test_summary_uses_minute_medians(self):
        samples = [(10.0, 273.15), (10.001, 273.15), (10.002, 400.0), (11.5, 263.15)]  # one spike in minute 600
        summary = summarise(samples)
        self.assertEqual([hour["hour"] for hour in summary["hourly"]], [10, 11])
        self.assertEqual(summary["hourly"][0]["mean_c"], 0.0)
        self.assertEqual(summary["max"]["c"], 0.0)
        self.assertEqual(summary["min"], {"c": -10.0, "lmst_hours": 11.5})
        self.assertIsNone(summarise([]))

    def test_local_time_on_a_sol(self):
        self.assertEqual(m20_sol(unix_ms_at_m20_local_time(426, 12.0)), 426)
        self.assertEqual(m20_sol(unix_ms_at_m20_local_time(426, 23.99)), 426)


if __name__ == "__main__":
    unittest.main()
