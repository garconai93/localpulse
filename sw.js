/* LocalEvent Service Worker — PWA with auto-update
 *
 * Version: v2 — adds update flow:
 * - Bump CACHE_NAME on each deploy to invalidate old caches
 * - Network-first strategy for HTML/JSON (always fetch fresh)
 * - Cache-first for static assets (icons, manifest)
 * - Skip waiting + claim clients for immediate activation
 * - Notify clients when update is available
 */

const VERSION = '2.1.0';
const CACHE_NAME = `localevent-v${VERSION}`;
const RUNTIME_CACHE = `localevent-runtime-v${VERSION}`;

const PRECACHE_URLS = [
  './',
  './index.html',
  './events.json',
  './manifest.json',
  './icons/icon.svg',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './privacy.html',
  './terms.html'
];

self.addEventListener('install', event => {
  console.log(`[SW v${VERSION}] Installing...`);
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log(`[SW v${VERSION}] Pre-caching ${PRECACHE_URLS.length} files`);
        return cache.addAll(PRECACHE_URLS);
      })
      // Force the new service worker to activate immediately,
      // even if there are old tabs open
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  console.log(`[SW v${VERSION}] Activating...`);
  event.waitUntil(
    // Clean up old cache versions
    caches.keys()
      .then(keys => {
        const oldCaches = keys.filter(key =>
          key !== CACHE_NAME && key !== RUNTIME_CACHE &&
          key.startsWith('localevent-')
        );
        return Promise.all(
          oldCaches.map(key => {
            console.log(`[SW v${VERSION}] Deleting old cache: ${key}`);
            return caches.delete(key);
          })
        );
      })
      // Take control of all open tabs immediately
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', event => {
  // Allow clients to request immediate update check
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;

  // Skip cross-origin (Google Fonts, analytics, etc.)
  if (!request.url.startsWith(self.location.origin)) {
    return;
  }

  const url = new URL(request.url);
  const isHTML = request.mode === 'navigate' ||
                 (request.headers.get('accept') || '').includes('text/html');
  const isJSON = url.pathname.endsWith('.json');

  if (isHTML || isJSON) {
    // Network-first for HTML and JSON: always fetch fresh, fall back to cache
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response && response.status === 200) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then(cache => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          // Offline: serve from cache
          return caches.match(request).then(cached => {
            if (cached) return cached;
            if (isHTML) return caches.match('./index.html');
            return new Response('Offline', { status: 503 });
          });
        })
    );
  } else {
    // Cache-first for static assets (icons, fonts)
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response && response.status === 200 && response.type === 'basic') {
            const responseClone = response.clone();
            caches.open(RUNTIME_CACHE).then(cache => {
              cache.put(request, responseClone);
            });
          }
          return response;
        });
      })
    );
  }
});
