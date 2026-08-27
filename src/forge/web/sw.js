/* Minimal service worker: enables install-to-home-screen; never caches
 * (forge is a local live-editing tool — stale assets would only confuse). */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
