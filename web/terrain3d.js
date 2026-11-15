// 3D terrain view: the HiRISE height model (NASA data) as a surface, with the map layer
// that is on laid over it, plus the routes and stops.
//
// - Heights: the elevation readout of the pack (one sample every 4 m), meshed every 16 m.
// - Picture: the same map tiles as the 2D map, stitched at zoom -2 (4 m per pixel).
// - Height can be exaggerated; the factor is always on screen and labelled as a display choice.
// - Opening flies from straight overhead (like the 2D map) to a tilted view; closing flies back.
// - Drawn only when something changes, so it costs nothing while you are not touching it.
//
// app.js uses it through window.navasaTerrain3d: open(container, scene), close(), setLayer(id, name).

import * as THREE from "./vendor/three/three.module.min.js";

const DEFAULT_TERRAIN = {
  textureZoom: -2, // map zoom of the stitched picture: 4 m per pixel, same as the elevation readout
  meshEverySamples: 4, // readout samples per mesh step: 4 x 4 m = a vertex every 16 m
  overlayOpacity: 0.65, // display choice: data layer over the HiRISE image
  heightScales: [1, 2, 3, 5],
  startHeightScaleIndex: 0, // x1 true scale: the 718 m of relief (delta to crater floor) already shows
  routeLiftM: 2, // routes float this far above the ground so they are never buried
  routeRadiusM: 12, // thick enough to see when the whole 10 km area is on screen
  routeStepM: 8, // routes are resampled this often so long straight legs follow the ground
  stopLabelSizeM: 160,
  stopPoleM: 120,
  fieldOfViewDeg: 45,
  openTiltDeg: 58, // 0 = straight down
  openAzimuthDeg: -20,
  overheadTiltDeg: 0.5, // not exactly 0: the camera's up direction must not line up with its view
  maxTiltDeg: 82,
  flyMs: 1400,
  dragDegPerPx: 0.3,
};

const state = {
  renderer: null,
  camera: null,
  world: null, // THREE.Scene
  container: null,
  root: null, // the overlay element
  info: null, // { manifest, stops, routes, packUrl }
  terrain: null, // { heights, columns, rows, noData, hMin, mesh, texture, canvas }
  routesGroup: null,
  stopsGroup: null,
  heightScaleIndex: DEFAULT_TERRAIN.startHeightScaleIndex,
  layerId: null,
  layerName: "IMAGE ONLY",
  tileCanvases: {}, // layer id -> stitched canvas, so turning the knob back is instant
  view: { azimuthDeg: 0, tiltDeg: 0, distance: 1000, fitDistance: 1000 },
  renderQueued: false,
  flying: null,
  isOpen: false,
  pointers: new Map(),
  resizeObserver: null,
  labels: {},
};

// ------------------------------------------------------------ data

function loadImage(url) {
  return new Promise(function (resolve, reject) {
    const image = new Image();
    image.onload = function () {
      resolve(image);
    };
    image.onerror = function () {
      reject(new Error("Could not load " + url));
    };
    image.src = url;
  });
}

// Same coding as the cursor readout: red = high byte, green = low byte.
async function loadHeights(manifest, packUrl) {
  let readout = null;
  for (const candidate of manifest.readouts || []) {
    if (candidate.id === "elevation") {
      readout = candidate;
    }
  }
  if (readout === null) {
    throw new Error("This data pack has no elevation readout, so there is no 3D view.");
  }
  const image = await loadImage(packUrl(readout.file));
  const canvas = document.createElement("canvas");
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(image, 0, 0);
  const pixels = context.getImageData(0, 0, image.width, image.height).data;
  const values = new Float32Array(image.width * image.height);
  for (let index = 0; index < values.length; index += 1) {
    const code = pixels[index * 4] * 256 + pixels[index * 4 + 1];
    values[index] = code === readout.no_data_code ? NaN : readout.base + code * readout.step;
  }
  return { values: values, width: image.width, height: image.height, everyPx: readout.sample_every_px };
}

// Ground height (m) at a grid position, from the nearest 4 m sample. NaN where there is no data.
function heightAtGrid(col, row) {
  const samples = state.terrain.samples;
  const x = Math.min(samples.width - 1, Math.max(0, Math.round(col / samples.everyPx)));
  const y = Math.min(samples.height - 1, Math.max(0, Math.round(row / samples.everyPx)));
  return samples.values[y * samples.width + x];
}

