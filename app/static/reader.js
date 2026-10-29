// 리더: 청크(쪽)를 화면 크기 페이지로 나눠 3D로 넘긴다(StPageFlip).
// 체류시간은 청크 단위로 재고, 순서대로 읽은 청크만 '읽음'으로 계정에 저장한다.
const stage = document.getElementById('stage');
const bookId = stage.dataset.book, total = +stage.dataset.total, csrf = stage.dataset.csrf;
const $ = id => document.getElementById(id);
const local = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

let verifiedUpTo = +stage.dataset.verified;
let chunk = Math.min(+stage.dataset.start || 0, total - 1);
let chunkData = null, minMs = 0, dwellMs = 0, pageFlip = null, pageCount = 0, lead = 0;
const cache = new Map();
let lastOpened = -1, sentVerify = false;
let mode = local.get('flip', '3d');   // '3d' = 책장 넘김, 'scroll' = 넘김 효과 끄기

function fetchChunk(i) {
  if (!cache.has(i)) cache.set(i, fetch(`/api/v1/books/${bookId}/chunks/${i}`).then(r => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }).catch(e => { cache.delete(i); throw e; }));
  return cache.get(i);
}

function save(verified = false) {
  fetch(`/api/v1/books/${bookId}/progress`, {
    method: 'PUT', keepalive: true,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ chunk_index: chunk, verified }),
  }).then(r => r.ok && r.json()).then(d => {
    if (!d) return;
    const opened = d.verified_chunk > verifiedUpTo;
    verifiedUpTo = d.verified_chunk;
    paintDwell();
    if (opened && verified) loadReactions(chunk);   // 다 읽은 순간 봉인이 풀린다
    // 서버 시계로는 아직 모자라면 잠시 뒤 다시 보낸다
    if (verified && d.verified_chunk < chunk) setTimeout(() => { sentVerify = false; }, 1500);
  }).catch(() => {});
}

// --- 페이지 나누기: 실제 페이지와 같은 크기의 측정용 상자에 문단을 채워 본다 ---
function paginate(text) {
  const m = $('measure');
  m.style.width = stage.clientWidth + 'px';
  m.style.height = stage.clientHeight + 'px';
  const fits = () => m.scrollHeight <= m.clientHeight;
  const pages = [];
  m.innerHTML = '';
  const flush = () => { if (m.childElementCount) { pages.push(m.innerHTML); m.innerHTML = ''; } };
  text.split(/\n\s*\n/).forEach((para, anchor) => {
    let rest = para, cont = false;
    while (rest) {
      const p = document.createElement('p');
      p.dataset.a = anchor;
      if (cont) p.className = 'cont';
      p.textContent = rest;
      m.appendChild(p);
      if (fits()) break;
      // 넘치면 들어가는 만큼만 남기고(이진 탐색) 나머지는 다음 페이지로
      const words = rest.split(' ');
      let lo = 0, hi = words.length;
      while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        p.textContent = words.slice(0, mid).join(' ');
        if (fits()) lo = mid; else hi = mid - 1;
      }
      if (lo === 0) {
        // 한 단어도 안 들어가면: 빈 페이지면 그냥 싣고, 아니면 새 페이지에서 다시 시도
        m.removeChild(p);
        if (!m.childElementCount) { m.appendChild(p); p.textContent = rest; break; }
        flush();
        continue;
      }
      p.textContent = words.slice(0, lo).join(' ');
      flush();
      rest = words.slice(lo).join(' ');
      cont = true;
    }
  });
  flush();
  return pages;
}

function pageEl(html, cls = '') {
  const d = document.createElement('div');
  d.className = 'pg ' + cls;
  d.innerHTML = html;
  return d;
}

