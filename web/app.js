// NAVASA web app: reads the data pack and shows it on a Leaflet map.
//
// Positions in the pack are grid pixels [col, row], counted from the top-left
// corner; one grid pixel is metres_per_pixel metres. Leaflet's flat map mode
// (CRS.Simple) counts upwards, so grid [col, row] is Leaflet position [-row, col].
// At zoom z one grid pixel is 2^z screen pixels, the same rule the tiles were cut with.
//
// Every text from the pack is shown with textContent, never as HTML.

"use strict";

const PACK_URL = "data/jezero_v1/";
const MAP_MAX_ZOOM = 3;

const LABEL_MARK = { "NASA DATA": "■", CALCULATED: "◆" };
const DATA_CACHE = "navasa-data-jezero_v1"; // same name as in sw.js
const OFFLINE_BATCH_SIZE = 6; // files saved at the same time, so saving never floods the network
const WRIST_MAX_WIDTH_PX = 600; // narrower screens use the wrist layout

let theMap = null;

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
  return PACK_URL + path;
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

function createMap(manifest) {
  const width = manifest.grid.width;
  const height = manifest.grid.height;
  const bounds = L.latLngBounds(gridToLatLng(0, height), gridToLatLng(width, 0));

  let minZoom = 0;
  for (const layer of manifest.layers) {
    if (layer.tiles) {
      minZoom = Math.min(minZoom, layer.tiles.min_zoom);
    }
  }

  const map = L.map("map", {
    crs: L.CRS.Simple,
    minZoom: minZoom,
    maxZoom: MAP_MAX_ZOOM,
    maxBounds: bounds.pad(0.25),
    attributionControl: false,
  });
  map.fitBounds(bounds);

  // The scale bar measures in grid pixels, so it is only right for a 1 m grid.
  if (manifest.grid.metres_per_pixel === 1) {
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
  }
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
}

