// Mission editor (MISSION tab): create, edit, delete, export and import missions for this site.
//
// - Your missions are kept on this device (browser storage) and can be exported as a mission file
//   in the same format as data/missions/<mission>.json; `python -m pipeline.run_mission <file>`
//   then builds a full data pack (shortest and gentlest routes, geology, photos) from it.
// - The built-in mission is read-only: DUPLICATE makes an editable copy.
// - Facts the browser can give for your stops and legs come from the pack's readouts
//   (elevation, slope, rock unit, sampled every 4 m) along STRAIGHT lines between stops;
//   routes are only made by the pipeline.

"use strict";

const MissionEditor = (function () {
  const STATUSES = ["ACTIVE", "PLANNED", "COMPLETE"];
  const USER_SOURCE_TEXT = "Set by you in the NAVASA mission editor";
  const USER_POSITION_SOURCE = "Placed on the map in the NAVASA mission editor (set by you)";
  const MAX_TEXT = 500;
  const MAX_STOPS = 50;

  function slug(text) {
    const cleaned = String(text)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40);
    return cleaned === "" ? "mission" : cleaned;
  }

  // New mission id: slug of the name + 6 random hex digits (no collisions between devices).
  function newMissionId(name, randomHex) {
    return slug(name) + "-" + randomHex.slice(0, 6);
  }

  // Equirectangular grid: lon/lat <-> grid [col, row] are straight lines.
  function gridFromLonLat(bounds, grid, lon, lat) {
    return [((lon - bounds[0]) / (bounds[2] - bounds[0])) * grid.width, ((bounds[3] - lat) / (bounds[3] - bounds[1])) * grid.height];
  }

  function lonLatFromGrid(bounds, grid, col, row) {
    return [bounds[0] + (col / grid.width) * (bounds[2] - bounds[0]), bounds[3] - (row / grid.height) * (bounds[3] - bounds[1])];
  }

  function isText(value) {
    return typeof value === "string" && value.trim() !== "" && value.length <= MAX_TEXT;
  }

  // Problems with a mission (empty list = usable). siteName and bounds: this pack's site.
  function check(mission, siteName, bounds) {
    const problems = [];
    if (typeof mission !== "object" || mission === null || Array.isArray(mission)) {
      return ["not a mission (must be a JSON object)"];
    }
    for (const field of ["id", "name", "objective"]) {
      if (!isText(mission[field])) {
        problems.push(field + " must be text (1-" + MAX_TEXT + " characters)");
      }
    }
    if (isText(mission.id) && !/^[a-z0-9][a-z0-9-]{0,60}$/.test(mission.id)) {
      problems.push("id may only use a-z, 0-9 and -");
    }
    if (!STATUSES.includes(mission.status)) {
      problems.push("status must be one of " + STATUSES.join(", "));
    }
    if (!Array.isArray(mission.objective_sources) || mission.objective_sources.length === 0) {
      problems.push("objective_sources must list at least one source");
    } else {
      mission.objective_sources.forEach(function (source, index) {
        if (typeof source !== "object" || source === null || !isText(source.text)) {
          problems.push("objective source " + (index + 1) + " needs text");
        } else if (source.url !== undefined && source.url !== null && !/^https:\/\/[^\s]+$/.test(source.url)) {
          problems.push("objective source " + (index + 1) + ": url must start with https://");
        }
      });
    }
    const siteNameOfMission = typeof mission.site === "object" && mission.site !== null ? mission.site.name : mission.site;
    if (siteNameOfMission !== siteName) {
      problems.push("this mission is for another site (" + String(siteNameOfMission) + "), not " + siteName);
    }
    if (!Array.isArray(mission.stops) || mission.stops.length === 0) {
      problems.push("needs at least one stop");
      return problems;
    }
    if (mission.stops.length > MAX_STOPS) {
      problems.push("at most " + MAX_STOPS + " stops");
    }
    const ids = new Set();
    mission.stops.forEach(function (stop, index) {
      const where = "stop " + (index + 1);
      if (typeof stop !== "object" || stop === null) {
        problems.push(where + " must be an object");
        return;
      }
      if (!Number.isInteger(stop.id) || ids.has(stop.id)) {
        problems.push(where + ": id must be a whole number, different for every stop");
      }
      ids.add(stop.id);
      for (const field of ["label", "question", "position_source"]) {
        if (!isText(stop[field])) {
          problems.push(where + ": " + field + " must be text");
        }
      }
      if (typeof stop.lat !== "number" || typeof stop.lon !== "number" || !Number.isFinite(stop.lat) || !Number.isFinite(stop.lon)) {
        problems.push(where + ": lat and lon must be numbers");
      } else if (stop.lon < bounds[0] || stop.lon > bounds[2] || stop.lat < bounds[1] || stop.lat > bounds[3]) {
        problems.push(where + ": outside this site's walk area");
      }
      if (stop.photos !== undefined && !Array.isArray(stop.photos)) {
        problems.push(where + ": photos must be a list");
      }
    });
    return problems;
  }

  // Mission file for the pipeline: the site block comes from this pack (site_template).
  function toMissionFile(mission, siteTemplate) {
    return {
      id: mission.id,
      name: mission.name,
      status: mission.status,
      objective: mission.objective,
      objective_sources: mission.objective_sources,
      pack_id: mission.id.replace(/-/g, "_") + "_v1",
      pack_version: "1.0.0",
      site: siteTemplate,
      stops: mission.stops.map(function (stop) {
        return {
          id: stop.id,
          label: stop.label,
          lat: stop.lat,
          lon: stop.lon,
          position_source: stop.position_source,
          question: stop.question,
          photos: Array.isArray(stop.photos) ? stop.photos : [],
        };
      }),
    };
  }

  // Facts along a straight line from samples (heights and slopes may hold null = no data).
  function lineFacts(heights, slopes) {
    let climb = 0;
    let descent = 0;
    let missing = 0;
    let previous = null;
    for (const height of heights) {
      if (height === null) {
        missing += 1;
        continue;
      }
      if (previous !== null) {
        if (height > previous) {
          climb += height - previous;
        } else {
          descent += previous - height;
        }
      }
      previous = height;
    }
    let steepest = null;
    for (let index = 1; index < slopes.length - 1; index++) {
      if (slopes[index] !== null && (steepest === null || slopes[index] > steepest)) {
        steepest = slopes[index];
      }
    }
    return { climb: climb, descent: descent, steepest: steepest, missing: missing };
  }

  // Sources typed one per line: "text" or "text | https://...".
  function parseSources(text) {
    const sources = [];
    for (const line of String(text).split("\n")) {
      const trimmed = line.trim();
      if (trimmed === "") {
        continue;
      }
      const parts = trimmed.split("|");
      const source = { text: parts[0].trim() };
      if (parts.length > 1 && parts[1].trim() !== "") {
        source.url = parts[1].trim();
      }
      sources.push(source);
    }
    return sources;
  }

  function sourcesText(sources) {
    return (sources || [])
      .map(function (source) {
        return source.url ? source.text + " | " + source.url : source.text;
      })
      .join("\n");
  }

  return {
    STATUSES: STATUSES,
    USER_SOURCE_TEXT: USER_SOURCE_TEXT,
    USER_POSITION_SOURCE: USER_POSITION_SOURCE,
    slug: slug,
    newMissionId: newMissionId,
    gridFromLonLat: gridFromLonLat,
    lonLatFromGrid: lonLatFromGrid,
    check: check,
    toMissionFile: toMissionFile,
    lineFacts: lineFacts,
    parseSources: parseSources,
    sourcesText: sourcesText,
  };
})();

