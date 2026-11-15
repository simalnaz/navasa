"""Mars time, sun position and Earth-Mars distance.

Mars time and sun: NASA GISS Mars24 algorithm (Allison 1997; Allison & McEwen 2000),
"Mars24 Sunclock: Algorithm and Worked Examples", updated 2025-01-07,
https://www.giss.nasa.gov/tools/mars24/help/algorithm.html  (steps A-1 .. D-6).

Earth position: JPL Solar System Dynamics, "Approximate Positions of the Planets"
(Standish & Williams), Table 1, valid 1800-2050,
https://ssd.jpl.nasa.gov/planets/approx_pos.html

web/marstime.js implements the same formulas for the app; tests/test_mars_time.py
checks both against the Mars24 worked examples.
"""

import math

# TT - UTC = TAI - UTC + 32.184 s. TAI - UTC has been 37 s since 2017-01-01 (Mars24 step A-4).
TT_MINUS_UTC_S = 69.184
JD_UNIX_EPOCH = 2440587.5
JD_J2000 = 2451545.0
MS_PER_DAY = 86400000.0

AU_KM = 149597870.7  # IAU 2012
LIGHT_SPEED_KM_S = 299792.458

PBS_TERMS = (  # Mars24 B-3: (A, tau, phi)
    (0.0071, 2.2353, 49.409),
    (0.0057, 2.7543, 168.173),
    (0.0039, 1.1177, 191.837),
    (0.0037, 15.7866, 21.736),
    (0.0021, 2.1354, 15.704),
    (0.0020, 2.4694, 95.528),
    (0.0018, 32.8493, 49.095),
)

# JPL Table 1 (1800-2050), Earth-Moon barycentre: value and rate per century
EARTH_ELEMENTS = {
    "a": (1.00000261, 0.00000562),
    "e": (0.01671123, -0.00004392),
    "I": (-0.00001531, -0.01294668),
    "L": (100.46457166, 35999.37244981),
    "long_peri": (102.93768193, 0.32327364),
    "long_node": (0.0, 0.0),
}


def sin_deg(angle):
    return math.sin(math.radians(angle))


def cos_deg(angle):
    return math.cos(math.radians(angle))


def days_since_j2000(unix_ms, tt_minus_utc_s=TT_MINUS_UTC_S):
    """Mars24 A-2, A-5, A-6: days since J2000 in Terrestrial Time."""
    jd_ut = JD_UNIX_EPOCH + unix_ms / MS_PER_DAY
    jd_tt = jd_ut + tt_minus_utc_s / 86400.0
    return jd_tt - JD_J2000, jd_tt


def mars_sun(unix_ms, east_longitude_deg, latitude_deg, tt_minus_utc_s=TT_MINUS_UTC_S):
    """Mars24 B-1 .. D-6 for a place on Mars. Angles in degrees, times in Mars hours."""
    dt, jd_tt = days_since_j2000(unix_ms, tt_minus_utc_s)
    mean_anomaly = 19.3871 + 0.52402073 * dt  # B-1
    alpha_fms = 270.3871 + 0.524038496 * dt  # B-2
    pbs = 0.0
    for amplitude, tau, phi in PBS_TERMS:  # B-3
        pbs += amplitude * cos_deg(0.985626 * dt / tau + phi)
    equation_of_centre = (  # B-4: nu - M
        (10.691 + 3.0e-7 * dt) * sin_deg(mean_anomaly)
        + 0.623 * sin_deg(2 * mean_anomaly)
        + 0.050 * sin_deg(3 * mean_anomaly)
        + 0.005 * sin_deg(4 * mean_anomaly)
        + 0.0005 * sin_deg(5 * mean_anomaly)
        + pbs
    )
    ls = (alpha_fms + equation_of_centre) % 360.0  # B-5
    eot_deg = 2.861 * sin_deg(2 * ls) - 0.071 * sin_deg(4 * ls) + 0.002 * sin_deg(6 * ls) - equation_of_centre  # C-1
    mst = (24.0 * (((jd_tt - 2451549.5) / 1.0274912517) + 44796.0 - 0.0009626)) % 24.0  # C-2
    west_longitude = (360.0 - east_longitude_deg) % 360.0
    lmst = (mst - west_longitude / 15.0) % 24.0  # C-3
    ltst = (lmst + eot_deg / 15.0) % 24.0  # C-4
    subsolar_west_longitude = (mst * 15.0 + eot_deg + 180.0) % 360.0  # C-5
    declination = math.degrees(math.asin(0.42565 * sin_deg(ls))) + 0.25 * sin_deg(ls)  # D-1
    distance_au = 1.52367934 * (  # D-2
        1.00436
        - 0.09309 * cos_deg(mean_anomaly)
        - 0.004336 * cos_deg(2 * mean_anomaly)
        - 0.00031 * cos_deg(3 * mean_anomaly)
        - 0.00003 * cos_deg(4 * mean_anomaly)
    )
    helio_longitude = (ls + 85.061 - 0.015 * sin_deg(71 + 2 * ls) - 5.5e-6 * dt) % 360.0  # D-3
    helio_latitude = -(1.8497 - 2.23e-5 * dt) * sin_deg(ls - 144.50 + 2.57e-6 * dt)  # D-4
    hour_angle = west_longitude - subsolar_west_longitude  # D-5: H = Lambda - Lambda_s (west longitudes)
    zenith = math.degrees(
        math.acos(
            sin_deg(declination) * sin_deg(latitude_deg)
            + cos_deg(declination) * cos_deg(latitude_deg) * cos_deg(hour_angle)
        )
    )
    azimuth = math.degrees(  # D-6, clockwise from north
        math.atan2(sin_deg(hour_angle), cos_deg(latitude_deg) * math.tan(math.radians(declination)) - sin_deg(latitude_deg) * cos_deg(hour_angle))
    ) % 360.0
    return {
        "days_since_j2000": dt,
        "mean_anomaly": mean_anomaly,
        "alpha_fms": alpha_fms,
        "pbs": pbs,
        "equation_of_centre": equation_of_centre,
        "ls": ls,
        "eot_deg": eot_deg,
        "mst": mst,
        "lmst": lmst,
        "ltst": ltst,
        "subsolar_west_longitude": subsolar_west_longitude,
        "declination": declination,
        "distance_au": distance_au,
        "helio_longitude": helio_longitude,
        "helio_latitude": helio_latitude,
        "zenith": zenith,
        "elevation": 90.0 - zenith,
        "azimuth": azimuth,
    }


