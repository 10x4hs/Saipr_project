// 리더: 청크(쪽) 단위로 불러오고, 체류시간을 재서 '읽음'을 판정한다.
const page = document.getElementById('page');
const bookId = page.dataset.book, total = +page.dataset.total;
const $ = id => document.getElementById(id);
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
const title = document.querySelector('.r-title b').textContent;
const verified = new Set(store.get(`verified:${bookId}`, []));
let index = Math.min(store.get('progress', {})[bookId]?.index ?? 0, total - 1);
let minMs = 0, dwellMs = 0, timer = null;
const cache = new Map();

async function fetchChunk(i) {
  if (!cache.has(i)) cache.set(i, fetch(`/api/v1/books/${bookId}/chunks/${i}`).then(r => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }));
  return cache.get(i);
}

async function show(i, { fromEnd = false } = {}) {
  index = Math.max(0, Math.min(total - 1, i));
  const text = $('text');
  let c;
  try { c = await fetchChunk(index); }
  catch (e) { text.innerHTML = '<p>이 쪽을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.</p>'; return; }
  text.innerHTML = c.text.split(/\n\s*\n/).map(p => `<p>${p.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</p>`).join('')
    + (index === total - 1 ? '<div class="r-end"><b>끝</b>마지막 쪽까지 왔어요.</div>' : '');
  text.classList.remove('enter'); void text.offsetWidth; text.classList.add('enter');
  window.scrollTo({ top: fromEnd ? document.body.scrollHeight : 0 });
  minMs = c.min_dwell_ms; dwellMs = 0;
  $('pos').textContent = `${index + 1} / ${total}`;
  $('prog').style.width = ((index + 1) / total * 100) + '%';
  $('prev').disabled = index === 0;
  $('next').disabled = index === total - 1;
  paintDwell();
  const prog = store.get('progress', {});
  prog[bookId] = { index, total, title, at: Date.now() };
  store.set('progress', prog);
  if (index + 1 < total) fetchChunk(index + 1);
}

function paintDwell() {
  const ok = verified.has(index);
  $('dwell').style.width = ok ? '100%' : Math.min(100, dwellMs / Math.max(minMs, 1) * 100) + '%';
  $('dwell').parentElement.classList.toggle('ok', ok);
  $('state').textContent = ok ? '읽음' : '읽는 중';
  $('state').classList.toggle('ok', ok);
}

// 화면이 보이는 동안만 체류시간을 센다 (탭을 숨기면 멈춤)
timer = setInterval(() => {
  if (document.hidden || verified.has(index)) return;
  dwellMs += 250;
  if (dwellMs >= minMs) { verified.add(index); store.set(`verified:${bookId}`, [...verified]); }
  paintDwell();
}, 250);

$('prev').onclick = () => show(index - 1);
$('next').onclick = () => show(index + 1);
addEventListener('keydown', e => {
  if (e.target.matches('input')) return;
  if (e.key === 'ArrowRight') show(index + 1);
  if (e.key === 'ArrowLeft') show(index - 1);
});

// 글자 크기 · 테마
let size = store.get('size', 19);
const applySize = () => document.documentElement.style.setProperty('--size', size + 'px');
applySize();
$('smaller').onclick = () => { size = Math.max(15, size - 1); applySize(); store.set('size', size); };
$('bigger').onclick = () => { size = Math.min(26, size + 1); applySize(); store.set('size', size); };
const themes = ['dark', 'light', 'sepia'];
$('theme').onclick = () => {
  const cur = document.documentElement.dataset.theme || 'dark';
  const next = themes[(themes.indexOf(cur) + 1) % themes.length];
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch (e) {}
};

// 스크롤 내리면 상단 바 숨기기
let lastY = 0;
addEventListener('scroll', () => {
  document.querySelector('.r-top').classList.toggle('hide', scrollY > lastY && scrollY > 80);
  lastY = scrollY;
}, { passive: true });

show(index);
