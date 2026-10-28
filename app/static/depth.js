// 홈 3D: 인기 순위 책들이 깊이(Z) 방향으로 늘어서 있고, 스크롤하면 카메라가 그 사이를 지나간다.
(() => {
  const $ = id => document.getElementById(id);
  const depth = $('depth'), list = $('listview');
  const items = [...document.querySelectorAll('.depth-item')];
  const GAP = 520;               // 책 사이 간격(px, Z 방향)
  const FOCUS = -260;            // 이 깊이에 온 책이 '지금 보는 책'
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = { get: () => { try { return localStorage.getItem('homeView'); } catch (e) { return null; } },
                  set: v => { try { localStorage.setItem('homeView', v); } catch (e) {} } };
  let view = store.get() || (reduced ? 'list' : 'depth');
  let lenis = null, raf = 0, current = -1;

  function setView(v) {
    view = v; store.set(v);
    depth.hidden = v !== 'depth'; list.hidden = v === 'depth';
    document.body.classList.toggle('in-depth', v === 'depth');
    document.querySelectorAll('[data-view-label]').forEach(l => l.textContent = v === 'depth' ? '목록으로 보기' : '3D로 보기');
    if (v === 'depth') start(); else stop();
    window.scrollTo(0, 0);
  }
  document.querySelectorAll('[data-view-toggle]').forEach(b => b.addEventListener('click', () => setView(view === 'depth' ? 'list' : 'depth')));

  function layout() {
    $('depthSpacer').style.height = (items.length * GAP * 0.62 + innerHeight) + 'px';
  }

  function frame() {
    const max = document.documentElement.scrollHeight - innerHeight;
    const t = max > 0 ? scrollY / max : 0;                   // 0 → 1
    const cam = t * (items.length - 1) * GAP;                // 카메라가 나아간 거리
    let best = 0, bestD = Infinity;
    const w = Math.min(innerWidth, 480);
    items.forEach((el, i) => {
      const z = -i * GAP + cam;                              // 0에 가까울수록 앞
      const side = i % 2 ? 1 : -1;
      const x = side * w * 0.2 * Math.min(1, Math.abs(z - FOCUS) / 900 + .35);
      const y = Math.sin(i * 1.7) * 30;
      const rot = -side * 16 + (z - FOCUS) / 40;
      el.style.transform = `translate3d(${x}px, ${y}px, ${z}px) rotateY(${rot}deg)`;
      // 카메라를 지나치기 직전에 빠르게 사라지고, 먼 책은 안개 속처럼 옅어진다
      const fade = z > -80 ? Math.max(0, 1 - (z + 80) / 160) : Math.max(0, 1 + (z + 2600) / 1400);
      el.style.opacity = Math.min(1, fade);
      el.style.filter = z < FOCUS - 500 ? `blur(${Math.min(4, (FOCUS - 500 - z) / 400)}px)` : 'none';
      el.style.pointerEvents = fade > .5 ? 'auto' : 'none';
      el.style.zIndex = 1000 + Math.round(z);
      const d = Math.abs(z - FOCUS);
      if (d < bestD) { bestD = d; best = i; }
    });
    if (best !== current) hud(best);
    $('depthHint').style.opacity = scrollY > 40 ? 0 : 1;
    raf = requestAnimationFrame(frame);
  }

  function hud(i) {
    current = i;
    const el = items[i];
    items.forEach((x, k) => x.classList.toggle('focus', k === i));
    $('hudRank').textContent = `#${String(el.dataset.rank).padStart(2, '0')} · 인기 고전${+el.dataset.readers ? ` · 함께읽기 독자 ${el.dataset.readers}명` : ''}`;
    $('hudTitle').textContent = el.dataset.title;
    $('hudAuthor').textContent = el.dataset.author;
    $('hudRead').href = el.getAttribute('href');
    $('hudRaceForm').action = el.dataset.race;
    const hudEl = $('depthHud'); hudEl.classList.remove('swap'); void hudEl.offsetWidth; hudEl.classList.add('swap');
  }

  function start() {
    layout();
    if (window.Lenis && !lenis) {
      lenis = new Lenis({ lerp: 0.08, wheelMultiplier: 0.9, touchMultiplier: 1.4 });
      const loop = time => { if (lenis) { lenis.raf(time); requestAnimationFrame(loop); } };
      requestAnimationFrame(loop);
    }
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  }
  function stop() { cancelAnimationFrame(raf); if (lenis) { lenis.destroy(); lenis = null; } }

  addEventListener('resize', () => view === 'depth' && layout());
  setView(view);
})();
