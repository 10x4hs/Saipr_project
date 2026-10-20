// Liquid Glass — 유리 카드의 빛 반사가 손가락(포인터)·휴대폰 기울기를 따라온다.
// - 하이라이트(.glass::after의 --lx/--ly)는 모든 브라우저에서.
// - 진짜 굴절(SVG feDisplacementMap)은 backdrop-filter에서 SVG 필터를 그리는 Chromium만, 그리고 표면 두 곳만.
//   Safari·Firefox는 이 필터를 무시하고, CSS.supports는 거짓 양성이 있어 엔진으로 판별한다.
(function () {
  "use strict";
  const root = document.documentElement;
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const reduceGlass = matchMedia("(prefers-reduced-transparency: reduce)").matches;
  const chromium = !!navigator.userAgentData?.brands?.some((b) => b.brand === "Chromium");
  const capable = (navigator.hardwareConcurrency || 4) >= 4 && !(navigator.connection && navigator.connection.saveData);

  if (chromium && capable && !reduceGlass) root.classList.add("lg-refract");
  if (reduceMotion || reduceGlass) return;

  // 화면에 보이는 유리 요소마다 '빛이 닿는 자리'를 요소 기준 좌표로 맞춘다 (한 프레임에 한 번)
  let px = innerWidth * 0.3, py = 0, queued = false;
  function paint() {
    queued = false;
    const vh = innerHeight;
    for (const el of document.querySelectorAll(".glass")) {
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > vh || !r.width) continue;
      el.style.setProperty("--lx", (((px - r.left) / r.width) * 100).toFixed(1) + "%");
      el.style.setProperty("--ly", (((py - r.top) / r.height) * 100).toFixed(1) + "%");
    }
  }
  const schedule = () => { if (!queued) { queued = true; requestAnimationFrame(paint); } };
  addEventListener("pointermove", (e) => { px = e.clientX; py = e.clientY; schedule(); }, { passive: true });
  addEventListener("scroll", schedule, { passive: true, capture: true });

  // 휴대폰 기울기: 빛이 화면 위쪽에서 기울기 방향으로 미끄러진다
  function onTilt(e) {
    if (e.gamma == null) return;
    px = innerWidth * (0.5 + Math.max(-45, Math.min(45, e.gamma)) / 90);
    py = innerHeight * (0.15 + Math.max(-30, Math.min(30, (e.beta || 45) - 45)) / 120);
    schedule();
  }
  let tilting = false;
  async function enableTilt() {
    if (tilting) return true;
    // iOS 13+는 사용자가 탭한 순간에만 권한을 물을 수 있다
    if (typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function") {
      try { if ((await DeviceOrientationEvent.requestPermission()) !== "granted") return false; } catch (_) { return false; }
    }
    addEventListener("deviceorientation", onTilt, { passive: true });
    tilting = true;
    try { localStorage.setItem("saipr:tilt", "1"); } catch (_) { /* 저장 불가 */ }
    return true;
  }
  // 안드로이드는 권한 없이 바로, iOS는 '내 정보'에서 켠 적이 있을 때만
  const needsPermission = typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function";
  let remembered = false;
  try { remembered = localStorage.getItem("saipr:tilt") === "1"; } catch (_) { /* 저장 불가 */ }
  if (matchMedia("(pointer: coarse)").matches && (!needsPermission || remembered)) {
    if (needsPermission) addEventListener("pointerup", () => enableTilt(), { once: true });
    else enableTilt();
  }

  window.liquid = { enableTilt, refract: root.classList.contains("lg-refract") };
  paint();
})();
