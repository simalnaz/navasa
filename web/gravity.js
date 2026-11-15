// Gravity panel (ROUTE tab): your mass, typed on screen, gives your weight on Mars and the
// work against gravity for each leg's climb.
//
// g at the site: MarsTime.gravity (NASA NSSDC Mars Fact Sheet 2025 constants: GM, J2, radii, rotation;
// tested in pipeline/mars_time.py). NASA's published means: Mars 3.73, Earth 9.82 m/s².
// Work against gravity = m * g * climb (potential energy only).

"use strict";

const Gravity = (function () {
  // Mass typed by the user, in kg: a number > 0 and <= 1000, or null when empty or not valid.
  function parseMass(text) {
    const trimmed = String(text).trim().replace(",", ".");
    if (trimmed === "") {
      return null;
    }
    const value = Number(trimmed);
    return Number.isFinite(value) && value > 0 && value <= 1000 ? value : null;
  }

  function weightNewtons(massKg, gravity) {
    return massKg * gravity;
  }

  // The mass that would weigh the same on Earth (NASA mean Earth gravity).
  function earthEquivalentKg(massKg, gravity, earthGravity) {
    return (massKg * gravity) / earthGravity;
  }

  function climbWorkJoules(massKg, gravity, climbM) {
    return massKg * gravity * climbM;
  }

  return { parseMass: parseMass, weightNewtons: weightNewtons, earthEquivalentKg: earthEquivalentKg, climbWorkJoules: climbWorkJoules };
})();

if (typeof module !== "undefined") {
  module.exports = Gravity;
}

// ---------------------------------------------------------------- browser: ROUTE tab card
// Uses app.js helpers (makeElement, factTable) and MarsTime.

function setUpGravityCard(manifest, routes) {
  const box = manifest.site.bounds_lonlat;
  const latitude = (box[1] + box[3]) / 2;
  // Height above the reference ellipsoid from the site's distance to Mars' centre, when the pack has it.
  const surface = manifest.site.surface_radius || null;
  const heightM = surface !== null ? surface.radius_m - MarsTime.ellipsoidRadius(latitude) : 0;
  const siteGravity = MarsTime.gravity(latitude, heightM);
  const marsMean = MarsTime.GRAVITY.marsMean;
  const earthMean = MarsTime.GRAVITY.earthMean;

  const tab = document.getElementById("tab-route");
  tab.appendChild(makeElement("h2", "section-title", "> GRAVITY · YOUR MASS · ◆ CALCULATED"));
  const card = makeElement("div", "card");
  tab.appendChild(card);

  card.appendChild(
    factTable(
      ["GRAVITY", "m/s²", ""],
      [
        ["THIS SITE (" + latitude.toFixed(2) + "° N, " + (heightM / 1000).toFixed(2) + " km vs ellipsoid)", siteGravity.toFixed(3), "◆ CALCULATED"],
        ["MARS MEAN", marsMean.toFixed(2), "■ NASA DATA"],
        ["EARTH MEAN", earthMean.toFixed(2), "■ NASA DATA"],
        ["MARS / EARTH", (siteGravity / earthMean).toFixed(3), "◆ CALCULATED"],
      ]
    )
  );

  const field = makeElement("label", "antenna-field");
  field.appendChild(makeElement("span", "", "YOUR MASS in kg: you, suit and everything you carry · YOUR VALUE"));
  const input = document.createElement("input");
  input.type = "text";
  input.inputMode = "decimal";
  input.className = "message-input";
  input.placeholder = "type kg";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Your mass in kilograms, including suit and kit");
  field.appendChild(input);
  card.appendChild(field);

  const results = makeElement("div");
  results.setAttribute("aria-live", "polite");
  card.appendChild(results);
  card.appendChild(
    makeElement(
      "p",
      "note",
      "Site gravity: GM, J2, radii and rotation from the NASA NSSDC Mars Fact Sheet (updated 19 May 2025), at " +
        (surface !== null ? "the site's distance from Mars' centre (" + surface.source + "). " : "the reference ellipsoid. ") +
        "Means 3.73 and 9.82 m/s²: same sheet. Work against gravity = mass × g × climb (route climb from the ROUTE table): " +
        "the potential energy gained, not the energy a body or suit spends walking (that depends on speed, terrain and suit, not in our data). " +
        "1 kJ = 0.239 kcal."
    )
  );

  function kilojoules(joules) {
    return (joules / 1000).toFixed(0) + " kJ";
  }

  function update() {
    const mass = Gravity.parseMass(input.value);
    input.classList.toggle("invalid", input.value.trim() !== "" && mass === null);
    results.replaceChildren();
    if (mass === null) {
      results.appendChild(makeElement("p", "dim", "Type your mass (0–1000 kg) to see your weight and the climb work per leg."));
      return;
    }
    const weight = Gravity.weightNewtons(mass, siteGravity);
    results.appendChild(
      factTable(
        ["YOUR WEIGHT", "ON MARS (SITE)", "ON EARTH"],
        [
          ["FORCE", weight.toFixed(0) + " N", Gravity.weightNewtons(mass, earthMean).toFixed(0) + " N"],
          ["SAME WEIGHT AS (on Earth)", Gravity.earthEquivalentKg(mass, siteGravity, earthMean).toFixed(1) + " kg", mass.toFixed(1) + " kg"],
        ]
      )
    );
    const rows = [];
    const totals = { shortest: 0, gentlest: 0 };
    const complete = { shortest: true, gentlest: true };
    for (const leg of routes) {
      const cells = ["LEG " + leg.from + " → " + leg.to];
      for (const kind of ["shortest", "gentlest"]) {
        const route = leg[kind];
        if (route === null) {
          complete[kind] = false;
          cells.push("no data");
          continue;
        }
        const work = Gravity.climbWorkJoules(mass, siteGravity, route.climb_m);
        totals[kind] += work;
        cells.push(kilojoules(work) + " (" + route.climb_m.toFixed(0) + " m up)");
      }
      rows.push(cells);
    }
    rows.push([
      "ALL LEGS",
      complete.shortest ? kilojoules(totals.shortest) : "no data",
      complete.gentlest ? kilojoules(totals.gentlest) : "no data",
    ]);
    rows.push([
      "SAME CLIMB ON EARTH",
      complete.shortest ? kilojoules((totals.shortest * earthMean) / siteGravity) : "no data",
      complete.gentlest ? kilojoules((totals.gentlest * earthMean) / siteGravity) : "no data",
    ]);
    results.appendChild(factTable(["WORK AGAINST GRAVITY", "SHORTEST", "GENTLEST"], rows));
  }
  input.addEventListener("input", update);
  update();
}
