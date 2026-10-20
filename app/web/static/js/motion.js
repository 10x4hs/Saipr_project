// 모션 도우미 — 페이지 전환 방향, 숫자 카운트업, 햅틱, 축하 효과.
// 모든 기능은 지원 여부를 확인하고, 움직임 줄이기 설정이면 결과만 바로 보여 준다.
(function () {
  "use strict";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ── 1. 페이지 전환 방향 ───────────────────────────
  // 들어오는 화면의 'pagereveal'은 defer 스크립트보다 먼저 일어나서 base.html <head>의 인라인 스크립트가 맡는다.
  // 여기서는 떠나는 화면의 'pageswap'만 처리한다. 순위 계산(window.__vtRank)은 그 인라인 스크립트에 있다.
  addEventListener("pageswap", (e) => {
    if (!e.viewTransition || !e.activation || !window.__vtDirection) return;
    const t = window.__vtDirection(location.href, e.activation.entry.url);
    if (t) e.viewTransition.types.add(t);
  });

  // ── 2. 숫자 카운트업 (점수·포인트) ───────────────────
  function countUp(el, to, ms = 900) {
    const decimals = (String(to).split(".")[1] || "").length;
    const fmt = (v) => v.toLocaleString("ko-KR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    if (reduce) { el.textContent = fmt(to); return; }
    const from = 0, t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 4);
      el.textContent = fmt(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function startCounters(root = document) {
    root.querySelectorAll("[data-count-up]").forEach((el) => {
      const v = Number(el.dataset.countUp);
      if (!Number.isNaN(v)) countUp(el, v);
    });
  }

  // ── 3. 햅틱 (안드로이드만 — iOS·데스크톱은 조용히 없음) ─────
  const haptic = (pattern = 12) => { try { navigator.vibrate?.(pattern); } catch (_) { /* 지원 안 함 */ } };

  // ── 4. 숫자가 바뀌면 살짝 튀기 ───────────────────────
  function bump(el) { if (!el || reduce) return; el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump"); }

  // ── 5. 축하 효과 (이정표·승리) ──────────────────────
  function confetti(n = 36) {
    if (reduce) return;
    const host = document.querySelector(".screen") || document.body;
    const box = document.createElement("div");
    box.className = "confetti";
    const colors = ["#ffd60a", "#8fe3ff", "#ff8fd0", "#bfe0ff", "#ffffff", "#9be15d"];
    for (let i = 0; i < n; i++) {
      const p = document.createElement("i");
      p.style.left = Math.random() * 100 + "%";
      p.style.background = colors[i % colors.length];
      p.style.setProperty("--dx", (Math.random() * 120 - 60).toFixed(0) + "px");
      p.style.setProperty("--rot", (Math.random() * 720 - 360).toFixed(0) + "deg");
      p.style.animationDelay = (Math.random() * 0.35).toFixed(2) + "s";
      box.appendChild(p);
    }
    host.appendChild(box);
    setTimeout(() => box.remove(), 2400);
  }

  window.motion = { countUp, startCounters, haptic, bump, confetti, reduce };
  // defer로 불러오므로 이미 문서가 다 읽힌 뒤다
  startCounters();
})();
