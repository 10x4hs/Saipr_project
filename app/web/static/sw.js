// 함께읽기 서비스 워커 — /sw.js 로 제공되어 사이트 전체(scope "/")를 맡는다.
// 1) 앱 셸(CSS·JS·아이콘·오프라인 화면)을 미리 저장해 바로 뜨게 하고
// 2) 한 번 연 화면과 본문 쪽(청크)을 저장해 비행기 모드에서도 다시 읽을 수 있게 하고
// 3) 웹 푸시를 알림으로 띄우고 앱 아이콘 배지를 맞춘다.
const VERSION = "saipr-v9";
const SHELL = `${VERSION}-shell`;
const PAGES = "saipr-pages";
const CHUNKS = "saipr-chunks";
const SHELL_URLS = [
  "/offline",
  "/static/css/glass.css",
  "/static/css/motion.css",
  "/static/js/common.js",
  "/static/js/motion.js",
  "/static/js/liquid.js",
  "/static/js/reader.js",
  "/static/js/room.js",
  "/static/icons/icon-192.png",
  "/static/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_URLS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("saipr-v") && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const isChunk = (url) => /^\/books\/\d+\/chunk\/\d+$/.test(url.pathname);
const isReadable = (url) => /^\/books\/\d+(\/read)?$/.test(url.pathname) || url.pathname === "/" || url.pathname.startsWith("/rooms");

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  // 상태를 바꾸는 요청 · 다른 사이트 · 실시간 소켓 · JSON API는 그대로 네트워크로
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/ws") || url.pathname.startsWith("/api/")) return;

  if (isChunk(url)) {
    // 본문 쪽은 바뀌지 않으므로 저장본 먼저 (오프라인 읽기)
    event.respondWith(caches.open(CHUNKS).then(async (c) => {
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      // 로그인 화면으로 돌려보내진 응답(redirected)은 본문이 아니므로 저장하지 않는다
      if (res.ok && !res.redirected) c.put(req, res.clone());
      return res;
    }));
    return;
  }

  if (req.mode === "navigate") {
    // 화면은 늘 최신이 먼저, 안 되면 저장해 둔 화면 → 오프라인 안내
    event.respondWith(fetch(req).then((res) => {
      if (res.ok && !res.redirected && isReadable(url)) {
        // 응답 본문은 브라우저가 곧 읽어 버리므로, 돌려주기 전에 바로 복사해 둔다
        const copy = res.clone();
        event.waitUntil(caches.open(PAGES).then((c) => c.put(req, copy)));
      }
      return res;
    }).catch(async () => (await caches.match(req, { ignoreSearch: false })) || (await caches.match(req, { ignoreSearch: true })) || caches.match("/offline")));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    // 정적 파일: 저장본으로 바로 보여 주고 뒤에서 새로 받아 둔다
    event.respondWith(caches.open(SHELL).then(async (c) => {
      const hit = await c.match(req);
      const fresh = fetch(req).then((res) => { if (res.ok) c.put(req, res.clone()); return res; }).catch(() => hit);
      return hit || fresh;
    }));
  }
});

// ── 웹 푸시 ───────────────────────────────────────
self.addEventListener("push", (event) => {
  let data = { title: "함께읽기", body: "새 소식이 있어요", url: "/" };
  try { data = { ...data, ...event.data.json() }; } catch (_) { /* 본문 없음 */ }
  event.waitUntil(Promise.all([
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/static/icons/icon-192.png",
      badge: "/static/icons/icon-192.png",
      tag: data.kind || "saipr",
      renotify: true,
      data: { url: data.url },
    }),
    data.badge && self.navigator.setAppBadge ? self.navigator.setAppBadge(data.badge) : null,
  ]));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    const open = list.find((c) => c.url === target) || list[0];
    if (open) return open.navigate(target).then((c) => (c || open).focus());
    return self.clients.openWindow(target);
  }));
});