async function open(i, { atEnd = false } = {}) {
  chunk = Math.max(0, Math.min(total - 1, i));
  try { chunkData = await fetchChunk(chunk); }
  catch (e) { stage.innerHTML = '<p class="r-err">이 쪽을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.</p>'; return; }
  await document.fonts.ready;
  minMs = chunkData.min_dwell_ms; dwellMs = 0; sentVerify = false;

  if (mode === 'scroll') return openScroll();
  const pages = paginate(chunkData.text).map(h => pageEl(h));
  // 청크 경계에 '넘김용' 페이지를 붙여, 그 페이지에 닿으면 이웃 청크를 불러온다
  lead = chunk > 0 ? 1 : 0;
  if (lead) pages.unshift(pageEl('<div class="turn">‹ 앞 쪽으로</div>', 'edge-page'));
  if (chunk < total - 1) pages.push(pageEl('<div class="turn">다음 쪽으로 ›</div>', 'edge-page'));
  else pages.push(pageEl('<div class="fin"><b>끝</b><span>마지막 쪽까지 왔어요</span><a class="btn primary" href="/library">서재로</a></div>', 'edge-page'));
  pageCount = pages.length;

  if (pageFlip) { pageFlip.destroy(); }
  const book = document.createElement('div');
  book.className = 'flip';
  stage.replaceChildren(book);
  pages.forEach(p => book.appendChild(p));
  pageFlip = new St.PageFlip(book, {
    width: stage.clientWidth, height: stage.clientHeight, size: 'fixed',
    usePortrait: true, showCover: false, mobileScrollSupport: true,
    maxShadowOpacity: .45, flippingTime: 650, swipeDistance: 24, drawShadow: true, disableFlipByClick: true,
  });
  pageFlip.loadFromHTML(book.querySelectorAll('.pg'));
  const startAt = atEnd ? pageCount - 2 : lead;
  pageFlip.turnToPage(Math.max(0, startAt));
  pageFlip.on('flip', e => onPage(e.data));
  onPage(pageFlip.getCurrentPageIndex());
  if (lastOpened !== chunk) { lastOpened = chunk; save(false); }
  loadReactions(chunk);
  if (chunk + 1 < total) fetchChunk(chunk + 1).catch(() => {});
}

function onPage(idx) {
  if (lead && idx === 0) return open(chunk - 1, { atEnd: true });
  if (idx === pageCount - 1 && chunk < total - 1) return open(chunk + 1);
  const inChunk = idx - lead + 1, pagesInChunk = pageCount - lead - 1;
  $('pos').textContent = `${chunk + 1}/${total}쪽 · ${Math.min(inChunk, pagesInChunk)}/${pagesInChunk}`;
  paintDwell();
}

function paintDwell() {
  const ok = chunk <= verifiedUpTo;
  $('dwell').style.width = ok ? '100%' : Math.min(100, dwellMs / Math.max(minMs, 1) * 100) + '%';
  $('dwell').parentElement.classList.toggle('ok', ok);
  $('state').textContent = ok ? '읽음' : '읽는 중';
  $('state').classList.toggle('ok', ok);
}

setInterval(() => {
  if (document.hidden || !chunkData || chunk <= verifiedUpTo || chunk > verifiedUpTo + 1) return;
  dwellMs += 250;
  if (dwellMs >= minMs && !sentVerify) { sentVerify = true; save(true); }
  paintDwell();
}, 250);

addEventListener('keydown', e => {
  if (mode === 'scroll' && chunkData) {
    if (e.key === 'ArrowRight' && chunk < total - 1) open(chunk + 1);
    if (e.key === 'ArrowLeft' && chunk > 0) open(chunk - 1);
    return;
  }
  if (!pageFlip) return;
  if (e.key === 'ArrowRight') pageFlip.flipNext();
  if (e.key === 'ArrowLeft') pageFlip.flipPrev();
});

