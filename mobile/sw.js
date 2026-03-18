/**
 * Service Worker — Trading Bot PWA
 * Cache les assets statiques pour un chargement rapide.
 * Les données en temps réel (API) ne sont jamais mises en cache.
 */

const CACHE_NAME = "trading-bot-v1";

// Assets à mettre en cache (chargement offline)
const STATIC_ASSETS = [
  "/",
  "/static/css/style.css",
  "/static/js/app.js",
  "/static/js/api.js",
  "/static/js/charts.js",
  "/static/js/config-editor.js",
  "/manifest.json",
];

// Préfixes des requêtes API — jamais mis en cache
const API_PREFIXES = ["/api/", "/ws"];

// ─────────────────────────────────────────────────────────────────────────────
// Install : mise en cache des assets statiques
// ─────────────────────────────────────────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Activate : supprimer les anciens caches
// ─────────────────────────────────────────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Fetch : stratégie Network-first pour l'API, Cache-first pour les assets
// ─────────────────────────────────────────────────────────────────────────────
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // WebSocket → pas de cache
  if (event.request.url.startsWith("ws")) return;

  // API → network only (données temps réel)
  const isApi = API_PREFIXES.some((p) => url.pathname.startsWith(p));
  if (isApi) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Assets statiques → cache first, fallback network
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        // Mettre en cache uniquement les requêtes GET réussies
        if (
          event.request.method === "GET" &&
          response.status === 200 &&
          response.type !== "opaque"
        ) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
