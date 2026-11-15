// Earth link: light time between Mars and Earth and the SEND message simulation.
// Positions: MarsTime.earthLink (Mars24 D-2..D-4 for Mars, JPL Table 1 for Earth), ecliptic J2000, AU.
// No DOM here, so the maths can be checked with node.

"use strict";

const Comms = (function () {
  const MS_PER_S = 1000;

  // A message sent from Mars at sendMs reaches Earth one light time later; the earliest
  // reply reaches Mars one more light time later (no time to read or answer counted).
  // Light time at the send moment is used for both ways (Earth and Mars move < 0.01 AU meanwhile).
  function messageTimeline(sendMs, oneWaySeconds) {
    return {
      sent: sendMs,
      arrivesEarth: sendMs + oneWaySeconds * MS_PER_S,
      earliestReply: sendMs + 2 * oneWaySeconds * MS_PER_S,
    };
  }

  // State of a message at a moment: "to-earth" (fraction 0..1 along the way), "to-mars" (the
  // earliest possible reply on its way), or "done".
  function messageState(timeline, nowMs) {
    if (nowMs < timeline.arrivesEarth) {
      return { phase: "to-earth", fraction: Math.max(0, (nowMs - timeline.sent) / (timeline.arrivesEarth - timeline.sent)) };
    }
    if (nowMs < timeline.earliestReply) {
      return { phase: "to-mars", fraction: (nowMs - timeline.arrivesEarth) / (timeline.earliestReply - timeline.arrivesEarth) };
    }
    return { phase: "done", fraction: 1 };
  }

  // Orbit paths for the diagram: positions over one orbital period, [x, y] in AU.
  function orbitPath(positionAt, startMs, periodDays, samples) {
    const points = [];
    for (let index = 0; index <= samples; index++) {
      const xyz = positionAt(startMs + (index / samples) * periodDays * 86400000);
      points.push([xyz[0], xyz[1]]);
    }
    return points;
  }

  function formatDuration(seconds) {
    const total = Math.round(seconds);
    const minutes = Math.floor(total / 60);
    return minutes + " min " + String(total % 60).padStart(2, "0") + " s";
  }

  return { messageTimeline: messageTimeline, messageState: messageState, orbitPath: orbitPath, formatDuration: formatDuration };
})();

if (typeof module !== "undefined") {
  module.exports = Comms;
}