function addPackLayers(map, bounds, manifest) {
  for (const layer of manifest.layers) {
    if (!layer.tiles) {
      continue;
    }
    const tag = (LABEL_MARK[layer.label] || "") + " " + layer.label + " · " + (layer.as_of !== null ? layer.as_of : "no date");
    let legend = null;
    if (layer.id === "slope") {
      legend = slopeLegend(layer.legend);
    } else if (layer.id === "geology") {
      legend = geologyLegend(layer.legend);
    }
    const name = LAYER_NAMES[layer.id] || layer.id.toUpperCase();
    addLayerButton(map, name, tag, makeTileLayer(layer, bounds), legend, layer.kind === "imagery");
  }
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
      const line = L.polyline(points, styles[kind]);
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
      "Value of the nearest 1 m cell, sampled every " + every + " m. Elevation: NASA DATA. Slope: CALCULATED.";
  }

  const elevationCell = document.getElementById("readout-elevation");
  const slopeCell = document.getElementById("readout-slope");
  const unitCell = document.getElementById("readout-unit");

  function clear() {
    elevationCell.textContent = "—";
    slopeCell.textContent = "—";
    unitCell.textContent = "—";
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

// ---------------------------------------------------------------- STOPS tab

function fillStopsTab(stops) {
  const tab = document.getElementById("tab-stops");
  tab.appendChild(makeElement("h2", "section-title", "> STOPS"));
  for (const stop of stops) {
    const card = makeElement("div", "card stop-card");
    card.id = "stop-card-" + stop.id;
    card.appendChild(makeElement("h3", "card-title", "STOP " + stop.id + " · " + stop.label.toUpperCase()));
    card.appendChild(makeElement("p", "dim", "Position: " + stop.position_source + "."));

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
  "Terrain cells are 1 m: rocks and obstacles smaller than about 1 m are not in the terrain data.",
  "Slope depends on cell size: these values are slopes over 1 m.",
  "Cursor readout uses values sampled every 4 m; stop cards and routes use every 1 m cell.",
  "Stop positions are where the rover was on that sol, not the exact spot each photo shows.",
  "Current surface conditions (weather, dust) are not included.",
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
  tab.appendChild(photosCard);

  const limitsCard = makeElement("div", "card");
  limitsCard.appendChild(makeElement("h3", "card-title", "KNOWN LIMITS"));
  for (const limit of KNOWN_LIMITS) {
    limitsCard.appendChild(makeElement("p", "note", "· " + limit));
  }
  tab.appendChild(limitsCard);
}

// ---------------------------------------------------------------- HUD (next stop, bearing, distance)

// Bearing in degrees clockwise from map north (up). Rows grow downwards, so north is -row.
function bearingDegrees(from, to) {
  const east = to[0] - from[0];
  const north = from[1] - to[1];
  return (Math.atan2(east, north) * 180 / Math.PI + 360) % 360;
}

function setUpHud(map, manifest, stops, routes) {
  const tab = document.getElementById("tab-hud");
  const metresPerPixel = manifest.grid.metres_per_pixel;
  let atIndex = 0;

  const title = makeElement("h2", "section-title", "> HUD · ◆ CALCULATED FROM POSITIONS");
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
  for (const element of [title, atLine, nextLine, compass, bearingLine, facts, buttons]) {
    tab.appendChild(element);
  }
  tab.appendChild(makeElement("p", "note", "Bearing: degrees clockwise from map north. Distances: horizontal."));

  function routeText(route) {
    if (route === null) {
      return "no data";
    }
    return (route.distance_m / 1000).toFixed(2) + " km · steepest " + route.max_slope_deg.toFixed(1) + "°";
  }

  function show() {
    const at = stops[atIndex];
    atLine.textContent = "AT STOP " + at.id + " · " + at.label.toUpperCase();
    facts.textContent = "";
    if (atIndex === stops.length - 1) {
      nextLine.textContent = "LAST STOP";
      bearingLine.textContent = "—";
      compass.hidden = true;
      document.getElementById("strip-stop").textContent = "STOP " + at.id + " · LAST";
      document.getElementById("strip-bearing").textContent = "BRG —";
      document.getElementById("strip-distance").textContent = "— km";
    } else {
      const target = stops[atIndex + 1];
      const bearing = bearingDegrees(at.position, target.position);
      const straight = Math.hypot(target.position[0] - at.position[0], target.position[1] - at.position[1]) * metresPerPixel;
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

  previous.addEventListener("click", function () {
    atIndex = Math.max(0, atIndex - 1);
    show();
  });
  next.addEventListener("click", function () {
    atIndex = Math.min(stops.length - 1, atIndex + 1);
    show();
  });
  show();
}

// ---------------------------------------------------------------- wrist layout

function setUpWristLayout() {
  const toggle = document.getElementById("wrist-toggle");
  const narrowScreen = window.matchMedia("(max-width: " + (WRIST_MAX_WIDTH_PX - 1) + "px)");
  let chosen = null; // null = follow the screen width

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

// Save the files of one stage in small batches. Files already saved are skipped.
async function saveStage(cache, paths, stageName) {
  let done = 0;
  for (let start = 0; start < paths.length; start += OFFLINE_BATCH_SIZE) {
    const batch = paths.slice(start, start + OFFLINE_BATCH_SIZE);
    await Promise.all(
      batch.map(async function (path) {
        const url = packUrl(path);
        const saved = await cache.match(url);
        if (!saved) {
          await cache.add(url);
        }
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

// ---------------------------------------------------------------- start

async function start() {
  setUpTabs();
  setUpWristLayout();
  try {
    const manifest = await loadJson("manifest.json");
    checkManifest(manifest);
    const stops = await loadJson("stops.json");
    const routes = await loadJson("routes.json");

    fillStatusBar(manifest);
    const created = createMap(manifest);
    theMap = created.map;
    addPackLayers(created.map, created.bounds, manifest);
    addRoutes(created.map, routes);
    addStops(created.map, stops);
    fillRouteTab(created.map, manifest, stops, routes);
    fillStopsTab(stops);
    fillDataTab(manifest);
    setUpHud(created.map, manifest, stops, routes);
    openTab("map");
    await setUpReadout(created.map, manifest);
    saveForOffline(); // runs in the background after the app is ready
  } catch (error) {
    showError("NAVASA could not start: " + error.message);
  }
}

document.addEventListener("DOMContentLoaded", start);
