# NAVASA — Navigation Assistance System for Aliens

**Planning a walk on Mars means combining many separate NASA datasets. NAVASA puts them in one map that works offline.**

NAVASA turns NASA orbital images, terrain heights, a USGS geologic map and Perseverance rover photos into one mission plan for a walk on Mars: a layered map, two routes between every pair of stops (the **shortest** and the **gentlest**), stop cards and a wrist-sized navigator. It shows only facts that are in the data or calculated from it, and says where each one comes from.

On Mars, we are the aliens.

- **Live app:** https://simalnaz.github.io/navasa/
- **First mission:** *Follow the water to a potential biosignature* — four stops in Jezero Crater, from the crater floor to the Bright Angel area.

NAVASA is an entry to the NASA Space Apps Challenge 2026. It is not affiliated with or endorsed by NASA.

---

## What you can do

| Tab | What it shows |
|---|---|
| **Boot screen** | A rotating Mars globe (orbit view) with each mission site; pick a mission and the globe turns to its site and dives in |
| **MAP** | HiRISE 25 cm image, slope (5° bands) and rock units; elevation, slope and unit under the cursor or a tap; **radio line of sight** astronaut ↔ astronaut and astronaut ↔ habitat (landing site), with antenna heights you type (empty until you do) |
| **ROUTE** | For each leg, shortest vs gentlest route: distance, climb, descent, steepest point (and where it is); **gravity panel**: site gravity, and with your mass (typed, empty until you do) your weight on Mars vs Earth and the work against gravity per leg |
| **STOPS** | Rock unit and its description, Perseverance photos (two cameras), the mission question, "mark stop as reached" |
| **SKY** | Mars clock (Perseverance sol, LMST, LTST, season Ls), sunrise and sunset, time to sunset; choose a sol and time or play the sol; terrain shadows on the map; share of each route in shadow; sun arrow on the map; **Earth link**: one-way and round-trip light time, distance, Sun–Earth–Mars angle, a to-scale Sun–Earth–Mars diagram and a **SEND** message simulation (real time or 60× faster) |
| **DATA** | Source, product, date, label (NASA DATA or CALCULATED) and method of every layer and number; known limits |
| **MISSION** | Objective and its sources, progress, next stop with bearing and distance; **health / status**: A this device's battery (real), B EVA timer + time to sunset (real), C temperatures measured by Perseverance MEDA on the sol it was at each stop (air and ground, hourly chart and table), D suit TRAINING SIMULATION from values you type; **mission editor**: create, edit, delete, export and import your own missions on this site (stops placed on the map, straight-line facts per leg; kept in the browser; the export is a mission file the pipeline builds) |

Layouts: wide (laptop or habitat screen), tablet (tab bar at the bottom) and **wrist view** (phones, or the WRIST VIEW button): a compact navigator for a suit sleeve.

**Wrist unit concept** (`wrist.html`, linked from the boot screen): the app running on a wrist unit drawn on an EVA suit sleeve. Its keys switch tabs, the knob zooms the map and the amber switches step through the stops.

**Offline:** after the first visit the app saves itself and the mission data in two stages: the whole area at coarse zoom levels plus all data files (about 17 MB), then full detail within 250 m of every route and stop (about 29 MB). The status bar shows the progress and then `OFFLINE READY`. Anything else you look at while online is kept too.

---

## Data used

