// 함께 읽는 중(presence) + 문장 공유 — reader.js와 따로 동작한다.
// 지금 쪽은 (1) 'haedok:page' 이벤트(detail.chunk) (2) reader.js의 진행 저장 요청 (3) #stage 의 data-start 순으로 알아낸다.
// 실시간은 5초 폴링: Vercel 서버리스는 메모리 WebSocket 허브를 붙들 수 없다. 서버는 60초 소식 없는 사람을 뺀다.
// 보이는 곳: 쪽 위 가장자리의 색 아바타(같은 쪽이면 이름표·맥박), 하단 막대의 색 점, 오고 갈 때 토스트.
// 친구마다 색 하나 — reader.js(오른쪽 열·하단 동그라미)도 window.haedokPresence.colorOf 로 같은 색을 쓴다.
(() => {
  const stage = document.getElementById('stage');
  if (!stage) return;
  const bookId = stage.dataset.book, csrf = stage.dataset.csrf;
  const total = +stage.dataset.total || 1;
  let chunk = Math.max(0, Math.min(+stage.dataset.start || 0, total - 1));
  let rooms = [], friends = [], lastOk = 0, primed = false;
  let seenAt = new Map(), seenChunk = chunk;   // 지난 박동 때 친구 위치, 그때 내 쪽
  const BEAT = 5000, STALE = 60000;

  // ── 친구 색: 대결 화면(palette.js / app/services/palette.py)과 같은 목록·규칙 PALETTE[id % 8] ──
  // palette.js가 먼저 불렸으면 그것을 쓰고, 아니면 같은 내용의 사본을 쓴다
  const PALETTE = ['#E8603C', '#2F80ED', '#1FA463', '#9B51E0', '#E0457B', '#C9920A', '#0E9AA7', '#5B6CD9'];
  const colorOf = uid => (typeof window.colorFor === 'function' ? window.colorFor(uid)
    : PALETTE[(Math.abs(Math.trunc(Number(uid))) || 0) % PALETTE.length]);
  window.haedokPresence = { colorOf, friends: () => friends.slice() };

  // ── 지금 쪽 알아내기 ──
  const setChunk = i => {
    i = +i;
    if (!Number.isFinite(i) || i === chunk) return;
    chunk = Math.max(0, Math.min(i, total - 1));
    paint();
    const here = friends.filter(f => f.chunk === chunk);
    if (here.length) toast(here[0], here.length > 1 ? `친구 ${here.length}명이 이 쪽에 있어요` : `${here[0].nickname}님이 이 쪽에 있어요`);
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
.pz-edge{position:fixed;z-index:22;display:flex;align-items:center;gap:8px;flex-direction:row-reverse;pointer-events:none;max-width:calc(100% - 24px)}
.pz-edge[hidden]{display:none}
.pz-here{display:flex;align-items:center;gap:8px;padding:3px 12px 3px 3px;border-radius:999px;pointer-events:auto;
  background:color-mix(in srgb,var(--pc) 16%,var(--bg,#fff));border:1.5px solid var(--pc);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  box-shadow:0 6px 22px color-mix(in srgb,var(--pc) 35%,transparent);animation:pz-in .45s cubic-bezier(.16,1,.3,1);min-width:0}
.pz-here .pz-text{font-size:12.5px;font-weight:600;color:var(--text,inherit);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pz-faces{display:flex;flex:none}
.pz-face{--pc:#888;position:relative;flex:none;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;font:700 12px var(--f-ui,system-ui);color:#fff;background:var(--pc);
  box-shadow:0 0 0 2px var(--surface-solid,var(--bg,#fff)),0 0 0 4px var(--pc);margin-left:-6px}
.pz-face:first-child{margin-left:0}
.pz-face img{width:100%;height:100%;object-fit:cover;border-radius:50%}
.pz-here .pz-face::after{content:"";position:absolute;inset:-4px;border-radius:50%;border:2px solid var(--pc);animation:pz-pulse 1.8s ease-out infinite}
.pz-away{pointer-events:auto;position:relative;opacity:.92}
.pz-away .pz-face{width:24px;height:24px;font-size:11px;margin:0;box-shadow:0 0 0 2px var(--bg,#fff),0 0 0 3.5px var(--pc)}
.pz-away b{position:absolute;right:-7px;bottom:-6px;min-width:18px;height:15px;padding:0 4px;border-radius:8px;font:600 9.5px/15px var(--f-mono,monospace);text-align:center;color:#fff;background:var(--pc);box-shadow:0 0 0 1.5px var(--bg,#fff)}
.pz-more{pointer-events:auto;font-size:11px;font-weight:600;color:var(--dim,#888);padding:0 4px}
.r-stage.pz-shared{box-shadow:0 0 0 2px var(--pc),0 0 28px -4px var(--pc);border-radius:14px;animation:pz-glow 2.4s ease-in-out infinite}
.pz-mark{position:absolute;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;background:var(--pc);box-shadow:0 0 0 2px var(--bg,#000);pointer-events:auto}
.pz-mark.here{width:14px;height:14px;margin:-7px 0 0 -7px;animation:pz-dot 1.8s ease-out infinite}
.pz-share{position:fixed;z-index:30;padding:8px 14px;border-radius:999px;border:0;font:inherit;font-size:13px;font-weight:600;background:var(--accent,#333);color:var(--accent-ink,#fff);box-shadow:0 8px 24px rgba(0,0,0,.2);cursor:pointer;transform:translate(-50%,-100%)}
.pz-menu{position:fixed;z-index:30;display:grid;gap:4px;padding:6px;border-radius:14px;background:var(--surface,#fff);border:1px solid var(--glass-line,rgba(0,0,0,.08));box-shadow:0 8px 24px rgba(0,0,0,.2);transform:translate(-50%,-100%)}
.pz-menu button{border:0;background:none;font:inherit;font-size:13px;padding:8px 12px;border-radius:10px;text-align:left;color:var(--text,inherit);cursor:pointer}
.pz-menu button:hover{background:var(--sunken,rgba(0,0,0,.05))}
.pz-toast{position:fixed;z-index:31;left:50%;bottom:calc(108px + env(safe-area-inset-bottom));transform:translateX(-50%);display:flex;align-items:center;gap:8px;max-width:calc(100% - 32px);
  padding:6px 16px 6px 6px;border-radius:999px;font-size:13px;font-weight:500;white-space:nowrap;background:rgba(20,20,22,.9);color:#fff;border:1.5px solid var(--pc,transparent);animation:pz-up .35s ease}
.pz-toast.plain{padding:9px 16px}
.pz-toast .pz-face{width:24px;height:24px;font-size:11px;box-shadow:none}
@keyframes pz-in{from{opacity:0;transform:translateY(-6px) scale(.96)}}
@keyframes pz-up{from{opacity:0;transform:translate(-50%,8px)}}
@keyframes pz-pulse{from{opacity:.9;transform:scale(1)}to{opacity:0;transform:scale(1.55)}}
@keyframes pz-dot{0%{box-shadow:0 0 0 2px var(--bg,#000),0 0 0 2px var(--pc)}100%{box-shadow:0 0 0 2px var(--bg,#000),0 0 0 9px transparent}}
@keyframes pz-glow{50%{box-shadow:0 0 0 2px var(--pc),0 0 12px -6px var(--pc)}}
@media (prefers-reduced-motion:reduce){.pz-here,.pz-toast,.pz-here .pz-face::after,.r-stage.pz-shared,.pz-mark.here{animation:none}}`;
  document.head.appendChild(css);

  const edge = document.createElement('div');
  edge.className = 'pz-edge'; edge.hidden = true; edge.setAttribute('aria-live', 'polite');
  document.body.appendChild(edge);

  const face = f => {
    const el = document.createElement('span');
    el.className = 'pz-face';
    el.style.setProperty('--pc', colorOf(f.user_id));
    if (f.avatar) { const im = new Image(); im.src = f.avatar; im.alt = ''; el.appendChild(im); } else el.textContent = (f.nickname || '?').slice(0, 1);
    return el;
  };
  // 쪽(무대) 위 가장자리에 붙인다 — 무대 크기·위치는 화면·펼침에 따라 바뀐다
  const place = () => {
    const r = stage.getBoundingClientRect();
    edge.style.top = Math.max(r.top - 4, 8) + 'px';   // 쪽 위 여백(본문 위)에 걸친다
    edge.style.right = Math.max(innerWidth - r.right + 10, 8) + 'px';
    edge.style.maxWidth = Math.max(r.width - 20, 120) + 'px';
  };
  addEventListener('resize', place);
  if (window.ResizeObserver) new ResizeObserver(place).observe(stage);

  function paintMarks() {
    const box = document.getElementById('marks');
    if (!box) return;
    const at = new Map();
    box.replaceChildren(...friends.map(f => {
      const n = at.get(f.chunk) || 0; at.set(f.chunk, n + 1);
      const m = document.createElement('i');
      m.className = 'pz-mark' + (f.chunk === chunk ? ' here' : '');
      m.style.setProperty('--pc', colorOf(f.user_id));
      m.style.left = ((f.chunk + .5) / total * 100) + '%';
      if (n) m.style.transform = `translateY(${n % 2 ? -n * 7 : n * 7}px)`;   // 같은 쪽 친구는 살짝 비켜 쌓는다
      m.title = `${f.nickname} · 지금 ${f.chunk + 1}쪽`;
      return m;
    }));
  }

  function paint() {
    const here = friends.filter(f => f.chunk === chunk);
    const others = friends.filter(f => f.chunk !== chunk).sort((a, b) => Math.abs(a.chunk - chunk) - Math.abs(b.chunk - chunk));
    stage.classList.toggle('pz-shared', here.length > 0);
    if (here.length) stage.style.setProperty('--pc', colorOf(here[0].user_id));
    paintMarks();
    if (!friends.length) { edge.hidden = true; edge.replaceChildren(); paint.key = ''; return; }
    // 같은 모습이면 다시 그리지 않는다 — 5초마다 등장 애니메이션이 반복되지 않게
    const key = chunk + '|' + friends.map(f => `${f.user_id}:${f.chunk}:${f.avatar || ''}`).join(',');
    if (key === paint.key && !edge.hidden) return place();
    paint.key = key;
    const parts = [];
    if (here.length) {
      const h = document.createElement('div');
      h.className = 'pz-here';
      h.style.setProperty('--pc', colorOf(here[0].user_id));
      const faces = document.createElement('span'); faces.className = 'pz-faces';
      faces.append(...here.slice(0, 3).map(face));
      const t = document.createElement('span'); t.className = 'pz-text';
      t.textContent = here.length === 1 ? `${here[0].nickname}님이 이 쪽을 읽고 있어요` : `${here[0].nickname}님 외 ${here.length - 1}명이 이 쪽을 읽고 있어요`;
      h.title = here.map(f => f.nickname).join(', ');
      h.append(faces, t);
      parts.push(h);
    }
    const room = here.length ? 2 : 4;
    others.slice(0, room).forEach(f => {
      const a = document.createElement('span');
      a.className = 'pz-away';
      a.style.setProperty('--pc', colorOf(f.user_id));
      a.title = `${f.nickname}님 · 지금 ${f.chunk + 1}쪽 (${f.chunk > chunk ? '앞서 있어요' : '뒤에 있어요'})`;
      const b = document.createElement('b'); b.textContent = f.chunk + 1;
      a.append(face(f), b);
      parts.push(a);
    });
    if (others.length > room) {
      const m = document.createElement('span'); m.className = 'pz-more'; m.textContent = `+${others.length - room}`;
      parts.push(m);
    }
    edge.replaceChildren(...parts);
    edge.hidden = false;
    place();
  }

  // 친구가 내 쪽에 오고 갈 때 — 내가 쪽을 넘겨서 생긴 변화는 알리지 않는다
  function announce(prev) {
    if (!primed || seenChunk !== chunk) return;
    const now = new Map(friends.map(f => [f.user_id, f]));
    friends.forEach(f => {
      const was = prev.get(f.user_id);
      if (f.chunk === chunk && (!was || was.chunk !== chunk)) toast(f, `${f.nickname}님이 이 쪽에 왔어요`);
    });
    prev.forEach((was, uid) => {
      if (was.chunk !== chunk) return;
      const f = now.get(uid);
      if (f && f.chunk === chunk) return;
      toast(was, !f ? `${was.nickname}님이 이 쪽을 떠났어요` : f.chunk > chunk ? `${was.nickname}님이 ${f.chunk + 1}쪽으로 넘어갔어요` : `${was.nickname}님이 ${f.chunk + 1}쪽으로 돌아갔어요`);
    });
  }

  function apply(list) {
    const prev = seenAt;
    friends = list;
    announce(prev);
    seenAt = new Map(friends.map(f => [f.user_id, f]));
    seenChunk = chunk; primed = true;
    paint();
    document.dispatchEvent(new CustomEvent('haedok:presence', { detail: { friends: friends.slice(), chunk } }));
  }

  // ── 심장박동(겸 조회): 5초마다 ──
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
      lastOk = Date.now();
      apply(d.friends || []);
    } catch (e) {
      // 네트워크가 오래 끊기면 친구 위치는 믿을 수 없다 — 지운다
      if (friends.length && Date.now() - lastOk > STALE) apply([]);
    }
  }
  setInterval(beat, BEAT);
  beat();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) beat(); });

  // ── 토스트: 친구 색 테두리 + 아바타 ──
  let toastEl = null, toastT = 0;
  function toast(f, msg) {
    if (typeof f === 'string') { msg = f; f = null; }
    toastEl?.remove(); clearTimeout(toastT);
    const t = document.createElement('div');
    t.className = 'pz-toast' + (f ? '' : ' plain');
    t.setAttribute('role', 'status');
    if (f) { t.style.setProperty('--pc', colorOf(f.user_id)); t.appendChild(face(f)); }
    t.append(msg);
    document.body.appendChild(t); toastEl = t;
    toastT = setTimeout(() => { t.remove(); if (toastEl === t) toastEl = null; }, 3200);
  }

  // ── 문장 공유: 본문에서 고르면 '대결방에 공유' ──
  let btn = null, menu = null;
  const close = () => { btn?.remove(); menu?.remove(); btn = menu = null; };
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
