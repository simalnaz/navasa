// Orbit view: a rotating Mars globe drawn on a canvas from a global
// longitude/latitude image, with a marker for each mission site.
//
// Each screen pixel inside the disc is turned back into latitude/longitude
// (orthographic projection, inverse formulas) and coloured from the image.
// Lighting is a display choice only (a fixed light direction).

"use strict";

const NavasaGlobe = (function () {
  const DEGREES = Math.PI / 180;
  const LIGHT = normalise([-0.45, 0.35, 0.82]); // display choice
  const SPIN_DEG_PER_SECOND = 6;

  function normalise(vector) {
    const length = Math.hypot(vector[0], vector[1], vector[2]);
    return [vector[0] / length, vector[1] / length, vector[2] / length];
  }

  function loadTexture(url) {
    return new Promise(function (resolve, reject) {
      const image = new Image();
      image.onload = function () {
        const canvas = document.createElement("canvas");
        canvas.width = image.width;
        canvas.height = image.height;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        context.drawImage(image, 0, 0);
        resolve(context.getImageData(0, 0, image.width, image.height));
      };
      image.onerror = function () {
        reject(new Error("Could not load the Mars image"));
      };
      image.src = url;
    });
  }

  // Screen position of (lon, lat) seen from above (centreLon, centreLat); null if on the far side.
  function project(lon, lat, centreLon, centreLat) {
    const phi = lat * DEGREES;
    const phi0 = centreLat * DEGREES;
    const deltaLambda = (lon - centreLon) * DEGREES;
    const cosC = Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(deltaLambda);
    if (cosC < 0) {
      return null;
    }
    return {
      x: Math.cos(phi) * Math.sin(deltaLambda),
      y: Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(deltaLambda),
    };
  }

  function create(canvas, textureUrl, sites) {
    const context = canvas.getContext("2d");
    const size = canvas.width;
    const radius = size / 2 - 6;
    const frame = context.createImageData(size, size);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let texture = null;
    let centreLon = sites.length > 0 ? sites[0].lon - 60 : 0;
    let centreLat = 15;
    let spinning = !reduceMotion;
    let lastTime = null;
    let animation = null; // {fromLon, fromLat, toLon, toLat, start, duration, resolve}

    function drawSphere() {
      const data = frame.data;
      const phi0 = centreLat * DEGREES;
      const sinPhi0 = Math.sin(phi0);
      const cosPhi0 = Math.cos(phi0);
      const width = texture.width;
      const height = texture.height;
      for (let row = 0; row < size; row++) {
        const y = (size / 2 - row) / radius;
        for (let col = 0; col < size; col++) {
          const x = (col - size / 2) / radius;
          const index = (row * size + col) * 4;
          const rho = Math.hypot(x, y);
          if (rho > 1) {
            data[index + 3] = 0;
            continue;
          }
          const z = Math.sqrt(1 - rho * rho);
          let lat;
          let lon;
          if (rho === 0) {
            lat = centreLat;
            lon = centreLon;
          } else {
            const c = Math.asin(rho);
            const sinC = Math.sin(c);
            const cosC = Math.cos(c);
            lat = Math.asin(cosC * sinPhi0 + (y * sinC * cosPhi0) / rho) / DEGREES;
            lon = centreLon + Math.atan2(x * sinC, rho * cosPhi0 * cosC - y * sinPhi0 * sinC) / DEGREES;
          }
          let u = Math.floor(((((lon + 180) % 360) + 360) % 360) / 360 * width);
          let v = Math.floor(((90 - lat) / 180) * height);
          u = Math.min(width - 1, Math.max(0, u));
          v = Math.min(height - 1, Math.max(0, v));
          const source = (v * width + u) * 4;
          const light = 0.25 + 0.75 * Math.max(0, x * LIGHT[0] + y * LIGHT[1] + z * LIGHT[2]);
          data[index] = texture.data[source] * light;
          data[index + 1] = texture.data[source + 1] * light;
          data[index + 2] = texture.data[source + 2] * light;
          data[index + 3] = 255;
        }
      }
      context.putImageData(frame, 0, 0);
    }

    function drawAtmosphere() {
      const glow = context.createRadialGradient(size / 2, size / 2, radius * 0.96, size / 2, size / 2, radius * 1.05);
      glow.addColorStop(0, "rgba(255, 170, 120, 0)");
      glow.addColorStop(0.5, "rgba(255, 170, 120, 0.35)");
      glow.addColorStop(1, "rgba(255, 170, 120, 0)");
      context.fillStyle = glow;
      context.beginPath();
      context.arc(size / 2, size / 2, radius * 1.05, 0, 2 * Math.PI);
      context.fill();
    }

    function drawSites(time) {
      const pulse = reduceMotion ? 0.5 : (Math.sin(time / 300) + 1) / 2;
      for (const site of sites) {
        const point = project(site.lon, site.lat, centreLon, centreLat);
        if (point === null) {
          continue;
        }
        const screenX = size / 2 + point.x * radius;
        const screenY = size / 2 - point.y * radius;
        context.strokeStyle = "#8cff9e";
        context.lineWidth = 2;
        context.beginPath();
        context.arc(screenX, screenY, 5 + pulse * 7, 0, 2 * Math.PI);
        context.stroke();
        context.fillStyle = "#8cff9e";
        context.beginPath();
        context.arc(screenX, screenY, 3, 0, 2 * Math.PI);
        context.fill();
        context.font = "bold 12px ui-monospace, Menlo, monospace";
        context.fillText(site.label, screenX + 14, screenY + 4);
      }
    }

    function easeInOut(fraction) {
      return fraction < 0.5 ? 2 * fraction * fraction : 1 - Math.pow(-2 * fraction + 2, 2) / 2;
    }

    function tick(time) {
      if (lastTime === null) {
        lastTime = time;
      }
      const seconds = (time - lastTime) / 1000;
      lastTime = time;
      if (animation !== null) {
        const fraction = Math.min(1, (time - animation.start) / animation.duration);
        const eased = easeInOut(fraction);
        let lonChange = animation.toLon - animation.fromLon;
        lonChange = ((((lonChange + 180) % 360) + 360) % 360) - 180; // shortest way round
        centreLon = animation.fromLon + lonChange * eased;
        centreLat = animation.fromLat + (animation.toLat - animation.fromLat) * eased;
        if (fraction === 1) {
          const done = animation.resolve;
          animation = null;
          done();
        }
      } else if (spinning) {
        centreLon += SPIN_DEG_PER_SECOND * seconds;
      }
      drawSphere();
      drawAtmosphere();
      drawSites(time);
      window.requestAnimationFrame(tick);
    }

    return loadTexture(textureUrl).then(function (loaded) {
      texture = loaded;
      window.requestAnimationFrame(tick);
      return {
        // Turn the globe until (lon, lat) faces the viewer.
        focus: function (lon, lat, duration) {
          spinning = false;
          return new Promise(function (resolve) {
            if (reduceMotion) {
              centreLon = lon;
              centreLat = lat;
              resolve();
              return;
            }
            animation = {
              fromLon: centreLon,
              fromLat: centreLat,
              toLon: lon,
              toLat: lat,
              start: performance.now(),
              duration: duration,
              resolve: resolve,
            };
          });
        },
      };
    });
  }

  return { create: create, project: project };
})();