| Data | Mission / owner | Used for | Label |
|---|---|---|---|
| HiRISE orthomosaic, 25 cm/pixel, Mars 2020 Terrain Relative Navigation — Fergason and others, 2020, USGS, [doi:10.5066/P9QJDP48](https://doi.org/10.5066/P9QJDP48) | MRO, NASA/JPL-Caltech/University of Arizona; mosaic USGS Astrogeology | Base map | NASA DATA |
| HiRISE DTM mosaic, ~1 m/pixel, Mars 2020 Terrain Relative Navigation — Fergason and others, 2020, USGS, [doi:10.5066/P9REJ9JN](https://doi.org/10.5066/P9REJ9JN) | MRO, NASA/JPL-Caltech/University of Arizona; mosaic USGS Astrogeology | Elevation, slope, routes | NASA DATA / CALCULATED |
| Geologic Map of Jezero Crater and the Nili Planum Region, Mars — Sun, V.Z., and Stack, K.M., 2020, [USGS SIM 3464](https://pubs.usgs.gov/publication/sim3464) | NASA-funded USGS map | Rock units, unit descriptions | NASA DATA |
| Perseverance raw images (Navcam, Mastcam-Z), [mars.nasa.gov](https://mars.nasa.gov/mars2020/multimedia/raw-images/) | Perseverance, NASA/JPL-Caltech | Stop photos | NASA DATA |
| Mars Viking MDIM 2.1 Colorized Global Mosaic, 232 m/pixel — [USGS Astrogeology](https://planetarymaps.usgs.gov/mosaic/Mars_Viking_MDIM21_ClrMosaic_global_232m.tif) (the same layer NASA's Mars Trek shows) | Viking Orbiter (NASA); mosaic USGS Astrogeology | Orbit-view globe (2,048 × 1,024 copy) | NASA DATA |
| Mars 2020 MEDA calibrated environmental data (CAL_ATS, CAL_TIRS) for sols 15, 426, 1162 and 1210 — [NASA PDS Atmospheres Node](https://pds-atmospheres.nmsu.edu/PDS/data/PDS4/Mars2020/mars2020_meda/), release 2026-08-11 | Perseverance, NASA/JPL-Caltech; MEDA (Rodriguez-Manfredi and others, 2021) | Measured air and ground temperature at the stops | NASA DATA |
| Mars 2020 rover waypoints, [M20_waypoints.json](https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json) (data behind NASA's "Where is Perseverance?" map) | Perseverance, NASA/JPL-Caltech | Stop positions | NASA DATA |

The mission objective's fact ("Perseverance found a potential biosignature") comes from NASA/JPL, 10 September 2025, [*NASA Says Mars Rover Discovered Potential Biosignature Last Year*](https://www.jpl.nasa.gov/news/nasa-says-mars-rover-discovered-potential-biosignature-last-year/), and Hurowitz, J.A., and others, 2025, *Redox-driven mineral and organic associations in Jezero Crater, Mars*, Nature.

**Credits:** NASA/JPL-Caltech/University of Arizona (HiRISE) · USGS Astrogeology Science Center (Mars 2020 TRN mosaics; Viking MDIM 2.1 colour mosaic) · NASA Viking Orbiter · Sun, V.Z., and Stack, K.M., 2020, USGS SIM 3464 · NASA/JPL-Caltech (Perseverance raw images and Mars 2020 rover waypoints). Map library: [Leaflet](https://leafletjs.com) 1.9.4 (BSD 2-Clause, `web/vendor/leaflet/LICENSE`).

---

## Methods (every CALCULATED value)

| Value | How it is calculated |
|---|---|
| Slope | Angle of the steepest rise at each 1 m cell, from the height differences to the neighbouring DTM cells (central differences). No limit or mask is applied. |
| Shortest route | Least horizontal distance over cells with terrain data: 8-neighbour grid path (scikit-image), then straightened wherever a straight line crosses only such cells. |
| Gentlest route | The lowest slope S for which two stops are still connected through cells with slope ≤ S (the stops' own cells not counted), then the shortest route through those cells. Its steepest point is S. |
| Distance | Horizontal length along the route. |
| Climb / descent | Sum of all height rises / drops from cell to cell along the route. |
| Steepest point | Steepest 1 m cell on the route, the two stops not counted. |
| Ground slope at a stop | Slope of the 1 m cell at the stop position. |
| Bearing, straight distance | From the two stops' grid positions; bearing in degrees clockwise from map north. |
| Cursor readout | Value of the nearest 1 m cell, sampled every 4 m. |
| Mars clock, sun position, sunrise / sunset | NASA GISS [Mars24 algorithm](https://www.giss.nasa.gov/tools/mars24/help/algorithm.html) (updated 2025-01-07); sunrise / sunset = sun centre at 0° over a flat horizon, no atmosphere. |
| Perseverance sol | Sol 0 = landing sol (2021-02-18 20:55 UTC), counted in local mean solar time at the landing site; tested against the sols in NASA raw-image IDs. |
| Radio line of sight | Straight line between the antenna tips (your heights) vs the terrain every 4 m (elevation readout) plus Mars curvature d(D−d)/2R; first blocking point and least clearance. No Fresnel zone, diffraction, refraction or radio range. Habitat = Perseverance landing site from the first NASA M20 waypoint (sol 13, before the first drive). |
| Site gravity, weight, climb work | g = GM/r² (1 − 1.5 J2 (a/r)² (3 sin²φ − 1)) − ω² r cos²φ with the NASA NSSDC Mars Fact Sheet (2025) constants; r = the landing site's distance from Mars' centre (NASA M20 waypoints, 3,391,936.53 m) → 3.715 m/s². Weight = m g; work against gravity = m g × route climb (potential energy, not the energy spent walking). |
| MEDA temperatures | Air: mean of the three mast sensors (ATS 1–3). Ground: TIRS ground brightness temperature, rows left out when a quality flag says the rover moved, tilted ≥ 20°, shaded the spot or had a wheel in view. Median per Mars minute, then hourly means (LMST) and the lowest / highest minute. |
| EVA timer, suit simulation | Elapsed Earth time since START EVA; simulation = your start amount − your use per hour × elapsed time (constant use), compared with the Mars24 sunset. |
| Earth–Mars light time | Distance between Mars (Mars24 D-2..D-4) and Earth ([JPL approximate positions](https://ssd.jpl.nasa.gov/planets/approx_pos.html), Table 1, 1800–2050) ÷ light speed. SEND simulation: arrives after one light time, earliest reply after two; relay passes and DSN schedules not included. |
| Ground scale | The grid is equirectangular with true scale at the equator: one cell is 1 m north-south and cos(latitude) m east-west on the ground (0.948 m at Jezero). Slope, distances, bearings, the scale bar and shadows use ground metres. |
| Terrain horizon | Per 16 m cell and 36 directions: the highest angle to the terrain within 10 km inside the HiRISE DTM, with Mars curvature (d² / 2R); east-west map distances corrected to ground distances (× cos latitude). |
| Terrain shadow, route in shadow | In shadow when the sun is at or below 0° or lower than the horizon in its direction (interpolated between directions); route share sampled every 8 m. |

Display choices (no meaning beyond telling things apart): 5° slope bands, unit colours and hatch patterns, the 1,000 m margin around the stops, the 250 m offline detail corridor.

## Known limits

- Terrain cells are 1 m: rocks and obstacles smaller than about 1 m are not in the terrain data.
- Slope depends on cell size: these values are slopes over 1 m.
- Our sources give no human slope limit, so NAVASA applies none; it compares routes instead of judging them.
- Stop positions are where the rover was on that sol, not the exact spot each photo shows.
- Current surface conditions (weather, dust) are not included.
- Unit descriptions are included for the units at the stops; other units show their name only.
- Offline, full detail is saved only within 250 m of the routes and stops.
- Shadows use 16 m terrain cells and only the terrain inside the HiRISE DTM (3.7–9.2 km beyond the walk area); the far crater rim is not included. No atmosphere; the sun is treated as a point.

---

## Run it

The app is a static site published by GitHub Actions (`.github/workflows/pages.yml`) on every push to `main`: open the live link.

## Build a mission's data pack

Requires Python 3.10+ and the libraries in `requirements.txt`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.run_mission data/missions/jezero-biosignature.json
python -m unittest discover tests
```

`run_mission` checks the mission file, crops the image and terrain to the walk area, computes slope, routes and geology, and writes and validates the pack in `web/data/<pack>/` plus the mission list `web/missions.json`.

The raw files go in `data/raw/` (not in this repository; links above). The geologic units were converted once from the SIM 3464 geodatabase with GDAL 3.13 (command at the top of `pipeline/geology.py`). The orbit-view globe image is made once with `python -m pipeline.make_globe`, which reads only every 45th row and column of the 12.7 GB Viking mosaic over the network.

### A new mission

Everything mission-specific is in one file, `data/missions/<mission>.json`: name, status, objective and its sources, the site's raw files and their credits, and the stops in walking order (position, position source, question, photos). For a new mission:

1. Put the site's DTM, orthoimage, geologic units and photos in `data/raw/`.
2. Write `data/missions/<mission>.json` (copy the Jezero one).
3. Run `python -m pipeline.run_mission data/missions/<mission>.json`.

The new mission appears on the boot screen. Each objective needs a source; missing values stop the build instead of being filled in.

**From the app:** MISSION tab → MISSION EDITOR → NEW MISSION (or DUPLICATE the built-in one), place stops on the map, SAVE, then EXPORT. The exported file is a complete mission file for the same site (stops without photos are allowed); put it in `data/missions/` and run `run_mission` on it to get its routes and full pack.

---

## Repository layout

```
pipeline/   Python steps: mission, stops, crop_layers, terrain, routes, geology, thermal, horizon, build_pack, pack_format,
            run_mission, make_globe, context_maps, mars_time
tests/      unittest
data/       missions/ (mission files), unit_descriptions.json; raw/ and work/ are not committed
web/        the app: index.html, styles.css, app.js, globe.js, marstime.js, sun.js, comms.js, los.js, gravity.js, health.js, editor.js, sw.js, wrist.html/css/js, vendor/leaflet,
            missions.json, data/<pack>/, data/globe/
.github/    workflow that publishes web/ to GitHub Pages
```
