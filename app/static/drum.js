// 홈 3D: 책이 세 권씩 줄지어 펼쳐져 있고, 스크롤하면 맨 윗줄부터 화면 위쪽의 롤러에 감기듯 말려 올라간다.
// 롤러 아래 줄은 평평한 격자라 첫 화면에 책이 많이 보이고, 감기는 줄만 원통을 따라 뒤로 넘어간다.
(() => {
  const $ = id => document.getElementById(id);
  const drum = $('drum'), list = $('listview'), axis = $('drumAxis');
  const rows = [...document.querySelectorAll('.drum-row')];
  const ROLL_R = 95;                // 롤러 반지름(px) — 작을수록 더 촘촘히 말린다
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = { get: () => { try { return localStorage.getItem('homeView'); } catch (e) { return null; } },
                  set: v => { try { localStorage.setItem('homeView', v); } catch (e) {} } };
  let view = store.get() === 'list' ? 'list' : 'drum';
  let lenis = null, raf = 0, focusEl = null, pitch = 200;

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
    pitch = (rows[0]?.offsetHeight || 180) + 26;         // 줄 간격 = 스크롤 한 줄
    $('drumSpacer').style.height = ((rows.length - 1) * pitch + innerHeight * .6) + 'px';
  }

  function frame() {
    const pos = scrollY / pitch;                           // 롤러에 감긴 줄 수(소수)
    let best = null;
    rows.forEach((row, r) => {
      const d = r - pos;
      let tf, alpha = 1;
      if (d >= 0) {                                        // 롤러 아래: 평평하게
        tf = `translate3d(0, ${d * pitch}px, 0)`;
        alpha = d * pitch > innerHeight ? 0 : 1;
      } else {                                             // 롤러 위: 원통을 따라 감긴다
        const theta = (-d * pitch) / ROLL_R;               // 감긴 호의 각도(rad)
        if (theta > 2.1) { row.style.visibility = 'hidden'; return; }
        tf = `translate3d(0, ${-ROLL_R * Math.sin(theta)}px, ${-ROLL_R * (1 - Math.cos(theta))}px) rotateX(${theta}rad)`;
        alpha = Math.max(0, Math.cos(theta * .85));
      }
      row.style.visibility = alpha ? 'visible' : 'hidden';
      row.style.transform = tf;
      row.style.opacity = alpha;
      row.style.filter = d < 0 ? `brightness(${.35 + .65 * alpha})` : 'none';
      const front = d >= -.5 && d < .5;
      row.classList.toggle('front', front);
      if (front) best = row.children[Math.min(1, row.children.length - 1)];
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
