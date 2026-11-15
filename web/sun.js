// Terrain shadow from the horizon angles in the data pack (pipeline/horizon.py).
// A cell is in shadow when the sun is at or below 0° or lower than the terrain horizon in the
// sun's direction; the horizon between two stored directions is interpolated linearly.
// No DOM here except decoding the horizon images, so the maths can be checked with node.

"use strict";

const Shadow = (function () {
  // horizon: the manifest "horizon" entry; codes: one Uint8Array per direction (row-major cells).
  function horizonAt(horizon, codes, cellIndex, azimuth) {
    const directions = horizon.directions_deg;
    const step = 360 / directions.length;
    const position = (((azimuth % 360) + 360) % 360) / step;
    const lower = Math.floor(position) % directions.length;
    const upper = (lower + 1) % directions.length;
    const fraction = position - Math.floor(position);
    const lowerCode = codes[lower][cellIndex];
    const upperCode = codes[upper][cellIndex];
    if (lowerCode === horizon.no_data_code || upperCode === horizon.no_data_code) {
      return null;
    }
    return (lowerCode * (1 - fraction) + upperCode * fraction) * horizon.angle_step_deg;
  }

  // true = shadow, false = sunlit, null = no terrain data.
  function inShadow(horizon, codes, cellIndex, sunAzimuth, sunElevation) {
    const angle = horizonAt(horizon, codes, cellIndex, sunAzimuth);
    if (angle === null) {
      return null;
    }
    return sunElevation <= 0 || sunElevation < angle;
  }

  // Grid position [col, row] (1 m cells) -> horizon cell index, or -1 outside.
  function cellIndexAt(horizon, col, row) {
    const x = Math.floor(col / horizon.cell_px);
    const y = Math.floor(row / horizon.cell_px);
    if (x < 0 || y < 0 || x >= horizon.width || y >= horizon.height) {
      return -1;
    }
    return y * horizon.width + x;
  }

  // Share of a route (by length) in shadow: points every half horizon cell along the line.
  // Returns {shadow: 0..1, sampled: number of samples with data, missing: samples without data}.
  function routeShadow(horizon, codes, points, sunAzimuth, sunElevation) {
    const spacing = horizon.cell_px / 2;
    let shaded = 0;
    let sampled = 0;
    let missing = 0;
    for (let index = 1; index < points.length; index++) {
      const from = points[index - 1];
      const to = points[index];
      const length = Math.hypot(to[0] - from[0], to[1] - from[1]);
      const count = Math.max(1, Math.ceil(length / spacing));
      for (let sample = 0; sample < count; sample++) {
        const t = (sample + 0.5) / count;
        const cell = cellIndexAt(horizon, from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t);
        const shadow = cell < 0 ? null : inShadow(horizon, codes, cell, sunAzimuth, sunElevation);
        if (shadow === null) {
          missing += 1;
        } else {
          sampled += 1;
          if (shadow) {
            shaded += 1;
          }
        }
      }
    }
    return { shadow: sampled > 0 ? shaded / sampled : null, sampled: sampled, missing: missing };
  }

  // Fill RGBA pixels (one per horizon cell): shadow = shade colour, sunlit or no data = clear.
  function paintShadow(horizon, codes, pixels, sunAzimuth, sunElevation, shade) {
    const cells = horizon.width * horizon.height;
    for (let cell = 0; cell < cells; cell++) {
      const shadow = inShadow(horizon, codes, cell, sunAzimuth, sunElevation);
      const offset = cell * 4;
      pixels[offset] = shade[0];
      pixels[offset + 1] = shade[1];
      pixels[offset + 2] = shade[2];
      pixels[offset + 3] = shadow === true ? shade[3] : 0;
    }
  }

  // Direction of a ground azimuth on the map (map metres east-west are 1 / east_scale ground metres).
  function mapAngle(azimuth, eastScale) {
    const radians = (azimuth * Math.PI) / 180;
    return ((Math.atan2(Math.sin(radians) / eastScale, Math.cos(radians)) * 180) / Math.PI + 360) % 360;
  }

  // Browser only: decode the horizon RGB images into one Uint8Array per direction.
  function loadCodes(horizon, urlFor) {
    const codes = new Array(horizon.directions_deg.length);
    const loads = horizon.files.map(function (entry) {
      return new Promise(function (resolve, reject) {
        const image = new Image();
        image.onload = function () {
          if (image.width !== horizon.width || image.height !== horizon.height) {
            reject(new Error("Horizon image " + entry.file + " has the wrong size"));
            return;
          }
          const canvas = document.createElement("canvas");
          canvas.width = image.width;
          canvas.height = image.height;
          const context = canvas.getContext("2d", { willReadFrequently: true });
          context.drawImage(image, 0, 0);
          const data = context.getImageData(0, 0, image.width, image.height).data;
          entry.directions_deg.forEach(function (direction, channel) {
            const values = new Uint8Array(image.width * image.height);
            for (let cell = 0; cell < values.length; cell++) {
              values[cell] = data[cell * 4 + channel];
            }
            codes[horizon.directions_deg.indexOf(direction)] = values;
          });
          resolve();
        };
        image.onerror = function () {
          reject(new Error("Could not load horizon image " + entry.file));
        };
        image.src = urlFor(entry.file);
      });
    });
    return Promise.all(loads).then(function () {
      return codes;
    });
  }

  return {
    horizonAt: horizonAt,
    inShadow: inShadow,
    cellIndexAt: cellIndexAt,
    routeShadow: routeShadow,
    paintShadow: paintShadow,
    mapAngle: mapAngle,
    loadCodes: loadCodes,
  };
})();

if (typeof module !== "undefined") {
  module.exports = Shadow; // lets the same file be checked from the command line
}
