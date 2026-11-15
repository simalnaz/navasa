// Radio line of sight: astronaut <-> astronaut and astronaut <-> habitat, over the terrain.
//
// Geometric line of sight: the straight line between the two antenna tips must stay above
// the terrain. Terrain heights from the elevation readout (NASA DATA, sampled every 4 m),
// lifted by Mars curvature d * (D - d) / (2 R) at distance d along a line of length D.
// Antenna heights are the user's own values (typed on screen, empty until then).
// Not included: Fresnel zone, diffraction, refraction, radio power and range.

"use strict";

const LineOfSight = (function () {
  const MARS_RADIUS_M = 3396190; // radius of the DTM's map projection (Mars 2000 sphere, IAU)

  // heights: terrain heights (m) at equal steps along the line, first = A, last = B (null = no data).
  // Returns {clear: true|false|null, firstBlock: index|null, minClearance: m|null, missing: count}.
  function check(heights, lengthM, antennaA, antennaB, radiusM) {
    const radius = radiusM || MARS_RADIUS_M;
    const last = heights.length - 1;
    if (last < 1 || heights[0] === null || heights[last] === null) {
      return { clear: null, firstBlock: null, minClearance: null, missing: heights.length };
    }
    const tipA = heights[0] + antennaA;
    const tipB = heights[last] + antennaB;
    let firstBlock = null;
    let minClearance = null;
    let missing = 0;
    for (let index = 1; index < last; index++) {
      if (heights[index] === null) {
        missing += 1;
        continue;
      }
      const d = (index / last) * lengthM;
      const lineHeight = tipA + (tipB - tipA) * (index / last);
      const bulge = (d * (lengthM - d)) / (2 * radius);
      const clearance = lineHeight - (heights[index] + bulge);
      if (minClearance === null || clearance < minClearance) {
        minClearance = clearance;
      }
      if (clearance < 0 && firstBlock === null) {
        firstBlock = index;
      }
    }
    let clear = firstBlock === null;
    if (clear && missing > 0) {
      clear = null; // nothing blocks where there is data, but part of the line has none
    }
    return { clear: clear, firstBlock: firstBlock, minClearance: minClearance, missing: missing };
  }

  // Sample points [col, row] from a to b (grid), about every stepM ground metres.
  function samplePoints(a, b, eastScale, metresPerPixel, stepM) {
    const lengthM = Math.hypot((b[0] - a[0]) * eastScale, b[1] - a[1]) * metresPerPixel;
    const count = Math.max(1, Math.ceil(lengthM / stepM));
    const points = [];
    for (let index = 0; index <= count; index++) {
      const t = index / count;
      points.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
    return { points: points, lengthM: lengthM };
  }

  // Antenna height typed by the user: a number of metres >= 0, or null when empty or not valid.
  function parseAntenna(text) {
    const trimmed = String(text).trim().replace(",", ".");
    if (trimmed === "") {
      return null;
    }
    const value = Number(trimmed);
    return Number.isFinite(value) && value >= 0 && value <= 1000 ? value : null;
  }

  return { check: check, samplePoints: samplePoints, parseAntenna: parseAntenna, MARS_RADIUS_M: MARS_RADIUS_M };
})();

if (typeof module !== "undefined") {
  module.exports = LineOfSight;
}

// ---------------------------------------------------------------- browser: card and map tools
// Uses app.js helpers (makeElement, factTable, gridToLatLng, loadReadout, readValue, eastScaleOf).

const LOS_SAMPLE_STEP_M = 4; // the elevation readout's sample spacing

async function setUpLineOfSight(map, manifest, stops) {
  const elevationInfo = (manifest.readouts || []).find(function (readout) {
    return readout.id === "elevation";
  });
  if (elevationInfo === undefined) {
    return; // no heights in this pack
  }
  const elevation = await loadReadout(elevationInfo);
  const eastScale = eastScaleOf(manifest);
  const metresPerPixel = manifest.grid.metres_per_pixel;
  const habitat = manifest.habitat || null;

  const tab = document.getElementById("tab-map");
  tab.appendChild(makeElement("h2", "section-title", "> RADIO LINE OF SIGHT · ◆ CALCULATED"));
  const card = makeElement("div", "card");
  tab.appendChild(card);

  card.appendChild(makeElement("h3", "card-title", "ANTENNA HEIGHTS · YOUR VALUES"));
  const inputs = {};
  const inputRow = makeElement("div", "antenna-inputs");
  const who = [
    ["a", "ASTRONAUT A"],
    ["b", "ASTRONAUT B"],
  ];
  if (habitat !== null) {
    who.push(["habitat", "HABITAT"]);
  }
  for (const [key, label] of who) {
    const field = makeElement("label", "antenna-field");
    field.appendChild(makeElement("span", "", label + " (m above ground)"));
    const input = document.createElement("input");
    input.type = "text";
    input.inputMode = "decimal";
    input.className = "message-input";
    input.placeholder = "type m";
    input.autocomplete = "off";
    field.appendChild(input);
    inputRow.appendChild(field);
    inputs[key] = input;
  }
  card.appendChild(inputRow);

  const placeRow = makeElement("div", "button-row");
  const placeA = makeElement("button", "text-button", "PLACE A ON MAP");
  const placeB = makeElement("button", "text-button", "PLACE B ON MAP");
  const clearButton = makeElement("button", "text-button", "CLEAR");
  for (const button of [placeA, placeB, clearButton]) {
    button.type = "button";
    placeRow.appendChild(button);
  }
  card.appendChild(placeRow);
  const stopRow = makeElement("div", "button-row");
  for (const stop of stops) {
    for (const key of ["a", "b"]) {
      const button = makeElement("button", "text-button", key.toUpperCase() + " AT STOP " + stop.id);
      button.type = "button";
      button.addEventListener("click", function () {
        place(key, stop.position.slice());
      });
      stopRow.appendChild(button);
    }
  }
  card.appendChild(stopRow);

  const prompt = makeElement("p", "dim", "Type the antenna heights, then place A and B (tap the map or pick a stop).");
  prompt.setAttribute("aria-live", "polite");
  card.appendChild(prompt);
  const resultHolder = makeElement("div");
  card.appendChild(resultHolder);
  card.appendChild(
    makeElement(
      "p",
      "note",
      "Geometric line of sight between the antenna tips: blocked where the terrain (elevation readout, every 4 m, NASA DATA) " +
        "plus Mars curvature d(D−d)/2R rises above the straight line. Antenna heights are your values. " +
        "Not included: Fresnel zone, diffraction, refraction, radio power and range, objects smaller than the 4 m samples." +
        (habitat !== null ? " Habitat position: " + habitat.label + " — " + habitat.source + "." : "")
    )
  );

  const group = L.layerGroup().addTo(map);
  const markers = { a: null, b: null };
  const positions = { a: null, b: null };
  let placing = null;

  if (habitat !== null) {
    const icon = L.divIcon({ html: makeElement("div", "los-marker habitat", "H"), className: "", iconSize: [28, 28], iconAnchor: [14, 14] });
    L.marker(gridToLatLng(habitat.position[0], habitat.position[1]), { icon: icon, title: habitat.label })
      .bindTooltip("HABITAT · " + habitat.label.toUpperCase(), { className: "stop-tooltip", direction: "top", offset: [0, -14] })
      .addTo(map);
  }

  function heightAt(point) {
    if (point[0] < 0 || point[1] < 0 || point[0] >= manifest.grid.width || point[1] >= manifest.grid.height) {
      return null;
    }
    return readValue(elevation, point[0], point[1]);
  }

  function place(key, position) {
    positions[key] = position;
    if (markers[key] !== null) {
      map.removeLayer(markers[key]);
    }
    const icon = L.divIcon({ html: makeElement("div", "los-marker", key.toUpperCase()), className: "", iconSize: [28, 28], iconAnchor: [14, 14] });
    markers[key] = L.marker(gridToLatLng(position[0], position[1]), { icon: icon, title: "Astronaut " + key.toUpperCase() }).addTo(map);
    placing = null;
    map.getContainer().classList.remove("placing");
    update();
  }

  function startPlacing(key) {
    placing = key;
    map.getContainer().classList.add("placing");
    prompt.textContent = "Tap the map to place astronaut " + key.toUpperCase() + ".";
  }

  placeA.addEventListener("click", function () {
    startPlacing("a");
  });
  placeB.addEventListener("click", function () {
    startPlacing("b");
  });
  clearButton.addEventListener("click", function () {
    for (const key of ["a", "b"]) {
      if (markers[key] !== null) {
        map.removeLayer(markers[key]);
      }
      markers[key] = null;
      positions[key] = null;
    }
    update();
  });
  map.on("click", function (event) {
    if (placing === null) {
      return;
    }
    place(placing, [event.latlng.lng, -event.latlng.lat]);
  });
  for (const input of Object.values(inputs)) {
    input.addEventListener("input", update);
  }

  function link(name, from, to, antennaFrom, antennaTo) {
    const sampled = LineOfSight.samplePoints(from, to, eastScale, metresPerPixel, LOS_SAMPLE_STEP_M);
    const heights = sampled.points.map(heightAt);
    const result = LineOfSight.check(heights, sampled.lengthM, antennaFrom, antennaTo);
    const fromLatLng = gridToLatLng(from[0], from[1]);
    const toLatLng = gridToLatLng(to[0], to[1]);
    let verdict;
    if (result.clear === true) {
      verdict = "CLEAR";
      L.polyline([fromLatLng, toLatLng], { className: "los-line clear", weight: 3, interactive: false }).addTo(group);
    } else if (result.clear === false) {
      verdict = "BLOCKED";
      const block = sampled.points[result.firstBlock];
      const blockLatLng = gridToLatLng(block[0], block[1]);
      L.polyline([fromLatLng, blockLatLng], { className: "los-line clear", weight: 3, interactive: false }).addTo(group);
      L.polyline([blockLatLng, toLatLng], { className: "los-line blocked", weight: 3, dashArray: "6 6", interactive: false }).addTo(group);
      L.circleMarker(blockLatLng, { radius: 7, className: "los-block", weight: 2, interactive: false }).addTo(group);
    } else {
      verdict = "NO DATA ON PART OF THE LINE";
      L.polyline([fromLatLng, toLatLng], { className: "los-line blocked", weight: 2, dashArray: "2 6", interactive: false }).addTo(group);
    }
    const blockText =
      result.firstBlock === null ? "—" : ((result.firstBlock / (sampled.points.length - 1)) * sampled.lengthM).toFixed(0) + " m from the first end";
    return [
      name,
      verdict,
      (sampled.lengthM / 1000).toFixed(2) + " km",
      result.minClearance === null ? "—" : result.minClearance.toFixed(1) + " m",
      blockText,
    ];
  }

  function update() {
    group.clearLayers();
    const antenna = {};
    for (const key of Object.keys(inputs)) {
      antenna[key] = LineOfSight.parseAntenna(inputs[key].value);
      inputs[key].classList.toggle("invalid", inputs[key].value.trim() !== "" && antenna[key] === null);
    }
    const rows = [];
    const needs = [];
    if (positions.a !== null && positions.b !== null) {
      if (antenna.a !== null && antenna.b !== null) {
        rows.push(link("A ↔ B", positions.a, positions.b, antenna.a, antenna.b));
      } else {
        needs.push("antenna heights for A and B");
      }
    }
    if (habitat !== null) {
      for (const key of ["a", "b"]) {
        if (positions[key] === null) {
          continue;
        }
        if (antenna[key] !== null && antenna.habitat !== null) {
          rows.push(link(key.toUpperCase() + " ↔ HABITAT", positions[key], habitat.position, antenna[key], antenna.habitat));
        } else {
          needs.push("antenna heights for " + key.toUpperCase() + " and the habitat");
        }
      }
    }
    resultHolder.replaceChildren();
    if (rows.length > 0) {
      resultHolder.appendChild(factTable(["LINK", "LINE OF SIGHT", "DISTANCE", "LEAST CLEARANCE", "FIRST BLOCK"], rows));
    }
    if (placing === null) {
      if (positions.a === null && positions.b === null) {
        prompt.textContent = "Type the antenna heights, then place A and B (tap the map or pick a stop).";
      } else if (needs.length > 0) {
        prompt.textContent = "Waiting for your values: " + needs.join("; ") + " (metres, 0–1000).";
      } else {
        prompt.textContent = "";
      }
    }
  }
  update();
}
