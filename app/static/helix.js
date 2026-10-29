// 홈 3D (bloomworld 방식): 책들이 나선 계단을 따라 위쪽·뒤쪽으로 감겨 쌓여 있다.
// 스크롤하면 나선 전체가 앞으로 돌아 내려와, 맨 앞 책은 화면 앞으로 지나가고 다음 책이 그 자리에 온다.
// 책은 앞표지·책등·페이지 단면이 있는 3D 상자이고, 부모에 opacity/filter를 걸지 않아 입체가 눌리지 않는다.
(() => {
  const $ = id => document.getElementById(id);
  const home = $('drum'), list = $('listview');
  const books = [...document.querySelectorAll('.hx-book')];
  const PER = 150;            // 책 한 권 넘기는 스크롤 거리(px)
  const TURN = 24;            // 다음 책까지 나선이 도는 각도(도)
  const RISE = 62;            // 다음 책까지 올라가는 높이(px)
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = { get: () => { try { return localStorage.getItem('homeView'); } catch (e) { return null; } },
                  set: v => { try { localStorage.setItem('homeView', v); } catch (e) {} } };
  let view = store.get() === 'list' ? 'list' : 'drum';
  let lenis = null, raf = 0, focusEl = null, R = 160, hudTimer = 0, snapTimer = 0;

  function setView(v) {
    view = v; store.set(v);
    home.hidden = v !== 'drum'; list.hidden = v === 'drum';
    document.body.classList.toggle('in-drum', v === 'drum');
    document.querySelectorAll('[data-view-label]').forEach(l => l.textContent = v === 'drum' ? '목록으로 보기' : '3D로 보기');
    v === 'drum' ? start() : stop();
    scrollTo(0, 0);
  }
  document.querySelectorAll('[data-view-toggle]').forEach(b => b.addEventListener('click', () => setView(view === 'drum' ? 'list' : 'drum')));

  function layout() {
    R = Math.min(innerWidth, 480) * .42;                 // 나선 반지름
    $('drumSpacer').style.height = ((books.length - 1) * PER + innerHeight) + 'px';
  }

  function frame() {
    const pos = scrollY / PER;
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
    const rank = el.dataset.rank, readers = +el.dataset.readers;
    const text = $('drumHud').querySelector('.hud-text');
    text.classList.add('fading');
    clearTimeout(hudTimer);
    hudTimer = setTimeout(() => {                        // 흐려진 뒤 바꾸고 다시 선명하게
      $('hudRank').textContent = rank ? `인기 ${rank}위${readers ? ` · 독자 ${readers}명` : ''}` : '오늘의 추천';
      $('hudTitle').textContent = el.dataset.title;
      $('hudAuthor').textContent = el.dataset.author || '\u00a0';
      text.classList.remove('fading');
    }, 140);
    $('hudRead').href = el.getAttribute('href');
    $('hudRaceForm').action = el.dataset.race;
  }

  // 스크롤이 멈추면 가장 가까운 책에 부드럽게 맞춘다
  function snap() {
    clearTimeout(snapTimer);
    snapTimer = setTimeout(() => {
      const target = Math.round(scrollY / PER) * PER;
      if (Math.abs(target - scrollY) < 2) return;
      if (lenis) lenis.scrollTo(target, { duration: .9, easing: t => 1 - Math.pow(1 - t, 4) });
      else scrollTo({ top: target, behavior: 'smooth' });
    }, 160);
  }

  function start() {
    layout();
    if (window.Lenis && !lenis && !reduced) {
      lenis = new Lenis({ lerp: 0.06, wheelMultiplier: 0.6, touchMultiplier: 1.1 });
      const loop = t => { if (lenis) { lenis.raf(t); requestAnimationFrame(loop); } };
      requestAnimationFrame(loop);
    }
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  }
  function stop() { cancelAnimationFrame(raf); if (lenis) { lenis.destroy(); lenis = null; } }

  addEventListener('scroll', () => view === 'drum' && snap(), { passive: true });
  addEventListener('resize', () => view === 'drum' && layout());
  setView(view);
})();
