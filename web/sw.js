// Service worker: lets NAVASA work without a network.
//
// - On install it saves the app itself (page, style, code, Leaflet).
// - App files: network first (so updates show), saved copy when offline.
// - Data files: saved copy first; if there is none, fetched from the network and
//   saved, so anything viewed online stays available offline.
// - The data pack is saved in stages by app.js (offline.json lists the files).

"use strict";

const APP_CACHE = "navasa-app-v1";
const DATA_CACHE = "navasa-data-jezero_v1";
const APP_FILES = [
  "./",
  "index.html",
  "styles.css",
  "app.js",
  "manifest.webmanifest",
  "vendor/leaflet/leaflet.js",
  "vendor/leaflet/leaflet.css",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(APP_CACHE).then(function (cache) {
      return cache.addAll(APP_FILES);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      const deletions = [];
      for (const name of names) {
        if (name !== APP_CACHE && name !== DATA_CACHE) {
          deletions.push(caches.delete(name));
        }
      }
      return Promise.all(deletions);
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    return;
  }
  const isData = new URL(request.url).pathname.includes("/data/");
  if (isData) {
    event.respondWith(dataFirstFromCache(request));
  } else {
    event.respondWith(appFirstFromNetwork(request));
  }
});

function dataFirstFromCache(request) {
  return caches.match(request, { ignoreSearch: true }).then(function (saved) {
    if (saved) {
      return saved;
    }
    return fetch(request).then(function (response) {
      if (response.ok) {
        const copy = response.clone();
        caches.open(DATA_CACHE).then(function (cache) {
          cache.put(request, copy);
        });
      }
      return response;
    });
  });
}

function appFirstFromNetwork(request) {
  return fetch(request)
    .then(function (response) {
      if (response.ok) {
        const copy = response.clone();
        caches.open(APP_CACHE).then(function (cache) {
          cache.put(request, copy);
        });
      }
      return response;
    })
    .catch(function () {
      return caches.match(request, { ignoreSearch: true }).then(function (saved) {
        return saved || caches.match("index.html");
      });
    });
}
