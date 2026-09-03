/* Forge service worker: precaches the app shell so the installed app keeps
 * working when the network (or the local server) is unreachable.
 *
 * Strategy is network-first everywhere — forge is a live-editing tool, so a
 * stale editor would be worse than a slow one; the cache is only a fallback.
 * Live endpoints (the JSON API, previews, the app proxy, injected live.js)
 * are never intercepted or cached. Bump CACHE with the app version whenever
 * shell files change so old copies are dropped on activate.
 */
const CACHE = "forge-shell-v0.5.0";
const SHELL = [
  "/offline.html",
  "/assets/style.css", "/assets/app.js", "/assets/editor.js",
  "/icon.svg", "/icon-180.png", "/icon-512.png", "/manifest.webmanifest",
];
const LIVE = /^\/(api|p|proxy|__forge)\//;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (LIVE.test(url.pathname)) return;

  e.respondWith((async () => {
    try {
      const res = await fetch(e.request);
      // Keep the cached shell copy fresh (app routes all serve the SPA, so
      // only cache the fixed shell files — an offline SPA with no API would
      // just render broken; failed navigations get offline.html instead).
      if (res.ok && e.request.mode !== "navigate") {
        const cache = await caches.open(CACHE);
        cache.put(e.request, res.clone());
      }
      return res;
    } catch (err) {
      if (e.request.mode === "navigate") {
        const page = await caches.match("/offline.html");
        if (page) return page;
      }
      const cached = await caches.match(e.request);
      if (cached) return cached;
      throw err;
    }
  })());
});