// --- 보기 설정 ---
let size = local.get('size', 18), tone = local.get('tone', '');
const applySize = () => document.documentElement.style.setProperty('--size', size + 'px');
const applyTone = () => {
  document.body.dataset.tone = tone;
  document.querySelectorAll('#tones button').forEach(b => b.setAttribute('aria-pressed', b.dataset.tone === tone));
};
applySize(); applyTone();
const relayout = () => { if (chunkData) open(chunk); };
$('smaller').onclick = () => { size = Math.max(14, size - 1); applySize(); local.set('size', size); relayout(); };
$('bigger').onclick = () => { size = Math.min(26, size + 1); applySize(); local.set('size', size); relayout(); };
document.querySelectorAll('#tones button').forEach(b => b.onclick = () => { tone = b.dataset.tone; applyTone(); local.set('tone', tone); });
$('aa').onclick = () => { const s = $('sheet'); s.hidden = !s.hidden; $('aa').setAttribute('aria-expanded', !s.hidden); };
let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(relayout, 250); });

open(chunk);

// ---------------- 함께 읽기: 반응 · 친구 · 실시간 ----------------
let reacts = { items: [], sealed: 0 }, friendMap = new Map(), emojis = ['❤️', '😂', '😮', '😢', '👏'];
let sheetAnchor = 0;

async function loadReactions(i) {
  try {
    const r = await fetch(`/api/v1/books/${bookId}/reactions?chunk=${i}`);
    if (!r.ok || i !== chunk) return;
    reacts = await r.json();
    paintReactions();
    if (reacts.sealed) toast(`🔒 이 쪽에 친구 반응 ${reacts.sealed}개 — 다 읽으면 열려요`);
  } catch (e) {}
}

function paintReactions() {
  const by = new Map();
  reacts.items.forEach(x => { if (!by.has(x.anchor)) by.set(x.anchor, []); by.get(x.anchor).push(x); });
  // 페이지 넘김 라이브러리가 페이지를 복제하므로 화면에 있는 모든 사본에 붙인다
  stage.querySelectorAll('p[data-a]').forEach(p => {
    p.querySelector('.rx')?.remove();
    const list = by.get(+p.dataset.a);
    // 문단이 여러 페이지에 걸치면 마지막 조각에만 붙인다
    if (!list || (p.nextElementSibling && p.nextElementSibling.dataset.a === p.dataset.a)) return;
    const counts = {};
    list.forEach(x => { const k = x.kind === 'comment' ? '💬' : x.body; counts[k] = (counts[k] || 0) + 1; });
    const b = document.createElement('span');
    b.className = 'rx';
    b.textContent = Object.entries(counts).map(([k, n]) => n > 1 ? `${k}${n}` : k).join(' ');
    p.appendChild(b);
  });
}

// 탭: 문단이면 반응 시트, 페이지 가장자리면 넘김
let down = null;
stage.addEventListener('pointerdown', e => { down = { x: e.clientX, y: e.clientY }; });
stage.addEventListener('click', e => {
  if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 8) return;
  if (pageFlip) {                                     // 3D 넘김일 때만 가장자리 탭으로 넘긴다
    const r = stage.getBoundingClientRect(), x = (e.clientX - r.left) / r.width;
    if (x > .82) return pageFlip.flipNext();
    if (x < .18) return pageFlip.flipPrev();
  }
  const p = e.target.closest('p[data-a]');
  if (p) openSheet(+p.dataset.a, p.textContent.replace(/[❤️😂😮😢👏💬\d\s]+$/u, ''));
});

function openSheet(anchor, quote) {
  sheetAnchor = anchor;
  $('reactQuote').textContent = quote.length > 90 ? quote.slice(0, 90) + '…' : quote;
  $('reactMsg').textContent = chunk > verifiedUpTo + 1 ? '아직 읽지 않은 쪽이에요' : '';
  renderSheetList();
  $('react').hidden = false;
  document.body.classList.add('locked');
}
function closeSheet() { $('react').hidden = true; document.body.classList.remove('locked'); }
$('react').addEventListener('click', e => { if (e.target.id === 'react' || e.target.closest('[data-close]')) closeSheet(); });

