// 홈 3D 드럼: 책이 세 권씩 줄지어 원통 바깥에 꽂혀 있고, 스크롤하면 원통이 굴러 줄이 위로 말려 올라간다.
(() => {
  const $ = id => document.getElementById(id);
  const drum = $('drum'), list = $('listview'), axis = $('drumAxis');
  const rows = [...document.querySelectorAll('.drum-row')];
  const STEP = 27;                 // 줄 사이 각도(도) — 클수록 더 둥글게 말린다
  const PX_PER_ROW = 150;          // 한 줄 넘기는 데 필요한 스크롤 거리
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = { get: () => { try { return localStorage.getItem('homeView'); } catch (e) { return null; } },
                  set: v => { try { localStorage.setItem('homeView', v); } catch (e) {} } };
  let view = store.get() === 'list' ? 'list' : 'drum';
  let lenis = null, raf = 0, focusEl = null, radius = 400;

  function setView(v) {
    view = v; store.set(v);
    drum.hidden = v !== 'drum'; list.hidden = v === 'drum';
    document.body.classList.toggle('in-drum', v === 'drum');
    document.querySelectorAll('[data-view-label]').forEach(l => l.textContent = v === 'drum' ? '목록으로 보기' : '3D로 보기');
    v === 'drum' ? start() : stop();
    scrollTo(0, 0);
  }
  document.querySelectorAll('[data-view-toggle]').forEach(b => b.addEventListener('click', () => setView(view === 'drum' ? 'list' : 'drum')));

  function layout() {
    const rowH = rows[0]?.offsetHeight || 180;
    // 줄 높이와 각도로 원통 반지름을 정한다: 이웃한 줄이 겹치지 않을 만큼
    radius = (rowH + 18) / (2 * Math.sin(STEP * Math.PI / 360));
    axis.style.transform = `translateZ(${-radius}px)`;
    $('drumSpacer').style.height = ((rows.length - 1) * PX_PER_ROW + innerHeight) + 'px';
  }

  function frame() {
    const pos = scrollY / PX_PER_ROW;              // 지금 맨 앞에 온 줄(소수)
    let best = null;
    rows.forEach((row, r) => {
      const a = (r - pos) * STEP;                 // 앞(0°)에서 위로 말려 올라가면 +각도
      const hidden = a < -95 || a > 95;
      row.style.visibility = hidden ? 'hidden' : 'visible';
      if (hidden) return;
      row.style.transform = `rotateX(${-a}deg) translateZ(${radius}px)`;
      const k = Math.cos(a * Math.PI / 180);
      row.style.opacity = Math.max(0, Math.min(1, k * 1.6 - .2));
      row.style.filter = Math.abs(a) > 40 ? `brightness(${.4 + .6 * k})` : 'none';
      row.classList.toggle('front', Math.abs(a) < STEP / 2);
      if (Math.abs(a) < STEP / 2) best = row.children[Math.min(1, row.children.length - 1)];
    });
    if (best && best !== focusEl) hud(best);
    raf = requestAnimationFrame(frame);
  }

  function hud(el) {
    focusEl = el;
    document.querySelectorAll('.drum-book.focus').forEach(x => x.classList.remove('focus'));
    el.classList.add('focus');
    const rank = el.dataset.rank, readers = +el.dataset.readers;
    $('hudRank').textContent = rank ? `인기 ${rank}위${readers ? ` · 독자 ${readers}명` : ''}` : '오늘의 추천';
    $('hudTitle').textContent = el.dataset.title;
    $('hudAuthor').textContent = el.dataset.author;
    $('hudRead').href = el.getAttribute('href');
    $('hudRaceForm').action = el.dataset.race;
    const h = $('drumHud'); h.classList.remove('swap'); void h.offsetWidth; h.classList.add('swap');
  }
  // 어느 책이든 누르기 전에 살짝 고르면(마우스 올림·터치) 아래 카드에 보인다
  document.querySelectorAll('.drum-book').forEach(b => b.addEventListener('pointerenter', () => hud(b)));

  function start() {
    layout();
    if (window.Lenis && !lenis && !reduced) {
      lenis = new Lenis({ lerp: 0.085, wheelMultiplier: 0.8, touchMultiplier: 1.3 });
      const loop = t => { if (lenis) { lenis.raf(t); requestAnimationFrame(loop); } };
      requestAnimationFrame(loop);
    }
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  }
  function stop() { cancelAnimationFrame(raf); if (lenis) { lenis.destroy(); lenis = null; } }

  addEventListener('resize', () => view === 'drum' && layout());
  setView(view);
})();
