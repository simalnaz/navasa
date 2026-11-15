// Wrist unit showcase: a 3D wrist unit on an EVA suit sleeve, running the real app.
//
// - The scene turns slowly by itself; drag the background to turn it yourself.
// - AUTO DEMO: a fingertip presses the keys, turns the knob and flips the stop
//   switches; the app in the screen reacts. Any click hands control to you.
// - EXPLODED VIEW: the parts move apart in depth, with labels.
// Commands go to the app with postMessage, to this same site only.

"use strict";

const SCENE_WIDTH = 1700;
const SCENE_HEIGHT = 760;
const KNOB_STEP_DEG = 30;
const MAX_TURN_DEG = 40;
const DRAG_DEG_PER_PX = 0.25;

const view = {
  scale: 1,
  turnX: 12, // degrees around the horizontal axis
  turnY: -18, // degrees around the vertical axis
  targetX: 12,
  targetY: -18,
  dragging: false,
  userTurned: false,
  tilted: false,
};
let knobAngle = 0;
let demoRunning = true;
let demoTimer = null;

// ------------------------------------------------------------ talking to the app

function sendToScreen(command) {
  const frame = document.getElementById("screen-frame");
  if (frame.contentWindow) {
    frame.contentWindow.postMessage(command, window.location.origin);
  }
}

function markActiveKey(tab) {
  for (const key of document.querySelectorAll(".key")) {
    key.setAttribute("aria-pressed", key.dataset.tab === tab ? "true" : "false");
  }
}

function pressKey(tab) {
  markActiveKey(tab);
  sendToScreen({ type: "navasa:tab", tab: tab });
}

// The knob steps through the map layers; the app opens the MAP tab and answers with the layer name.
function turnKnob(direction) {
  knobAngle += direction === "next" ? KNOB_STEP_DEG : -KNOB_STEP_DEG;
  // Only the dial inside turns; the button itself never moves, so it keeps its clicks in 3D.
  document.getElementById("knob-dial").style.transform = "rotate(" + knobAngle + "deg)";
  markActiveKey("map");
  sendToScreen({ type: "navasa:layer", direction: direction });
}

function listenToScreen() {
  window.addEventListener("message", function (event) {
    const frame = document.getElementById("screen-frame");
    if (event.origin !== window.location.origin || event.source !== frame.contentWindow) {
      return;
    }
    const message = event.data;
    if (typeof message === "object" && message !== null && message.type === "navasa:layer-shown" && typeof message.name === "string") {
      document.getElementById("knob-label").textContent = message.name; // textContent: never parsed as HTML
    }
  });
}

function stepStop(direction) {
  pressKey("hud");
  sendToScreen({ type: "navasa:stop", direction: direction });
}

// ------------------------------------------------------------ 3D view

function fitScene() {
  const stage = document.getElementById("stage");
  view.scale = Math.min(stage.clientWidth / SCENE_WIDTH, stage.clientHeight / SCENE_HEIGHT) * 0.86;
}

function clamp(value, limit) {
  return Math.max(-limit, Math.min(limit, value));
}

function animateView(time) {
  if (!view.dragging && !view.userTurned) {
    if (view.tilted) {
      view.targetX = 32;
      view.targetY = -10;
    } else {
      // slow showcase sway
      view.targetX = 12 + 4 * Math.sin(time / 4100);
      view.targetY = -18 + 22 * Math.sin(time / 5200);
    }
  }
  view.turnX += (view.targetX - view.turnX) * 0.08;
  view.turnY += (view.targetY - view.turnY) * 0.08;
  document.getElementById("scene").style.transform =
    "translate(-50%, -50%) scale(" + view.scale.toFixed(3) + ") rotateX(" + view.turnX.toFixed(2) + "deg) rotateY(" + view.turnY.toFixed(2) + "deg)";
  window.requestAnimationFrame(animateView);
}

