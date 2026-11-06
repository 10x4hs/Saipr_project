// 앱 다운로드 버튼: 안드로이드·PC는 APK를 받고, iOS는 '홈 화면에 추가' 안내 시트를 연다.
(() => {
  const btn = document.querySelector('[data-install]');
  const sheet = document.getElementById('iosSheet');
  if (!btn || !sheet) return;
  const ua = navigator.userAgent;
  const isIOS = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (standalone) { btn.hidden = true; return; }           // 이미 홈 화면 앱으로 열었다
  if (!isIOS) return;                                       // 그 외에는 APK 다운로드 그대로
  btn.removeAttribute('download');
  btn.setAttribute('href', '#install');
  const open = () => { sheet.hidden = false; requestAnimationFrame(() => sheet.classList.add('on')); };
  const close = () => { sheet.classList.remove('on'); setTimeout(() => { sheet.hidden = true; }, 250); };
  btn.addEventListener('click', e => { e.preventDefault(); open(); });
  sheet.addEventListener('click', e => { if (e.target === sheet || e.target.closest('[data-close]')) close(); });
  addEventListener('keydown', e => { if (e.key === 'Escape' && !sheet.hidden) close(); });
})();
