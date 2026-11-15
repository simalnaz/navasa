// NAVASA web app: reads the data pack and shows it on a Leaflet map.
//
// Positions in the pack are grid pixels [col, row], counted from the top-left
// corner; one grid pixel is metres_per_pixel metres. Leaflet's flat map mode
// (CRS.Simple) counts upwards, so grid [col, row] is Leaflet position [-row, col].
// At zoom z one grid pixel is 2^z screen pixels, the same rule the tiles were cut with.
//
// Every text from the pack is shown with textContent, never as HTML.

"use strict";

const MISSIONS_INDEX_URL = "missions.json";
const GLOBE_IMAGE_URL = "data/globe/mars_viking_colour.jpg";
const DESCENT_MS = 1400; // turn the globe to the site
const DIVE_MS = 900; // then zoom into it
const MAP_MAX_ZOOM = 3;

const LABEL_MARK = { "NASA DATA": "■", CALCULATED: "◆" };
const DATA_CACHE = "navasa-data-v2"; // same name as in sw.js (bump both when the data pack changes)
const OFFLINE_BATCH_SIZE = 6; // files saved at the same time, so saving never floods the network
const OFFLINE_MAX_ATTEMPTS = 4; // tries per file before offline saving pauses
const OFFLINE_RETRY_DELAY_MS = 1000; // pause before the 2nd try; doubles each try (1 s, 2 s, 4 s)
const WRIST_MAX_WIDTH_PX = 600; // narrower screens use the wrist layout

let theMap = null;
let packBase = null; // "data/<pack>/", set when a mission starts
let missionControls = null; // previous / next stop, set by the MISSION tab
let layerDial = null; // the wrist knob's layer positions, set when the pack layers are added

// "?view=wrist" shows only the wrist layout, for the wrist device page (wrist.html).
const IS_EMBEDDED_WRIST = new URLSearchParams(window.location.search).get("view") === "wrist";

// ---------------------------------------------------------------- helpers

function showError(message) {
  const box = document.getElementById("load-error");
  box.textContent = message;
  box.hidden = false;
}

// A pack path must stay inside the pack folder: no absolute paths, no "..", no other sites.
function packUrl(path) {
  if (typeof path !== "string" || path === "" || path.startsWith("/") || path.includes("..") || path.includes(":")) {
    throw new Error("Refused a path outside the data pack: " + String(path));
  }
  if (packBase === null) {
    throw new Error("No mission selected");
  }
  return packBase + path;
}

async function loadJson(path) {
  const response = await fetch(packUrl(path));
  if (!response.ok) {
    throw new Error("Could not load " + path + " (" + response.status + ")");
  }
  return response.json();
}

