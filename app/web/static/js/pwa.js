// PWA — 설치, 서비스 워커, 웹 푸시 구독, 앱 아이콘 배지, 저장 공간 유지.
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const screen = document.querySelector(".screen");
  const loggedIn = !!document.querySelector(".tabs, [data-logged-in]");

  // ── 서비스 워커 ─────────────────────────────────
  const ready = "serviceWorker" in navigator
    ? navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(() => navigator.serviceWorker.ready).catch(() => null)
    : Promise.resolve(null);

  // 로그아웃하면 이 기기에 저장해 둔 화면을 지운다 (다른 사람이 같은 기기를 쓸 수 있으니까)
  document.addEventListener("submit", (e) => {
    if (e.target.matches('form[action="/logout"]') && "caches" in window) caches.delete("saipr-pages");
  });

  // ── 앱 아이콘 배지: 안 읽은 알림 수 ─────────────────
  const unread = Number(screen?.dataset.unread || 0);
  if (loggedIn && "setAppBadge" in navigator) {
    (unread ? navigator.setAppBadge(unread) : navigator.clearAppBadge()).catch(() => {});
  }

  // ── 설치(홈 화면에 추가) ───────────────────────────
  let deferred = null;
  const installButtons = () => document.querySelectorAll("[data-install]");
  addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    installButtons().forEach((b) => (b.hidden = false));
  });
  addEventListener("appinstalled", () => { deferred = null; installButtons().forEach((b) => (b.hidden = true)); });
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-install]");
    if (!b || !deferred) return;
    deferred.prompt();
    await deferred.userChoice;
    deferred = null;
    b.hidden = true;
  });
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  document.querySelectorAll("[data-ios-install]").forEach((el) => {
    // iOS에는 설치 버튼이 없어서 방법을 알려 준다
    el.hidden = standalone || !/iP(hone|ad|od)/.test(navigator.userAgent);
  });

  // ── 저장 공간 유지 (오프라인으로 읽은 쪽이 지워지지 않게) ───
  if (loggedIn && navigator.storage?.persist) {
    ready.then(() => navigator.storage.persisted()).then((p) => p || navigator.storage.persist()).catch(() => {});
  }

  // ── 웹 푸시 ───────────────────────────────────
  const b64ToBytes = (b64) => {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  async function post(url, body) {
    const r = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.status === 204 ? null : r.json();
  }
  const push = {
    supported: "serviceWorker" in navigator && "PushManager" in window && "Notification" in window,
    async status() {
      if (!this.supported) return "unsupported";
      const reg = await ready;
      const sub = reg && (await reg.pushManager.getSubscription());
      if (Notification.permission === "denied") return "denied";
      return sub ? "on" : "off";
    },
    async enable() {
      const reg = await ready;
      if (!reg) throw new Error("서비스 워커를 쓸 수 없어요");
      if ((await Notification.requestPermission()) !== "granted") throw new Error("알림 권한이 꺼져 있어요");
      const { public_key } = await (await fetch("/api/v1/push/key")).json();
      const sub = (await reg.pushManager.getSubscription()) ||
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(public_key) }));
      await post("/api/v1/push/subscribe", sub.toJSON());
    },
    async disable() {
      const reg = await ready;
      const sub = reg && (await reg.pushManager.getSubscription());
      if (!sub) return;
      await post("/api/v1/push/unsubscribe", { endpoint: sub.endpoint });
      await sub.unsubscribe();
    },
    test: () => post("/api/v1/push/test"),
  };
  window.saiprPWA = { push, ready, installAvailable: () => !!deferred };
})();
