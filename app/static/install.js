// 다운로드 버튼 두 개: '안드로이드 다운로드'는 APK를 받고, 'iOS 다운로드'는 홈 화면 추가 안내 시트를 연다.
(() => {
  const ios = document.querySelector('[data-install="ios"]');
  const android = document.querySelector('[data-install="android"]');
  const sheet = document.getElementById('iosSheet');
  const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (standalone) { [ios, android].forEach(b => b && (b.hidden = true)); return; }  // 이미 앱으로 열었다
  if (!ios || !sheet) return;
  const open = () => { sheet.hidden = false; requestAnimationFrame(() => sheet.classList.add('on')); };
  const close = () => { sheet.classList.remove('on'); setTimeout(() => { sheet.hidden = true; }, 250); };
  ios.addEventListener('click', e => { e.preventDefault(); open(); });
  sheet.addEventListener('click', e => { if (e.target === sheet || e.target.closest('[data-close]')) close(); });
  addEventListener('keydown', e => { if (e.key === 'Escape' && !sheet.hidden) close(); });
})();