function gridToLatLng(col, row) {
  return L.latLng(-row, col);
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function checkManifest(manifest) {
  const required = ["id", "version", "site", "grid", "layers"];
  for (const field of required) {
    if (!(field in manifest)) {
      throw new Error("manifest.json is missing '" + field + "'");
    }
  }
  if (!Array.isArray(manifest.layers)) {
    throw new Error("manifest.json 'layers' must be a list");
  }
}

// ---------------------------------------------------------------- status bar and tabs

function fillStatusBar(manifest) {
  document.getElementById("status-site").textContent = "SITE " + manifest.site.name.toUpperCase();
  document.getElementById("status-pack").textContent = "PACK " + manifest.id.toUpperCase() + " v" + manifest.version;
  const dates = [];
  for (const layer of manifest.layers) {
    if (layer.as_of !== null && !dates.includes(layer.as_of)) {
      dates.push(layer.as_of);
    }
  }
  document.getElementById("status-as-of").textContent = "DATA AS OF " + (dates.length > 0 ? dates.join(", ") : "no data");
}

function openTab(tabName) {
  for (const button of document.querySelectorAll(".tabs button")) {
    const isThis = button.dataset.tab === tabName;
    button.setAttribute("aria-selected", isThis ? "true" : "false");
    document.getElementById("tab-" + button.dataset.tab).hidden = !isThis;
  }
  document.body.dataset.tab = tabName;
  // In the wrist layout the map is hidden on other tabs; tell Leaflet when it is back.
  if (theMap !== null) {
    setTimeout(function () {
      theMap.invalidateSize();
    }, 0);
  }
}

function setUpTabs() {
  for (const button of document.querySelectorAll(".tabs button")) {
    button.addEventListener("click", function () {
      openTab(button.dataset.tab);
    });
  }
}

// ---------------------------------------------------------------- map and layers

// Longitude/latitude <-> map position. The grid is equirectangular, so both are straight lines.
function lonLatToLatLng(manifest, lon, lat) {
  const box = manifest.site.bounds_lonlat; // west, south, east, north
  const col = ((lon - box[0]) / (box[2] - box[0])) * manifest.grid.width;
  const row = ((box[3] - lat) / (box[3] - box[1])) * manifest.grid.height;
  return gridToLatLng(col, row);
}

function lonLatBounds(manifest, box) {
  return L.latLngBounds(lonLatToLatLng(manifest, box[0], box[1]), lonLatToLatLng(manifest, box[2], box[3]));
}

function siteCentre(manifest) {
  const box = manifest.site.bounds_lonlat;
  return lonLatToLatLng(manifest, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2);
}

function createMap(manifest) {
  const width = manifest.grid.width;
  const height = manifest.grid.height;
  const bounds = L.latLngBounds(gridToLatLng(0, height), gridToLatLng(width, 0));
  let hasContext = false;
  for (const layer of manifest.layers) {
    if (layer.context) {
      hasContext = true;
    }
  }
  const planetBounds = hasContext ? lonLatBounds(manifest, [-180, -90, 180, 90]) : bounds.pad(0.25);

  let minZoom = 0;
  for (const layer of manifest.layers) {
    if (layer.tiles) {
      minZoom = Math.min(minZoom, layer.tiles.min_zoom);
    }
  }

  // Flat map in grid metres, but distances (scale bar) in ground metres: east-west grid metres
  // are east_scale ground metres on this equirectangular grid.
  const eastScale = eastScaleOf(manifest);
  const groundCrs = L.extend({}, L.CRS.Simple, {
    distance: function (a, b) {
      return Math.hypot((b.lng - a.lng) * eastScale, b.lat - a.lat) * manifest.grid.metres_per_pixel;
    },
  });
  const map = L.map("map", {
    crs: groundCrs,
    minZoom: minZoom,
    maxZoom: MAP_MAX_ZOOM,
    maxBounds: planetBounds,
    maxBoundsViscosity: 0.8,
    attributionControl: false,
  });
  map.fitBounds(bounds);
  setUpWalkAreaPane(map, bounds);
  addContextLayers(map, manifest);
  // Far out (planet, region) the stop squares and routes would sit on top of each other.
  map.on("zoomend", function () {
    map.getContainer().classList.toggle("far-out", map.getZoom() < FAR_OUT_ZOOM);
  });

  // The scale bar is horizontal, so it measures ground metres east-west (see groundCrs).
  L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
  return { map: map, bounds: bounds };
}

function makeTileLayer(layer, bounds) {
  const isOverlay = layer.kind !== "imagery";
  return L.tileLayer(packUrl(layer.tiles.url), {
    tileSize: layer.tiles.tile_size,
    minZoom: layer.tiles.min_zoom,
    maxZoom: MAP_MAX_ZOOM,
    minNativeZoom: layer.tiles.min_zoom,
    maxNativeZoom: layer.tiles.max_zoom,
    bounds: bounds,
    noWrap: true,
    className: isOverlay ? "pixelated" : "",
    pane: isOverlay ? "dataOverlays" : "walkArea",
  });
}

const LAYER_NAMES = { hirise: "HIRISE IMAGE 25 CM", slope: "SLOPE", geology: "ROCK UNITS" };

function slopeLegend(legend) {
  const box = makeElement("div", "legend");
  for (const band of legend) {
    const row = makeElement("div", "legend-row");
    const swatch = makeElement("span", "legend-swatch");
    swatch.style.background = "rgb(" + band.color.join(",") + ")";
    row.appendChild(swatch);
    row.appendChild(makeElement("span", "", band.from_deg + "–" + band.to_deg + "°"));
    box.appendChild(row);
  }
  return box;
}

function geologyLegend(legend) {
  const box = makeElement("div", "legend");
  for (const unit of legend) {
    const row = makeElement("div", "legend-row");
    const swatch = makeElement("span", "legend-swatch");
    swatch.style.background = "rgb(" + unit.color.join(",") + ")";
    row.appendChild(swatch);
    row.appendChild(makeElement("span", "", unit.symbol + " · " + unit.name + " (" + unit.pattern + ")"));
    box.appendChild(row);
  }
  return box;
}

function thermalLegend(layer) {
  const box = makeElement("div", "legend");
  for (const band of layer.legend) {
    const row = makeElement("div", "legend-row");
    const swatch = makeElement("span", "legend-swatch");
    swatch.style.background = "rgb(" + band.color.join(",") + ")";
    row.appendChild(swatch);
    row.appendChild(makeElement("span", "", band.from_value + "–" + band.to_value));
    box.appendChild(row);
  }
  box.appendChild(makeElement("p", "note", layer.units));
  return box;
}

function routeLegend() {
  const box = makeElement("div", "legend");
  for (const kind of ["shortest", "gentlest"]) {
    const row = makeElement("div", "legend-row");
    row.appendChild(makeElement("span", "legend-line " + kind));
    row.appendChild(makeElement("span", "", kind === "shortest" ? "SHORTEST (dashed)" : "GENTLEST (solid)"));
    box.appendChild(row);
  }
  return box;
}

// One button per layer: [x] on, [ ] off. The legend shows while the layer is on.
function addLayerButton(map, name, tag, mapLayer, legend, startOn) {
  const list = document.getElementById("layer-list");
  const wrapper = makeElement("div");
  const button = makeElement("button", "layer-button");
  button.type = "button";
  const nameSpan = makeElement("span");
  const tagSpan = makeElement("span", "layer-tag", tag);
  button.appendChild(nameSpan);
  button.appendChild(tagSpan);
  wrapper.appendChild(button);
  if (legend) {
    wrapper.appendChild(legend);
  }
  list.appendChild(wrapper);

  function show(isOn) {
    nameSpan.textContent = (isOn ? "[x] " : "[ ] ") + name;
    button.setAttribute("aria-pressed", isOn ? "true" : "false");
    if (legend) {
      legend.hidden = !isOn;
    }
    if (isOn) {
      map.addLayer(mapLayer);
    } else {
      map.removeLayer(mapLayer);
    }
  }
  button.addEventListener("click", function () {
    show(!map.hasLayer(mapLayer));
  });
  show(startOn);
  return show;
}

// The 25 cm image tiles pad their edges with black (JPEG has no transparency); this pane
// shows only the walk area, so the Mars surface around it stays visible.
const FAR_OUT_ZOOM = -7;

function setUpWalkAreaPane(map, walkBounds) {
  const pane = map.createPane("walkArea");
  pane.style.zIndex = 250; // above the Mars context tiles (200)
  map.createPane("dataOverlays").style.zIndex = 300; // slope, rock units, thermal: above the image
  function clip() {
    const topLeft = map.latLngToLayerPoint(walkBounds.getNorthWest());
    const bottomRight = map.latLngToLayerPoint(walkBounds.getSouthEast());
    pane.style.clipPath =
      "polygon(" + topLeft.x + "px " + topLeft.y + "px, " + bottomRight.x + "px " + topLeft.y + "px, " +
      bottomRight.x + "px " + bottomRight.y + "px, " + topLeft.x + "px " + bottomRight.y + "px)";
  }
  map.on("zoomend moveend viewreset resize", clip);
  clip();
}

// Mars around the walk area (planet, region, crater), always underneath the mission layers.
const CONTEXT_EXTRA_ZOOM = 6; // how far a context layer may be enlarged past its sharpest zoom

function addContextLayers(map, manifest) {
  const group = L.layerGroup();
  for (const layer of manifest.layers) {
    if (!layer.context) {
      continue;
    }
    const tiles = layer.tiles;
    group.addLayer(
      L.tileLayer(packUrl(tiles.url), {
        tileSize: tiles.tile_size,
        minZoom: tiles.min_zoom,
        maxZoom: Math.min(MAP_MAX_ZOOM, tiles.max_zoom + CONTEXT_EXTRA_ZOOM),
        minNativeZoom: tiles.min_zoom,
        maxNativeZoom: tiles.max_zoom,
        bounds: lonLatBounds(manifest, tiles.bounds_lonlat),
        noWrap: true,
      })
    );
  }
  if (group.getLayers().length > 0) {
    addLayerButton(map, "MARS SURFACE (VIKING)", "■ NASA DATA · USGS / MARS TREK", group, null, true);
  }
}

// The wrist knob steps through: image only, then one data layer at a time.
const IMAGE_ONLY_NAME = "IMAGE ONLY";

function addPackLayers(map, bounds, manifest) {
  const overlays = []; // { id, name, show, mapLayer } for each tiled data layer (not imagery)
  for (const layer of manifest.layers) {
    if (!layer.tiles || layer.context) {
      continue;
    }
    const tag = (LABEL_MARK[layer.label] || "") + " " + layer.label + " · " + (layer.as_of !== null ? layer.as_of : "no date");
    let legend = null;
    if (layer.id === "slope") {
      legend = slopeLegend(layer.legend);
    } else if (layer.id === "geology") {
      legend = geologyLegend(layer.legend);
    } else if (layer.id.startsWith("thermal-")) {
      legend = thermalLegend(layer);
    }
    const name = layer.display_name || LAYER_NAMES[layer.id] || layer.id.toUpperCase();
    const isImagery = layer.kind === "imagery";
    const mapLayer = makeTileLayer(layer, bounds);
    const show = addLayerButton(map, name, tag, mapLayer, legend, isImagery);
    if (!isImagery) {
      overlays.push({ id: layer.id, name: name, show: show, mapLayer: mapLayer });
    }
  }
  layerDial = { map: map, overlays: overlays, position: 0 }; // 0 = image only (data layers start off)
}

// Turn the knob one step: exactly one data layer on (or none). Returns the layer now shown.
function stepLayerDial(direction) {
  const positionCount = layerDial.overlays.length + 1;
  const step = direction === "next" ? 1 : -1;
  layerDial.position = (layerDial.position + step + positionCount) % positionCount;
  for (let index = 0; index < layerDial.overlays.length; index += 1) {
    layerDial.overlays[index].show(layerDial.position === index + 1);
  }
  const shown = currentDataLayer();
  if (window.navasaTerrain3d !== undefined) {
    window.navasaTerrain3d.setLayer(shown.id, shown.name);
  }
  return shown;
}

// What the wrist page needs to draw its selector: every position's name and which one is on.
function layerDialMessage() {
  const names = [IMAGE_ONLY_NAME];
  for (const overlay of layerDial.overlays) {
    names.push(overlay.name);
  }
  return { type: "navasa:layer-dial", names: names, position: layerDial.position };
}

// The data layer on the map now (the last one switched on wins), for the 3D view and the knob.
function currentDataLayer() {
  let shown = { id: null, name: IMAGE_ONLY_NAME };
  for (const overlay of layerDial.overlays) {
    if (layerDial.map.hasLayer(overlay.mapLayer)) {
      shown = { id: overlay.id, name: overlay.name };
    }
  }
  return shown;
}

// ---------------------------------------------------------------- 2D / 3D

// A button on the map that swaps the flat map for the 3D terrain (terrain3d.js) and back.
function addTerrainToggle(map, manifest, stops, routes) {
  const Toggle = L.Control.extend({
    options: { position: "topright" },
    onAdd: function () {
      const button = L.DomUtil.create("button", "view-toggle");
      button.type = "button";
      button.textContent = "3D";
      button.setAttribute("aria-pressed", "false");
      button.title = "Show the terrain in 3D (HiRISE heights)";
      L.DomEvent.disableClickPropagation(button);
      let busy = false;
      button.addEventListener("click", async function () {
        const terrain = window.navasaTerrain3d;
        if (terrain === undefined) {
          showError("The 3D view could not start: terrain3d.js did not load (this browser may not support it).");
          return;
        }
        if (busy) {
          return; // a fly-in or fly-out is still running
        }
        busy = true;
        try {
          if (terrain.isOpen()) {
            button.textContent = "3D";
            button.setAttribute("aria-pressed", "false");
            await terrain.close();
          } else {
            button.textContent = "2D";
            button.setAttribute("aria-pressed", "true");
            const shown = currentDataLayer();
            await terrain.open(map.getContainer(), {
              manifest: manifest,
              stops: stops,
              routes: routes,
              packUrl: packUrl,
              layerId: shown.id,
              layerName: shown.name,
            });
          }
        } catch (error) {
          button.textContent = "3D";
          button.setAttribute("aria-pressed", "false");
          showError("The 3D view could not start: " + error.message);
        } finally {
          busy = false;
        }
      });
      return button;
    },
  });
  new Toggle().addTo(map);
}

// ---------------------------------------------------------------- routes and stops

function addRoutes(map, routes) {
  const group = L.layerGroup();
  for (const leg of routes) {
    const styles = {
      shortest: { color: getComputedStyle(document.documentElement).getPropertyValue("--shortest").trim(), weight: 3, dashArray: "8 6" },
      gentlest: { color: getComputedStyle(document.documentElement).getPropertyValue("--gentlest").trim(), weight: 4 },
    };
    for (const kind of ["shortest", "gentlest"]) {
      const route = leg[kind];
      if (route === null) {
        continue; // no data for this route
      }
      const points = route.points.map(function (point) {
        return gridToLatLng(point[0], point[1]);
      });
      const line = L.polyline(points, Object.assign({ className: "route-line" }, styles[kind]));
      line.bindTooltip(
        "LEG " + leg.from + "→" + leg.to + " · " + kind.toUpperCase() + " · " +
          (route.distance_m / 1000).toFixed(2) + " km · steepest " + route.max_slope_deg.toFixed(1) + "°",
        { sticky: true, className: "stop-tooltip" }
      );
      group.addLayer(line);
    }
  }
  addLayerButton(map, "ROUTES", "◆ CALCULATED", group, routeLegend(), true);
}

function addStops(map, stops) {
  for (const stop of stops) {
    const markerContent = makeElement("div", "stop-marker", String(stop.id));
    const icon = L.divIcon({ html: markerContent, className: "", iconSize: [44, 44], iconAnchor: [22, 22] });
    const marker = L.marker(gridToLatLng(stop.position[0], stop.position[1]), {
      icon: icon,
      keyboard: true,
      title: "Stop " + stop.id + ": " + stop.label,
    });
    marker.bindTooltip(stop.id + " · " + stop.label.toUpperCase(), { className: "stop-tooltip", direction: "top", offset: [0, -24] });
    marker.on("click", function () {
      showStopCard(stop.id);
    });
    marker.addTo(map);
  }
}

// ---------------------------------------------------------------- cursor readout

// Each readout image stores a 16-bit code per sampled cell: red = high byte, green = low byte.
// value = base + code * step. The cell [col, row] is read from pixel [round(col / n), round(row / n)].
function loadReadout(readout) {
  return new Promise(function (resolve, reject) {
    const image = new Image();
    image.onload = function () {
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.drawImage(image, 0, 0);
      resolve({ info: readout, pixels: context.getImageData(0, 0, image.width, image.height) });
    };
    image.onerror = function () {
      reject(new Error("Could not load readout " + readout.file));
    };
    image.src = packUrl(readout.file);
  });
}

function readValue(loaded, col, row) {
  const info = loaded.info;
  const pixels = loaded.pixels;
  const x = Math.min(pixels.width - 1, Math.max(0, Math.round(col / info.sample_every_px)));
  const y = Math.min(pixels.height - 1, Math.max(0, Math.round(row / info.sample_every_px)));
  const index = (y * pixels.width + x) * 4;
  const code = pixels.data[index] * 256 + pixels.data[index + 1];
  if (code === info.no_data_code) {
    return null;
  }
  return info.base + code * info.step;
}

function placeReadoutBox(map) {
  const box = document.getElementById("readout-box");
  const control = L.control({ position: "topright" });
  control.onAdd = function () {
    L.DomEvent.disableClickPropagation(box);
    L.DomEvent.disableScrollPropagation(box);
    return box;
  };
  control.addTo(map);
}

async function setUpReadout(map, manifest) {
  placeReadoutBox(map);
  const readouts = manifest.readouts || [];
  const loaded = {};
  for (const readout of readouts) {
    loaded[readout.id] = await loadReadout(readout);
  }
  const unitsById = {};
  for (const layer of manifest.layers) {
    if (layer.id === "geology") {
      for (const unit of layer.legend) {
        unitsById[unit.id] = unit;
      }
    }
  }
  if (readouts.length > 0) {
    const every = readouts[0].sample_every_px * manifest.grid.metres_per_pixel;
    document.getElementById("readout-note").textContent =
      "Value of the nearest 1 m cell, sampled every " + every + " m. Elevation: NASA DATA. Slope: CALCULATED." +
      (loaded.thermal_night ? " Night/Day IR: THEMIS 100 m pixels, 0-255, qualitative (NASA DATA)." : "");
  }

  const thermalCells = { night: document.getElementById("readout-thermal-night"), day: document.getElementById("readout-thermal-day") };
  for (const kind of ["night", "day"]) {
    thermalCells[kind].parentElement.hidden = !loaded["thermal_" + kind];
  }
  const elevationCell = document.getElementById("readout-elevation");
  const slopeCell = document.getElementById("readout-slope");
  const unitCell = document.getElementById("readout-unit");

  function clear() {
    elevationCell.textContent = "—";
    slopeCell.textContent = "—";
    unitCell.textContent = "—";
    thermalCells.night.textContent = "—";
    thermalCells.day.textContent = "—";
  }

  function update(event) {
    const col = event.latlng.lng;
    const row = -event.latlng.lat;
    if (col < 0 || row < 0 || col >= manifest.grid.width || row >= manifest.grid.height) {
      clear();
      return;
    }
    if (loaded.elevation) {
      const elevation = readValue(loaded.elevation, col, row);
      elevationCell.textContent = elevation === null ? "no data" : elevation.toFixed(1) + " m";
    }
    if (loaded.slope) {
      const slope = readValue(loaded.slope, col, row);
      slopeCell.textContent = slope === null ? "no data" : slope.toFixed(2) + "°";
    }
    if (loaded.unit) {
      const unitId = readValue(loaded.unit, col, row);
      const unit = unitId === null ? undefined : unitsById[Math.round(unitId)];
      unitCell.textContent = unit === undefined ? "no data" : unit.symbol + " · " + unit.name;
    }
    for (const kind of ["night", "day"]) {
      if (loaded["thermal_" + kind]) {
        const value = readValue(loaded["thermal_" + kind], col, row);
        thermalCells[kind].textContent = value === null ? "no data" : Math.round(value) + " / 255";
      }
    }
  }
  map.on("mousemove", update);
  map.on("click", update); // a tap on a touch screen
  map.on("mouseout", clear);
}

// ---------------------------------------------------------------- ROUTE tab

function formatKm(metres) {
  return (metres / 1000).toFixed(2) + " km";
}

function formatM(metres) {
  return Math.round(metres) + " m";
}

function factTable(headers, rows) {
  const table = makeElement("table", "fact-table");
  const head = makeElement("thead");
  const headRow = makeElement("tr");
  for (const header of headers) {
    headRow.appendChild(makeElement("th", "", header));
  }
  head.appendChild(headRow);
  table.appendChild(head);
  const body = makeElement("tbody");
  for (const row of rows) {
    const tableRow = makeElement("tr");
    for (const cell of row) {
      tableRow.appendChild(makeElement("td", "", cell));
    }
    body.appendChild(tableRow);
  }
  table.appendChild(body);
  return table;
}

function routeValue(route, format) {
  return route === null ? "no data" : format(route);
}

function fillRouteTab(map, manifest, stops, routes) {
  const tab = document.getElementById("tab-route");
  const labelsById = {};
  for (const stop of stops) {
    labelsById[stop.id] = stop.label;
  }
  const steepestMark = L.layerGroup().addTo(map);

  function showSteepest(route, kind) {
    steepestMark.clearLayers();
    const point = gridToLatLng(route.max_slope_at[0], route.max_slope_at[1]);
    const icon = L.divIcon({ html: makeElement("div", "slope-mark"), className: "", iconSize: [16, 16], iconAnchor: [8, 8] });
    L.marker(point, { icon: icon, interactive: false }).addTo(steepestMark);
    L.circleMarker(point, { radius: 18, color: kind === "shortest" ? "#ffc266" : "#8cff9e", weight: 2, fill: false }).addTo(steepestMark);
    map.setView(point, 1);
  }

  tab.appendChild(makeElement("h2", "section-title", "> ROUTE · " + stops.length + " STOPS · ◆ CALCULATED"));

  const totals = { shortest: { distance: 0, climb: 0, descent: 0, steepest: 0, complete: true }, gentlest: { distance: 0, climb: 0, descent: 0, steepest: 0, complete: true } };

  for (const leg of routes) {
    const card = makeElement("div", "card");
    card.appendChild(makeElement("h3", "card-title", "LEG " + leg.from + " → " + leg.to));
    card.appendChild(makeElement("p", "dim", (labelsById[leg.from] || "") + " → " + (labelsById[leg.to] || "")));
    card.appendChild(
      factTable(
        ["", "SHORTEST", "GENTLEST"],
        [
          ["DISTANCE", routeValue(leg.shortest, (r) => formatKm(r.distance_m)), routeValue(leg.gentlest, (r) => formatKm(r.distance_m))],
          ["CLIMB", routeValue(leg.shortest, (r) => formatM(r.climb_m)), routeValue(leg.gentlest, (r) => formatM(r.climb_m))],
          ["DESCENT", routeValue(leg.shortest, (r) => formatM(r.descent_m)), routeValue(leg.gentlest, (r) => formatM(r.descent_m))],
          ["STEEPEST", routeValue(leg.shortest, (r) => r.max_slope_deg.toFixed(1) + "°"), routeValue(leg.gentlest, (r) => r.max_slope_deg.toFixed(1) + "°")],
        ]
      )
    );
    const buttons = makeElement("div", "button-row");
    for (const kind of ["shortest", "gentlest"]) {
      const route = leg[kind];
      if (route === null) {
        totals[kind].complete = false;
        continue;
      }
      totals[kind].distance += route.distance_m;
      totals[kind].climb += route.climb_m;
      totals[kind].descent += route.descent_m;
      totals[kind].steepest = Math.max(totals[kind].steepest, route.max_slope_deg);
      const button = makeElement("button", "text-button", "SHOW STEEPEST POINT · " + kind.toUpperCase());
      button.type = "button";
      button.addEventListener("click", function () {
        showSteepest(route, kind);
      });
      buttons.appendChild(button);
    }
    const showLeg = makeElement("button", "text-button", "SHOW LEG ON MAP");
    showLeg.type = "button";
    showLeg.addEventListener("click", function () {
      const points = [];
      for (const kind of ["shortest", "gentlest"]) {
        if (leg[kind] !== null) {
          for (const point of leg[kind].points) {
            points.push(gridToLatLng(point[0], point[1]));
          }
        }
      }
      steepestMark.clearLayers();
      map.fitBounds(L.latLngBounds(points).pad(0.15));
    });
    buttons.appendChild(showLeg);
    card.appendChild(buttons);
    tab.appendChild(card);
  }

  const totalCard = makeElement("div", "card");
  totalCard.appendChild(makeElement("h3", "card-title", "ALL LEGS"));
  function total(kind, format) {
    return totals[kind].complete ? format(totals[kind]) : "no data";
  }
  totalCard.appendChild(
    factTable(
      ["", "SHORTEST", "GENTLEST"],
      [
        ["DISTANCE", total("shortest", (t) => formatKm(t.distance)), total("gentlest", (t) => formatKm(t.distance))],
        ["CLIMB", total("shortest", (t) => formatM(t.climb)), total("gentlest", (t) => formatM(t.climb))],
        ["DESCENT", total("shortest", (t) => formatM(t.descent)), total("gentlest", (t) => formatM(t.descent))],
        ["STEEPEST", total("shortest", (t) => t.steepest.toFixed(1) + "°"), total("gentlest", (t) => t.steepest.toFixed(1) + "°")],
      ]
    )
  );
  tab.appendChild(totalCard);

  const methods = manifest.methods || {};
  for (const name of ["shortest", "gentlest", "distance", "climb_descent", "steepest"]) {
    if (methods[name]) {
      tab.appendChild(makeElement("p", "note", name.replace("_", " / ").toUpperCase() + ": " + methods[name]));
    }
  }
}

// ---------------------------------------------------------------- SUN tab

const MARS_MINUTES_PER_SOL = 24 * 60;
const PLAY_STEP_MARS_MINUTES = 10;
const PLAY_INTERVAL_MS = 150;
const SHADE_RGBA = [8, 10, 40, 165]; // display choice only
const REPAINT_MIN_SUN_CHANGE_DEG = 0.05;

function formatUtc(unixMs) {
  return new Date(unixMs).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

function formatEarthDuration(ms) {
  const minutes = Math.round(ms / 60000);
  return Math.floor(minutes / 60) + " h " + String(minutes % 60).padStart(2, "0") + " min";
}

function makeSunArrow(map) {
  const box = makeElement("div", "sun-arrow");
  box.setAttribute("aria-live", "off");
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  svg.setAttribute("viewBox", "-20 -20 40 40");
  svg.setAttribute("width", "44");
  svg.setAttribute("height", "44");
  svg.setAttribute("aria-hidden", "true");
  const ring = document.createElementNS(svgNs, "circle");
  ring.setAttribute("r", "17");
  ring.setAttribute("class", "sun-arrow-ring");
  const pointer = document.createElementNS(svgNs, "path");
  pointer.setAttribute("d", "M0,-16 L6,-4 L1.5,-4 L1.5,12 L-1.5,12 L-1.5,-4 L-6,-4 Z");
  pointer.setAttribute("class", "sun-arrow-pointer");
  const north = document.createElementNS(svgNs, "text");
  north.setAttribute("y", "-6");
  north.setAttribute("x", "11");
  north.setAttribute("class", "sun-arrow-north");
  north.textContent = "N";
  svg.appendChild(ring);
  svg.appendChild(pointer);
  svg.appendChild(north);
  const text = makeElement("span", "sun-arrow-text", "SUN —");
  box.appendChild(svg);
  box.appendChild(text);
  const control = L.control({ position: "bottomright" });
  control.onAdd = function () {
    L.DomEvent.disableClickPropagation(box);
    return box;
  };
  control.addTo(map);
  return function update(mapAngleDeg, azimuth, elevation, timeText) {
    pointer.setAttribute("transform", "rotate(" + mapAngleDeg.toFixed(1) + ")");
    box.classList.toggle("sun-down", elevation <= 0);
    text.textContent = (elevation <= 0 ? "SUN BELOW HORIZON" : "SUN AZ " + azimuth.toFixed(0) + "° · EL " + elevation.toFixed(1) + "°") + " · " + timeText;
  };
}

async function setUpSunTab(map, manifest, routes) {
  const tab = document.getElementById("tab-sun");
  const box = manifest.site.bounds_lonlat;
  const lon = (box[0] + box[2]) / 2;
  const lat = (box[1] + box[3]) / 2;
  const horizon = manifest.horizon || null;
  const eastScale = eastScaleOf(manifest);

  tab.appendChild(makeElement("h2", "section-title", "> SKY · MARS CLOCK · SUN · EARTH LINK · ◆ CALCULATED"));

  const clockCard = makeElement("div", "card");
  clockCard.appendChild(makeElement("h3", "card-title", "MARS CLOCK · SITE CENTRE " + lon.toFixed(2) + "° E " + lat.toFixed(2) + "° N"));
  const clock = makeElement("dl", "readout clock");
  const fields = {};
  for (const [key, label] of [
    ["utc", "EARTH"],
    ["sol", "SOL"],
    ["lmst", "LMST"],
    ["ltst", "LTST"],
    ["ls", "SEASON Ls"],
    ["sun", "SUN"],
    ["sunrise", "SUNRISE"],
    ["sunset", "SUNSET"],
    ["left", "TO SUNSET"],
  ]) {
    clock.appendChild(makeElement("dt", "", label));
    fields[key] = makeElement("dd", "", "—");
    clock.appendChild(fields[key]);
  }
  clockCard.appendChild(clock);
  clockCard.appendChild(
    makeElement(
      "p",
      "note",
      "SOL = Perseverance mission sol (sol 0 = landing, 18 Feb 2021). LMST = local mean solar time, LTST = local true solar time (sun-based), " +
        "in Mars hours. Sunrise / sunset: centre of the sun at 0° over a flat horizon, no atmosphere; terrain makes it later / earlier locally (see shadows). " +
        "Method: NASA GISS Mars24 algorithm (2025-01-07)."
    )
  );
  tab.appendChild(clockCard);

  const controlCard = makeElement("div", "card");
  controlCard.appendChild(makeElement("h3", "card-title", "CHOOSE A TIME"));
  const solRow = makeElement("div", "button-row");
  const previousSol = makeElement("button", "text-button", "◀ SOL");
  const nowButton = makeElement("button", "text-button", "NOW");
  const nextSol = makeElement("button", "text-button", "SOL ▶");
  const playButton = makeElement("button", "text-button", "▶ PLAY SOL");
  for (const button of [previousSol, nowButton, nextSol, playButton]) {
    button.type = "button";
    solRow.appendChild(button);
  }
  controlCard.appendChild(solRow);
  const sliderLabel = makeElement("label", "slider-label");
  const sliderText = makeElement("span", "", "LMST —");
  const slider = document.createElement("input");
  slider.type = "range";
  slider.min = "0";
  slider.max = String(MARS_MINUTES_PER_SOL - 5);
  slider.step = "5";
  slider.className = "time-slider";
  slider.setAttribute("aria-label", "Local mean solar time on the chosen sol");
  sliderLabel.appendChild(sliderText);
  sliderLabel.appendChild(slider);
  controlCard.appendChild(sliderLabel);
  const modeLine = makeElement("p", "dim", "");
  controlCard.appendChild(modeLine);
  tab.appendChild(controlCard);

  const updateEarthLink = setUpEarthLinkCard(tab);

  const shadowCard = makeElement("div", "card");
  shadowCard.appendChild(makeElement("h3", "card-title", "ROUTES IN TERRAIN SHADOW"));
  const shadowButtonRow = makeElement("div", "button-row");
  const shadowToggle = makeElement("button", "text-button", "SHOW SHADOWS ON MAP");
  shadowToggle.type = "button";
  shadowButtonRow.appendChild(shadowToggle);
  shadowCard.appendChild(shadowButtonRow);
  const shadowTableHolder = makeElement("div");
  shadowCard.appendChild(shadowTableHolder);
  shadowCard.appendChild(
    makeElement(
      "p",
      "note",
      horizon === null
        ? "This data pack has no terrain horizon (pipeline/horizon.py), so no shadows."
        : "Share of each route's length in the shadow of the terrain at the chosen time (route sampled every " +
            horizon.cell_px / 2 + " m). " + horizon.method + " Heights: " + horizon.source +
            ". The DTM ends " + horizon.dtm_margin_m.west + " m (W), " + horizon.dtm_margin_m.east + " m (E), " +
            horizon.dtm_margin_m.north + " m (N), " + horizon.dtm_margin_m.south + " m (S) from the walk area; " +
            "features smaller than " + horizon.cell_px + " m (boulders) are not included."
    )
  );
  tab.appendChild(shadowCard);

  const updateArrow = makeSunArrow(map);

  // Shadow overlay: one pixel per horizon cell.
  let codes = null;
  let overlay = null;
  let showShadowLayer = null;
  let canvas = null;
  if (horizon !== null) {
    try {
      codes = await Shadow.loadCodes(horizon, packUrl);
    } catch (error) {
      shadowTableHolder.appendChild(makeElement("p", "note", "Shadows unavailable: " + error.message));
    }
  }
  if (codes !== null) {
    canvas = document.createElement("canvas");
    canvas.width = horizon.width;
    canvas.height = horizon.height;
    const bounds = L.latLngBounds(gridToLatLng(0, horizon.height * horizon.cell_px), gridToLatLng(horizon.width * horizon.cell_px, 0));
    overlay = L.imageOverlay(canvas.toDataURL(), bounds, { pane: "dataOverlays", className: "pixelated", interactive: false });
    const legend = makeElement("div", "legend");
    const row = makeElement("div", "legend-row");
    const swatch = makeElement("span", "legend-swatch");
    swatch.style.background = "rgba(" + SHADE_RGBA.slice(0, 3).join(",") + "," + (SHADE_RGBA[3] / 255).toFixed(2) + ")";
    row.appendChild(swatch);
    row.appendChild(makeElement("span", "", "IN TERRAIN SHADOW at the time chosen in the SKY tab"));
    legend.appendChild(row);
    legend.appendChild(makeElement("p", "note", horizon.cell_px + " m cells"));
    showShadowLayer = addLayerButton(map, "TERRAIN SHADOW", "◆ CALCULATED · SKY TAB TIME", overlay, legend, false);
  } else {
    shadowToggle.disabled = true;
  }

  const state = { live: true, sol: 0, minutes: 0 };
  let playTimer = null;
  let lastPainted = null;
  const sunTimesBySol = {};

  function sunTimes(sol) {
    if (!(sol in sunTimesBySol)) {
      sunTimesBySol[sol] = MarsTime.sunriseSunset(sol, lon, lat);
    }
    return sunTimesBySol[sol];
  }

  function timeLine(unixMs) {
    const at = MarsTime.sun(unixMs, lon, lat);
    return "LTST " + MarsTime.formatHours(at.ltst) + " · LMST " + MarsTime.formatHours(at.lmst) + " · " + formatUtc(unixMs);
  }

  function paintShadows(at) {
    if (codes === null) {
      return;
    }
    const sunKey = { az: at.azimuth, el: at.elevation };
    const moved =
      lastPainted === null ||
      Math.abs(lastPainted.az - sunKey.az) > REPAINT_MIN_SUN_CHANGE_DEG ||
      Math.abs(lastPainted.el - sunKey.el) > REPAINT_MIN_SUN_CHANGE_DEG;
    if (!moved) {
      return;
    }
    lastPainted = sunKey;
    if (map.hasLayer(overlay)) {
      const context = canvas.getContext("2d");
      const image = context.createImageData(horizon.width, horizon.height);
      Shadow.paintShadow(horizon, codes, image.data, at.azimuth, at.elevation, SHADE_RGBA);
      context.putImageData(image, 0, 0);
      overlay.setUrl(canvas.toDataURL());
    }
    const rows = [];
    for (const leg of routes) {
      const cells = ["LEG " + leg.from + " → " + leg.to];
      for (const kind of ["shortest", "gentlest"]) {
        if (leg[kind] === null) {
          cells.push("no data");
          continue;
        }
        const result = Shadow.routeShadow(horizon, codes, leg[kind].points, at.azimuth, at.elevation);
        cells.push(result.shadow === null ? "no data" : Math.round(result.shadow * 100) + " %");
      }
      rows.push(cells);
    }
    shadowTableHolder.replaceChildren(factTable(["IN SHADOW", "SHORTEST", "GENTLEST"], rows));
    if (at.elevation <= 0) {
      shadowTableHolder.appendChild(makeElement("p", "dim", "NIGHT: the sun is below 0°, the whole area is without direct sunlight."));
    }
  }

  function render() {
    let unixMs;
    if (state.live) {
      unixMs = Date.now();
      state.sol = MarsTime.m20Sol(unixMs);
      state.minutes = Math.floor(MarsTime.sun(unixMs, lon, lat).lmst * 60);
    } else {
      unixMs = MarsTime.unixMsAtLocalTime(state.sol, state.minutes / 60, lon);
    }
    const at = MarsTime.sun(unixMs, lon, lat);
    const times = sunTimes(state.sol);
    fields.utc.textContent = state.live
      ? new Date(unixMs).toISOString().slice(0, 19).replace("T", " ") + " UTC (now)"
      : formatUtc(unixMs) + " (chosen)";
    fields.sol.textContent = String(state.sol) + " · Mars Sol Date " + MarsTime.marsSolDate(unixMs).toFixed(3);
    fields.lmst.textContent = MarsTime.formatHours(at.lmst);
    fields.ltst.textContent = MarsTime.formatHours(at.ltst);
    fields.ls.textContent = at.ls.toFixed(1) + "°";
    fields.sun.textContent = "azimuth " + at.azimuth.toFixed(1) + "° · elevation " + at.elevation.toFixed(1) + "°";
    fields.sunrise.textContent = times.sunrise === null ? "none this sol" : timeLine(times.sunrise);
    fields.sunset.textContent = times.sunset === null ? "none this sol" : timeLine(times.sunset);
    if (times.sunset === null) {
      fields.left.textContent = "—";
    } else if (unixMs < times.sunset) {
      fields.left.textContent = formatEarthDuration(times.sunset - unixMs) + " (Earth time)";
    } else {
      fields.left.textContent = "after sunset";
    }
    slider.value = String(state.minutes - (state.minutes % 5));
    sliderText.textContent = "SOL " + state.sol + " · LMST " + MarsTime.formatHours(state.minutes / 60);
    modeLine.textContent = state.live ? "SHOWING NOW (updates every second)" : playTimer !== null ? "PLAYING THE SOL" : "SHOWING THE CHOSEN TIME";
    updateEarthLink(unixMs);
    updateArrow(Shadow.mapAngle(at.azimuth, eastScale), at.azimuth, at.elevation, "LMST " + MarsTime.formatHours(at.lmst) + (state.live ? " NOW" : ""));
    paintShadows(at);
  }

  function stopPlaying() {
    if (playTimer !== null) {
      clearInterval(playTimer);
      playTimer = null;
      playButton.textContent = "▶ PLAY SOL";
    }
  }

  function choose(sol, minutes) {
    state.live = false;
    state.sol = sol;
    state.minutes = ((minutes % MARS_MINUTES_PER_SOL) + MARS_MINUTES_PER_SOL) % MARS_MINUTES_PER_SOL;
    render();
  }

  previousSol.addEventListener("click", function () {
    choose(state.sol - 1, state.minutes);
  });
  nextSol.addEventListener("click", function () {
    choose(state.sol + 1, state.minutes);
  });
  nowButton.addEventListener("click", function () {
    stopPlaying();
    state.live = true;
    render();
  });
  slider.addEventListener("input", function () {
    stopPlaying();
    choose(state.sol, Number(slider.value));
  });
  playButton.addEventListener("click", function () {
    if (playTimer !== null) {
      stopPlaying();
      render();
      return;
    }
    if (showShadowLayer !== null && !map.hasLayer(overlay)) {
      showShadowLayer(true);
      lastPainted = null;
    }
    playButton.textContent = "■ STOP";
    playTimer = setInterval(function () {
      choose(state.sol, state.minutes + PLAY_STEP_MARS_MINUTES);
    }, PLAY_INTERVAL_MS);
    choose(state.sol, state.minutes);
  });
  shadowToggle.addEventListener("click", function () {
    if (showShadowLayer !== null) {
      showShadowLayer(!map.hasLayer(overlay));
    }
  });
  if (overlay !== null) {
    overlay.on("add", function () {
      lastPainted = null;
      shadowToggle.textContent = "HIDE SHADOWS ON MAP";
      render();
    });
    overlay.on("remove", function () {
      shadowToggle.textContent = "SHOW SHADOWS ON MAP";
    });
  }
  setInterval(function () {
    if (state.live) {
      render();
    }
  }, 1000);
  render();
}

// ---------------------------------------------------------------- Earth link (SKY tab)

// NASA NSSDC fact sheets (Earth, Mars): sidereal orbit periods, for drawing the orbits only.
const ORBIT_PERIOD_DAYS = { earth: 365.256, mars: 686.98 };
const DIAGRAM_SIZE_PX = 280;
const DIAGRAM_MAX_AU = 1.75;
const MESSAGE_SPEEDS = [1, 60]; // real time, 60x faster (shown on screen)
const MESSAGE_MAX_CHARS = 140;

function svgElement(name, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function setUpEarthLinkCard(tab) {
  const card = makeElement("div", "card");
  card.appendChild(makeElement("h3", "card-title", "EARTH LINK · ◆ CALCULATED"));
  const facts = makeElement("dl", "readout clock");
  const fields = {};
  for (const [key, label] of [
    ["oneWay", "ONE WAY"],
    ["roundTrip", "ROUND TRIP"],
    ["distance", "DISTANCE"],
    ["angle", "SUN–EARTH–MARS"],
  ]) {
    facts.appendChild(makeElement("dt", "", label));
    fields[key] = makeElement("dd", "", "—");
    facts.appendChild(fields[key]);
  }
  card.appendChild(facts);

  const scale = DIAGRAM_SIZE_PX / 2 / DIAGRAM_MAX_AU;
  const svg = svgElement("svg", {
    viewBox: -DIAGRAM_SIZE_PX / 2 + " " + -DIAGRAM_SIZE_PX / 2 + " " + DIAGRAM_SIZE_PX + " " + DIAGRAM_SIZE_PX,
    class: "orbit-diagram",
    role: "img",
    "aria-label": "Sun, Earth and Mars to scale, seen from above the ecliptic",
  });
  const earthOrbit = svgElement("polyline", { class: "orbit" });
  const marsOrbit = svgElement("polyline", { class: "orbit" });
  const linkLine = svgElement("line", { class: "link-line" });
  const sunDot = svgElement("circle", { r: 6, class: "body-sun" });
  const earthDot = svgElement("circle", { r: 4, class: "body-earth" });
  const marsDot = svgElement("circle", { r: 4, class: "body-mars" });
  const pulse = svgElement("circle", { r: 4, class: "pulse", visibility: "hidden" });
  const earthLabel = svgElement("text", { class: "body-label" });
  earthLabel.textContent = "EARTH";
  const marsLabel = svgElement("text", { class: "body-label" });
  marsLabel.textContent = "MARS";
  for (const element of [earthOrbit, marsOrbit, linkLine, sunDot, earthDot, marsDot, pulse, earthLabel, marsLabel]) {
    svg.appendChild(element);
  }
  card.appendChild(svg);
  card.appendChild(makeElement("p", "note", "To scale, ecliptic seen from the north, x towards the March equinox. Orbits drawn from the same formulas over one orbit."));

  // SEND simulation
  card.appendChild(makeElement("h3", "card-title", "SEND A MESSAGE · SIMULATION"));
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = MESSAGE_MAX_CHARS;
  input.className = "message-input";
  input.placeholder = "message to Earth";
  input.setAttribute("aria-label", "Message to send to Earth (simulation)");
  card.appendChild(input);
  const buttons = makeElement("div", "button-row");
  const sendButton = makeElement("button", "text-button", "SEND ▶");
  sendButton.type = "button";
  const speedButton = makeElement("button", "text-button", "SPEED: REAL TIME");
  speedButton.type = "button";
  buttons.appendChild(sendButton);
  buttons.appendChild(speedButton);
  card.appendChild(buttons);
  const status = makeElement("p", "", "—");
  status.setAttribute("aria-live", "polite");
  const progress = makeElement("div", "message-progress");
  const progressBar = makeElement("div", "message-progress-bar");
  progress.appendChild(progressBar);
  card.appendChild(progress);
  card.appendChild(status);
  card.appendChild(
    makeElement(
      "p",
      "note",
      "SIMULATION: nothing is sent. Timing is light time only, at the time chosen above; real links add relay orbiter passes and Deep Space Network schedules. " +
        "SUN–EARTH–MARS near 0° = solar conjunction (Mars behind the Sun seen from Earth). " +
        "Method: Mars from NASA GISS Mars24 (D-2..D-4), Earth from JPL \"Approximate Positions of the Planets\" Table 1 (1800–2050); light speed 299,792.458 km/s, AU 149,597,870.7 km."
    )
  );
  tab.appendChild(card);

  let speedIndex = 0;
  let message = null; // {text, timeline, startedReal, speed}
  let lastLink = null;
  let lastOrbitDay = null;
  let animation = null;

  function toSvg(xyz) {
    return [xyz[0] * scale, -xyz[1] * scale];
  }

  function drawOrbits(unixMs) {
    const day = Math.floor(unixMs / 86400000);
    if (day === lastOrbitDay) {
      return;
    }
    lastOrbitDay = day;
    for (const [line, positionAt, period] of [
      [earthOrbit, MarsTime.earthXyz, ORBIT_PERIOD_DAYS.earth],
      [marsOrbit, MarsTime.marsXyz, ORBIT_PERIOD_DAYS.mars],
    ]) {
      const points = Comms.orbitPath(positionAt, unixMs, period, 180).map(function (point) {
        return (point[0] * scale).toFixed(1) + "," + (-point[1] * scale).toFixed(1);
      });
      line.setAttribute("points", points.join(" "));
    }
  }

  function placeBody(dot, label, xyz) {
    const point = toSvg(xyz);
    dot.setAttribute("cx", point[0].toFixed(1));
    dot.setAttribute("cy", point[1].toFixed(1));
    label.setAttribute("x", (point[0] + 7).toFixed(1));
    label.setAttribute("y", (point[1] - 7).toFixed(1));
  }

  function showMessage() {
    if (message === null) {
      return;
    }
    const simulatedNow = message.timeline.sent + (Date.now() - message.startedReal) * message.speed;
    const state = Comms.messageState(message.timeline, simulatedNow);
    const mars = toSvg(message.mars);
    const earth = toSvg(message.earth);
    let from = mars;
    let to = earth;
    if (state.phase === "to-mars") {
      from = earth;
      to = mars;
    }
    pulse.setAttribute("visibility", state.phase === "done" ? "hidden" : "visible");
    pulse.setAttribute("cx", (from[0] + (to[0] - from[0]) * state.fraction).toFixed(1));
    pulse.setAttribute("cy", (from[1] + (to[1] - from[1]) * state.fraction).toFixed(1));
    pulse.setAttribute("class", state.phase === "to-mars" ? "pulse reply" : "pulse");
    const total = (message.timeline.earliestReply - message.timeline.sent);
    progressBar.style.width = (Math.min(1, (simulatedNow - message.timeline.sent) / total) * 100).toFixed(1) + "%";
    const quoted = "“" + message.text + "”";
    const speedText = message.speed === 1 ? "" : " · shown " + message.speed + "× faster";
    if (state.phase === "to-earth") {
      status.textContent = "IN TRANSIT TO EARTH " + quoted + " · arrives in " +
        Comms.formatDuration((message.timeline.arrivesEarth - simulatedNow) / 1000) + " (" + formatUtc(message.timeline.arrivesEarth) + ")" + speedText;
    } else if (state.phase === "to-mars") {
      status.textContent = "ARRIVED AT EARTH " + formatUtc(message.timeline.arrivesEarth) + " · earliest reply reaches Mars in " +
        Comms.formatDuration((message.timeline.earliestReply - simulatedNow) / 1000) + " (" + formatUtc(message.timeline.earliestReply) + ")" + speedText;
    } else {
      status.textContent = "DONE · sent " + formatUtc(message.timeline.sent) + " · at Earth " + formatUtc(message.timeline.arrivesEarth) +
        " · earliest reply at Mars " + formatUtc(message.timeline.earliestReply);
      sendButton.disabled = false;
      animation = null;
      return;
    }
    animation = requestAnimationFrame(showMessage);
  }

  sendButton.addEventListener("click", function () {
    if (lastLink === null) {
      return;
    }
    const text = input.value.trim().slice(0, MESSAGE_MAX_CHARS) || "(empty message)";
    if (animation !== null) {
      cancelAnimationFrame(animation);
    }
    message = {
      text: text,
      timeline: Comms.messageTimeline(lastLink.unixMs, lastLink.oneWaySeconds),
      startedReal: Date.now(),
      speed: MESSAGE_SPEEDS[speedIndex],
      mars: lastLink.mars,
      earth: lastLink.earth,
    };
    showMessage();
  });
  speedButton.addEventListener("click", function () {
    speedIndex = (speedIndex + 1) % MESSAGE_SPEEDS.length;
    speedButton.textContent = "SPEED: " + (MESSAGE_SPEEDS[speedIndex] === 1 ? "REAL TIME" : MESSAGE_SPEEDS[speedIndex] + "× FASTER");
  });

  return function update(unixMs) {
    const link = MarsTime.earthLink(unixMs);
    lastLink = { unixMs: unixMs, oneWaySeconds: link.oneWaySeconds, mars: link.mars, earth: link.earth };
    fields.oneWay.textContent = Comms.formatDuration(link.oneWaySeconds);
    fields.roundTrip.textContent = Comms.formatDuration(2 * link.oneWaySeconds);
    fields.distance.textContent = link.distanceAu.toFixed(3) + " AU · " + ((link.distanceAu * 149597870.7) / 1e6).toFixed(1) + " million km";
    fields.angle.textContent = link.sunMarsAngleDeg.toFixed(1) + "°";
    drawOrbits(unixMs);
    linkLine.setAttribute("x1", toSvg(link.mars)[0].toFixed(1));
    linkLine.setAttribute("y1", toSvg(link.mars)[1].toFixed(1));
    linkLine.setAttribute("x2", toSvg(link.earth)[0].toFixed(1));
    linkLine.setAttribute("y2", toSvg(link.earth)[1].toFixed(1));
    placeBody(earthDot, earthLabel, link.earth);
    placeBody(marsDot, marsLabel, link.mars);
  };
}

// ---------------------------------------------------------------- STOPS tab

function fillStopsTab(stops, mission, progress) {
  const tab = document.getElementById("tab-stops");
  tab.appendChild(makeElement("h2", "section-title", "> STOPS"));
  for (const stop of stops) {
    const card = makeElement("div", "card stop-card");
    card.id = "stop-card-" + stop.id;
    card.appendChild(makeElement("h3", "card-title", "STOP " + stop.id + " · " + stop.label.toUpperCase()));
    card.appendChild(makeElement("p", "dim", "Position: " + stop.position_source + "."));

    const question = questionFor(mission, stop.id);
    if (question !== null) {
      card.appendChild(makeElement("p", "dim", "MISSION QUESTION · set by the mission planner"));
      card.appendChild(makeElement("p", "", question));
    }
    const reachedButton = makeElement("button", "text-button");
    reachedButton.type = "button";
    function showReached() {
      const isReached = progress.has(stop.id);
      reachedButton.textContent = isReached ? "[x] STOP REACHED" : "[ ] MARK STOP AS REACHED";
      reachedButton.setAttribute("aria-pressed", isReached ? "true" : "false");
    }
    reachedButton.addEventListener("click", function () {
      progress.toggle(stop.id);
    });
    progress.onChange(showReached);
    showReached();
    card.appendChild(reachedButton);

    card.appendChild(makeElement("p", "dim", "GROUND SLOPE AT STOP · ◆ CALCULATED"));
    card.appendChild(makeElement("p", "", stop.ground_slope_deg === null ? "no data" : stop.ground_slope_deg.toFixed(1) + "°"));

    card.appendChild(makeElement("p", "dim", "ROCK UNIT · ■ NASA DATA · USGS SIM 3464"));
    if (stop.unit === null) {
      card.appendChild(makeElement("p", "", "no data"));
    } else {
      card.appendChild(makeElement("p", "", stop.unit.symbol + " · " + stop.unit.name));
      card.appendChild(makeElement("p", "note", stop.unit.description === null ? "Description: no data" : stop.unit.description));
    }

    if (stop.photos.length > 0) {
      card.appendChild(makeElement("p", "dim", "PERSEVERANCE PHOTO · ■ NASA DATA"));
      const photo = makeElement("img", "stop-photo");
      photo.loading = "lazy";
      const caption = makeElement("p", "note");
      const cameraButtons = makeElement("div", "button-row");
      const buttonList = [];
      function showPhoto(index) {
        const chosen = stop.photos[index];
        photo.src = packUrl(chosen.file);
        photo.alt = "Stop " + stop.id + ", sol " + chosen.sol + ", " + chosen.camera;
        caption.textContent =
          "Sol " + chosen.sol + " · " + chosen.camera + " · image ID " + (chosen.image_id === null ? "no data" : chosen.image_id) + " · " + chosen.credit;
        for (let other = 0; other < buttonList.length; other++) {
          buttonList[other].setAttribute("aria-pressed", other === index ? "true" : "false");
        }
      }
      stop.photos.forEach(function (chosen, index) {
        const button = makeElement("button", "text-button", chosen.camera.toUpperCase());
        button.type = "button";
        button.addEventListener("click", function () {
          showPhoto(index);
        });
        buttonList.push(button);
        cameraButtons.appendChild(button);
      });
      if (stop.photos.length > 1) {
        card.appendChild(cameraButtons);
      }
      card.appendChild(photo);
      card.appendChild(caption);
      showPhoto(0);
    }
    tab.appendChild(card);
  }
}

function showStopCard(stopId) {
  openTab("stops");
  for (const card of document.querySelectorAll(".stop-card")) {
    card.classList.toggle("selected", card.id === "stop-card-" + stopId);
  }
  const card = document.getElementById("stop-card-" + stopId);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ---------------------------------------------------------------- DATA tab

const KNOWN_LIMITS = [
  "Terrain cells are about 1 m (east-west they are cos(latitude) shorter on the ground, see GROUND_SCALE in methods): rocks and obstacles smaller than about 1 m are not in the terrain data.",
  "Slope depends on cell size: these values are slopes over 1 m.",
  "Cursor readout uses values sampled every 4 m; stop cards and routes use every 1 m cell.",
  "Stop positions are where the rover was on that sol, not the exact spot each photo shows.",
  "Current surface conditions (weather, dust) are not included.",
  "Shadows use 16 m terrain cells and terrain inside the HiRISE DTM only (the far crater rim is outside it); no atmosphere, the sun is treated as a point.",
];

function fillDataTab(manifest) {
  const tab = document.getElementById("tab-data");
  tab.appendChild(makeElement("h2", "section-title", "> DATA PACK " + manifest.id.toUpperCase() + " v" + manifest.version + " · BUILT " + manifest.created));

  for (const layer of manifest.layers) {
    const card = makeElement("div", "card");
    card.appendChild(makeElement("h3", "card-title", (LAYER_NAMES[layer.id] || layer.id.toUpperCase())));
    card.appendChild(makeElement("p", "dim", (LABEL_MARK[layer.label] || "") + " " + layer.label + " · AS OF " + (layer.as_of !== null ? layer.as_of : "no data")));
    card.appendChild(makeElement("p", "note", "Source: " + layer.source));
    card.appendChild(makeElement("p", "note", "Product: " + layer.product_id));
    if (layer.method) {
      card.appendChild(makeElement("p", "note", "Method: " + layer.method));
    }
    tab.appendChild(card);
  }

  const readouts = manifest.readouts || [];
  if (readouts.length > 0) {
    const card = makeElement("div", "card");
    card.appendChild(makeElement("h3", "card-title", "CURSOR READOUT"));
    for (const readout of readouts) {
      card.appendChild(makeElement("p", "note", readout.id.toUpperCase() + " · " + readout.label + " · " + readout.source));
    }
    if (manifest.methods && manifest.methods.readout) {
      card.appendChild(makeElement("p", "note", "Method: " + manifest.methods.readout));
    }
    tab.appendChild(card);
  }

  const methodsCard = makeElement("div", "card");
  methodsCard.appendChild(makeElement("h3", "card-title", "METHODS · ◆ CALCULATED"));
  for (const [name, text] of Object.entries(manifest.methods || {})) {
    methodsCard.appendChild(makeElement("p", "note", name.replace("_", " / ").toUpperCase() + ": " + text));
  }
  tab.appendChild(methodsCard);

  const photosCard = makeElement("div", "card");
  photosCard.appendChild(makeElement("h3", "card-title", "PHOTOS AND POSITIONS"));
  photosCard.appendChild(makeElement("p", "note", "Photos: Perseverance raw images, NASA/JPL-Caltech."));
  photosCard.appendChild(makeElement("p", "note", "Stop positions: NASA Mars 2020 rover waypoints (Perseverance)."));
  photosCard.appendChild(
    makeElement("p", "note", "Orbit view: Mars Viking MDIM 2.1 Colorized Global Mosaic, 232 m (USGS Astrogeology Science Center; NASA Viking Orbiter images).")
  );
  tab.appendChild(photosCard);

  const sunCard = makeElement("div", "card");
  sunCard.appendChild(makeElement("h3", "card-title", "SUN, MARS CLOCK, SHADOWS · ◆ CALCULATED"));
  sunCard.appendChild(
    makeElement(
      "p",
      "note",
      "Mars time, sun position, sunrise and sunset: NASA GISS Mars24 \"Algorithm and Worked Examples\" (Allison 1997; Allison & McEwen 2000), updated 2025-01-07."
    )
  );
  sunCard.appendChild(
    makeElement(
      "p",
      "note",
      "Perseverance sol: sol 0 = landing sol (2021-02-18 20:55 UTC), local mean solar time at the landing site (first NASA M20 waypoint); checked against sols in NASA raw-image IDs."
    )
  );
  if (manifest.horizon) {
    sunCard.appendChild(makeElement("p", "note", "Terrain shadow: " + manifest.horizon.method + " Heights: " + manifest.horizon.source + "."));
  }
  tab.appendChild(sunCard);

  const limitsCard = makeElement("div", "card");
  limitsCard.appendChild(makeElement("h3", "card-title", "KNOWN LIMITS"));
  for (const limit of KNOWN_LIMITS) {
    limitsCard.appendChild(makeElement("p", "note", "· " + limit));
  }
  tab.appendChild(limitsCard);
}

// ---------------------------------------------------------------- HUD (next stop, bearing, distance)

// Ground metres per grid metre east-west (equirectangular grid, true scale at the equator).
function eastScaleOf(manifest) {
  return typeof manifest.grid.east_scale === "number" ? manifest.grid.east_scale : 1;
}

// Ground offset in metres [east, north] between two grid positions. Rows grow downwards.
function groundOffset(manifest, from, to) {
  const metres = manifest.grid.metres_per_pixel;
  return [(to[0] - from[0]) * metres * eastScaleOf(manifest), (from[1] - to[1]) * metres];
}

// Bearing on the ground in degrees clockwise from north (map up).
function bearingDegrees(manifest, from, to) {
  const offset = groundOffset(manifest, from, to);
  return (Math.atan2(offset[0], offset[1]) * 180 / Math.PI + 360) % 360;
}

function groundDistance(manifest, from, to) {
  const offset = groundOffset(manifest, from, to);
  return Math.hypot(offset[0], offset[1]);
}

// Mission progress: the stops this viewer has marked as reached, kept on this device only.
function createProgress(missionId, stops) {
  const storageKey = "navasa-progress-" + missionId;
  const reached = new Set();
  try {
    const saved = JSON.parse(window.localStorage.getItem(storageKey) || "[]");
    for (const stopId of saved) {
      reached.add(stopId);
    }
  } catch (error) {
    // No storage (private window): progress lasts until the page is closed.
  }
  const listeners = [];
  return {
    has: function (stopId) {
      return reached.has(stopId);
    },
    count: function () {
      return stops.filter(function (stop) {
        return reached.has(stop.id);
      }).length;
    },
    toggle: function (stopId) {
      if (reached.has(stopId)) {
        reached.delete(stopId);
      } else {
        reached.add(stopId);
      }
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(Array.from(reached)));
      } catch (error) {
        // Not saved on this device; the page still works.
      }
      for (const listener of listeners) {
        listener(stopId);
      }
    },
    onChange: function (listener) {
      listeners.push(listener);
    },
  };
}

function questionFor(mission, stopId) {
  for (const entry of mission.questions) {
    if (entry.stop_id === stopId) {
      return entry.question;
    }
  }
  return null;
}

function setUpMissionTab(map, manifest, mission, stops, routes, progress) {
  const tab = document.getElementById("tab-hud");
  let atIndex = 0;

  // Briefing: name, objective (set by the mission planner) and its sources.
  const briefing = makeElement("div", "card mission-brief");
  briefing.appendChild(makeElement("p", "dim", "> MISSION · " + mission.status + " · " + mission.site.toUpperCase()));
  briefing.appendChild(makeElement("h2", "card-title", mission.name.toUpperCase()));
  briefing.appendChild(makeElement("p", "dim", "OBJECTIVE · set by the mission planner"));
  briefing.appendChild(makeElement("p", "", mission.objective));
  for (const source of mission.objective_sources) {
    if (source.url) {
      const link = makeElement("a", "note source-link", "Source: " + source.text);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      briefing.appendChild(link);
    } else {
      briefing.appendChild(makeElement("p", "note", "Source: " + source.text));
    }
  }
  tab.appendChild(briefing);

  // Objectives: one per stop, in walking order, with the planner's question.
  const objectivesCard = makeElement("div", "card");
  const progressTitle = makeElement("p", "dim");
  const progressBar = makeElement("div", "progress-bar");
  const progressFill = makeElement("div", "progress-fill");
  progressBar.appendChild(progressFill);
  progressBar.setAttribute("role", "progressbar");
  progressBar.setAttribute("aria-valuemin", "0");
  progressBar.setAttribute("aria-valuemax", String(stops.length));
  objectivesCard.appendChild(progressTitle);
  objectivesCard.appendChild(progressBar);
  const objectiveButtons = {};
  for (const stop of stops) {
    const button = makeElement("button", "objective-button");
    button.type = "button";
    button.addEventListener("click", function () {
      progress.toggle(stop.id);
    });
    objectiveButtons[stop.id] = button;
    objectivesCard.appendChild(button);
  }
  tab.appendChild(objectivesCard);

  // Navigator: from the stop you are at to the next one.
  const navigator = makeElement("div", "card");
  const atLine = makeElement("p", "hud-at");
  const nextLine = makeElement("p", "hud-next");
  const compass = makeElement("div", "hud-compass");
  const arrow = makeElement("div", "hud-arrow", "▲");
  arrow.setAttribute("aria-hidden", "true");
  compass.appendChild(arrow);
  const bearingLine = makeElement("p", "hud-big");
  const facts = makeElement("div", "hud-facts");
  const buttons = makeElement("div", "hud-buttons");
  const previous = makeElement("button", "hud-button", "◀ PREV");
  previous.type = "button";
  const next = makeElement("button", "hud-button", "NEXT ▶");
  next.type = "button";
  buttons.appendChild(previous);
  buttons.appendChild(next);
  navigator.appendChild(makeElement("p", "dim", "NAVIGATOR · ◆ CALCULATED FROM POSITIONS"));
  for (const element of [atLine, nextLine, compass, bearingLine, facts, buttons]) {
    navigator.appendChild(element);
  }
  navigator.appendChild(makeElement("p", "note", "Bearing: degrees clockwise from map north. Distances: horizontal."));
  tab.appendChild(navigator);

  function routeText(route) {
    if (route === null) {
      return "no data";
    }
    return (route.distance_m / 1000).toFixed(2) + " km · steepest " + route.max_slope_deg.toFixed(1) + "°";
  }

  function showObjectives() {
    const done = progress.count();
    progressTitle.textContent = "OBJECTIVES · " + done + " OF " + stops.length + " STOPS REACHED";
    progressFill.style.width = (100 * done) / stops.length + "%";
    progressBar.setAttribute("aria-valuenow", String(done));
    for (const stop of stops) {
      const isReached = progress.has(stop.id);
      const question = questionFor(mission, stop.id);
      objectiveButtons[stop.id].textContent =
        (isReached ? "[x] " : "[ ] ") + stop.id + " · " + stop.label.toUpperCase() + (question === null ? "" : " — " + question);
      objectiveButtons[stop.id].setAttribute("aria-pressed", isReached ? "true" : "false");
    }
    document.getElementById("status-mission").textContent =
      "MISSION " + mission.name.toUpperCase() + " · " + done + "/" + stops.length;
  }

  function showNavigator() {
    const at = stops[atIndex];
    atLine.textContent = "AT STOP " + at.id + " · " + at.label.toUpperCase() + (progress.has(at.id) ? " · REACHED" : "");
    facts.textContent = "";
    if (atIndex === stops.length - 1) {
      nextLine.textContent = progress.count() === stops.length ? "ALL STOPS REACHED" : "LAST STOP";
      bearingLine.textContent = "—";
      compass.hidden = true;
      document.getElementById("strip-stop").textContent = "STOP " + at.id + " · LAST";
      document.getElementById("strip-bearing").textContent = "BRG —";
      document.getElementById("strip-distance").textContent = progress.count() + "/" + stops.length + " REACHED";
    } else {
      const target = stops[atIndex + 1];
      const bearing = bearingDegrees(manifest, at.position, target.position);
      const straight = groundDistance(manifest, at.position, target.position);
      let leg = null;
      for (const candidate of routes) {
        if (candidate.from === at.id && candidate.to === target.id) {
          leg = candidate;
        }
      }
      nextLine.textContent = "NEXT STOP " + target.id + " · " + target.label.toUpperCase();
      compass.hidden = false;
      arrow.style.transform = "rotate(" + bearing.toFixed(0) + "deg)";
      bearingLine.textContent = "BRG " + bearing.toFixed(0) + "° · " + (straight / 1000).toFixed(2) + " km";
      const rows = [["STRAIGHT LINE", (straight / 1000).toFixed(2) + " km"]];
      if (leg !== null) {
        rows.push(["SHORTEST ROUTE", routeText(leg.shortest)]);
        rows.push(["GENTLEST ROUTE", routeText(leg.gentlest)]);
      }
      facts.appendChild(factTable(["", ""], rows));
      document.getElementById("strip-stop").textContent = "STOP " + at.id + " → " + target.id;
      document.getElementById("strip-bearing").textContent = "BRG " + bearing.toFixed(0) + "°";
      document.getElementById("strip-distance").textContent = (straight / 1000).toFixed(2) + " km";
    }
    previous.disabled = atIndex === 0;
    next.disabled = atIndex === stops.length - 1;
  }

  function goPrevious() {
    atIndex = Math.max(0, atIndex - 1);
    showNavigator();
  }
  function goNext() {
    atIndex = Math.min(stops.length - 1, atIndex + 1);
    showNavigator();
  }
  previous.addEventListener("click", goPrevious);
  next.addEventListener("click", goNext);
  missionControls = { previous: goPrevious, next: goNext };
  // Marking a stop as reached means you are there: the navigator moves to it.
  progress.onChange(function (stopId) {
    if (progress.has(stopId)) {
      for (let index = 0; index < stops.length; index++) {
        if (stops[index].id === stopId) {
          atIndex = index;
        }
      }
    }
    showObjectives();
    showNavigator();
  });
  showObjectives();
  showNavigator();
}

// ---------------------------------------------------------------- wrist layout

function setUpWristLayout() {
  const toggle = document.getElementById("wrist-toggle");
  const narrowScreen = window.matchMedia("(max-width: " + (WRIST_MAX_WIDTH_PX - 1) + "px)");
  let chosen = null; // null = follow the screen width

  if (IS_EMBEDDED_WRIST) {
    chosen = true;
    document.body.classList.add("embedded");
  }

  function apply() {
    const isWrist = chosen === null ? narrowScreen.matches : chosen;
    document.body.classList.toggle("wrist", isWrist);
    toggle.setAttribute("aria-pressed", isWrist ? "true" : "false");
    toggle.textContent = isWrist ? "FULL VIEW" : "WRIST VIEW";
    if (theMap !== null) {
      setTimeout(function () {
        theMap.invalidateSize();
      }, 0);
    }
  }
  toggle.addEventListener("click", function () {
    chosen = !document.body.classList.contains("wrist");
    apply();
  });
  narrowScreen.addEventListener("change", apply);
  apply();
}

// ---------------------------------------------------------------- offline saving

function setOfflineStatus(text) {
  document.getElementById("status-offline").textContent = text;
}

function wait(milliseconds) {
  return new Promise(function (resolve) {
    setTimeout(resolve, milliseconds);
  });
}

// Save one file. The static host sometimes drops a request or answers 503 when
// thousands of files are asked for in a row, so a failed file is tried again
// after a growing pause before saving gives up.
async function saveOneFile(cache, path) {
  const url = packUrl(path);
  const saved = await cache.match(url);
  if (saved) {
    return;
  }
  let lastError = null;
  for (let attempt = 0; attempt < OFFLINE_MAX_ATTEMPTS; attempt += 1) {
    if (attempt > 0) {
      await wait(OFFLINE_RETRY_DELAY_MS * 2 ** (attempt - 1));
    }
    try {
      await cache.add(url);
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(path + " failed " + OFFLINE_MAX_ATTEMPTS + " times (" + lastError.message + "); reload to resume");
}

// Save the files of one stage in small batches. Files already saved are skipped.
async function saveStage(cache, paths, stageName) {
  let done = 0;
  for (let start = 0; start < paths.length; start += OFFLINE_BATCH_SIZE) {
    const batch = paths.slice(start, start + OFFLINE_BATCH_SIZE);
    await Promise.all(
      batch.map(function (path) {
        return saveOneFile(cache, path);
      })
    );
    done += batch.length;
    setOfflineStatus("SAVING " + stageName + " " + Math.floor((100 * done) / paths.length) + "%");
  }
}

async function saveForOffline() {
  if (!("serviceWorker" in navigator) || !("caches" in window)) {
    setOfflineStatus("OFFLINE NOT SUPPORTED IN THIS BROWSER");
    return;
  }
  try {
    await navigator.serviceWorker.register("sw.js");
    const offline = await loadJson("offline.json");
    const cache = await caches.open(DATA_CACHE);
    await saveStage(cache, offline.core, "CORE");
    await saveStage(cache, offline.route_detail, "ROUTE DETAIL");
    setOfflineStatus("● OFFLINE READY · DETAIL WITHIN " + offline.corridor_m + " M OF ROUTES");
  } catch (error) {
    setOfflineStatus("OFFLINE SAVING PAUSED: " + error.message);
  }
}

// ---------------------------------------------------------------- intro: from orbit to the walk area

function flyAndWait(map, action) {
  return new Promise(function (resolve) {
    map.once("moveend", function () {
      resolve();
    });
    action();
  });
}

async function introFlight(map, manifest) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const walkBounds = L.latLngBounds(gridToLatLng(0, manifest.grid.height), gridToLatLng(manifest.grid.width, 0));
  let hasContext = false;
  for (const layer of manifest.layers) {
    if (layer.context) {
      hasContext = true;
    }
  }
  if (reduceMotion || !hasContext || IS_EMBEDDED_WRIST) {
    return;
  }
  const centre = siteCentre(manifest);
  let skipped = false;
  function skip() {
    skipped = true;
  }
  map.getContainer().addEventListener("pointerdown", skip, { once: true });
  window.addEventListener("keydown", skip, { once: true });

  const pulse = L.circleMarker(centre, { radius: 14, className: "site-pulse", interactive: false }).addTo(map);
  map.setView(centre, -15, { animate: false });
  await new Promise(function (resolve) {
    setTimeout(resolve, 1200);
  });
  const legs = [
    function () {
      map.flyTo(centre, -12, { duration: 2.2 });
    },
    function () {
      map.flyTo(centre, -9, { duration: 2.0 });
    },
    function () {
      map.flyToBounds(walkBounds, { duration: 2.4 });
    },
  ];
  for (const leg of legs) {
    if (skipped) {
      break;
    }
    await flyAndWait(map, leg);
  }
  map.removeLayer(pulse);
  if (skipped) {
    map.fitBounds(walkBounds, { animate: false });
  }
  // The walk area lights up and fades; the routes flash on.
  const glow = L.rectangle(walkBounds, { className: "walk-glow", interactive: false, fill: false }).addTo(map);
  map.getContainer().classList.add("intro-flash");
  setTimeout(function () {
    map.removeLayer(glow);
    map.getContainer().classList.remove("intro-flash");
  }, 4000);
}

// ---------------------------------------------------------------- start

// ---------------------------------------------------------------- boot screen and missions

// Accept only pack folders of the form "data/<name>/" from the missions index.
function safePackBase(pack) {
  if (typeof pack !== "string" || !/^data\/[A-Za-z0-9_-]+\/$/.test(pack)) {
    throw new Error("Refused a mission pack path: " + String(pack));
  }
  return pack;
}

async function loadMissionsIndex() {
  const response = await fetch(MISSIONS_INDEX_URL);
  if (!response.ok) {
    throw new Error("Could not load the mission list (" + response.status + ")");
  }
  const missions = await response.json();
  if (!Array.isArray(missions)) {
    throw new Error("The mission list must be a list");
  }
  return missions;
}

function missionCard(entry, onStart) {
  const card = makeElement("div", "card boot-mission");
  card.appendChild(makeElement("p", "dim", "[" + entry.status + "] · " + entry.site.toUpperCase() + " · " + entry.stop_count + " STOPS · PACK v" + entry.pack_version));
  card.appendChild(makeElement("h2", "card-title", entry.name.toUpperCase()));
  const button = makeElement("button", "hud-button boot-start", "START MISSION ▶");
  button.type = "button";
  button.addEventListener("click", function () {
    onStart(entry);
  });
  card.appendChild(button);
  return card;
}

// Lines appear one after another; any key, click or tap shows them all at once.
function playBootLines(boot) {
  const lines = boot.querySelectorAll(".boot-line, .boot-missions");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  lines.forEach(function (line, index) {
    line.style.animationDelay = reduceMotion ? "0s" : index * 0.35 + "s";
  });
  function showAll() {
    boot.classList.add("boot-skip");
  }
  boot.addEventListener("click", showAll, { once: true });
  document.addEventListener("keydown", showAll, { once: true });
}

// Orbit view: the globe turns to the chosen site, then the screen dives into it.
async function descend(boot, globe, entry) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (globe !== null && Array.isArray(entry.centre_lonlat)) {
    document.getElementById("globe-caption").textContent =
      "DESCENDING TO " + entry.site.toUpperCase() + " · " + entry.centre_lonlat[1].toFixed(2) + "° N, " + entry.centre_lonlat[0].toFixed(2) + "° E";
    await globe.focus(entry.centre_lonlat[0], entry.centre_lonlat[1], DESCENT_MS);
  }
  if (!reduceMotion) {
    boot.classList.add("diving");
    await new Promise(function (resolve) {
      setTimeout(resolve, DIVE_MS);
    });
  }
  boot.hidden = true;
}

function startGlobe(missions) {
  const sites = [];
  for (const entry of missions) {
    if (Array.isArray(entry.centre_lonlat)) {
      sites.push({ lon: entry.centre_lonlat[0], lat: entry.centre_lonlat[1], label: entry.site.toUpperCase() });
    }
  }
  return NavasaGlobe.create(document.getElementById("globe"), GLOBE_IMAGE_URL, sites).catch(function (error) {
    document.getElementById("globe-caption").textContent = "ORBIT VIEW UNAVAILABLE: " + error.message;
    return null;
  });
}

function showBoot() {
  return new Promise(function (resolve) {
    const boot = document.getElementById("boot");
    boot.hidden = false;
    playBootLines(boot);
    const list = document.getElementById("boot-missions");
    const indexLine = document.getElementById("boot-index-line");
    loadMissionsIndex()
      .then(async function (missions) {
        indexLine.textContent = "> LOADING MISSION INDEX ... OK · " + missions.length + (missions.length === 1 ? " MISSION" : " MISSIONS");
        const globePromise = startGlobe(missions);
        for (const entry of missions) {
          list.appendChild(
            missionCard(entry, async function (chosen) {
              const globe = await globePromise;
              await descend(boot, globe, chosen);
              resolve(chosen);
            })
          );
        }
        if (missions.length === 0) {
          list.appendChild(makeElement("p", "", "No missions are built yet."));
        }
      })
      .catch(function (error) {
        indexLine.textContent = "> LOADING MISSION INDEX ... FAILED: " + error.message;
      });
  });
}

async function chooseMission() {
  // A mission named in the address (#mission=<id>) starts directly, e.g. after a reload.
  const match = window.location.hash.match(/^#mission=([A-Za-z0-9_-]+)$/);
  if (match) {
    const missions = await loadMissionsIndex();
    for (const entry of missions) {
      if (entry.id === match[1]) {
        return entry;
      }
    }
  }
  return showBoot();
}

async function launchMission(entry) {
  packBase = safePackBase(entry.pack);
  const manifest = await loadJson("manifest.json");
  checkManifest(manifest);
  const mission = await loadJson("mission.json");
  const stops = await loadJson("stops.json");
  const routes = await loadJson("routes.json");
  const progress = createProgress(mission.id, stops);

  fillStatusBar(manifest);
  const created = createMap(manifest);
  theMap = created.map;
  addPackLayers(created.map, created.bounds, manifest);
  addRoutes(created.map, routes);
  addStops(created.map, stops);
  addTerrainToggle(created.map, manifest, stops, routes);
  if (IS_EMBEDDED_WRIST && window.parent !== window) {
    window.parent.postMessage(layerDialMessage(), window.location.origin); // the wrist selector's positions
  }
  fillRouteTab(created.map, manifest, stops, routes);
  fillStopsTab(stops, mission, progress);
  fillDataTab(manifest);
  setUpMissionTab(created.map, manifest, mission, stops, routes, progress);
  openTab("hud");
  introFlight(created.map, manifest);
  await setUpReadout(created.map, manifest);
  await setUpSunTab(created.map, manifest, routes);
  await setUpLineOfSight(created.map, manifest, stops);
  setUpGravityCard(manifest, routes);
  setUpHealthCard(manifest);
  saveForOffline(); // runs in the background after the app is ready
}

// Commands from the wrist device page. Only messages from this same site are accepted.
const DEVICE_TABS = ["map", "route", "stops", "sun", "data", "hud"];

function setUpDeviceCommands() {
  window.addEventListener("message", function (event) {
    if (event.origin !== window.location.origin || typeof event.data !== "object" || event.data === null) {
      return;
    }
    const command = event.data;
    if (command.type === "navasa:tab" && DEVICE_TABS.includes(command.tab)) {
      openTab(command.tab);
    } else if (command.type === "navasa:layer" && layerDial !== null) {
      if (command.direction === "next" || command.direction === "previous") {
        openTab("map"); // the map is hidden on other wrist tabs, so show it first
        stepLayerDial(command.direction);
        // Tell the wrist page which position is on, so the selector can point at it.
        event.source.postMessage(layerDialMessage(), window.location.origin);
      }
    } else if (command.type === "navasa:stop" && missionControls !== null) {
      if (command.direction === "next") {
        missionControls.next();
      } else if (command.direction === "previous") {
        missionControls.previous();
      }
    }
  });
}

async function start() {
  setUpTabs();
  setUpWristLayout();
  setUpDeviceCommands();
  document.getElementById("missions-button").addEventListener("click", function () {
    window.location.hash = "";
    window.location.reload();
  });
  try {
    const entry = await chooseMission();
    window.location.hash = "mission=" + entry.id;
    await launchMission(entry);
  } catch (error) {
    showError("NAVASA could not start: " + error.message);
  }
}

document.addEventListener("DOMContentLoaded", start);
