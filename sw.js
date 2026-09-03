/* LocalEvent Service Worker — PWA offline support */
const CACHE_NAME = 'localevent-v1';
const RUNTIME_CACHE = 'localevent-runtime-v1';

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
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(key => key !== CACHE_NAME && key !== RUNTIME_CACHE)
            .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;

  // Skip cross-origin requests (Google Fonts, etc.)
  if (!request.url.startsWith(self.location.origin)) {
    return;
  }

  event.respondWith(
    caches.match(request).then(cachedResponse => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(request).then(response => {
        // Cache successful responses for next time
        if (response && response.status === 200 && response.type === 'basic') {
          const responseClone = response.clone();
          caches.open(RUNTIME_CACHE).then(cache => {
            cache.put(request, responseClone);
          });
        }
        return response;
      }).catch(() => {
        // Offline fallback for HTML
        if (request.headers.get('accept').includes('text/html')) {
          return caches.match('./index.html');
        }
      });
    })
  );
});