function renderSheetList() {
  const list = reacts.items.filter(x => x.anchor === sheetAnchor);
  $('reactList').innerHTML = list.length ? '' : '<li class="muted">아직 반응이 없어요. 첫 반응을 남겨 보세요.</li>';
  list.forEach(x => {
    const li = document.createElement('li');
    li.innerHTML = `<span class="avatar sm"></span><div><b></b><p></p></div>`;
    if (x.mine) {                                         // 내가 남긴 반응은 지울 수 있다
      const del = document.createElement('button');
      del.type = 'button'; del.className = 'r-del'; del.textContent = '삭제';
      del.setAttribute('aria-label', '이 반응 삭제');
      del.onclick = () => removeReaction(x.id, del);
      li.appendChild(del);
    }
    li.querySelector('.avatar').textContent = x.nickname.slice(0, 1);
    li.querySelector('b').textContent = x.mine ? `${x.nickname} (나)` : x.nickname;
    li.querySelector('p').textContent = x.body;
    if (x.kind === 'emoji') li.classList.add('emoji');
    $('reactList').appendChild(li);
  });
}

async function sendReaction(payload) {
  const r = await fetch(`/api/v1/books/${bookId}/reactions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ chunk_index: chunk, anchor: sheetAnchor, ...payload }),
  });
  if (!r.ok) { $('reactMsg').textContent = (await r.json().catch(() => ({}))).detail || '남기지 못했어요'; return; }
  reacts.items.push(await r.json());
  paintReactions(); renderSheetList();
  if (payload.comment) $('reactText').value = '';   // 이모지를 보낼 때는 쓰던 글을 지우지 않는다
  $('reactMsg').textContent = '남겼어요';
}
async function removeReaction(id, btn) {
  btn.disabled = true; btn.textContent = '…';
  const r = await fetch(`/api/v1/books/${bookId}/reactions/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } }).catch(() => null);
  if (!r || !r.ok) { btn.disabled = false; btn.textContent = '삭제'; $('reactMsg').textContent = '지우지 못했어요'; return; }
  reacts.items = reacts.items.filter(x => x.id !== id);
  paintReactions(); renderSheetList();
  $('reactMsg').textContent = '지웠어요';
}
$('reactForm').addEventListener('submit', e => { e.preventDefault(); const t = $('reactText').value.trim(); if (t) sendReaction({ comment: t }); });

function renderEmojis() {
  $('emojiRow').innerHTML = '';
  emojis.forEach(em => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = em; b.setAttribute('aria-label', `${em} 반응`);
    b.onclick = () => { b.classList.remove('pop'); void b.offsetWidth; b.classList.add('pop'); sendReaction({ emoji: em }); };
    $('emojiRow').appendChild(b);
  });
}

function paintFriends() {
  const box = $('friends'); box.innerHTML = '';
  [...friendMap.values()].forEach(f => {
    const s = document.createElement('span');
    s.className = 'fchip';
    s.title = `${f.nickname} · ${f.current_chunk + 1}쪽`;
    s.innerHTML = '<i></i><em></em>';
    s.querySelector('i').textContent = f.nickname.slice(0, 1);
    s.querySelector('em').textContent = f.verified_chunk + 1;
    box.appendChild(s);
  });
}

let toastTimer = 0;
function toast(text) {
  const t = $('toast'); t.textContent = text; t.hidden = false;
  t.classList.remove('in'); void t.offsetWidth; t.classList.add('in');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}

async function social() {
  renderEmojis();
  try {
    const d = await (await fetch(`/api/v1/books/${bookId}/social`)).json();
    emojis = d.emojis || emojis; renderEmojis();
    d.friends.forEach(f => friendMap.set(f.user_id, f));
    paintFriends();
    if (d.sealed_ahead) setTimeout(() => toast(`🔒 앞에서 ${d.sealed_ahead}개의 반응이 기다리고 있어요`), 1200);
  } catch (e) {}
  connect();
}

