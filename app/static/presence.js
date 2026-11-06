// 함께 읽는 중(presence) + 문장 공유 — reader.js와 따로 동작한다.
// 지금 쪽은 (1) 'haedok:page' 이벤트(detail.chunk) (2) reader.js의 진행 저장 요청 (3) #stage 의 data-start 순으로 알아낸다.
// 실시간 기본값은 5초 폴링: Vercel 서버리스는 메모리 WebSocket 허브를 붙들 수 없다.
(() => {
  const stage = document.getElementById('stage');
  if (!stage) return;
  const bookId = stage.dataset.book, csrf = stage.dataset.csrf;
  const total = +stage.dataset.total || 1;
  let chunk = Math.max(0, Math.min(+stage.dataset.start || 0, total - 1));
  let rooms = [], friends = [], timer = null;
  const BEAT = 5000;

  // ── 지금 쪽 알아내기 ──
  const setChunk = i => {
    i = +i;
    if (!Number.isFinite(i) || i === chunk) return;
    chunk = Math.max(0, Math.min(i, total - 1));
    paint();
    clearTimeout(setChunk.t);
    setChunk.t = setTimeout(beat, 400);  // 쪽을 넘기면 곧바로 알린다(연속 넘김은 묶어서)
  };
  document.addEventListener('haedok:page', e => setChunk(e.detail && (e.detail.chunk ?? e.detail.index)));
  const progressUrl = `/api/v1/books/${bookId}/progress`;
  const origFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    try {
      const url = typeof input === 'string' ? input : input && input.url;
      if (url && url.endsWith(progressUrl) && init && init.method === 'PUT' && typeof init.body === 'string') {
        setChunk(JSON.parse(init.body).chunk_index);
      }
    } catch (e) { /* 진행 저장은 그대로 보낸다 */ }
    return origFetch(input, init);
  };

  // ── 화면 ──
  const css = document.createElement('style');
  css.textContent = `
.pz-pill{position:fixed;z-index:21;right:max(14px,calc(50% - var(--app,720px) / 2 + 14px));top:calc(66px + env(safe-area-inset-top));display:flex;align-items:center;gap:8px;max-width:calc(100% - 28px);padding:5px 12px 5px 6px;border-radius:999px;font-size:12px;
  background:color-mix(in srgb,var(--surface,#fff) 82%,transparent);border:1px solid var(--glass-line,rgba(0,0,0,.08));backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);box-shadow:0 6px 24px rgba(0,0,0,.12);animation:pz-in .4s cubic-bezier(.16,1,.3,1)}
.pz-pill[hidden]{display:none}
.pz-faces{display:flex}
.pz-face{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;overflow:hidden;font-size:12px;font-weight:600;background:var(--accent,#6b5);color:var(--accent-ink,#fff);border:2px solid var(--surface,#fff);margin-left:-8px;position:relative}
.pz-face:first-child{margin-left:0}
.pz-face img{width:100%;height:100%;object-fit:cover}
.pz-face.here::after{content:"";position:absolute;right:0;bottom:0;width:8px;height:8px;border-radius:50%;background:#3c3;box-shadow:0 0 0 2px var(--surface,#fff)}
.pz-text{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text,inherit)}
.pz-share{position:fixed;z-index:30;padding:8px 14px;border-radius:999px;border:0;font:inherit;font-size:13px;font-weight:600;background:var(--accent,#333);color:var(--accent-ink,#fff);box-shadow:0 8px 24px rgba(0,0,0,.2);cursor:pointer;transform:translate(-50%,-100%)}
.pz-menu{position:fixed;z-index:30;display:grid;gap:4px;padding:6px;border-radius:14px;background:var(--surface,#fff);border:1px solid var(--glass-line,rgba(0,0,0,.08));box-shadow:0 8px 24px rgba(0,0,0,.2);transform:translate(-50%,-100%)}
.pz-menu button{border:0;background:none;font:inherit;font-size:13px;padding:8px 12px;border-radius:10px;text-align:left;color:var(--text,inherit);cursor:pointer}
.pz-menu button:hover{background:var(--sunken,rgba(0,0,0,.05))}
.pz-toast{position:fixed;z-index:31;left:50%;bottom:calc(84px + env(safe-area-inset-bottom));transform:translateX(-50%);padding:9px 16px;border-radius:999px;font-size:13px;background:rgba(20,20,20,.86);color:#fff;animation:pz-in .3s ease}
@keyframes pz-in{from{opacity:0;transform:translateY(-6px)}}
@media (prefers-reduced-motion:reduce){.pz-pill,.pz-toast{animation:none}}`;
  document.head.appendChild(css);

  const pill = document.createElement('div');
  pill.className = 'pz-pill'; pill.hidden = true; pill.setAttribute('aria-live', 'polite');
  pill.innerHTML = '<span class="pz-faces"></span><span class="pz-text"></span>';
  document.body.appendChild(pill);

  const face = f => {
    const el = document.createElement('span');
    el.className = 'pz-face' + (f.chunk === chunk ? ' here' : '');
    el.title = `${f.nickname} · ${f.chunk + 1}쪽`;
    if (f.avatar) { const im = new Image(); im.src = f.avatar; im.alt = ''; el.appendChild(im); } else el.textContent = f.nickname.slice(0, 1);
    return el;
  };

  function paint() {
    if (!friends.length) { pill.hidden = true; return; }
    const here = friends.filter(f => f.chunk === chunk);
    const others = friends.filter(f => f.chunk !== chunk).sort((a, b) => Math.abs(a.chunk - chunk) - Math.abs(b.chunk - chunk));
    const faces = pill.querySelector('.pz-faces');
    faces.replaceChildren(...[...here, ...others].slice(0, 4).map(face));
    let text;
    if (here.length === 1) text = `${here[0].nickname}님이 이 쪽을 읽고 있어요`;
    else if (here.length > 1) text = `친구 ${here.length}명이 이 쪽을 읽고 있어요`;
    else text = others.slice(0, 2).map(f => `${f.nickname} ${f.chunk + 1}쪽`).join(' · ') + ' 읽는 중';
    pill.querySelector('.pz-text').textContent = text;
    pill.hidden = false;
  }

  // ── 심장박동(겸 조회) ──
  async function beat() {
    if (document.hidden) return;
    try {
      const r = await origFetch(`/api/v1/books/${bookId}/presence`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ chunk_index: chunk }),
      });
      if (!r.ok) return;
      const d = await r.json();
      rooms = d.rooms || [];
      friends = d.friends || [];
      paint();
      // 대결방이 없으면 굳이 자주 묻지 않는다
      schedule(rooms.length ? BEAT : BEAT * 6);
    } catch (e) { /* 네트워크가 잠깐 끊겨도 다음 박동에서 다시 */ }
  }
  function schedule(ms) { clearInterval(timer); timer = setInterval(beat, ms); }
  schedule(BEAT);
  beat();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) beat(); });

  // ── 문장 공유: 본문에서 고르면 '대결방에 공유' ──
  let btn = null, menu = null;
  const close = () => { btn?.remove(); menu?.remove(); btn = menu = null; };
  const toast = msg => {
    const t = document.createElement('div'); t.className = 'pz-toast'; t.textContent = msg;
    document.body.appendChild(t); setTimeout(() => t.remove(), 2400);
  };
  const share = async (roomId, text) => {
    close();
    try {
      const r = await origFetch(`/api/v1/races/${roomId}/quotes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ chunk_index: chunk, text }),
      });
      if (r.ok) { toast('대결방에 공유했어요'); window.getSelection()?.removeAllRanges(); return; }
      const d = await r.json().catch(() => ({}));
      toast(typeof d.detail === 'string' ? d.detail : '공유하지 못했어요');
    } catch (e) { toast('공유하지 못했어요'); }
  };
  const selected = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    if (!stage.contains(range.commonAncestorContainer)) return null;
    const text = sel.toString().replace(/\s+/g, ' ').trim();
    return text ? { text: text.slice(0, 280), rect: range.getBoundingClientRect() } : null;
  };
  const offer = () => {
    close();
    if (!rooms.length) return;
    const s = selected();
    if (!s) return;
    const x = Math.min(Math.max(s.rect.left + s.rect.width / 2, 80), innerWidth - 80);
    const y = Math.max(s.rect.top - 8, 60);
    btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'pz-share'; btn.textContent = '대결방에 공유';
    btn.style.left = x + 'px'; btn.style.top = y + 'px';
    // 누르는 순간 선택이 풀리지 않게
    btn.addEventListener('pointerdown', e => e.preventDefault());
    btn.addEventListener('click', e => {
      e.stopPropagation();
      if (rooms.length === 1) return share(rooms[0].id, s.text);
      menu = document.createElement('div'); menu.className = 'pz-menu';
      menu.style.left = x + 'px'; menu.style.top = y + 'px';
      rooms.forEach(room => {
        const b = document.createElement('button'); b.type = 'button'; b.textContent = room.name;
        b.addEventListener('pointerdown', ev => ev.preventDefault());
        b.addEventListener('click', ev => { ev.stopPropagation(); share(room.id, s.text); });
        menu.appendChild(b);
      });
      btn.remove(); btn = null;
      document.body.appendChild(menu);
    });
    document.body.appendChild(btn);
  };
  let pending = null;
  document.addEventListener('selectionchange', () => { clearTimeout(pending); pending = setTimeout(offer, 350); });
  document.addEventListener('pointerdown', e => { if (!e.target.closest('.pz-share,.pz-menu')) close(); });
})();
