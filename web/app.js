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

function setUpTabs() {
  const buttons = document.querySelectorAll(".tabs button");
  for (const button of buttons) {
    button.addEventListener("click", function () {
      for (const other of buttons) {
        const isThis = other === button;
        other.setAttribute("aria-selected", isThis ? "true" : "false");
        document.getElementById("tab-" + other.dataset.tab).hidden = !isThis;
      }
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

async function setUpReadout(map, manifest) {
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

  map.on("mousemove", function (event) {
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
  });
  map.on("mouseout", clear);
}

// ---------------------------------------------------------------- start

async function start() {
  setUpTabs();
  try {
    const manifest = await loadJson("manifest.json");
    checkManifest(manifest);
    const stops = await loadJson("stops.json");
    const routes = await loadJson("routes.json");

    fillStatusBar(manifest);
    const created = createMap(manifest);
    addPackLayers(created.map, created.bounds, manifest);
    addRoutes(created.map, routes);
    addStops(created.map, stops);
    await setUpReadout(created.map, manifest);
  } catch (error) {
    showError("NAVASA could not start: " + error.message);
  }
}

document.addEventListener("DOMContentLoaded", start);
