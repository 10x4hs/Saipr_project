// 해독 서비스 워커 — 화면·CSS·JS는 네트워크 우선(배포 직후 옛 스타일이 남지 않게), 끊기면 저장본. 이미지·폰트만 저장본 우선.
const VERSION = 'haedok-v2';
const OFFLINE = '/static/offline.html';
const PRECACHE = [OFFLINE, '/static/app.css', '/static/looks.css', '/static/icons/icon-192.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // API·실시간·APK 다운로드는 건드리지 않는다
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws') || url.pathname.endsWith('.apk')) return;

  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(async () => (await caches.match(req)) || caches.match(OFFLINE)));
    return;
  }
  if (url.pathname.startsWith('/static/') && /\.(css|js|json|html)$/.test(url.pathname)) {
    e.respondWith(caches.open(VERSION).then(cache =>
      fetch(req).then(res => { if (res.ok) cache.put(req, res.clone()); return res; })
        .catch(async () => (await cache.match(req)) || Response.error())
    ));
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.open(VERSION).then(async cache => {
      const hit = await cache.match(req);
      const fresh = fetch(req).then(res => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => hit);
      return hit || fresh;
    }));
  }
});
