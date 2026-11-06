// 홈 3D (bloomworld 방식): 책들이 나선 계단을 따라 위쪽·뒤쪽으로 감겨 쌓여 있다.
// 스크롤하면 나선 전체가 앞으로 돌아 내려와, 맨 앞 책은 화면 앞으로 지나가고 다음 책이 그 자리에 온다.
// 책은 앞표지·책등·페이지 단면이 있는 3D 상자이고, 부모에 opacity/filter를 걸지 않아 입체가 눌리지 않는다.
(() => {
  const $ = id => document.getElementById(id);
  const home = $('drum');
  const books = [...document.querySelectorAll('.hx-book')];
  const PER = 150;            // 책 한 권 넘기는 스크롤 거리(px)
  const TURN = 24;            // 다음 책까지 나선이 도는 각도(도)
  const RISE = 62;            // 다음 책까지 올라가는 높이(px)
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let lenis = null, raf = 0, focusEl = null, R = 160, hudTimer = 0, snapTimer = 0;
  let dirX = .7, dirY = .7, stepPx = 90;   // 끌기: 뒤 책 → 앞자리 방향(화면 단위 벡터)과 한 권 사이 화면 거리
  document.body.classList.add('in-drum');

  function layout() {
    lastPos = -1;
    // 나선 반지름: 휴대폰은 화면 폭, 넓은 화면은 사이드바를 뺀 본문 폭 기준(너무 퍼지지 않게 상한)
    const side = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--side')) || 0;
    R = Math.min(innerWidth - side, innerWidth >= 768 ? 820 : 480) * (innerWidth >= 768 ? .36 : .42);
    $('drumSpacer').style.height = ((books.length - 1) * PER + innerHeight) + 'px';
    // 바로 뒤 책(t=1)은 앞자리보다 왼쪽 위에 있다. 그 책을 앞자리로 끌어오는 방향 = 오른쪽 아래.
    // 원근(perspective 1100px)으로 조금 작아지는 만큼 줄여서, 손가락 아래 책이 손가락을 따라오게 한다
    const phi = TURN * Math.PI / 180, z1 = (1 - Math.cos(phi)) * R + 70, k = 1100 / (1100 + z1);
    const vx = Math.sin(phi) * R * k, vy = RISE * k;
    stepPx = Math.hypot(vx, vy); dirX = vx / stepPx; dirY = vy / stepPx;
  }

  let lastPos = -1;
  function frame() {
    const pos = scrollY / PER;
    // 스크롤이 그대로면 아무것도 다시 계산하지 않는다 — 가만히 있을 때 휴대폰 배터리·발열을 아낀다
    if (Math.abs(pos - lastPos) < 0.0005) { raf = requestAnimationFrame(frame); return; }
    lastPos = pos;
    let best = null;
    books.forEach((el, i) => {
      const t = i - pos;                                 // 0 = 맨 앞, + = 위·뒤에서 기다리는 책
      if (t < -1.2 || t > 9) { el.style.visibility = 'hidden'; return; }
      el.style.visibility = 'visible';
      let x, y, z, ry, rx, a;
      if (t >= 0) {
        const phi = t * TURN * Math.PI / 180;            // 나선 위의 각도
        x = -Math.sin(phi) * R;                          // 왼쪽 뒤로 감겨 올라간다
        z = -(1 - Math.cos(phi)) * R - t * 70;
        y = -t * RISE;
        ry = 26 + t * TURN * .9;                         // 나선을 따라 몸을 돌려 책등이 보인다
        rx = 4 + t * 1.5;
        a = Math.max(0, 1 - Math.max(0, t - 6) / 3);     // 아주 먼 책은 안개 속으로
      } else {                                           // 맨 앞을 지나 화면 앞으로 빠져나간다
        const k = -t;
        // 아래로 지나가지 않고 제자리에서 살짝 다가오며 조용히 사라진다(글씨 위를 지나지 않게)
        x = 0; y = -k * 24; z = k * 120; ry = 26 - k * 8; rx = 4;
        a = Math.max(0, 1 - k * 4);                     // 한 걸음의 1/4 안에 사라져 겹침이 짧다
      }
      el.style.transform = `translate3d(${x}px, ${y}px, ${z}px) rotateY(${ry}deg) rotateX(${rx}deg)`;
      el.style.setProperty('--a', a.toFixed(3));
      el.style.setProperty('--shade', (t > 0 ? Math.max(.45, 1 - t * .09) : 1).toFixed(3));
      el.style.zIndex = 1000 - Math.round(t * 10);
      el.style.pointerEvents = a > .5 ? 'auto' : 'none';
    });
    // 지금 앞에 선 책 = 떠나기 시작한 책의 다음 권
    best = books[Math.min(books.length - 1, Math.max(0, Math.ceil(pos - .15)))];
    if (best && best !== focusEl) hud(best);
    $('hxCount').textContent = `${String(books.indexOf(best) + 1).padStart(2, '0')} / ${books.length}`;
    raf = requestAnimationFrame(frame);
  }

  function hud(el) {
    focusEl = el;
    books.forEach(b => b.classList.toggle('focus', b === el));
    caption(el);
    // 앞에 선 책과 다음 책만 선명한 큰 표지로 바꾼다 (나머지는 작은 판으로 메모리를 아낀다)
    const i = books.indexOf(el);
    [books[i], books[i + 1]].forEach(b => {
      const img = b && b.dataset.hi && b.querySelector('.bk-front img');
      if (img && img.src !== new URL(b.dataset.hi, location.href).href) img.src = b.dataset.hi;
    });
  }

  // 넓은 화면에서만 보이는 큰 제목: 바뀔 때 잠깐 흐려졌다가 새 이름으로
  const cap = $('hxCap');
  function caption(el) {
    if (!cap || !getComputedStyle(cap).display || getComputedStyle(cap).display === 'none') return;
    cap.classList.add('fading');
    clearTimeout(hudTimer);
    hudTimer = setTimeout(() => {
      $('capRank').textContent = el.dataset.rank ? `인기 ${el.dataset.rank}위` : '';
      $('capTitle').textContent = el.dataset.title;
      $('capAuthor').textContent = el.dataset.author;
      $('capMeta').textContent = +el.dataset.readers ? `해독 독자 ${el.dataset.readers}명이 읽는 중` : '눌러서 바로 읽기';
      cap.classList.remove('fading');
    }, 180);
  }

  // 맨 앞 책을 누르면 열고, 뒤에 있는 책을 누르면 그 책을 앞으로 데려온다
  books.forEach((el, i) => el.addEventListener('click', e => {
    if (dragMoved) { e.preventDefault(); dragMoved = false; return; }   // 끌다가 놓은 것은 누름이 아니다
    if (el === focusEl) return;                          // 링크 그대로 → 책 열기
    e.preventDefault();
    const target = i * PER;
    if (lenis) lenis.scrollTo(target, { duration: 1.1, easing: t => 1 - Math.pow(1 - t, 4) });
    else scrollTo({ top: target, behavior: 'smooth' });
  }));

  // 스크롤이 멈추면 가장 가까운 책에 부드럽게 맞춘다.
  // 손가락이 화면에 닿아 있는 동안에는 맞추지 않는다 — 멈칫할 때마다 끌어당기면 손과 싸운다
  let touching = false;
  addEventListener('touchstart', () => { touching = true; clearTimeout(snapTimer); }, { passive: true });
  addEventListener('touchend', () => { touching = false; snap(); }, { passive: true });
  addEventListener('touchcancel', () => { touching = false; }, { passive: true });
  function snap() {
    clearTimeout(snapTimer);
    if (touching || drag) return;
    snapTimer = setTimeout(() => {
      const target = Math.round(scrollY / PER) * PER;
      if (Math.abs(target - scrollY) < 2) return;
      if (lenis) lenis.scrollTo(target, { duration: .9, easing: t => 1 - Math.pow(1 - t, 4) });
      else scrollTo({ top: target, behavior: 'smooth' });
    }, matchMedia('(pointer: coarse)').matches ? 260 : 160);   // 터치는 관성 스크롤이 끝난 뒤에
  }

  // --- 책을 잡고 끌기 (안드로이드 크롬 터치 · PC 마우스) ---
  // 책을 누른 채 앞(오른쪽 아래)으로 끌면 그 책이 손가락을 따라 앞자리로 온다. 실제로는 페이지 스크롤을 움직여서
  // 스크롤할 때와 똑같은 나선 움직임이 나온다. 놓으면 던진 속도만큼 더 가다가 가장 가까운 책에 멈춘다.
  // 거의 움직이지 않고 떼면 평소처럼 누름(맨 앞 책 = 열기, 뒤 책 = 앞으로 데려오기).
  const MOVE = 8;                       // 이만큼(px) 움직여야 끌기로 본다 — 손 떨림은 누름
  const maxY = () => (books.length - 1) * PER;
  const clampY = y => Math.max(0, Math.min(maxY(), y));
  let drag = null, dragMoved = false, fling = 0;
  const setScroll = y => { if (lenis) lenis.scrollTo(y, { immediate: true, force: true }); else scrollTo(0, y); };
  function glide(to) {                  // 관성으로 미끄러져 책 자리에 멈춘다
    const from = scrollY, dist = Math.abs(to - from);
    if (dist < 1) return;
    const dur = Math.min(1100, Math.max(380, 260 + dist * 1.6));
    const ease = t => 1 - Math.pow(1 - t, 4);
    if (lenis) { lenis.scrollTo(to, { duration: dur / 1000, easing: ease, force: true }); return; }
    const t0 = performance.now();
    cancelAnimationFrame(fling);
    const step = now => {
      const t = Math.min(1, (now - t0) / dur);
      scrollTo(0, from + (to - from) * ease(t));
      if (t < 1 && !drag) fling = requestAnimationFrame(step);
    };
    fling = requestAnimationFrame(step);
  }
  function onDown(e) {
    if (drag || (e.pointerType === 'mouse' && e.button !== 0)) return;
    if (e.pointerType === 'mouse') e.preventDefault();   // 링크 끌기·글자 선택 대신 책을 끈다
    cancelAnimationFrame(fling); lenis?.stop(); lenis?.start();   // 굴러가던 것을 손으로 잡아 멈춘다
    dragMoved = false; clearTimeout(snapTimer);
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY, y0: scrollY, moved: false, pts: [{ t: e.timeStamp, y: scrollY }] };
    addEventListener('pointermove', onMove, { passive: false });
    addEventListener('pointerup', onUp); addEventListener('pointercancel', onUp);
  }
  function onMove(e) {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < MOVE) return;
    drag.moved = true;
    if (e.cancelable) e.preventDefault();
    const along = dx * dirX + dy * dirY;                 // 앞쪽 방향 성분만 쓴다
    const y = clampY(drag.y0 + along / stepPx * PER);
    setScroll(y);
    drag.pts.push({ t: e.timeStamp, y });
    if (drag.pts.length > 8) drag.pts.shift();
  }
  function onUp(e) {
    if (!drag || e.pointerId !== drag.id) return;
    removeEventListener('pointermove', onMove); removeEventListener('pointerup', onUp); removeEventListener('pointercancel', onUp);
    const d = drag; drag = null;
    if (!d.moved) return;                                // 누름 → click이 그대로 간다
    dragMoved = true; setTimeout(() => { dragMoved = false; }, 400);   // 바로 뒤따르는 click만 막는다
    // 마지막 100ms의 속도로 던진 거리를 정하고, 가장 가까운 책 자리에 맞춘다
    const now = d.pts[d.pts.length - 1], old = d.pts.find(p => now.t - p.t <= 100) || d.pts[0];
    const v = now.t > old.t ? (now.y - old.y) / (now.t - old.t) : 0;   // 스크롤 px/ms
    const cur = scrollY, aim = cur + Math.max(-4 * PER, Math.min(4 * PER, v * 240));
    glide(clampY(Math.round(aim / PER) * PER));
  }
  books.forEach(el => {
    el.addEventListener('pointerdown', onDown);
    el.addEventListener('dragstart', e => e.preventDefault());
    el.addEventListener('contextmenu', e => { if (drag?.moved || dragMoved) e.preventDefault(); });
  });

  function start() {
    layout();
    if (window.Lenis && !lenis && !reduced) {
      lenis = new Lenis({ lerp: 0.06, wheelMultiplier: 0.6, touchMultiplier: 1.1 });
      const loop = t => { if (lenis) { lenis.raf(t); requestAnimationFrame(loop); } };
      requestAnimationFrame(loop);
    }
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  }

  addEventListener('scroll', snap, { passive: true });
  addEventListener('resize', () => { layout(); if (focusEl) caption(focusEl); });
  start();
})();