function findLayer(layerId) {
  for (const layer of state.info.manifest.layers) {
    if (layer.id === layerId) {
      return layer;
    }
  }
  return null;
}

// Stitch one layer's tiles into a single picture of the walk area.
async function stitchLayer(layerId) {
  if (state.tileCanvases[layerId] !== undefined) {
    return state.tileCanvases[layerId];
  }
  const layer = findLayer(layerId);
  if (layer === null || !layer.tiles) {
    throw new Error("Unknown map layer " + layerId);
  }
  const grid = state.info.manifest.grid;
  const tiles = layer.tiles;
  const zoom = Math.min(tiles.max_zoom, Math.max(tiles.min_zoom, DEFAULT_TERRAIN.textureZoom));
  const zoomScale = Math.pow(2, zoom);
  const drawScale = Math.pow(2, DEFAULT_TERRAIN.textureZoom) / zoomScale; // tile pixels -> canvas pixels
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(grid.width * Math.pow(2, DEFAULT_TERRAIN.textureZoom));
  canvas.height = Math.ceil(grid.height * Math.pow(2, DEFAULT_TERRAIN.textureZoom));
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = layer.kind === "imagery"; // data layers keep sharp cell edges

  const tileColumns = Math.ceil((grid.width * zoomScale) / tiles.tile_size);
  const tileRows = Math.ceil((grid.height * zoomScale) / tiles.tile_size);
  const jobs = [];
  let missing = 0;
  for (let tileY = 0; tileY < tileRows; tileY += 1) {
    for (let tileX = 0; tileX < tileColumns; tileX += 1) {
      const url = state.info.packUrl(
        tiles.url.replace("{z}", String(zoom)).replace("{x}", String(tileX)).replace("{y}", String(tileY))
      );
      jobs.push(
        loadImage(url).then(
          function (image) {
            const size = tiles.tile_size * drawScale;
            context.drawImage(image, tileX * size, tileY * size, size, size);
          },
          function () {
            missing += 1;
          }
        )
      );
    }
  }
  await Promise.all(jobs);
  if (missing > 0) {
    console.warn("3D view: " + missing + " of " + jobs.length + " tiles of " + layerId + " could not be loaded; those parts stay blank.");
  }
  state.tileCanvases[layerId] = canvas;
  return canvas;
}

// The picture on the surface: the HiRISE image, with the chosen data layer over it.
async function paintSurface() {
  const base = await stitchLayer("hirise");
  const picture = state.terrain.canvas;
  const context = picture.getContext("2d");
  context.globalAlpha = 1;
  context.drawImage(base, 0, 0);
  if (state.layerId !== null) {
    const overlay = await stitchLayer(state.layerId);
    context.globalAlpha = DEFAULT_TERRAIN.overlayOpacity;
    context.drawImage(overlay, 0, 0);
    context.globalAlpha = 1;
  }
  state.terrain.texture.needsUpdate = true;
  state.labels.layer.textContent = state.layerName;
  requestRender();
}

// ------------------------------------------------------------ geometry

function heightScale() {
  return DEFAULT_TERRAIN.heightScales[state.heightScaleIndex];
}

// Grid position -> 3D position in ground metres, centred on the walk area. North is -z.
function toWorld(col, row, heightM) {
  const grid = state.info.manifest.grid;
  const eastScale = typeof grid.east_scale === "number" ? grid.east_scale : 1;
  const x = (col - grid.width / 2) * grid.metres_per_pixel * eastScale;
  const z = (row - grid.height / 2) * grid.metres_per_pixel;
  const y = (heightM - state.terrain.hMin) * heightScale();
  return new THREE.Vector3(x, y, z);
}

