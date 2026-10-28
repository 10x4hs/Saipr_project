// 이어 읽기 · 진행률 막대 (브라우저에 저장된 읽기 기록)
(() => {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('progress') || '{}'); } catch (e) {}
  document.querySelectorAll('.book[data-id]').forEach(a => {
    const p = saved[a.dataset.id];
    if (p) a.querySelector('.bar i').style.setProperty('--p', ((p.index + 1) / p.total * 100) + '%');
  });
  const last = Object.entries(saved).sort((a, b) => b[1].at - a[1].at)[0];
  if (last) {
    const [id, p] = last, el = document.getElementById('resume');
    el.href = `/books/${id}`;
    el.innerHTML = `이어 읽기 <b>${p.title}</b> <span class="mono">${p.index + 1} / ${p.total}</span>`;
    el.hidden = false;
  }
})();
