import math
import unittest

from pipeline.mars_time import (
    earth_heliocentric_xyz,
    earth_mars_light_time_s,
    m20_sol,
    mars_sol_date,
    mars_sun,
    unix_ms_from_mars_sol_date,
)


def unix_ms_from_jd_ut(jd_ut):
    return (jd_ut - 2440587.5) * 86400000.0


class Mars24WorkedExamplesTest(unittest.TestCase):
    """NASA GISS Mars24 'Algorithm and Worked Examples' (updated 2025-01-07)."""

    def test_example_1_jan_6_2000(self):
        # 00:00:00 UTC 2000-01-06, TT-UTC = 64.184 s, site 0 W 0 N
        sun = mars_sun(947116800000, 0.0, 0.0, tt_minus_utc_s=64.184)
        self.assertAlmostEqual(sun["days_since_j2000"], 4.50074, places=5)
        self.assertAlmostEqual(sun["mean_anomaly"], 21.74558, places=4)
        self.assertAlmostEqual(sun["alpha_fms"], 272.74566, places=4)
        self.assertAlmostEqual(sun["pbs"], 0.00142, places=4)
        self.assertAlmostEqual(sun["equation_of_centre"], 4.44193, places=4)
        self.assertAlmostEqual(sun["ls"], 277.18758, places=4)
        self.assertAlmostEqual(sun["eot_deg"], -5.18774, places=4)
        self.assertAlmostEqual(sun["mst"], 23.99425, places=4)
        self.assertAlmostEqual(sun["ltst"], 23.64840, places=4)
        self.assertAlmostEqual(sun["subsolar_west_longitude"], 174.72600, places=3)
        self.assertAlmostEqual(sun["declination"], -25.22825, places=4)
        self.assertAlmostEqual(sun["distance_au"], 1.39358, places=4)
        self.assertAlmostEqual(sun["helio_longitude"], 2.26352, places=4)
        self.assertAlmostEqual(sun["helio_latitude"], -1.35957, places=4)
        self.assertAlmostEqual(sun["zenith"], 154.26182, places=3)
        self.assertAlmostEqual(sun["azimuth"], 191.03905, places=3)

    def test_example_2_spirit_landing(self):
        # 13:46:31 UTC 2004-01-03, site 184.702 W, 14.640 S -> east longitude 175.298
        sun = mars_sun(1073137591000, 360.0 - 184.702, -14.640, tt_minus_utc_s=64.184)
        self.assertAlmostEqual(sun["days_since_j2000"], 1463.07471, places=4)
        self.assertAlmostEqual(sun["ls"], 327.32416, places=3)
        self.assertAlmostEqual(sun["eot_deg"], -12.77553, places=3)
        self.assertAlmostEqual(sun["mst"], 13.16537, places=4)
        self.assertAlmostEqual(sun["lmst"], 0.85190, places=3)
        self.assertAlmostEqual(sun["ltst"], 0.00025, places=3)
        self.assertAlmostEqual(sun["declination"], -13.42065, places=3)
        self.assertAlmostEqual(sun["zenith"], 151.93895, places=2)
        self.assertAlmostEqual(sun["azimuth"], 179.99383, places=2)


class EarthMarsDistanceTest(unittest.TestCase):
    def test_earth_is_about_one_au_from_the_sun(self):
        x, y, z = earth_heliocentric_xyz(unix_ms_from_jd_ut(2451545.0))
        self.assertAlmostEqual(math.sqrt(x * x + y * y + z * z), 0.983, places=2)  # early January: perihelion

    def test_light_time_stays_within_the_physical_range(self):
        # Earth-Mars distance is always between about 0.37 and 2.68 AU (3 to 22 light-minutes).
        for days in range(0, 800, 20):
            seconds, distance_au = earth_mars_light_time_s(unix_ms_from_jd_ut(2460000.0 + days))
            self.assertGreater(distance_au, 0.36)
            self.assertLess(distance_au, 2.7)
            self.assertAlmostEqual(seconds, distance_au * 149597870.7 / 299792.458, places=6)



class MarsGravityTest(unittest.TestCase):
    """Checked against the NASA NSSDC fact sheet values (2025)."""

    def test_pole_matches_nasa(self):
        from pipeline.mars_time import mars_gravity_m_s2
        self.assertAlmostEqual(mars_gravity_m_s2(90.0), 3.73, delta=0.01)  # sheet: pole 3.73

    def test_equator_close_to_nasa(self):
        from pipeline.mars_time import mars_gravity_m_s2
        self.assertAlmostEqual(mars_gravity_m_s2(0.0), 3.69, delta=0.02)  # sheet: equator 3.69

    def test_gravity_grows_towards_the_pole(self):
        from pipeline.mars_time import mars_gravity_m_s2
        self.assertLess(mars_gravity_m_s2(0.0), mars_gravity_m_s2(18.47))
        self.assertLess(mars_gravity_m_s2(18.47), mars_gravity_m_s2(90.0))

    def test_ratio_to_earth(self):
        from pipeline.mars_time import NASA_EARTH_MEAN_SURFACE_GRAVITY, NASA_MARS_MEAN_SURFACE_GRAVITY
        self.assertAlmostEqual(NASA_MARS_MEAN_SURFACE_GRAVITY / NASA_EARTH_MEAN_SURFACE_GRAVITY, 0.380, places=3)


if __name__ == "__main__":
    unittest.main()


J2000_UNIX_MS = 946728000000.0  # 2000-01-01 12:00:00 UTC

# (sol, spacecraft clock) read from NASA Perseverance raw-image IDs on mars.nasa.gov,
# e.g. FLF_0999_0755633592_... = sol 999, clock 755633592 s. The clock counts seconds from
# J2000 (taken here as TT, so UTC = J2000 + clock - 69.184 s; clock drift is seconds at most).
RAW_IMAGE_SOLS = (
    (1, 667022674),
    (999, 755633592),
    (1002, 755902653),
    (1003, 755993613),
    (1007, 756328035),
    (1009, 756528077),
    (1303, 782643014),
    (1400, 791224654),
)


class PerseveranceSolTest(unittest.TestCase):
    def test_landing_is_sol_0(self):
        self.assertEqual(m20_sol(1613681700000.0), 0)

    def test_sols_match_nasa_raw_image_ids(self):
        for sol, clock_s in RAW_IMAGE_SOLS:
            unix_ms = J2000_UNIX_MS + (clock_s - 69.184) * 1000.0
            self.assertEqual(m20_sol(unix_ms), sol)

    def test_sol_date_round_trip(self):
        unix_ms = 1763164800000.0
        self.assertAlmostEqual(unix_ms_from_mars_sol_date(mars_sol_date(unix_ms)), unix_ms, delta=1.0)
