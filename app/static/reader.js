// 리더: 청크(쪽) 단위로 불러오고, 체류시간을 재서 '읽음'을 판정해 계정에 저장한다.
const page = document.getElementById('page');
const bookId = page.dataset.book, total = +page.dataset.total, csrf = page.dataset.csrf;
const $ = id => document.getElementById(id);
const local = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
let verifiedUpTo = +page.dataset.verified;  // 서버가 인정한 최대 청크
let index = Math.min(+page.dataset.start || 0, total - 1);
let minMs = 0, dwellMs = 0;
const cache = new Map();

const isVerified = i => i <= verifiedUpTo;

function save(verified = false) {
  fetch(`/api/v1/books/${bookId}/progress`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ chunk_index: index, verified }),
    keepalive: true,
  }).then(r => r.ok && r.json()).then(d => { if (d) verifiedUpTo = d.verified_chunk; }).catch(() => {});
}

function fetchChunk(i) {
  if (!cache.has(i)) cache.set(i, fetch(`/api/v1/books/${bookId}/chunks/${i}`).then(r => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }));
  return cache.get(i);
}

async function show(i) {
  index = Math.max(0, Math.min(total - 1, i));
  const text = $('text');
  let c;
  try { c = await fetchChunk(index); }
  catch (e) { cache.delete(index); text.innerHTML = '<p class="r-err">이 쪽을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.</p>'; return; }
  text.innerHTML = c.text.split(/\n\s*\n/).map(p => `<p>${p.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</p>`).join('')
    + (index === total - 1 ? '<div class="r-end"><b>끝</b><span>마지막 쪽까지 왔어요.</span><a class="btn primary" href="/library">서재로 돌아가기</a></div>' : '');
  text.classList.remove('enter'); void text.offsetWidth; text.classList.add('enter');
  window.scrollTo({ top: 0 });
  minMs = c.min_dwell_ms; dwellMs = 0;
  $('pos').textContent = `${index + 1} / ${total}`;
  $('prog').style.width = ((index + 1) / total * 100) + '%';
  $('prev').disabled = index === 0;
  $('next').disabled = index === total - 1;
  paintDwell();
  save(false);
  if (index + 1 < total) fetchChunk(index + 1);
}

function paintDwell() {
  const ok = isVerified(index);
  $('dwell').style.width = ok ? '100%' : Math.min(100, dwellMs / Math.max(minMs, 1) * 100) + '%';
  $('dwell').parentElement.classList.toggle('ok', ok);
  $('state').textContent = ok ? '읽음' : '읽는 중';
  $('state').classList.toggle('ok', ok);
}

// 화면이 보이는 동안만 체류시간을 센다. 순서대로 읽은 쪽만 '읽음'으로 인정한다.
setInterval(() => {
  if (document.hidden || isVerified(index) || index > verifiedUpTo + 1) return;
  dwellMs += 250;
  if (dwellMs >= minMs) { verifiedUpTo = index; save(true); }
  paintDwell();
}, 250);

$('prev').onclick = () => show(index - 1);
$('next').onclick = () => show(index + 1);
addEventListener('keydown', e => {
  if (e.key === 'ArrowRight') show(index + 1);
  if (e.key === 'ArrowLeft') show(index - 1);
});

let size = local.get('size', 19);
const applySize = () => document.documentElement.style.setProperty('--size', size + 'px');
applySize();
$('smaller').onclick = () => { size = Math.max(15, size - 1); applySize(); local.set('size', size); };
$('bigger').onclick = () => { size = Math.min(26, size + 1); applySize(); local.set('size', size); };
const tones = ['', 'paper', 'night'];
let tone = local.get('tone', '');
const applyTone = () => { document.body.dataset.tone = tone; };
applyTone();
$('tone').onclick = () => { tone = tones[(tones.indexOf(tone) + 1) % tones.length]; applyTone(); local.set('tone', tone); };

let lastY = 0;
addEventListener('scroll', () => {
  document.querySelector('.r-top').classList.toggle('hide', scrollY > lastY && scrollY > 80);
  lastY = scrollY;
}, { passive: true });

show(index);