function buildTerrainMesh(samples) {
  const step = DEFAULT_TERRAIN.meshEverySamples;
  const columns = Math.floor((samples.width - 1) / step) + 1;
  const rows = Math.floor((samples.height - 1) / step) + 1;
  const heights = new Float32Array(columns * rows);
  let hMin = Infinity;
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < columns; col += 1) {
      const value = samples.values[row * step * samples.width + col * step];
      heights[row * columns + col] = value;
      if (!Number.isNaN(value) && value < hMin) {
        hMin = value;
      }
    }
  }
  if (hMin === Infinity) {
    throw new Error("The elevation readout has no data cells.");
  }

  const grid = state.info.manifest.grid;
  const textureWidth = Math.ceil(grid.width * Math.pow(2, DEFAULT_TERRAIN.textureZoom));
  const textureHeight = Math.ceil(grid.height * Math.pow(2, DEFAULT_TERRAIN.textureZoom));
  const positions = new Float32Array(columns * rows * 3);
  const uvs = new Float32Array(columns * rows * 2);
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < columns; col += 1) {
      const index = row * columns + col;
      const gridCol = col * step * samples.everyPx;
      const gridRow = row * step * samples.everyPx;
      uvs[index * 2] = (gridCol * Math.pow(2, DEFAULT_TERRAIN.textureZoom)) / textureWidth;
      uvs[index * 2 + 1] = 1 - (gridRow * Math.pow(2, DEFAULT_TERRAIN.textureZoom)) / textureHeight;
      positions[index * 3] = gridCol; // turned into metres in placeVertices
      positions[index * 3 + 2] = gridRow;
    }
  }

  // Two triangles per square, left out wherever a corner has no height data.
  const indices = [];
  for (let row = 0; row < rows - 1; row += 1) {
    for (let col = 0; col < columns - 1; col += 1) {
      const topLeft = row * columns + col;
      const topRight = topLeft + 1;
      const bottomLeft = topLeft + columns;
      const bottomRight = bottomLeft + 1;
      if (Number.isNaN(heights[topLeft]) || Number.isNaN(heights[topRight]) ||
          Number.isNaN(heights[bottomLeft]) || Number.isNaN(heights[bottomRight])) {
        continue;
      }
      indices.push(topLeft, bottomLeft, topRight, topRight, bottomLeft, bottomRight);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
  geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(indices), 1));

  const canvas = document.createElement("canvas");
  canvas.width = textureWidth;
  canvas.height = textureHeight;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = state.renderer.capabilities.getMaxAnisotropy();
  const material = new THREE.MeshLambertMaterial({ map: texture });
  const mesh = new THREE.Mesh(geometry, material);

  state.terrain = {
    samples: samples,
    heights: heights,
    columns: columns,
    rows: rows,
    hMin: hMin,
    mesh: mesh,
    canvas: canvas,
    texture: texture,
    gridPositions: positions.slice(), // grid col/row, kept to re-place vertices
  };
  state.world.add(mesh);
}

// Put every vertex at its ground position for the current height scale.
function placeVertices() {
  const terrain = state.terrain;
  const positions = terrain.mesh.geometry.attributes.position.array;
  for (let index = 0; index < terrain.heights.length; index += 1) {
    const height = Number.isNaN(terrain.heights[index]) ? terrain.hMin : terrain.heights[index];
    const point = toWorld(terrain.gridPositions[index * 3], terrain.gridPositions[index * 3 + 2], height);
    positions[index * 3] = point.x;
    positions[index * 3 + 1] = point.y;
    positions[index * 3 + 2] = point.z;
  }
  terrain.mesh.geometry.attributes.position.needsUpdate = true;
  terrain.mesh.geometry.computeVertexNormals();
  terrain.mesh.geometry.computeBoundingSphere();
}

function cssColor(name) {
  return new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
}

// A route as a tube that follows the ground: resampled every few metres, lifted a little.
function routeTube(points, color) {
  const grid = state.info.manifest.grid;
  const stepPx = DEFAULT_TERRAIN.routeStepM / grid.metres_per_pixel;
  const path = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const from = points[index];
    const to = points[index + 1];
    const steps = Math.max(1, Math.ceil(Math.hypot(to[0] - from[0], to[1] - from[1]) / stepPx));
    for (let step = 0; step < steps; step += 1) {
      const col = from[0] + ((to[0] - from[0]) * step) / steps;
      const row = from[1] + ((to[1] - from[1]) * step) / steps;
      const height = heightAtGrid(col, row);
      if (!Number.isNaN(height)) {
        path.push(toWorld(col, row, height + DEFAULT_TERRAIN.routeLiftM / heightScale()));
      }
    }
  }
  const last = points[points.length - 1];
  const lastHeight = heightAtGrid(last[0], last[1]);
  if (!Number.isNaN(lastHeight)) {
    path.push(toWorld(last[0], last[1], lastHeight + DEFAULT_TERRAIN.routeLiftM / heightScale()));
  }
  if (path.length < 2) {
    return null;
  }
  const curve = new THREE.CatmullRomCurve3(path, false, "centripetal");
  const geometry = new THREE.TubeGeometry(curve, path.length, DEFAULT_TERRAIN.routeRadiusM, 5, false);
  return new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: color }));
}

