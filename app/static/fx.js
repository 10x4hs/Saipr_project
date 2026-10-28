// 움직이는 날씨·우주 배경을 캔버스로 그린다. 빗줄기는 세 겹(먼·중간·가까운)의 속도와 굵기로 깊이를 낸다.
(() => {
  const fx = document.getElementById('fx');
  if (!fx) return;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let canvas = null, ctx = null, kind = null, parts = [], raf = 0, W = 0, H = 0, flash = 0, t0 = 0;
  const DPR = Math.min(devicePixelRatio || 1, 2);
  const KINDS = { rain: 1, storm: 1, snow: 1, petals: 1, stars: 1 };
  const rnd = (a, b) => a + Math.random() * (b - a);

  function size() {
    W = innerWidth; H = innerHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function spawn() {
    const area = W * H / 10000;
    if (kind === 'rain' || kind === 'storm') {
      const n = Math.round(area * (kind === 'storm' ? 9 : 6));
      parts = Array.from({ length: n }, () => {
        const z = Math.random();                                   // 0 = 멀다, 1 = 가깝다
        return { x: rnd(-.2, 1.1) * W, y: rnd(-1, 1) * H, z, len: 8 + z * 26, v: 9 + z * 16, w: .4 + z * 1.1, a: .12 + z * .4 };
      });
    } else if (kind === 'snow') {
      parts = Array.from({ length: Math.round(area * 2.2) }, () => {
        const z = Math.random();
        return { x: rnd(0, W), y: rnd(0, H), z, r: .6 + z * 2.6, v: .3 + z * 1.1, ph: rnd(0, 6.28), a: .35 + z * .55 };
      });
    } else if (kind === 'petals') {
      parts = Array.from({ length: Math.round(area * .55) }, () => ({ x: rnd(0, W), y: rnd(-H, H), r: rnd(3, 7), v: rnd(.4, 1.1), rot: rnd(0, 6.28), vr: rnd(-.03, .03), ph: rnd(0, 6.28) }));
    } else if (kind === 'stars') {
      parts = Array.from({ length: Math.round(area * 2.5) }, () => ({ x: rnd(0, W), y: rnd(0, H), r: Math.random() ** 3 * 1.6 + .3, ph: rnd(0, 6.28), sp: rnd(.5, 2) }));
    }
  }

  function draw(time) {
    const dt = Math.min(2, (time - t0) / 16.7 || 1); t0 = time;
    ctx.clearRect(0, 0, W, H);
    if (kind === 'rain' || kind === 'storm') {
      const wind = kind === 'storm' ? .32 : .16;
      ctx.lineCap = 'round';
      // 깊이별 세 겹을 각각 한 번에 그린다(빗방울마다 그리면 휴대폰에서 느리다)
      const layers = [[], [], []];
      for (const p of parts) {
        p.y += p.v * dt; p.x += p.v * wind * dt;
        if (p.y > H + 40) { p.y = rnd(-80, -10); p.x = rnd(-.2, 1.05) * W; }
        layers[p.z < .45 ? 0 : p.z < .8 ? 1 : 2].push(p);
      }
      [[.13, .5], [.24, .9], [.42, 1.4]].forEach(([alpha, width], i) => {
        ctx.strokeStyle = `rgba(205,225,245,${alpha})`; ctx.lineWidth = width; ctx.beginPath();
        for (const p of layers[i]) { ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - p.len * wind, p.y - p.len); }
        ctx.stroke();
      });
      ctx.fillStyle = 'rgba(205,225,245,.18)';
      for (const p of layers[2]) if (p.y > H - 8) { ctx.beginPath(); ctx.ellipse(p.x, H - 3, 3, 1, 0, 0, 6.28); ctx.fill(); }
      if (kind === 'storm') {
        if (flash <= 0 && Math.random() < .0025 * dt) flash = 1;
        if (flash > 0) { ctx.fillStyle = `rgba(210,215,255,${flash * .22})`; ctx.fillRect(0, 0, W, H); flash -= .05 * dt; }
      }
    } else if (kind === 'snow') {
      for (const p of parts) {
        p.y += p.v * dt; p.ph += .01 * dt; p.x += Math.sin(p.ph) * .35 * p.z * dt;
        if (p.y > H + 5) { p.y = -5; p.x = rnd(0, W); }
        ctx.fillStyle = `rgba(255,255,255,${p.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.28); ctx.fill();
      }
    } else if (kind === 'petals') {
      for (const p of parts) {
        p.y += p.v * dt; p.ph += .012 * dt; p.x += Math.sin(p.ph) * .8 * dt; p.rot += p.vr * dt;
        if (p.y > H + 10) { p.y = -10; p.x = rnd(0, W); }
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.scale(1, .55 + .45 * Math.sin(p.ph * 2));
        ctx.fillStyle = 'rgba(255,190,212,.75)'; ctx.beginPath(); ctx.ellipse(0, 0, p.r, p.r * .6, 0, 0, 6.28); ctx.fill(); ctx.restore();
      }
    } else if (kind === 'stars') {
      const s = time / 1000;
      for (const p of parts) {
        const a = .35 + .65 * (.5 + .5 * Math.sin(s * p.sp + p.ph));
        ctx.fillStyle = `rgba(255,255,255,${a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.28); ctx.fill();
      }
    }
    if (!still && !document.hidden) raf = requestAnimationFrame(draw);
  }

  function sync() {
    const next = KINDS[fx.dataset.bg] ? fx.dataset.bg : null;
    if (next === kind) return;
    cancelAnimationFrame(raf); kind = next;
    if (!kind) { canvas?.remove(); canvas = null; return; }
    if (!canvas) { canvas = document.createElement('canvas'); ctx = canvas.getContext('2d'); fx.appendChild(canvas); }
    size(); spawn(); raf = requestAnimationFrame(draw);
  }

  addEventListener('resize', () => { if (canvas) { size(); spawn(); } });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && kind && !still) raf = requestAnimationFrame(draw); });
  new MutationObserver(sync).observe(fx, { attributes: true, attributeFilter: ['data-bg'] });
  sync();
})();
