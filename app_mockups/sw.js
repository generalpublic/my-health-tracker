const CACHE_NAME = 'health-tracker-v30';
const ASSETS = [
  'today.html',
  'sleep-detail.html',
  'log-entry.html',
  'trends.html',
  'activity.html',
  'profile.html',
  'calendar.html',
  'design-system.css',
  'css/index.css',
  'css/today.css',
  'css/activity.css',
  'css/calendar.css',
  'css/trends.css',
  'css/sleep-detail.css',
  'css/log-entry.css',
  'css/profile.css',
  'config.js',
  'auth.js',
  'crypto-store.js',
  'data-loader.js',
  'js/sw-register.js',
  'js/dom.js',
  'js/index.js',
  'js/today.js',
  'js/activity.js',
  'js/calendar.js',
  'js/trends.js',
  'js/sleep-detail.js',
  'js/log-entry.js',
  'js/profile.js',
  'js/pull-to-refresh.js',
  'icon.svg',
  'manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      // Cache each asset individually — one 404 won't block the entire install
      Promise.allSettled(
        ASSETS.map(url => cache.add(url).catch(e => console.warn('[SW] Failed to cache:', url, e)))
      )
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('message', event => {
  if (event.data && event.data.type === 'GET_VERSION') {
    event.ports[0].postMessage({ cacheName: CACHE_NAME });
  }
});

self.addEventListener('fetch', event => {
  // Never cache Supabase API calls — always fetch fresh data
  if (event.request.url.includes('supabase.co')) {
    event.respondWith(fetch(event.request));
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
