// Mars time, sun position, Earth-Mars light time and Mars gravity, in the browser.
// The same formulas as pipeline/mars_time.py (tested there against NASA's worked examples):
// - NASA GISS Mars24 "Algorithm and Worked Examples" (updated 2025-01-07), steps A-1 .. D-6
// - JPL SSD "Approximate Positions of the Planets", Table 1 (1800-2050), Earth-Moon barycentre
// - NASA NSSDC Mars Fact Sheet (updated 19 May 2025): GM, J2, radii, rotation

"use strict";

const MarsTime = (function () {
  const TT_MINUS_UTC_S = 69.184; // TAI-UTC 37 s since 2017 + 32.184 s (Mars24 A-4)
  const AU_KM = 149597870.7;
  const LIGHT_SPEED_KM_S = 299792.458;
  const PBS_TERMS = [
    [0.0071, 2.2353, 49.409],
    [0.0057, 2.7543, 168.173],
    [0.0039, 1.1177, 191.837],
    [0.0037, 15.7866, 21.736],
    [0.0021, 2.1354, 15.704],
    [0.002, 2.4694, 95.528],
    [0.0018, 32.8493, 49.095],
  ];
  const EARTH_ELEMENTS = {
    a: [1.00000261, 0.00000562],
    e: [0.01671123, -0.00004392],
    I: [-0.00001531, -0.01294668],
    L: [100.46457166, 35999.37244981],
    longPeri: [102.93768193, 0.32327364],
    longNode: [0.0, 0.0],
  };
  const GRAVITY = {
    gm: 0.042828e6 * 1e9,
    j2: 1960.45e-6,
    equatorialRadius: 3396.2e3,
    polarRadius: 3376.2e3,
    siderealRotationS: 24.6229 * 3600,
    marsMean: 3.73,
    earthMean: 9.82,
  };

  const rad = Math.PI / 180;
  const sin = (degrees) => Math.sin(degrees * rad);
  const cos = (degrees) => Math.cos(degrees * rad);
  const mod = (value, base) => ((value % base) + base) % base;

  function daysSinceJ2000(unixMs) {
    const jdUt = 2440587.5 + unixMs / 86400000;
    const jdTt = jdUt + TT_MINUS_UTC_S / 86400;
    return { dt: jdTt - 2451545.0, jdTt: jdTt };
  }

  // Sun and Mars time for a place on Mars (east longitude, latitude in degrees).
  function sun(unixMs, eastLongitude, latitude) {
    const time = daysSinceJ2000(unixMs);
    const dt = time.dt;
    const meanAnomaly = 19.3871 + 0.52402073 * dt;
    const alphaFms = 270.3871 + 0.524038496 * dt;
    let pbs = 0;
    for (const term of PBS_TERMS) {
      pbs += term[0] * cos((0.985626 * dt) / term[1] + term[2]);
    }
    const centre =
      (10.691 + 3.0e-7 * dt) * sin(meanAnomaly) +
      0.623 * sin(2 * meanAnomaly) +
      0.05 * sin(3 * meanAnomaly) +
      0.005 * sin(4 * meanAnomaly) +
      0.0005 * sin(5 * meanAnomaly) +
      pbs;
    const ls = mod(alphaFms + centre, 360);
    const eot = 2.861 * sin(2 * ls) - 0.071 * sin(4 * ls) + 0.002 * sin(6 * ls) - centre;
    const mst = mod(24 * ((time.jdTt - 2451549.5) / 1.0274912517 + 44796.0 - 0.0009626), 24);
    const westLongitude = mod(360 - eastLongitude, 360);
    const lmst = mod(mst - westLongitude / 15, 24);
    const ltst = mod(lmst + eot / 15, 24);
    const subsolarWest = mod(mst * 15 + eot + 180, 360);
    const declination = Math.asin(0.42565 * sin(ls)) / rad + 0.25 * sin(ls);
    const distanceAu =
      1.52367934 * (1.00436 - 0.09309 * cos(meanAnomaly) - 0.004336 * cos(2 * meanAnomaly) - 0.00031 * cos(3 * meanAnomaly) - 0.00003 * cos(4 * meanAnomaly));
    const helioLongitude = mod(ls + 85.061 - 0.015 * sin(71 + 2 * ls) - 5.5e-6 * dt, 360);
    const helioLatitude = -(1.8497 - 2.23e-5 * dt) * sin(ls - 144.5 + 2.57e-6 * dt);
    const hourAngle = westLongitude - subsolarWest;
    const zenith = Math.acos(sin(declination) * sin(latitude) + cos(declination) * cos(latitude) * cos(hourAngle)) / rad;
    const azimuth = mod(Math.atan2(sin(hourAngle), cos(latitude) * Math.tan(declination * rad) - sin(latitude) * cos(hourAngle)) / rad, 360);
    // Mars Sol Date, the same expression as inside Mars24 step C-2
    const marsSolDate = (time.jdTt - 2451549.5) / 1.0274912517 + 44796.0 - 0.0009626;
    return {
      ls: ls,
      mst: mst,
      lmst: lmst,
      ltst: ltst,
      declination: declination,
      elevation: 90 - zenith,
      azimuth: azimuth,
      distanceAu: distanceAu,
      helioLongitude: helioLongitude,
      helioLatitude: helioLatitude,
      marsSolDate: marsSolDate,
    };
  }

  function solveKepler(meanAnomaly, eccentricity) {
    const eStar = eccentricity / rad;
    let anomaly = meanAnomaly + eStar * sin(meanAnomaly);
    for (let step = 0; step < 20; step++) {
      const deltaE = (meanAnomaly - (anomaly - eStar * sin(anomaly))) / (1 - eccentricity * cos(anomaly));
      anomaly += deltaE;
      if (Math.abs(deltaE) < 1e-8) {
        break;
      }
    }
    return anomaly;
  }

  function earthXyz(unixMs) {
    const centuries = daysSinceJ2000(unixMs).dt / 36525;
    const v = {};
    for (const name of Object.keys(EARTH_ELEMENTS)) {
      v[name] = EARTH_ELEMENTS[name][0] + EARTH_ELEMENTS[name][1] * centuries;
    }
    const w = v.longPeri - v.longNode;
    const meanAnomaly = mod(v.L - v.longPeri + 180, 360) - 180;
    const anomaly = solveKepler(meanAnomaly, v.e);
    const xo = v.a * (cos(anomaly) - v.e);
    const yo = v.a * Math.sqrt(1 - v.e * v.e) * sin(anomaly);
    const node = v.longNode;
    const incl = v.I;
    return [
      (cos(w) * cos(node) - sin(w) * sin(node) * cos(incl)) * xo + (-sin(w) * cos(node) - cos(w) * sin(node) * cos(incl)) * yo,
      (cos(w) * sin(node) + sin(w) * cos(node) * cos(incl)) * xo + (-sin(w) * sin(node) + cos(w) * cos(node) * cos(incl)) * yo,
      sin(w) * sin(incl) * xo + cos(w) * sin(incl) * yo,
    ];
  }

  function marsXyz(unixMs) {
    const s = sun(unixMs, 0, 0);
    return [
      s.distanceAu * cos(s.helioLatitude) * cos(s.helioLongitude),
      s.distanceAu * cos(s.helioLatitude) * sin(s.helioLongitude),
      s.distanceAu * sin(s.helioLatitude),
    ];
  }

  // One-way light time Earth-Mars, distance, and the Sun-Earth-Mars angle seen from Earth.
  function earthLink(unixMs) {
    const earth = earthXyz(unixMs);
    const mars = marsXyz(unixMs);
    const toMars = [mars[0] - earth[0], mars[1] - earth[1], mars[2] - earth[2]];
    const distanceAu = Math.hypot(toMars[0], toMars[1], toMars[2]);
    const toSun = [-earth[0], -earth[1], -earth[2]];
    const sunDistance = Math.hypot(toSun[0], toSun[1], toSun[2]);
    const cosAngle = (toMars[0] * toSun[0] + toMars[1] * toSun[1] + toMars[2] * toSun[2]) / (distanceAu * sunDistance);
    return {
      oneWaySeconds: (distanceAu * AU_KM) / LIGHT_SPEED_KM_S,
      distanceAu: distanceAu,
      sunMarsAngleDeg: Math.acos(Math.max(-1, Math.min(1, cosAngle))) / rad,
      earth: earth,
      mars: mars,
    };
  }

  function gravity(latitude, heightM) {
    const a = GRAVITY.equatorialRadius;
    const b = GRAVITY.polarRadius;
    const radius = (a * b) / Math.sqrt((b * cos(latitude)) ** 2 + (a * sin(latitude)) ** 2) + heightM;
    const pointMass = GRAVITY.gm / radius ** 2;
    const flattening = 1 - 1.5 * GRAVITY.j2 * (a / radius) ** 2 * (3 * sin(latitude) ** 2 - 1);
    const omega = (2 * Math.PI) / GRAVITY.siderealRotationS;
    return pointMass * flattening - omega * omega * radius * cos(latitude) ** 2;
  }

  // Mars hours as hh:mm (Mars hours have 60 Mars minutes).
  function formatHours(hours) {
    const total = Math.round(mod(hours, 24) * 60);
    return String(Math.floor(total / 60) % 24).padStart(2, "0") + ":" + String(total % 60).padStart(2, "0");
  }

  return { sun: sun, earthLink: earthLink, gravity: gravity, formatHours: formatHours, GRAVITY: GRAVITY };
})();

if (typeof module !== "undefined") {
  module.exports = MarsTime; // lets the same file be checked from the command line
}
