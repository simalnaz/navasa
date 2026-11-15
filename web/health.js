// Health / status panel (MISSION tab), decided 15 Nov ([[2026-11-15-health-and-meda]]):
//   A  device battery: the browser's Battery Status API (the device running NAVASA), real
//   B  EVA timer: real elapsed time since START EVA, and time to sunset from the Mars24 clock
//   C  MEDA measured temperatures: separate step, after the download is approved
//   D  suit telemetry: TRAINING SIMULATION from values the user types (every field empty until then)
// No suit sensors exist; nothing here is presented as a real suit reading.

"use strict";

const Health = (function () {
  // A typed amount: a number >= 0 (rates must be > 0), or null when empty or not valid.
  function parseAmount(text, mustBePositive) {
    const trimmed = String(text).trim().replace(",", ".");
    if (trimmed === "") {
      return null;
    }
    const value = Number(trimmed);
    if (!Number.isFinite(value) || value < 0 || value > 1e6 || (mustBePositive && value === 0)) {
      return null;
    }
    return value;
  }

  // Simulated resource after elapsedHours of constant use. Times in hours.
  function simulate(start, ratePerHour, elapsedHours) {
    const remaining = Math.max(0, start - ratePerHour * elapsedHours);
    return {
      remaining: remaining,
      fraction: start > 0 ? remaining / start : 0,
      hoursLeft: remaining / ratePerHour,
      emptyAfterHours: start / ratePerHour,
    };
  }

  function formatHms(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    return hours + ":" + String(minutes).padStart(2, "0") + ":" + String(total % 60).padStart(2, "0");
  }

  return { parseAmount: parseAmount, simulate: simulate, formatHms: formatHms };
})();

if (typeof module !== "undefined") {
  module.exports = Health;
}

// ---------------------------------------------------------------- browser: MISSION tab card
// Uses app.js helpers (makeElement, factTable) and MarsTime.

const EVA_STORAGE_KEY = "navasa-eva-start"; // per device: the EVA keeps running across a reload
const SUIT_RESOURCES = [
  { id: "battery", name: "SUIT BATTERY", amountUnit: "Wh", rateUnit: "W" },
  { id: "oxygen", name: "OXYGEN", amountUnit: "kg", rateUnit: "kg per hour" },
  { id: "water", name: "COOLING WATER", amountUnit: "kg", rateUnit: "kg per hour" },
];

