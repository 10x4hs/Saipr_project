// 손에 반응하는 움직임 — 모든 화면 공통.
// 1) [data-tilt] 요소가 PC는 마우스, 휴대폰은 기기 기울기를 따라 살짝 기운다(transform만 바꿔 가볍다)
// 2) 책을 누르면 그 표지가 다음 화면(리더·서점)으로 이어지도록 이름을 붙인다(View Transitions)
// 3) haedok.fly(): 친구 반응·추월 소식이 화면 가장자리에서 아바타로 날아와 목적지에 내려앉는다
(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  };

  // ---------- 1. 기울기 ----------
  const targets = [...document.querySelectorAll('[data-tilt]')];
  let nx = 0, ny = 0, queued = false;
  const paint = () => {
    queued = false;
    targets.forEach(el => {
      const max = +el.dataset.tilt || 10;
      el.style.setProperty('--tx', (nx * max).toFixed(2) + 'deg');
      el.style.setProperty('--ty', (-ny * max).toFixed(2) + 'deg');
    });
  };
  const aim = (x, y) => {
    nx = Math.max(-1, Math.min(1, x)); ny = Math.max(-1, Math.min(1, y));
    if (!queued) { queued = true; requestAnimationFrame(paint); }
  };

  if (targets.length && !reduced) {
    addEventListener('pointermove', e => {
      if (e.pointerType === 'mouse') aim(e.clientX / innerWidth * 2 - 1, e.clientY / innerHeight * 2 - 1);
    }, { passive: true });
    document.addEventListener('mouseleave', () => aim(0, 0));

    // 휴대폰: 처음 잡은 자세를 기준으로 좌우(gamma)·앞뒤(beta)로 기운 만큼. 기준은 천천히 따라가 자세를 바꿔도 제자리로 돌아온다
    let g0 = null, b0 = null;
    const onTilt = e => {
      if (e.gamma == null || e.beta == null) return;
      if (g0 === null) { g0 = e.gamma; b0 = e.beta; }
      g0 += (e.gamma - g0) * .01; b0 += (e.beta - b0) * .01;
      aim((e.gamma - g0) / 20, (e.beta - b0) / 20);
    };
    const listen = () => addEventListener('deviceorientation', onTilt, { passive: true });
    const D = window.DeviceOrientationEvent;
    if (matchMedia('(pointer: coarse)').matches && D) {
      if (typeof D.requestPermission !== 'function') listen();          // 안드로이드: 허락 없이 된다
      else if (store.get('tilt') !== 'denied') {
        // 아이폰은 사용자가 화면을 누른 순간에만 허락을 물을 수 있다. 링크·버튼을 누른 탭은 피한다
        const ask = e => {
          if (e.target.closest('a,button,input,label,select,textarea')) return;
          document.removeEventListener('click', ask);
          D.requestPermission().then(r => { store.set('tilt', r); if (r === 'granted') listen(); }).catch(() => {});
        };
        document.addEventListener('click', ask);
      }
    }
  }

  // ---------- 2. 표지 → 다음 화면 이어짐 ----------
  // 누른 책의 앞표지에만 이름을 붙인다. 다음 화면의 리더 무대·서점 표지가 같은 이름을 갖고 있어 그 자리로 커진다
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href^="/open/"],a[href^="/books/"],a[href^="/store/"]');
    if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const face = a.querySelector('.bk-front,.flatbook,img');
    if (!face) return;
    // 이름은 화면에 하나만 있어야 한다: 다른 책·늘 이름을 가진 표지(서점)·리더 무대는 잠시 이름을 뗀다
    document.querySelectorAll('[style*="view-transition-name"]').forEach(el => { el.style.viewTransitionName = ''; });
    document.querySelectorAll('.store-cover,.r-stage').forEach(el => { el.style.viewTransitionName = 'none'; });
    face.style.viewTransitionName = 'book';
  });
  // 뒤로 가기로 돌아왔을 때 남은 이름 때문에 다음 전환이 꼬이지 않게
  addEventListener('pageshow', () => document.querySelectorAll('.bk-front,.flatbook,img').forEach(el => { el.style.viewTransitionName = ''; }));

  // ---------- 3. 날아오는 소식 ----------
  // 소식이 한꺼번에 오면 겹치지 않게 1.1초 간격으로 차례로 날린다
  let nextAt = 0;
  function fly(news) {
    const wait = Math.max(0, nextAt - Date.now());
    nextAt = Date.now() + wait + 1100;
    setTimeout(() => launch(news), wait);
  }
  function launch({ name = '', avatar = '', text = '', to = null }) {
    const el = document.createElement('div');
    el.className = 'fly glass';
    el.setAttribute('role', 'status');
    const av = document.createElement('span');
    av.className = 'avatar sm';
    if (avatar) { const im = new Image(); im.src = avatar; im.alt = ''; av.appendChild(im); } else av.textContent = name.slice(0, 1);
    const t = document.createElement('span');
    t.textContent = text;
    el.append(av, t);
    document.body.appendChild(el);

    const w = el.offsetWidth, h = el.offsetHeight;
    const r = to && to.getBoundingClientRect();
    const tx = r && r.width ? r.left + r.width / 2 : innerWidth - 40;
    const ty = r && r.height ? r.top + r.height / 2 : 90;
    // 목적지가 화면 아래쪽이면 그 위에, 위쪽이면 그 아래에 잠시 머문다
    const my = ty > innerHeight / 2 ? ty - h - 36 : ty + 36;
    const mx = Math.max(16, Math.min(innerWidth - w - 16, tx - w / 2));
    if (reduced) {
      el.style.transform = `translate(${mx}px, ${my}px)`;
      setTimeout(() => el.remove(), 3000);
      return;
    }
    const anim = el.animate([
      { transform: `translate(${innerWidth + 20}px, ${my + 40}px) scale(.7)`, opacity: 0 },
      { transform: `translate(${mx}px, ${my}px) scale(1)`, opacity: 1, offset: .18 },
      { transform: `translate(${mx}px, ${my}px) scale(1)`, opacity: 1, offset: .8 },
      { transform: `translate(${tx - w / 2}px, ${ty - h / 2}px) scale(.2)`, opacity: 0 },
    ], { duration: 3200, easing: 'cubic-bezier(.16,1,.3,1)', fill: 'forwards' });
    anim.onfinish = () => {
      el.remove();
      if (to) to.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.25)' }, { transform: 'scale(1)' }], { duration: 420, easing: 'ease-out' });
    };
  }

  window.haedok = { fly };
})();
