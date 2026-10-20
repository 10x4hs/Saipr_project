// 내 정보 — 푸시 알림 켜기/끄기 · 테스트 · 기울기 반짝임
(function () {
  "use strict";
  const { toast } = window.saipr;
  const pwa = window.saiprPWA;
  const sw = document.getElementById("push-switch");
  const state = document.getElementById("push-state");
  const testBtn = document.getElementById("push-test");
  const LABEL = {
    on: "켜짐 — 앱을 닫아도 친구 소식이 와요",
    off: "꺼짐",
    denied: "브라우저 설정에서 알림이 막혀 있어요",
    unsupported: "이 브라우저는 푸시를 지원하지 않아요 (아이폰은 홈 화면에 설치한 뒤 가능)",
  };
  async function refresh() {
    const s = await pwa.push.status();
    state.textContent = LABEL[s];
    sw.setAttribute("aria-checked", String(s === "on"));
    sw.disabled = s === "unsupported" || s === "denied";
    testBtn.hidden = s !== "on";
  }
  sw.addEventListener("click", async () => {
    sw.disabled = true;
    try {
      if (sw.getAttribute("aria-checked") === "true") { await pwa.push.disable(); toast("푸시 알림을 껐어요"); }
      else { await pwa.push.enable(); toast("푸시 알림을 켰어요"); window.motion?.haptic(15); }
    } catch (e) { toast(e.message || "푸시를 켜지 못했어요"); }
    refresh();
  });
  testBtn.addEventListener("click", async () => {
    try {
      const r = await pwa.push.test();
      toast(r.queued ? "보냈어요! 잠시 후 알림이 떠요" : "오늘 알림 5건을 다 썼거나 방해 금지 시간이에요");
    } catch (e) { toast(e.message); }
  });
  refresh();

  // iOS처럼 권한이 필요한 기기에서만 '기울기 반짝임' 스위치를 보여 준다
  const tiltRow = document.getElementById("tilt-row");
  const tiltSw = document.getElementById("tilt-switch");
  const needsPermission = typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function";
  if (window.liquid && needsPermission) {
    tiltRow.hidden = false;
    try { tiltSw.setAttribute("aria-checked", String(localStorage.getItem("saipr:tilt") === "1")); } catch (_) { /* 저장 불가 */ }
    tiltSw.addEventListener("click", async () => {
      const ok = await window.liquid.enableTilt();
      tiltSw.setAttribute("aria-checked", String(ok));
      if (!ok) toast("기울기 권한을 받지 못했어요");
    });
  }
})();
