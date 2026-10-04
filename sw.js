const CACHE_NAME = 'swm-v1';

// Pliki, które mają być dostępne offline od razu
const PRECACHE = [
  '/',
  '/index.html',
  '/manifest.json',
  '/favicon.svg'
  // Po dodaniu ikon odkomentuj:
  // '/icons/icon-192.png',
  // '/icons/icon-512.png'
];

// Instalacja – zapisujemy podstawowe pliki
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

// Aktywacja – usuwamy stare cache
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// Strategia: najpierw sieć, jak padnie → cache
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Nie cache'ujemy zewnętrznych API (pogoda, NBP, tłumaczenia)
  if (!request.url.startsWith(self.location.origin)) {
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Zapisujemy udaną odpowiedź do cache
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(request, responseClone);
        });
        return response;
      })
      .catch(() => {
        // Jesteśmy offline – bierzemy z cache
        return caches.match(request).then((cached) => {
          return cached || caches.match('/');
        });
      })
  );
});