function stopLabel(text) {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const context = canvas.getContext("2d");
  context.fillStyle = "rgba(5, 8, 6, 0.85)";
  context.fillRect(0, 0, 64, 64);
  context.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--text").trim();
  context.lineWidth = 4;
  context.strokeRect(2, 2, 60, 60);
  context.fillStyle = context.strokeStyle;
  context.font = "bold 36px ui-monospace, Menlo, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 32, 34);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false }));
  sprite.scale.set(DEFAULT_TERRAIN.stopLabelSizeM, DEFAULT_TERRAIN.stopLabelSizeM, 1);
  sprite.renderOrder = 2;
  return sprite;
}

function buildRoutesAndStops() {
  for (const group of [state.routesGroup, state.stopsGroup]) {
    if (group !== null) {
      state.world.remove(group);
      group.traverse(function (part) {
        if (part.geometry) {
          part.geometry.dispose();
        }
        if (part.material) {
          if (part.material.map) {
            part.material.map.dispose();
          }
          part.material.dispose();
        }
      });
    }
  }
  state.routesGroup = new THREE.Group();
  const colors = { shortest: cssColor("--shortest"), gentlest: cssColor("--gentlest") };
  for (const leg of state.info.routes) {
    for (const kind of ["shortest", "gentlest"]) {
      if (leg[kind] === null) {
        continue; // no data for this route
      }
      const tube = routeTube(leg[kind].points, colors[kind]);
      if (tube !== null) {
        state.routesGroup.add(tube);
      }
    }
  }
  state.world.add(state.routesGroup);

  state.stopsGroup = new THREE.Group();
  const poleMaterial = new THREE.LineBasicMaterial({ color: cssColor("--text") });
  for (const stop of state.info.stops) {
    const height = heightAtGrid(stop.position[0], stop.position[1]);
    if (Number.isNaN(height)) {
      console.warn("3D view: stop " + stop.id + " has no height data; it is not shown in 3D.");
      continue;
    }
    const ground = toWorld(stop.position[0], stop.position[1], height);
    const top = ground.clone();
    top.y += DEFAULT_TERRAIN.stopPoleM;
    const pole = new THREE.Line(new THREE.BufferGeometry().setFromPoints([ground, top]), poleMaterial);
    const label = stopLabel(String(stop.id));
    label.position.copy(top);
    state.stopsGroup.add(pole);
    state.stopsGroup.add(label);
  }
  state.world.add(state.stopsGroup);
}

// ------------------------------------------------------------ camera

function degToRad(degrees) {
  return (degrees * Math.PI) / 180;
}

function placeCamera() {
  const view = state.view;
  const tilt = degToRad(view.tiltDeg);
  const azimuth = degToRad(view.azimuthDeg);
  state.camera.position.set(
    view.distance * Math.sin(tilt) * Math.sin(azimuth),
    view.distance * Math.cos(tilt),
    view.distance * Math.sin(tilt) * Math.cos(azimuth)
  );
  state.camera.lookAt(0, 0, 0);
  state.camera.near = Math.max(1, view.distance / 200);
  state.camera.far = view.distance * 6;
  state.camera.updateProjectionMatrix();
}

// Distance at which the whole walk area fits on screen, seen from straight above.
function fitDistance() {
  const grid = state.info.manifest.grid;
  const eastScale = typeof grid.east_scale === "number" ? grid.east_scale : 1;
  const halfWidth = (grid.width * grid.metres_per_pixel * eastScale) / 2;
  const halfHeight = (grid.height * grid.metres_per_pixel) / 2;
  const halfAngle = degToRad(DEFAULT_TERRAIN.fieldOfViewDeg / 2);
  return Math.max(halfHeight / Math.tan(halfAngle), halfWidth / (Math.tan(halfAngle) * state.camera.aspect)) * 1.05;
}