function setUpDragging() {
  const stage = document.getElementById("stage");
  let startX = 0;
  let startY = 0;
  let fromX = 0;
  let fromY = 0;
  stage.addEventListener("pointerdown", function (event) {
    if (event.target.closest(".unit")) {
      return; // controls and screen keep their own clicks
    }
    view.dragging = true;
    view.userTurned = true;
    stopDemo();
    stage.classList.add("dragging");
    startX = event.clientX;
    startY = event.clientY;
    fromX = view.targetX;
    fromY = view.targetY;
    stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener("pointermove", function (event) {
    if (!view.dragging) {
      return;
    }
    view.targetY = clamp(fromY + (event.clientX - startX) * DRAG_DEG_PER_PX, MAX_TURN_DEG);
    view.targetX = clamp(fromX - (event.clientY - startY) * DRAG_DEG_PER_PX, MAX_TURN_DEG);
  });
  function endDrag() {
    view.dragging = false;
    stage.classList.remove("dragging");
  }
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);
}

// ------------------------------------------------------------ demo finger

// Position of an element in scene pixels (before the scene's own transform).
function positionInScene(element) {
  const scene = document.getElementById("scene");
  let left = element.offsetWidth / 2;
  let top = element.offsetHeight / 2;
  let current = element;
  while (current !== null && current !== scene) {
    left += current.offsetLeft;
    top += current.offsetTop;
    current = current.offsetParent;
  }
  return { left: left, top: top };
}

function wait(milliseconds) {
  return new Promise(function (resolve) {
    demoTimer = setTimeout(resolve, milliseconds);
  });
}

async function fingerPress(element, action) {
  if (!demoRunning) {
    return;
  }
  const finger = document.getElementById("finger");
  const target = positionInScene(element);
  finger.classList.add("visible");
  finger.style.left = target.left + "px";
  finger.style.top = target.top + "px";
  await wait(800);
  if (!demoRunning) {
    return;
  }
  finger.classList.add("tapping");
  element.classList.add("pressed");
  action();
  await wait(220);
  finger.classList.remove("tapping");
  element.classList.remove("pressed");
  await wait(250);
}

async function runDemo() {
  const key = function (tab) {
    return document.querySelector('.key[data-tab="' + tab + '"]');
  };
  const knob = document.getElementById("layer-knob");
  const next = document.getElementById("stop-next");
  const previous = document.getElementById("stop-previous");
  await wait(2500); // let the app start in the screen
  while (demoRunning) {
    await fingerPress(key("map"), function () { pressKey("map"); });
    await wait(1800);
    await fingerPress(knob, function () { turnKnob("next"); }); // slope
    await wait(1800);
    await fingerPress(knob, function () { turnKnob("next"); }); // rock units
    await wait(1800);
    await fingerPress(knob, function () { turnKnob("previous"); });
    await fingerPress(knob, function () { turnKnob("previous"); }); // back to image only
    await wait(1200);
    await fingerPress(key("route"), function () { pressKey("route"); });
    await wait(2500);
    await fingerPress(key("stops"), function () { pressKey("stops"); });
    await wait(2500);
    await fingerPress(key("sun"), function () { pressKey("sun"); });
    await wait(2500);
    await fingerPress(key("hud"), function () { pressKey("hud"); });
    await wait(1500);
    await fingerPress(next, function () { stepStop("next"); });
    await wait(1600);
    await fingerPress(next, function () { stepStop("next"); });
    await wait(1600);
    await fingerPress(previous, function () { stepStop("previous"); });
    await fingerPress(previous, function () { stepStop("previous"); });
    await wait(2000);
  }
}

function stopDemo() {
  if (!demoRunning) {
    return;
  }
  demoRunning = false;
  clearTimeout(demoTimer);
  document.getElementById("finger").classList.remove("visible", "tapping");
  document.getElementById("demo-button").setAttribute("aria-pressed", "false");
}

function startDemo() {
  demoRunning = true;
  view.userTurned = false;
  document.getElementById("demo-button").setAttribute("aria-pressed", "true");
  runDemo();
}

// ------------------------------------------------------------ screen

async function loadScreen() {
  // Start the first mission from the mission list directly in the wrist view.
  let missionHash = "";
  try {
    const response = await fetch("missions.json");
    if (response.ok) {
      const missions = await response.json();
      if (Array.isArray(missions) && missions.length > 0 && /^[A-Za-z0-9_-]+$/.test(missions[0].id)) {
        missionHash = "#mission=" + missions[0].id;
      }
    }
  } catch (error) {
    // Without the list the screen shows the app's own mission select.
  }
  document.getElementById("screen-frame").src = "index.html?view=wrist" + missionHash;
}

// ------------------------------------------------------------ start

function start() {
  // Real controls: a click by the viewer stops the demo first.
  for (const key of document.querySelectorAll(".key")) {
    key.addEventListener("click", function (event) {
      if (event.isTrusted) {
        stopDemo();
      }
      pressKey(key.dataset.tab);
    });
  }
  markActiveKey("hud"); // the app opens on the MISSION tab

  function viewerAction(handler) {
    return function (event) {
      if (event.isTrusted) {
        stopDemo();
      }
      handler();
    };
  }
  document.getElementById("layer-next").addEventListener("click", viewerAction(function () { turnKnob("next"); }));
  document.getElementById("layer-previous").addEventListener("click", viewerAction(function () { turnKnob("previous"); }));
  const knob = document.getElementById("layer-knob");
  knob.addEventListener("click", viewerAction(function () { turnKnob("next"); }));
  knob.addEventListener(
    "wheel",
    function (event) {
      event.preventDefault();
      stopDemo();
      turnKnob(event.deltaY < 0 ? "next" : "previous");
    },
    { passive: false }
  );
  document.getElementById("stop-previous").addEventListener("click", viewerAction(function () { stepStop("previous"); }));
  document.getElementById("stop-next").addEventListener("click", viewerAction(function () { stepStop("next"); }));

  document.getElementById("demo-button").addEventListener("click", function () {
    if (demoRunning) {
      stopDemo();
    } else {
      startDemo();
    }
  });
  const explodeButton = document.getElementById("explode-button");
  explodeButton.addEventListener("click", function () {
    const exploded = document.getElementById("scene").classList.toggle("exploded");
    explodeButton.setAttribute("aria-pressed", exploded ? "true" : "false");
    if (exploded) {
      view.userTurned = true;
      view.targetX = 22;
      view.targetY = -32;
    }
  });
  const tiltButton = document.getElementById("tilt-button");
  tiltButton.addEventListener("click", function () {
    view.tilted = !view.tilted;
    view.userTurned = false;
    tiltButton.setAttribute("aria-pressed", view.tilted ? "true" : "false");
  });

  window.addEventListener("resize", fitScene);
  fitScene();
  setUpDragging();
  listenToScreen();
  window.requestAnimationFrame(animateView);
  loadScreen();

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    stopDemo();
    view.userTurned = true;
  } else {
    runDemo();
  }
}

document.addEventListener("DOMContentLoaded", start);
