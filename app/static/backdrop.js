// 3D 홈 뒤 배경: 화면 전체를 덮는 고운 점 격자가 앞으로 기운 면처럼 깔려 천천히 일렁인다
// (bloomworld 배경 영상의 느낌을 코드로). 손가락·마우스가 닿으면 물결처럼 밀려나며 밝아지고, 스크롤하면 물결이 흐른다.
(() => {
  const host = document.getElementById('dotfield');
  if (!host) return;
  const canvas = document.createElement('canvas');
  host.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DPR = Math.min(devicePixelRatio || 1, 2);
  const GAP = 18;                  // 화면 위 점 간격(px)
  let W = 0, H = 0, raf = 0, grid = [];
  const pointer = { x: -9999, y: -9999, k: 0 };   // k: 닿아 있는 정도(부드럽게 0↔1)

  function size() {
    W = innerWidth; H = innerHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    grid = [];
    // 화면 전체를 덮는 점 격자. 아래로 갈수록 간격이 살짝 넓어져 앞으로 기울어진 면처럼 보인다
    const rows = Math.ceil(H / GAP) + 4, cols = Math.ceil(W / GAP) + 6;
    for (let r = 0; r < rows; r++) {
      const v = r / rows;
      const y = H * Math.pow(v, 1.12) - GAP;
      const spread = .9 + .22 * v;
      for (let c = -3; c < cols - 3; c++) grid.push({ x: W / 2 + (c * GAP - W / 2) * spread, y, v });
    }
  }

  function draw(ms) {
    const t = ms / 1000 + scrollY * .006;
    pointer.k += ((pointer.x > -999 ? 1 : 0) - pointer.k) * .08;
    ctx.clearRect(0, 0, W, H);
    // 점 색 = 지금 테마의 글자색 (밝은 테마면 검은 점, 어두운 테마면 흰 점)
    const ink = (getComputedStyle(document.body).color.match(/\d+/g) || [255, 255, 255]).slice(0, 3).join(',');
    ctx.fillStyle = `rgb(${ink})`;
    for (const p of grid) {
      // 부드러운 물결: 대각선으로 흐르는 두 겹의 파도
      const h = Math.sin(p.x * .012 + p.y * .006 - t * .7) * .6 + Math.sin(p.x * .004 - p.y * .011 + t * .45) * .4;
      let x = p.x, y = p.y + h * 4;
      let lift = 0;
      if (pointer.k > .01) {                 // 손이 닿은 곳은 물결처럼 밀려나며 밝아진다
        const dx = x - pointer.x, dy = y - pointer.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
        lift = pointer.k * Math.exp(-(d * d) / 7000);
        const push = lift * 10 * Math.sin(d * .05 - t * 4);
        x += dx / d * push; y += dy / d * push;
      }
      const a = (.08 + .1 * p.v + .09 * (h + 1)) + lift * .55;
      const r = .7 + .35 * p.v + .25 * (h + 1) * .5 + lift * 1.2;
      ctx.globalAlpha = Math.min(.8, a);
      ctx.fillRect(x - r / 2, y - r / 2, r, r);
    }
    ctx.globalAlpha = 1;
    if (!still && !document.hidden && !host.closest('[hidden]')) raf = requestAnimationFrame(draw);
  }

  const run = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); };
  const move = e => { pointer.x = e.clientX; pointer.y = e.clientY; };
  addEventListener('pointermove', move, { passive: true });
  addEventListener('pointerdown', move, { passive: true });
  addEventListener('pointerleave', () => { pointer.x = pointer.y = -9999; });
  addEventListener('pointerup', e => { if (e.pointerType !== 'mouse') pointer.x = pointer.y = -9999; });
  addEventListener('resize', () => { size(); run(); });
  document.addEventListener('visibilitychange', run);
  new MutationObserver(run).observe(document.getElementById('drum'), { attributes: true, attributeFilter: ['hidden'] });
  size(); run();
})();