if (typeof module !== "undefined") {
  module.exports = MissionEditor;
}

// ---------------------------------------------------------------- browser: storage

const USER_MISSIONS_KEY = "navasa-user-missions";

function readUserMissions() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(USER_MISSIONS_KEY) || "[]");
    return Array.isArray(saved) ? saved : [];
  } catch (error) {
    return [];
  }
}

// Returns true when saved; false when the browser refused (private window, blocked storage).
function writeUserMissions(missions) {
  try {
    window.localStorage.setItem(USER_MISSIONS_KEY, JSON.stringify(missions));
    return true;
  } catch (error) {
    return false;
  }
}

function randomHex() {
  const bytes = new Uint8Array(4);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function downloadJson(fileName, data) {
  const blob = new Blob([JSON.stringify(data, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(function () {
    URL.revokeObjectURL(url);
  }, 1000);
}

// ---------------------------------------------------------------- browser: MISSION tab card
// Uses app.js helpers (makeElement, factTable, gridToLatLng, loadReadout, readValue, groundDistance,
// bearingDegrees, eastScaleOf) and LineOfSight.samplePoints from los.js.

const EDITOR_SAMPLE_STEP_M = 4;

async function setUpMissionEditor(map, manifest, mission, packStops) {
  const tab = document.getElementById("tab-hud");
  const bounds = manifest.site.bounds_lonlat;
  const grid = manifest.grid;
  const siteName = manifest.site.name;
  const siteTemplate = mission.site_template || null;

  const loaded = {};
  for (const readout of manifest.readouts || []) {
    if (["elevation", "slope", "unit"].includes(readout.id)) {
      loaded[readout.id] = await loadReadout(readout);
    }
  }
  const unitsById = {};
  for (const layer of manifest.layers) {
    if (layer.id === "geology") {
      for (const unit of layer.legend) {
        unitsById[unit.id] = unit;
      }
    }
  }

  tab.appendChild(makeElement("h2", "section-title editor-section", "> MISSION EDITOR · YOUR MISSIONS ON THIS SITE"));
  const card = makeElement("div", "card editor-section");
  tab.appendChild(card);
  const listHolder = makeElement("div");
  card.appendChild(listHolder);
  const topButtons = makeElement("div", "button-row");
  const newButton = makeElement("button", "text-button", "NEW MISSION");
  const duplicateButton = makeElement("button", "text-button", "DUPLICATE “" + mission.name.toUpperCase() + "”");
  const importButton = makeElement("button", "text-button", "IMPORT MISSION FILE");
  for (const button of [newButton, duplicateButton, importButton]) {
    button.type = "button";
    topButtons.appendChild(button);
  }
  const importInput = document.createElement("input");
  importInput.type = "file";
  importInput.accept = "application/json,.json";
  importInput.hidden = true;
  topButtons.appendChild(importInput);
  card.appendChild(topButtons);
  const message = makeElement("p", "dim", "");
  message.setAttribute("aria-live", "polite");
  card.appendChild(message);
  const formHolder = makeElement("div");
  card.appendChild(formHolder);
  card.appendChild(
    makeElement(
      "p",
      "note",
      "Your missions are kept in this browser only: export them to keep or share them. An exported file is a mission file for this site; " +
        "`python -m pipeline.run_mission <file>` builds its full pack (routes, geology, photos). Facts here are along STRAIGHT lines " +
        "between your stops, from the 4 m readouts (elevation NASA DATA, slope and unit CALCULATED / NASA DATA); objectives and questions are set by you." +
        (siteTemplate === null ? " This pack has no site template, so EXPORT is not available; rebuild the pack." : "")
    )
  );

  const layer = L.layerGroup().addTo(map);
  let missions = readUserMissions();
  let draft = null; // the mission being edited (a copy)
  let placing = null; // null, "add", or the index of a stop being moved

  function say(text) {
    message.textContent = text;
  }

  function save() {
    if (!writeUserMissions(missions)) {
      say("This browser did not save it (storage blocked). Export the mission to keep it.");
    }
  }

  function siteMissions() {
    return missions.filter(function (item) {
      return item.site === siteName;
    });
  }

  function gridOf(stop) {
    return MissionEditor.gridFromLonLat(bounds, grid, stop.lon, stop.lat);
  }

  function readAt(name, position) {
    if (!loaded[name] || position[0] < 0 || position[1] < 0 || position[0] >= grid.width || position[1] >= grid.height) {
      return null;
    }
    return readValue(loaded[name], position[0], position[1]);
  }

  function stopFacts(stop) {
    const position = gridOf(stop);
    const elevation = readAt("elevation", position);
    const slope = readAt("slope", position);
    const unitId = readAt("unit", position);
    const unit = unitId === null ? undefined : unitsById[Math.round(unitId)];
    return (
      (elevation === null ? "elevation no data" : elevation.toFixed(1) + " m") +
      " · " +
      (slope === null ? "slope no data" : slope.toFixed(1) + "°") +
      " · " +
      (unit === undefined ? "unit no data" : unit.symbol + " " + unit.name)
    );
  }

  function legRows(stops) {
    const rows = [];
    for (let index = 1; index < stops.length; index++) {
      const from = gridOf(stops[index - 1]);
      const to = gridOf(stops[index]);
      const sampled = LineOfSight.samplePoints(from, to, eastScaleOf(manifest), grid.metres_per_pixel, EDITOR_SAMPLE_STEP_M);
      const facts = MissionEditor.lineFacts(
        sampled.points.map((point) => readAt("elevation", point)),
        sampled.points.map((point) => readAt("slope", point))
      );
      rows.push([
        stops[index - 1].id + " → " + stops[index].id,
        (groundDistance(manifest, from, to) / 1000).toFixed(2) + " km",
        bearingDegrees(manifest, from, to).toFixed(0) + "°",
        facts.climb.toFixed(0) + " m / " + facts.descent.toFixed(0) + " m",
        facts.steepest === null ? "no data" : facts.steepest.toFixed(1) + "°",
      ]);
    }
    return rows;
  }

  function drawOnMap(stops) {
    layer.clearLayers();
    const points = stops.map(function (stop) {
      const position = gridOf(stop);
      return gridToLatLng(position[0], position[1]);
    });
    if (points.length > 1) {
      L.polyline(points, { className: "editor-line", weight: 3, dashArray: "4 8", interactive: false }).addTo(layer);
    }
    stops.forEach(function (stop, index) {
      const icon = L.divIcon({ html: makeElement("div", "editor-marker", String(stop.id)), className: "", iconSize: [30, 30], iconAnchor: [15, 15] });
      L.marker(points[index], { icon: icon, title: stop.label, interactive: false }).addTo(layer);
    });
  }

  function renderList() {
    listHolder.replaceChildren();
    const mine = siteMissions();
    if (mine.length === 0) {
      listHolder.appendChild(makeElement("p", "dim", "No missions of your own on this site yet."));
      return;
    }
    for (const item of mine) {
      const row = makeElement("div", "editor-row");
      row.appendChild(makeElement("p", "", item.name + " · " + item.status + " · " + item.stops.length + " stops"));
      const buttons = makeElement("div", "button-row");
      for (const [label, action] of [
        ["SHOW", () => showMission(item)],
        ["EDIT", () => startEditing(item)],
        ["EXPORT", () => exportMission(item)],
        ["DELETE", () => deleteMission(item)],
      ]) {
        const button = makeElement("button", "text-button", label);
        button.type = "button";
        button.addEventListener("click", action);
        if (label === "EXPORT" && siteTemplate === null) {
          button.disabled = true;
        }
        buttons.appendChild(button);
      }
      row.appendChild(buttons);
      listHolder.appendChild(row);
    }
  }

  function showMission(item) {
    drawOnMap(item.stops);
    const points = item.stops.map((stop) => gridOf(stop)).map((position) => gridToLatLng(position[0], position[1]));
    map.fitBounds(L.latLngBounds(points).pad(0.3));
    formHolder.replaceChildren();
    formHolder.appendChild(makeElement("h3", "card-title", item.name.toUpperCase()));
    formHolder.appendChild(makeElement("p", "dim", "OBJECTIVE · set by you"));
    formHolder.appendChild(makeElement("p", "", item.objective));
    formHolder.appendChild(factTable(["STOP", "AT THE STOP (4 m readouts)", "QUESTION"], item.stops.map((stop) => [stop.id + " · " + stop.label, stopFacts(stop), stop.question])));
    if (item.stops.length > 1) {
      formHolder.appendChild(factTable(["LEG (STRAIGHT LINE)", "DISTANCE", "BEARING", "CLIMB / DESCENT", "STEEPEST 4 m"], legRows(item.stops)));
    }
    say("Showing " + item.name + " on the map (dashed: straight lines, not routes).");
  }

  function exportMission(item) {
    const file = MissionEditor.toMissionFile(item, siteTemplate);
    downloadJson(item.id + ".json", file);
    say("Exported " + item.id + ".json. Put it in data/missions/ and run: python -m pipeline.run_mission data/missions/" + item.id + ".json");
  }

  function deleteMission(item) {
    if (!window.confirm("Delete “" + item.name + "” from this device? Export it first if you want to keep it.")) {
      return;
    }
    missions = missions.filter((other) => other.id !== item.id);
    save();
    layer.clearLayers();
    formHolder.replaceChildren();
    renderList();
    say("Deleted " + item.name + ".");
  }

  function blankMission() {
    return {
      id: MissionEditor.newMissionId("new mission", randomHex()),
      name: "",
      status: "PLANNED",
      objective: "",
      objective_sources: [{ text: MissionEditor.USER_SOURCE_TEXT }],
      site: siteName,
      stops: [],
      user: true,
    };
  }

  function startEditing(item) {
    draft = JSON.parse(JSON.stringify(item));
    renderForm();
  }

  function stopPlacing() {
    placing = null;
    map.getContainer().classList.remove("placing");
  }

  function renderForm() {
    formHolder.replaceChildren();
    if (draft === null) {
      return;
    }
    const isNew = !missions.some((item) => item.id === draft.id);
    formHolder.appendChild(makeElement("h3", "card-title", isNew ? "NEW MISSION" : "EDIT MISSION"));
    const fields = makeElement("div", "editor-fields");

    function textField(label, value, multiline, onInput) {
      const field = makeElement("label", "antenna-field");
      field.appendChild(makeElement("span", "", label));
      const input = document.createElement(multiline ? "textarea" : "input");
      if (!multiline) {
        input.type = "text";
      } else {
        input.rows = 3;
      }
      input.className = "message-input";
      input.value = value;
      input.maxLength = 2000;
      input.addEventListener("input", function () {
        onInput(input.value);
      });
      field.appendChild(input);
      fields.appendChild(field);
      return input;
    }

    textField("NAME", draft.name, false, (value) => {
      draft.name = value;
    });
    const statusField = makeElement("label", "antenna-field");
    statusField.appendChild(makeElement("span", "", "STATUS"));
    const statusSelect = document.createElement("select");
    statusSelect.className = "message-input";
    for (const status of MissionEditor.STATUSES) {
      const option = document.createElement("option");
      option.value = status;
      option.textContent = status;
      option.selected = draft.status === status;
      statusSelect.appendChild(option);
    }
    statusSelect.addEventListener("change", () => {
      draft.status = statusSelect.value;
    });
    statusField.appendChild(statusSelect);
    fields.appendChild(statusField);
    textField("OBJECTIVE (set by you)", draft.objective, true, (value) => {
      draft.objective = value;
    });
    textField("SOURCES OF THE OBJECTIVE, one per line (text | https://link)", MissionEditor.sourcesText(draft.objective_sources), true, (value) => {
      draft.objective_sources = MissionEditor.parseSources(value);
    });
    formHolder.appendChild(fields);

    formHolder.appendChild(makeElement("h3", "card-title", "STOPS · " + draft.stops.length));
    draft.stops.forEach(function (stop, index) {
      const row = makeElement("div", "editor-stop");
      row.appendChild(makeElement("p", "", "STOP " + stop.id + " · " + stop.lat.toFixed(5) + "° N " + stop.lon.toFixed(5) + "° E · " + stopFacts(stop)));
      const stopFields = makeElement("div", "editor-fields");
      for (const [label, key] of [
        ["LABEL", "label"],
        ["QUESTION (set by you)", "question"],
      ]) {
        const field = makeElement("label", "antenna-field");
        field.appendChild(makeElement("span", "", label));
        const input = document.createElement("input");
        input.type = "text";
        input.className = "message-input";
        input.maxLength = 500;
        input.value = stop[key] || "";
        input.addEventListener("input", () => {
          stop[key] = input.value;
        });
        field.appendChild(input);
        stopFields.appendChild(field);
      }
      row.appendChild(stopFields);
      const buttons = makeElement("div", "button-row");
      for (const [label, action, enabled] of [
        ["↑", () => moveStop(index, -1), index > 0],
        ["↓", () => moveStop(index, 1), index < draft.stops.length - 1],
        ["MOVE ON MAP", () => startPlacing(index), true],
        ["REMOVE", () => removeStop(index), true],
      ]) {
        const button = makeElement("button", "text-button", label);
        button.type = "button";
        button.disabled = !enabled;
        button.setAttribute("aria-label", label + " stop " + stop.id);
        button.addEventListener("click", action);
        buttons.appendChild(button);
      }
      row.appendChild(buttons);
      formHolder.appendChild(row);
    });
    if (draft.stops.length > 1) {
      formHolder.appendChild(factTable(["LEG (STRAIGHT LINE)", "DISTANCE", "BEARING", "CLIMB / DESCENT", "STEEPEST 4 m"], legRows(draft.stops)));
    }
    const actions = makeElement("div", "button-row");
    for (const [label, action] of [
      ["ADD STOP: TAP THE MAP", () => startPlacing("add")],
      ["SAVE", saveDraft],
      ["CANCEL", cancelDraft],
    ]) {
      const button = makeElement("button", "text-button", label);
      button.type = "button";
      button.addEventListener("click", action);
      actions.appendChild(button);
    }
    formHolder.appendChild(actions);
    drawOnMap(draft.stops);
  }

  function renumber() {
    draft.stops.forEach(function (stop, index) {
      stop.id = index + 1;
    });
  }

  function moveStop(index, step) {
    const [stop] = draft.stops.splice(index, 1);
    draft.stops.splice(index + step, 0, stop);
    renumber();
    renderForm();
  }

  function removeStop(index) {
    draft.stops.splice(index, 1);
    renumber();
    renderForm();
  }

  function startPlacing(target) {
    placing = target;
    map.getContainer().classList.add("placing");
    say(target === "add" ? "Tap the map where the new stop is." : "Tap the map where stop " + draft.stops[target].id + " should be.");
  }

  map.on("click", function (event) {
    if (placing === null || draft === null) {
      return;
    }
    const col = event.latlng.lng;
    const row = -event.latlng.lat;
    if (col < 0 || row < 0 || col >= grid.width || row >= grid.height) {
      say("That is outside the walk area: tap inside it.");
      return;
    }
    const lonLat = MissionEditor.lonLatFromGrid(bounds, grid, col, row);
    if (placing === "add") {
      draft.stops.push({
        id: draft.stops.length + 1,
        label: "Stop " + (draft.stops.length + 1),
        lat: lonLat[1],
        lon: lonLat[0],
        position_source: MissionEditor.USER_POSITION_SOURCE,
        question: "",
        photos: [],
      });
    } else {
      draft.stops[placing].lat = lonLat[1];
      draft.stops[placing].lon = lonLat[0];
      draft.stops[placing].position_source = MissionEditor.USER_POSITION_SOURCE;
    }
    stopPlacing();
    say("");
    renderForm();
  });

  function saveDraft() {
    if (draft.name.trim() !== "" && !missions.some((item) => item.id === draft.id)) {
      draft.id = MissionEditor.newMissionId(draft.name, randomHex());
    }
    const problems = MissionEditor.check(draft, siteName, bounds);
    if (problems.length > 0) {
      say("Not saved: " + problems.join("; ") + ".");
      return;
    }
    const existing = missions.findIndex((item) => item.id === draft.id);
    if (existing >= 0) {
      missions[existing] = draft;
    } else {
      missions.push(draft);
    }
    save();
    const savedName = draft.name;
    draft = null;
    stopPlacing();
    renderList();
    formHolder.replaceChildren();
    layer.clearLayers();
    say("Saved “" + savedName + "” on this device.");
  }

  function cancelDraft() {
    draft = null;
    stopPlacing();
    formHolder.replaceChildren();
    layer.clearLayers();
    say("");
  }

  newButton.addEventListener("click", function () {
    startEditing(blankMission());
    say("Name it, write the objective, then add stops by tapping the map.");
  });

  duplicateButton.addEventListener("click", function () {
    const copy = blankMission();
    copy.name = mission.name + " (copy)";
    copy.status = "PLANNED";
    copy.objective = mission.objective;
    copy.objective_sources = JSON.parse(JSON.stringify(mission.objective_sources));
    const questions = {};
    for (const item of mission.questions || []) {
      questions[item.stop_id] = item.question;
    }
    copy.stops = packStops.map(function (stop) {
      const lonLat = MissionEditor.lonLatFromGrid(bounds, grid, stop.position[0], stop.position[1]);
      return {
        id: stop.id,
        label: stop.label,
        lat: lonLat[1],
        lon: lonLat[0],
        position_source: stop.position_source,
        question: questions[stop.id] || "",
        photos: [],
      };
    });
    startEditing(copy);
    say("Editable copy of the built-in mission (its photos stay with the original). Change it and SAVE.");
  });

  importButton.addEventListener("click", function () {
    importInput.value = "";
    importInput.click();
  });
  importInput.addEventListener("change", function () {
    const file = importInput.files && importInput.files[0];
    if (!file) {
      return;
    }
    if (file.size > 1000000) {
      say("Not imported: the file is larger than 1 MB.");
      return;
    }
    file.text().then(function (text) {
      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch (error) {
        say("Not imported: the file is not JSON.");
        return;
      }
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        say("Not imported: not a mission file.");
        return;
      }
      const stops = Array.isArray(parsed.stops) ? parsed.stops : [];
      const imported = {
        id: typeof parsed.id === "string" ? parsed.id : "",
        name: parsed.name,
        status: parsed.status,
        objective: parsed.objective,
        objective_sources: parsed.objective_sources,
        site: typeof parsed.site === "object" && parsed.site !== null ? parsed.site.name : parsed.site,
        stops: stops.map(function (stop) {
          return {
            id: stop.id,
            label: stop.label,
            lat: stop.lat,
            lon: stop.lon,
            position_source: stop.position_source,
            question: stop.question,
            photos: Array.isArray(stop.photos) ? stop.photos : [],
          };
        }),
        user: true,
      };
      const problems = MissionEditor.check(imported, siteName, bounds);
      if (problems.length > 0) {
        say("Not imported: " + problems.join("; ") + ".");
        return;
      }
      if (missions.some((item) => item.id === imported.id) && !window.confirm("A mission with id " + imported.id + " exists on this device. Replace it?")) {
        return;
      }
      missions = missions.filter((item) => item.id !== imported.id);
      missions.push(imported);
      save();
      renderList();
      say("Imported “" + imported.name + "”.");
    });
  });

  renderList();
}