def solve_kepler(mean_anomaly_deg, eccentricity):
    """Eccentric anomaly in degrees (JPL approximate positions, Newton iteration)."""
    e_star = math.degrees(eccentricity)
    anomaly = mean_anomaly_deg + e_star * sin_deg(mean_anomaly_deg)
    for _ in range(20):
        delta_m = mean_anomaly_deg - (anomaly - e_star * sin_deg(anomaly))
        delta_e = delta_m / (1 - eccentricity * cos_deg(anomaly))
        anomaly += delta_e
        if abs(delta_e) < 1e-8:
            break
    return anomaly


def earth_heliocentric_xyz(unix_ms):
    """Earth-Moon barycentre, ecliptic J2000 coordinates in AU (JPL Table 1)."""
    dt, _ = days_since_j2000(unix_ms)
    centuries = dt / 36525.0
    values = {}
    for name, (value, rate) in EARTH_ELEMENTS.items():
        values[name] = value + rate * centuries
    argument_of_perihelion = values["long_peri"] - values["long_node"]
    mean_anomaly = (values["L"] - values["long_peri"] + 180.0) % 360.0 - 180.0
    eccentric_anomaly = solve_kepler(mean_anomaly, values["e"])
    x_orbit = values["a"] * (cos_deg(eccentric_anomaly) - values["e"])
    y_orbit = values["a"] * math.sqrt(1 - values["e"] ** 2) * sin_deg(eccentric_anomaly)
    w, node, incl = argument_of_perihelion, values["long_node"], values["I"]
    x = (cos_deg(w) * cos_deg(node) - sin_deg(w) * sin_deg(node) * cos_deg(incl)) * x_orbit + (
        -sin_deg(w) * cos_deg(node) - cos_deg(w) * sin_deg(node) * cos_deg(incl)
    ) * y_orbit
    y = (cos_deg(w) * sin_deg(node) + sin_deg(w) * cos_deg(node) * cos_deg(incl)) * x_orbit + (
        -sin_deg(w) * sin_deg(node) + cos_deg(w) * cos_deg(node) * cos_deg(incl)
    ) * y_orbit
    z = sin_deg(w) * sin_deg(incl) * x_orbit + cos_deg(w) * sin_deg(incl) * y_orbit
    return x, y, z


def mars_heliocentric_xyz(unix_ms):
    """Mars from Mars24 D-2 .. D-4 (heliocentric distance, longitude, latitude), in AU."""
    sun = mars_sun(unix_ms, 0.0, 0.0)
    radius, longitude, latitude = sun["distance_au"], sun["helio_longitude"], sun["helio_latitude"]
    return (
        radius * cos_deg(latitude) * cos_deg(longitude),
        radius * cos_deg(latitude) * sin_deg(longitude),
        radius * sin_deg(latitude),
    )


