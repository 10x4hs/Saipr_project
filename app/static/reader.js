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
  }).then(r => r.ok && r.json()).then(d => { if (d) verifiedUpTo = d.verified_chunk; }).catch(() => {});
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
  for (const para of text.split(/\n\s*\n/)) {
    let rest = para, cont = false;
    while (rest) {
      const p = document.createElement('p');
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
  }
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
  minMs = chunkData.min_dwell_ms; dwellMs = 0;

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
    maxShadowOpacity: .45, flippingTime: 650, swipeDistance: 24, drawShadow: true,
  });
  pageFlip.loadFromHTML(book.querySelectorAll('.pg'));
  const startAt = atEnd ? pageCount - 2 : lead;
  pageFlip.turnToPage(Math.max(0, startAt));
  pageFlip.on('flip', e => onPage(e.data));
  onPage(pageFlip.getCurrentPageIndex());
  save(false);
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
  if (dwellMs >= minMs) { verifiedUpTo = chunk; save(true); }
  paintDwell();
}, 250);

addEventListener('keydown', e => {
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