let retry = 3000;
function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/ws/books/${bookId}`);
  const ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000);
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.type === 'progress.updated') {
      const before = friendMap.get(m.user_id);
      friendMap.set(m.user_id, { user_id: m.user_id, nickname: m.nickname, current_chunk: m.current_chunk, verified_chunk: m.verified_chunk });
      paintFriends();
      if (m.advanced) {
        const passed = before && before.verified_chunk <= verifiedUpTo && m.verified_chunk > verifiedUpTo;
        toast(passed ? `🏃 ${m.nickname}님이 나를 앞질렀어요` : `${m.nickname}님이 ${m.verified_chunk + 1}쪽을 다 읽었어요`);
      }
    } else if (m.type === 'reaction.removed') {
      if (m.chunk === chunk) loadReactions(chunk);
    } else if (m.type === 'reaction.added') {
      toast(`${m.nickname}님이 ${m.chunk + 1}쪽에 반응을 남겼어요`);
      if (m.chunk === chunk) loadReactions(chunk);
    }
  };
  // 서버리스 배포처럼 WebSocket이 없는 곳에서는 점점 드물게 다시 시도하고, 그동안은 주기적으로 물어본다
  ws.onopen = () => { retry = 3000; stopPolling(); };
  ws.onclose = () => { clearInterval(ping); startPolling(); setTimeout(connect, retry); retry = Math.min(retry * 2, 60000); };
}

social();

// ---------------- 넘김 효과 끄기: 한 쪽을 위아래로 스크롤해 읽는다 ----------------
function openScroll() {
  if (pageFlip) { pageFlip.destroy(); pageFlip = null; }
  const col = document.createElement('article');
  col.className = 'pg scroll-col';
  col.innerHTML = chunkData.text.split(/\n\s*\n/).map((p, a) => `<p data-a="${a}">${esc(p)}</p>`).join('')
    + `<nav class="scroll-nav">${chunk > 0 ? '<button class="btn ghost" data-go="-1">‹ 앞 쪽</button>' : '<span></span>'}`
    + (chunk < total - 1 ? '<button class="btn primary" data-go="1">다음 쪽 ›</button>' : '<a class="btn primary" href="/library">끝 · 서재로</a>') + '</nav>';
  stage.replaceChildren(col);
  col.scrollTop = 0;
  col.querySelectorAll('[data-go]').forEach(b => b.onclick = () => open(chunk + +b.dataset.go));
  $('pos').textContent = `${chunk + 1}/${total}쪽`;
  paintDwell();
  if (lastOpened !== chunk) { lastOpened = chunk; save(false); }
  loadReactions(chunk);
  if (chunk + 1 < total) fetchChunk(chunk + 1).catch(() => {});
}

const applyMode = () => document.querySelectorAll('#modes button').forEach(b => b.setAttribute('aria-pressed', b.dataset.mode === mode));
applyMode();
document.querySelectorAll('#modes button').forEach(b => b.onclick = () => {
  if (mode === b.dataset.mode) return;
  mode = b.dataset.mode; local.set('flip', mode); applyMode();
  if (chunkData) open(chunk);
});

// ---------------- WebSocket이 없을 때: 20초마다 친구 진행을 물어본다 ----------------
let pollTimer = 0;
function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    if (document.hidden) return;
    try {
      const d = await (await fetch(`/api/v1/books/${bookId}/social`)).json();
      d.friends.forEach(f => {
        const before = friendMap.get(f.user_id);
        friendMap.set(f.user_id, f);
        if (before && f.verified_chunk > before.verified_chunk) {
          const passed = before.verified_chunk <= verifiedUpTo && f.verified_chunk > verifiedUpTo;
          toast(passed ? `🏃 ${f.nickname}님이 나를 앞질렀어요` : `${f.nickname}님이 ${f.verified_chunk + 1}쪽을 다 읽었어요`);
        }
      });
      paintFriends();
    } catch (e) {}
  }, 20000);
}
function stopPolling() { clearInterval(pollTimer); pollTimer = 0; }