def earth_mars_light_time_s(unix_ms):
    """One-way light time between Earth and Mars in seconds, and the distance in AU."""
    earth = earth_heliocentric_xyz(unix_ms)
    mars = mars_heliocentric_xyz(unix_ms)
    distance_au = math.dist(earth, mars)
    return distance_au * AU_KM / LIGHT_SPEED_KM_S, distance_au


# ---------------------------------------------------------------- sols
# Mars Sol Date: the same expression as inside Mars24 step C-2 (MST = 24 h x its fraction).
# Perseverance (Mars 2020) sols: sol 0 is the sol of landing, 2021-02-18 20:55 UTC (NASA
# landing confirmation time), counted in local mean solar time at the landing site
# (first entry of NASA's M20_waypoints.json, 77.45088572 E). Checked in the tests against
# the sol and spacecraft clock in NASA Perseverance raw-image IDs.
M20_LANDING_UNIX_MS = 1613681700000.0  # 2021-02-18 20:55:00 UTC
M20_LANDING_EAST_LONGITUDE = 77.45088572


def mars_sol_date(unix_ms, tt_minus_utc_s=TT_MINUS_UTC_S):
    _, jd_tt = days_since_j2000(unix_ms, tt_minus_utc_s)
    return (jd_tt - 2451549.5) / 1.0274912517 + 44796.0 - 0.0009626


def unix_ms_from_mars_sol_date(sol_date, tt_minus_utc_s=TT_MINUS_UTC_S):
    """Inverse of mars_sol_date."""
    jd_tt = (sol_date - 44796.0 + 0.0009626) * 1.0274912517 + 2451549.5
    return (jd_tt - tt_minus_utc_s / 86400.0 - JD_UNIX_EPOCH) * MS_PER_DAY


def local_sol_date(unix_ms, east_longitude_deg):
    """Mars Sol Date counted in local mean solar time at a longitude (its fraction is LMST / 24)."""
    west_longitude = (360.0 - east_longitude_deg) % 360.0
    return mars_sol_date(unix_ms) - west_longitude / 360.0


def m20_sol(unix_ms):
    """Perseverance mission sol at a moment (sol 0 = landing sol)."""
    landing_sol = math.floor(local_sol_date(M20_LANDING_UNIX_MS, M20_LANDING_EAST_LONGITUDE))
    return math.floor(local_sol_date(unix_ms, M20_LANDING_EAST_LONGITUDE)) - landing_sol


# ---------------------------------------------------------------- gravity
# NASA NSSDC Mars Fact Sheet (updated 19 May 2025),
# https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html
MARS_GM_M3_S2 = 0.042828e6 * 1e9  # 0.042828 x 10^6 km^3/s^2
MARS_J2 = 1960.45e-6
MARS_EQUATORIAL_RADIUS_M = 3396.2e3
MARS_POLAR_RADIUS_M = 3376.2e3
MARS_SIDEREAL_ROTATION_S = 24.6229 * 3600.0
NASA_MARS_MEAN_SURFACE_GRAVITY = 3.73
NASA_EARTH_MEAN_SURFACE_GRAVITY = 9.82


def ellipsoid_radius_m(latitude_deg):
    """Distance from Mars' centre to the reference ellipsoid at a latitude (geocentric)."""
    a, b = MARS_EQUATORIAL_RADIUS_M, MARS_POLAR_RADIUS_M
    return a * b / math.sqrt((b * cos_deg(latitude_deg)) ** 2 + (a * sin_deg(latitude_deg)) ** 2)


def mars_gravity_m_s2(latitude_deg, height_m=0.0):
    """Gravity felt on the surface: point mass + J2 flattening term, minus rotation (first order).

    g = GM/r^2 * (1 - 3/2 J2 (a/r)^2 (3 sin^2(lat) - 1)) - w^2 r cos^2(lat)
    r = ellipsoid radius at the latitude + height above it.
    """
    radius = ellipsoid_radius_m(latitude_deg) + height_m
    point_mass = MARS_GM_M3_S2 / radius**2
    flattening = 1.0 - 1.5 * MARS_J2 * (MARS_EQUATORIAL_RADIUS_M / radius) ** 2 * (3.0 * sin_deg(latitude_deg) ** 2 - 1.0)
    angular_speed = 2.0 * math.pi / MARS_SIDEREAL_ROTATION_S
    rotation = angular_speed**2 * radius * cos_deg(latitude_deg) ** 2
    return point_mass * flattening - rotation