function easeInOut(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// Move the camera smoothly to a target view; resolves when it arrives.
function flyTo(target) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion) {
    Object.assign(state.view, target);
    requestRender();
    return Promise.resolve();
  }
  const from = { azimuthDeg: state.view.azimuthDeg, tiltDeg: state.view.tiltDeg, distance: state.view.distance };
  const startTime = performance.now();
  return new Promise(function (resolve) {
    let finished = false;
    function finish() {
      if (finished) {
        return;
      }
      finished = true;
      clearTimeout(fallback);
      Object.assign(state.view, target);
      state.flying = null;
      requestRender();
      resolve();
    }
    // Animation frames stop in a hidden tab; this makes sure the fly always ends.
    const fallback = setTimeout(finish, DEFAULT_TERRAIN.flyMs + 300);
    state.flying = function (now) {
      const t = Math.min(1, (now - startTime) / DEFAULT_TERRAIN.flyMs);
      const k = easeInOut(t);
      state.view.azimuthDeg = from.azimuthDeg + (target.azimuthDeg - from.azimuthDeg) * k;
      state.view.tiltDeg = from.tiltDeg + (target.tiltDeg - from.tiltDeg) * k;
      state.view.distance = from.distance + (target.distance - from.distance) * k;
      if (t >= 1) {
        finish();
      }
    };
    requestRender();
  });
}

function requestRender() {
  if (state.renderQueued || state.renderer === null) {
    return;
  }
  state.renderQueued = true;
  window.requestAnimationFrame(function (now) {
    state.renderQueued = false;
    if (state.flying !== null) {
      state.flying(now);
    }
    placeCamera();
    state.renderer.render(state.world, state.camera);
    if (state.flying !== null) {
      requestRender();
    }
  });
}

// One finger / mouse: turn and tilt. Two fingers: pinch to zoom. Wheel: zoom.
function setUpControls(canvas) {
  let lastPinch = null;
  canvas.addEventListener("pointerdown", function (event) {
    if (state.flying !== null) {
      return;
    }
    canvas.setPointerCapture(event.pointerId);
    state.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    lastPinch = null;
  });
  canvas.addEventListener("pointermove", function (event) {
    const previous = state.pointers.get(event.pointerId);
    if (previous === undefined) {
      return;
    }
    const current = { x: event.clientX, y: event.clientY };
    state.pointers.set(event.pointerId, current);
    if (state.pointers.size === 1) {
      state.view.azimuthDeg -= (current.x - previous.x) * DEFAULT_TERRAIN.dragDegPerPx;
      state.view.tiltDeg = Math.min(
        DEFAULT_TERRAIN.maxTiltDeg,
        Math.max(DEFAULT_TERRAIN.overheadTiltDeg, state.view.tiltDeg - (current.y - previous.y) * DEFAULT_TERRAIN.dragDegPerPx)
      );
    } else if (state.pointers.size === 2) {
      const points = Array.from(state.pointers.values());
      const spread = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      if (lastPinch !== null && spread > 0) {
        zoomBy(lastPinch / spread);
      }
      lastPinch = spread;
    }
    requestRender();
  });
  function release(event) {
    state.pointers.delete(event.pointerId);
    lastPinch = null;
  }
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener(
    "wheel",
    function (event) {
      event.preventDefault();
      if (state.flying === null) {
        zoomBy(Math.exp(event.deltaY * 0.001));
        requestRender();
      }
    },
    { passive: false }
  );
}

function zoomBy(factor) {
  const view = state.view;
  view.distance = Math.min(view.fitDistance * 2, Math.max(view.fitDistance * 0.08, view.distance * factor));
}

// ------------------------------------------------------------ overlay

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function heightLabelText() {
  return "HEIGHT ×" + heightScale() + (heightScale() === 1 ? " (TRUE SCALE)" : " (DISPLAY CHOICE)");
}

function buildOverlay(container) {
  const root = makeElement("div", "terrain-3d");
  // The overlay sits inside the Leaflet map: keep its drags and wheel turns away from the map.
  for (const type of ["pointerdown", "mousedown", "touchstart", "wheel", "dblclick", "click"]) {
    root.addEventListener(type, function (event) {
      event.stopPropagation();
    }, { passive: type !== "wheel" });
  }
  const bar = makeElement("div", "terrain-3d-bar");
  state.labels.layer = makeElement("span", "terrain-3d-layer", state.layerName);
  const heightButton = makeElement("button", "terrain-3d-height", heightLabelText());
  heightButton.type = "button";
  heightButton.addEventListener("click", function () {
    state.heightScaleIndex = (state.heightScaleIndex + 1) % DEFAULT_TERRAIN.heightScales.length;
    heightButton.textContent = heightLabelText();
    placeVertices();
    buildRoutesAndStops();
    requestRender();
  });
  bar.appendChild(state.labels.layer);
  bar.appendChild(heightButton);
  const note = makeElement(
    "p",
    "terrain-3d-note",
    "■ NASA DATA · HiRISE DTM heights, mesh every 16 m · drag to turn · scroll or pinch to zoom"
  );
  state.labels.status = makeElement("p", "terrain-3d-status", "BUILDING 3D TERRAIN…");
  root.appendChild(bar);
  root.appendChild(state.labels.status);
  root.appendChild(note);
  container.appendChild(root);
  return root;
}

