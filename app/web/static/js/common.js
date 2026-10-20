// 공통: CSRF 붙인 fetch, 토스트, 재연결되는 WebSocket, 내 알림 실시간 수신
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* 본문 없음 */ }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  let toastTimer;
  function toast(msg, ms = 3500) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.hidden = true), ms);
  }

  // 지수 백오프 재연결(1s → 30s), 끊기기 전 마지막 이벤트 id 이후부터 다시 받는다 (PRD EXC-05)
  function socket(path, onEvent) {
    let lastId = null, delay = 1000, ws = null, closed = false;
    function open() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const q = lastId === null ? "" : (path.includes("?") ? "&" : "?") + "last_event_id=" + lastId;
      ws = new WebSocket(`${proto}://${location.host}${path}${q}`);
      ws.onopen = () => { delay = 1000; };
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data);
        if (ev.id) lastId = ev.id;
        onEvent(ev);
      };
      ws.onclose = () => {
        if (closed) return;
        setTimeout(open, delay);
        delay = Math.min(delay * 2, 30000);
      };
    }
    open();
    return {
      send: (obj) => ws && ws.readyState === 1 && ws.send(JSON.stringify(obj)),
      close: () => { closed = true; ws && ws.close(); },
    };
  }

  window.saipr = { api, toast, socket, csrf };

  socket("/ws/me", (ev) => {
    if (ev.type !== "notification.created") return;
    toast("🔔 " + ev.data.body, 5000);
    // 홈 탭과 홈의 유리 구슬에 빨간 점
    for (const host of document.querySelectorAll('.tabs a[href="/"], a.orb')) {
      if (!host.querySelector(".dot")) host.insertAdjacentHTML("beforeend", '<span class="dot"></span>');
    }
  });

  // 복사 버튼 (팀 초대 코드 등)
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    try { await navigator.clipboard.writeText(b.dataset.copy); toast("복사했어요"); }
    catch (_) { toast(b.dataset.copy); }
  });
})();