function readStoredEvaStart() {
  try {
    const value = Number(window.localStorage.getItem(EVA_STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch (error) {
    return null;
  }
}

function storeEvaStart(value) {
  try {
    if (value === null) {
      window.localStorage.removeItem(EVA_STORAGE_KEY);
    } else {
      window.localStorage.setItem(EVA_STORAGE_KEY, String(value));
    }
  } catch (error) {
    // storage blocked: the timer still runs until the page closes
  }
}

function setUpHealthCard(manifest) {
  const box = manifest.site.bounds_lonlat;
  const lon = (box[0] + box[2]) / 2;
  const lat = (box[1] + box[3]) / 2;
  const tab = document.getElementById("tab-hud");
  tab.appendChild(makeElement("h2", "section-title", "> HEALTH / STATUS"));

  // A. Device battery
  const deviceCard = makeElement("div", "card");
  deviceCard.appendChild(makeElement("h3", "card-title", "A · THIS DEVICE'S BATTERY · REAL"));
  const deviceLine = makeElement("p", "", "no data");
  deviceCard.appendChild(deviceLine);
  deviceCard.appendChild(
    makeElement("p", "note", "The tablet or phone running NAVASA (browser Battery Status API; Chrome and Edge share it, other browsers show no data). Not a suit battery.")
  );
  tab.appendChild(deviceCard);

  function showBattery(battery) {
    let text = Math.round(battery.level * 100) + " %" + (battery.charging ? " · charging" : " · on battery");
    if (!battery.charging && Number.isFinite(battery.dischargingTime) && battery.dischargingTime > 0) {
      text += " · empty in about " + Health.formatHms(battery.dischargingTime * 1000) + " (browser estimate)";
    }
    deviceLine.textContent = text;
  }
  if (typeof navigator.getBattery === "function") {
    navigator.getBattery().then(
      function (battery) {
        showBattery(battery);
        for (const name of ["levelchange", "chargingchange", "dischargingtimechange"]) {
          battery.addEventListener(name, function () {
            showBattery(battery);
          });
        }
      },
      function () {
        deviceLine.textContent = "no data (the browser did not share the battery)";
      }
    );
  } else {
    deviceLine.textContent = "no data (this browser does not share the battery)";
  }

  // B. EVA timer
  const evaCard = makeElement("div", "card");
  evaCard.appendChild(makeElement("h3", "card-title", "B · EVA TIMER · REAL TIME"));
  const evaFacts = makeElement("dl", "readout clock");
  const evaFields = {};
  for (const [key, label] of [
    ["elapsed", "EVA TIME"],
    ["started", "STARTED"],
    ["sunset", "SUNSET"],
    ["left", "TO SUNSET"],
  ]) {
    evaFacts.appendChild(makeElement("dt", "", label));
    evaFields[key] = makeElement("dd", "", "—");
    evaFacts.appendChild(evaFields[key]);
  }
  evaCard.appendChild(evaFacts);
  const evaButtons = makeElement("div", "button-row");
  const startButton = makeElement("button", "text-button", "START EVA");
  const endButton = makeElement("button", "text-button", "END EVA");
  for (const button of [startButton, endButton]) {
    button.type = "button";
    evaButtons.appendChild(button);
  }
  evaCard.appendChild(evaButtons);
  evaCard.appendChild(
    makeElement("p", "note", "Earth hours:minutes:seconds since START EVA (kept on this device). Sunset at the site centre from the Mars24 clock (sun centre at 0°, flat horizon; the SKY tab shows terrain shadows).")
  );
  tab.appendChild(evaCard);

  // C. MEDA measured temperatures (filled when meda.json has loaded)
  if (manifest.meda) {
    const medaCard = makeElement("div", "card");
    medaCard.appendChild(makeElement("h3", "card-title", "C · MEASURED TEMPERATURES · PERSEVERANCE MEDA · ■ NASA DATA"));
    const medaBody = makeElement("div", "", "");
    medaBody.appendChild(makeElement("p", "dim", "Loading MEDA measurements ..."));
    medaCard.appendChild(medaBody);
    tab.appendChild(medaCard);
    loadJson(manifest.meda.file).then(
      function (meda) {
        fillMedaCard(medaBody, manifest.meda, meda);
      },
      function (error) {
        medaBody.replaceChildren(makeElement("p", "dim", "MEDA measurements unavailable: " + error.message));
      }
    );
  }

  // D. Suit simulation
  const suitCard = makeElement("div", "card");
  suitCard.appendChild(makeElement("h3", "card-title", "D · SUIT · TRAINING SIMULATION · YOUR VALUES"));
  suitCard.appendChild(
    makeElement("p", "dim", "No suit sensors are connected. Type a start amount and a use per hour; the simulation then counts down with the EVA timer.")
  );
  const suitInputs = {};
  const suitGrid = makeElement("div", "antenna-inputs");
  for (const resource of SUIT_RESOURCES) {
    suitInputs[resource.id] = {};
    for (const [key, label] of [
      ["start", resource.name + " AT START (" + resource.amountUnit + ")"],
      ["rate", resource.name + " USE (" + resource.rateUnit + ")"],
    ]) {
      const field = makeElement("label", "antenna-field");
      field.appendChild(makeElement("span", "", label));
      const input = document.createElement("input");
      input.type = "text";
      input.inputMode = "decimal";
      input.className = "message-input";
      input.placeholder = "type";
      input.autocomplete = "off";
      field.appendChild(input);
      suitGrid.appendChild(field);
      suitInputs[resource.id][key] = input;
      input.addEventListener("input", render);
    }
  }
  suitCard.appendChild(suitGrid);
  const suitResults = makeElement("div");
  suitCard.appendChild(suitResults);
  suitCard.appendChild(
    makeElement("p", "note", "TRAINING SIMULATION: constant use at your rates, from your start amounts. Not a real reading and not a safety limit. Values are not saved.")
  );
  tab.appendChild(suitCard);

  let evaStart = readStoredEvaStart();

  startButton.addEventListener("click", function () {
    evaStart = Date.now();
    storeEvaStart(evaStart);
    render();
  });
  endButton.addEventListener("click", function () {
    evaStart = null;
    storeEvaStart(null);
    render();
  });

  function render() {
    const now = Date.now();
    const elapsedMs = evaStart === null ? 0 : now - evaStart;
    startButton.disabled = evaStart !== null;
    endButton.disabled = evaStart === null;
    evaFields.elapsed.textContent = evaStart === null ? "not started" : Health.formatHms(elapsedMs);
    evaFields.started.textContent =
      evaStart === null ? "—" : new Date(evaStart).toISOString().slice(0, 19).replace("T", " ") + " UTC · LMST " + MarsTime.formatHours(MarsTime.sun(evaStart, lon, lat).lmst);
    const sol = MarsTime.m20Sol(now);
    let times = MarsTime.sunriseSunset(sol, lon, lat);
    let sunsetMs = times.sunset;
    if (sunsetMs !== null && sunsetMs < now) {
      times = MarsTime.sunriseSunset(sol + 1, lon, lat);
      sunsetMs = times.sunset;
    }
    const sunIsUp = MarsTime.sun(now, lon, lat).elevation > 0;
    evaFields.sunset.textContent = sunsetMs === null ? "none" : "LTST " + MarsTime.formatHours(MarsTime.sun(sunsetMs, lon, lat).ltst) + " · " + new Date(sunsetMs).toISOString().slice(0, 16).replace("T", " ") + " UTC";
    evaFields.left.textContent = sunsetMs === null ? "—" : sunIsUp ? Health.formatHms(sunsetMs - now) + " (Earth time)" : "night now; next sunset in " + Health.formatHms(sunsetMs - now);

    const rows = [];
    const waiting = [];
    for (const resource of SUIT_RESOURCES) {
      const startInput = suitInputs[resource.id].start;
      const rateInput = suitInputs[resource.id].rate;
      const start = Health.parseAmount(startInput.value, false);
      const rate = Health.parseAmount(rateInput.value, true);
      startInput.classList.toggle("invalid", startInput.value.trim() !== "" && start === null);
      rateInput.classList.toggle("invalid", rateInput.value.trim() !== "" && rate === null);
      if (start === null || rate === null) {
        if (startInput.value.trim() !== "" || rateInput.value.trim() !== "") {
          waiting.push(resource.name.toLowerCase());
        }
        continue;
      }
      const result = Health.simulate(start, rate, elapsedMs / 3600000);
      const leftMs = result.hoursLeft * 3600000;
      let versusSunset = "—";
      if (sunIsUp && sunsetMs !== null) {
        versusSunset = now + leftMs < sunsetMs ? "runs out " + Health.formatHms(sunsetMs - now - leftMs) + " before sunset" : "lasts past sunset";
      }
      rows.push([
        resource.name,
        result.remaining.toFixed(2) + " " + resource.amountUnit + " (" + Math.round(result.fraction * 100) + " %)",
        Health.formatHms(leftMs),
        versusSunset,
      ]);
    }
    suitResults.replaceChildren();
    if (rows.length > 0) {
      suitResults.appendChild(factTable(["SIMULATED", "LEFT", "TIME LEFT", "VS SUNSET"], rows));
    } else {
      suitResults.appendChild(makeElement("p", "dim", "Empty until you type both values for a resource."));
    }
    if (waiting.length > 0) {
      suitResults.appendChild(makeElement("p", "dim", "Needs both values (rate above 0): " + waiting.join(", ") + "."));
    }
  }
  setInterval(render, 1000);
  render();
}

// ---------------------------------------------------------------- C: MEDA card

const MEDA_SERIES = [
  { key: "air", name: "AIR", className: "meda-air" },
  { key: "ground", name: "GROUND", className: "meda-ground" },
];
const MEDA_CHART = { width: 320, height: 170, left: 34, right: 54, top: 10, bottom: 22, stepC: 20 };

function celsiusText(value) {
  return (value > 0 ? "+" : "") + value.toFixed(1) + " °C";
}

function medaChart(sol, readout) {
  const box = MEDA_CHART;
  const values = [];
  for (const series of MEDA_SERIES) {
    if (sol[series.key] !== null) {
      for (const hour of sol[series.key].hourly) {
        values.push(hour.mean_c);
      }
    }
  }
  const low = Math.floor(Math.min.apply(null, values) / box.stepC) * box.stepC;
  const high = Math.ceil(Math.max.apply(null, values) / box.stepC) * box.stepC;
  const plotWidth = box.width - box.left - box.right;
  const plotHeight = box.height - box.top - box.bottom;
  const x = (hour) => box.left + ((hour + 0.5) / 24) * plotWidth;
  const y = (celsius) => box.top + ((high - celsius) / Math.max(1, high - low)) * plotHeight;
  const svg = svgElement("svg", {
    viewBox: "0 0 " + box.width + " " + box.height,
    class: "meda-chart",
    role: "img",
    "aria-label": "Hourly mean air and ground temperature over sol " + sol.sol + ", local mean solar time",
  });
  for (let celsius = low; celsius <= high; celsius += box.stepC) {
    svg.appendChild(svgElement("line", { x1: box.left, x2: box.width - box.right, y1: y(celsius), y2: y(celsius), class: "meda-grid" }));
    const tick = svgElement("text", { x: box.left - 4, y: y(celsius) + 3, class: "meda-axis", "text-anchor": "end" });
    tick.textContent = String(celsius);
    svg.appendChild(tick);
  }
  for (const hour of [0, 6, 12, 18, 24]) {
    const tick = svgElement("text", { x: box.left + (hour / 24) * plotWidth, y: box.height - 6, class: "meda-axis", "text-anchor": "middle" });
    tick.textContent = String(hour).padStart(2, "0");
    svg.appendChild(tick);
  }
  const unit = svgElement("text", { x: 2, y: box.top + 3, class: "meda-axis" });
  unit.textContent = "°C";
  svg.appendChild(unit);
  const lastPoints = [];
  for (const series of MEDA_SERIES) {
    const summary = sol[series.key];
    if (summary === null) {
      continue;
    }
    // A line only joins hours next to each other: a missing hour is a gap, not a guess.
    let segment = [];
    const segments = [];
    let previousHour = null;
    for (const hour of summary.hourly) {
      if (previousHour !== null && hour.hour !== previousHour + 1) {
        segments.push(segment);
        segment = [];
      }
      segment.push(x(hour.hour).toFixed(1) + "," + y(hour.mean_c).toFixed(1));
      previousHour = hour.hour;
    }
    segments.push(segment);
    for (const points of segments) {
      if (points.length === 1) {
        const [px, py] = points[0].split(",");
        svg.appendChild(svgElement("circle", { cx: px, cy: py, r: 2.5, class: series.className + " meda-dot" }));
      } else {
        svg.appendChild(svgElement("polyline", { points: points.join(" "), class: series.className + " meda-line" }));
      }
    }
    const last = summary.hourly[summary.hourly.length - 1];
    lastPoints.push({ series: series, y: y(last.mean_c), x: x(last.hour) });
  }
  // Direct labels at the line ends, nudged apart when they would overlap.
  lastPoints.sort((a, b) => a.y - b.y);
  for (let index = 1; index < lastPoints.length; index++) {
    lastPoints[index].y = Math.max(lastPoints[index].y, lastPoints[index - 1].y + 11);
  }
  for (const point of lastPoints) {
    const label = svgElement("text", { x: box.width - box.right + 4, y: point.y + 3, class: "meda-label" });
    label.textContent = point.series.name;
    svg.appendChild(label);
  }
  // Hover / tap: crosshair on the nearest hour and the values in the readout line.
  const crosshair = svgElement("line", { y1: box.top, y2: box.height - box.bottom, class: "meda-crosshair", visibility: "hidden" });
  svg.appendChild(crosshair);
  const hit = svgElement("rect", { x: box.left, y: box.top, width: plotWidth, height: plotHeight, class: "meda-hit" });
  svg.appendChild(hit);
  function show(event) {
    const bounds = svg.getBoundingClientRect();
    const svgX = ((event.clientX - bounds.left) / bounds.width) * box.width;
    const hour = Math.max(0, Math.min(23, Math.floor(((svgX - box.left) / plotWidth) * 24)));
    crosshair.setAttribute("x1", x(hour));
    crosshair.setAttribute("x2", x(hour));
    crosshair.setAttribute("visibility", "visible");
    const parts = ["LMST " + String(hour).padStart(2, "0") + ":00–" + String(hour + 1).padStart(2, "0") + ":00"];
    for (const series of MEDA_SERIES) {
      const summary = sol[series.key];
      const found = summary === null ? undefined : summary.hourly.find((item) => item.hour === hour);
      parts.push(series.name + " " + (found === undefined ? "no data" : celsiusText(found.mean_c)));
    }
    readout.textContent = parts.join(" · ");
  }
  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerdown", show);
  hit.addEventListener("pointerleave", function () {
    crosshair.setAttribute("visibility", "hidden");
    readout.textContent = "Move over or tap the chart for an hour's values.";
  });
  return svg;
}

function lmstText(hours) {
  return "LMST " + MarsTime.formatHours(hours);
}

function fillMedaCard(body, info, meda) {
  body.replaceChildren();
  const picker = makeElement("div", "button-row");
  body.appendChild(picker);
  const view = makeElement("div", "meda-view");
  body.appendChild(view);
  body.appendChild(
    makeElement(
      "p",
      "note",
      "Measured by Perseverance where the rover was on that sol (not a forecast, not a GO/NO-GO). " +
        info.method + " Source: " + info.source + ". " + info.product_id + ", release " + info.as_of + "."
    )
  );
  const buttons = [];

  function select(index) {
    const sol = meda.sols[index];
    buttons.forEach((button, buttonIndex) => button.setAttribute("aria-pressed", buttonIndex === index ? "true" : "false"));
    view.replaceChildren();
    view.appendChild(
      makeElement("p", "", "SOL " + sol.sol + " · " + sol.utc_start + " → " + sol.utc_end + " UTC" + (sol.stop_id !== null ? " · at stop " + sol.stop_id : ""))
    );
    if (sol.note) {
      view.appendChild(makeElement("p", "dim", sol.note));
    }
    const rows = [];
    for (const series of MEDA_SERIES) {
      const summary = sol[series.key];
      rows.push(
        summary === null
          ? [series.name, "no data", "no data", "0 h"]
          : [
              series.name,
              celsiusText(summary.min.c) + " · " + lmstText(summary.min.lmst_hours),
              celsiusText(summary.max.c) + " · " + lmstText(summary.max.lmst_hours),
              summary.hourly.length + " of 24 h",
            ]
      );
    }
    view.appendChild(factTable(["", "LOWEST", "HIGHEST", "MEASURED"], rows));
    const legend = makeElement("div", "legend");
    for (const series of MEDA_SERIES) {
      const row = makeElement("div", "legend-row");
      row.appendChild(makeElement("span", "legend-line " + series.className));
      row.appendChild(makeElement("span", "", series.name + " · hourly mean"));
      legend.appendChild(row);
    }
    view.appendChild(legend);
    const readout = makeElement("p", "dim", "Move over or tap the chart for an hour's values.");
    readout.setAttribute("aria-live", "polite");
    view.appendChild(medaChart(sol, readout));
    view.appendChild(readout);
    const tableToggle = makeElement("button", "text-button", "SHOW HOURLY TABLE");
    tableToggle.type = "button";
    const tableHolder = makeElement("div");
    tableHolder.hidden = true;
    const hourlyRows = [];
    for (let hour = 0; hour < 24; hour++) {
      const cells = [String(hour).padStart(2, "0") + ":00"];
      for (const series of MEDA_SERIES) {
        const found = sol[series.key] === null ? undefined : sol[series.key].hourly.find((item) => item.hour === hour);
        cells.push(found === undefined ? "—" : celsiusText(found.mean_c));
      }
      hourlyRows.push(cells);
    }
    tableHolder.appendChild(factTable(["LMST", "AIR", "GROUND"], hourlyRows));
    tableToggle.addEventListener("click", function () {
      tableHolder.hidden = !tableHolder.hidden;
      tableToggle.textContent = tableHolder.hidden ? "SHOW HOURLY TABLE" : "HIDE HOURLY TABLE";
    });
    view.appendChild(tableToggle);
    view.appendChild(tableHolder);
  }

  meda.sols.forEach(function (sol, index) {
    const button = makeElement("button", "text-button", (sol.stop_id !== null ? "STOP " + sol.stop_id + " · " : "") + "SOL " + sol.sol);
    button.type = "button";
    button.addEventListener("click", function () {
      select(index);
    });
    picker.appendChild(button);
    buttons.push(button);
  });
  select(0);
}