// ------------------------------------------------------------ public

async function open(container, scene) {
  if (state.isOpen) {
    return;
  }
  state.isOpen = true;
  state.layerId = scene.layerId;
  state.layerName = scene.layerName;

  if (state.renderer === null || state.container !== container) {
    state.info = { manifest: scene.manifest, stops: scene.stops, routes: scene.routes, packUrl: scene.packUrl };
    state.container = container;
    state.root = buildOverlay(container);
    state.renderer = new THREE.WebGLRenderer({ antialias: true });
    state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    state.renderer.setClearColor(new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--background-deep").trim()));
    const canvas = state.renderer.domElement;
    canvas.className = "terrain-3d-canvas";
    canvas.setAttribute("aria-label", "3D view of the walk area: HiRISE heights with the chosen map layer");
    state.root.insertBefore(canvas, state.root.firstChild);
    state.camera = new THREE.PerspectiveCamera(DEFAULT_TERRAIN.fieldOfViewDeg, 1, 1, 100000);
    state.world = new THREE.Scene();
    state.world.add(new THREE.AmbientLight(0xffffff, 1.6));
    const sunlight = new THREE.DirectionalLight(0xffffff, 1.4);
    sunlight.position.set(-1, 1.2, -0.6); // from the north-west, like the usual map convention
    state.world.add(sunlight);
    setUpControls(canvas);
    state.resizeObserver = new ResizeObserver(function () {
      const width = state.root.clientWidth;
      const height = state.root.clientHeight;
      if (width === 0 || height === 0) {
        return;
      }
      state.renderer.setSize(width, height, false);
      state.camera.aspect = width / height;
      state.view.fitDistance = fitDistance();
      requestRender();
    });
    state.resizeObserver.observe(state.root);

    state.root.hidden = false;
    try {
      const samples = await loadHeights(scene.manifest, scene.packUrl);
      buildTerrainMesh(samples);
      placeVertices();
      buildRoutesAndStops();
    } catch (error) {
      state.labels.status.textContent = "3D VIEW UNAVAILABLE: " + error.message;
      console.error(error);
      state.isOpen = false;
      throw error;
    }
  }
  state.root.hidden = false;
  container.classList.add("showing-3d"); // hides the 2D map's controls (see terrain3d.css)
  state.labels.status.textContent = "BUILDING 3D TERRAIN…";
  state.labels.status.hidden = false;
  state.camera.aspect = Math.max(1, state.root.clientWidth) / Math.max(1, state.root.clientHeight);
  state.view.fitDistance = fitDistance();
  try {
    await paintSurface();
  } catch (error) {
    state.labels.status.textContent = "3D VIEW UNAVAILABLE: " + error.message;
    console.error(error);
    state.isOpen = false;
    throw error;
  }
  state.labels.status.hidden = true;
  // Start where the 2D map is (straight down, north up), then tilt into 3D.
  state.view.azimuthDeg = 0;
  state.view.tiltDeg = DEFAULT_TERRAIN.overheadTiltDeg;
  state.view.distance = state.view.fitDistance;
  await flyTo({
    azimuthDeg: DEFAULT_TERRAIN.openAzimuthDeg,
    tiltDeg: DEFAULT_TERRAIN.openTiltDeg,
    distance: state.view.fitDistance * 0.75,
  });
}

async function close() {
  if (!state.isOpen) {
    return;
  }
  state.isOpen = false;
  await flyTo({ azimuthDeg: 0, tiltDeg: DEFAULT_TERRAIN.overheadTiltDeg, distance: state.view.fitDistance });
  state.root.hidden = true;
  state.container.classList.remove("showing-3d");
}

function setLayer(layerId, layerName) {
  state.layerId = layerId;
  state.layerName = layerName;
  if (state.isOpen && state.terrain !== null) {
    paintSurface().catch(function (error) {
      state.labels.status.textContent = "LAYER UNAVAILABLE IN 3D: " + error.message;
      state.labels.status.hidden = false;
      console.error(error);
    });
  }
}

window.navasaTerrain3d = {
  open: open,
  close: close,
  setLayer: setLayer,
  isOpen: function () {
    return state.isOpen;
  },
};
