// 앱 공통: 오른쪽 위 메뉴, 화면 꾸미기 시트
(() => {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const root = document.documentElement;
  const csrf = document.querySelector('meta[name="csrf"]')?.content;

  // --- 메뉴 ---
  const menuBtn = $('#menuBtn'), menu = $('#menu');
  const setMenu = open => { menu.hidden = !open; menuBtn.setAttribute('aria-expanded', open); menuBtn.classList.toggle('open', open); };
  menuBtn?.addEventListener('click', () => setMenu(menu.hidden));
  menu?.addEventListener('click', e => { if (e.target === menu || e.target.closest('a,button')) setMenu(false); });
  addEventListener('keydown', e => { if (e.key === 'Escape') { setMenu(false); closeLook(true); } });

  // --- 화면 꾸미기 ---
  const sheet = $('#look');
  if (!sheet) return;
  const saved = { mode: root.dataset.theme || 'auto', bg: $('#fx').dataset.bg, accent: root.dataset.accent, hex: getComputedStyle(root).getPropertyValue('--accent').trim() };
  let pick = { ...saved };

  const apply = p => {
    if (p.mode === 'auto') delete root.dataset.theme; else root.dataset.theme = p.mode;
    $('#fx').dataset.bg = p.bg; $('#lookPreviewBg').dataset.bg = p.bg;
    root.dataset.accent = p.accent; root.style.setProperty('--accent', p.hex);
    $$('#lookMode button').forEach(b => b.setAttribute('aria-pressed', b.dataset.mode === p.mode));
    $$('[data-bgpick]').forEach(b => b.setAttribute('aria-pressed', b.dataset.bgpick === p.bg));
    $$('#lookAccent button').forEach(b => b.setAttribute('aria-pressed', b.dataset.accent === p.accent));
  };
  function openLook() { pick = { ...saved }; apply(pick); sheet.hidden = false; document.body.classList.add('locked'); }
  function closeLook(revert) { if (sheet.hidden) return; if (revert) apply(saved); sheet.hidden = true; document.body.classList.remove('locked'); }
  window.closeLook = closeLook;

  $$('[data-open-look]').forEach(b => b.addEventListener('click', openLook));
  $$('[data-close-look]').forEach(b => b.addEventListener('click', () => closeLook(true)));
  sheet.addEventListener('click', e => { if (e.target === sheet) closeLook(true); });
  $$('#lookMode button').forEach(b => b.onclick = () => apply(pick = { ...pick, mode: b.dataset.mode }));
  $$('[data-bgpick]').forEach(b => b.onclick = () => apply(pick = { ...pick, bg: b.dataset.bgpick }));
  $$('#lookAccent button').forEach(b => b.onclick = () => apply(pick = { ...pick, accent: b.dataset.accent, hex: b.dataset.hex }));
  $$('#bgTabs button').forEach(t => t.onclick = () => {
    $$('#bgTabs button').forEach(x => x.setAttribute('aria-pressed', x === t));
    $$('[data-group-panel]').forEach(p => p.hidden = p.dataset.groupPanel !== t.dataset.group);
  });
  $('#lookReset').onclick = () => {
    const d = $('#lookAccent button[data-accent="pink"]');
    apply(pick = { mode: 'auto', bg: 'plain', accent: 'pink', hex: d.dataset.hex });
  };
  $('#lookDone').onclick = async () => {
    const btn = $('#lookDone'); btn.disabled = true; btn.textContent = '저장 중…';
    try {
      const r = await fetch('/api/v1/me/settings', {
        method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ mode: pick.mode, bg: pick.bg, accent: pick.accent }),
      });
      if (!r.ok) throw new Error(r.status);
      Object.assign(saved, pick);
      closeLook(false);
    } catch (e) { btn.textContent = '다시 시도'; btn.disabled = false; return; }
    btn.textContent = '완료'; btn.disabled = false;
  };
  if (location.hash === '#look') openLook();
})();
