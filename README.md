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
| **MAP** | HiRISE 25 cm image, slope (5° bands) and rock units; elevation, slope and unit under the cursor or a tap |
| **ROUTE** | For each leg, shortest vs gentlest route: distance, climb, descent, steepest point (and where it is) |
| **STOPS** | Rock unit and its description, Perseverance photos (two cameras), the mission question, "mark stop as reached" |
| **DATA** | Source, product, date, label (NASA DATA or CALCULATED) and method of every layer and number; known limits |
| **MISSION** | Objective and its sources, progress, next stop with bearing and distance |

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

Display choices (no meaning beyond telling things apart): 5° slope bands, unit colours and hatch patterns, the 1,000 m margin around the stops, the 250 m offline detail corridor.

## Known limits

- Terrain cells are 1 m: rocks and obstacles smaller than about 1 m are not in the terrain data.
- Slope depends on cell size: these values are slopes over 1 m.
- Our sources give no human slope limit, so NAVASA applies none; it compares routes instead of judging them.
- Stop positions are where the rover was on that sol, not the exact spot each photo shows.
- Current surface conditions (weather, dust) are not included.
- Unit descriptions are included for the units at the stops; other units show their name only.
- Offline, full detail is saved only within 250 m of the routes and stops.

---

## Run it

The app is a static site: open the live link, or serve the `web/` folder locally.

```bash
python3 -m http.server 8000 --directory web
# open http://localhost:8000
```

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

---

## Repository layout

```
pipeline/   Python steps: mission, stops, crop_layers, terrain, routes, geology, build_pack, pack_format, run_mission, make_globe
tests/      unittest
data/       missions/ (mission files), unit_descriptions.json; raw/ and work/ are not committed
web/        the app: index.html, styles.css, app.js, globe.js, sw.js, wrist.html/css/js, vendor/leaflet,
            missions.json, data/<pack>/, data/globe/
.github/    workflow that publishes web/ to GitHub Pages
```
