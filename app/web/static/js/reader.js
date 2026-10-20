// 인앱 리더 (PRD READ-01) — 시안 Glass v2의 종이 시트
// - 지금 보이는 영역 가운데에 걸친 청크 하나에만 시간을 쌓는다. 탭이 숨겨진 동안은 세지 않는다 (EXC-04).
//   PC에서는 폰 프레임 안(#scroll)이, 폰에서는 창이 스크롤되므로 '보이는 영역'을 둘 다 고려한다.
// - 청크가 바뀌거나 10초가 지나면 이벤트를 만들어 로컬 큐에 넣고, 10초마다 서버로 보낸다.
//   오프라인이면 큐에 남겨 두었다가 다시 연결되면 보낸다 (EXC-05).
// - 판정은 서버가 한다. 여기서는 측정과 표시만.
(function () {
  "use strict";
  const { api, toast, socket } = window.saipr;
  const root = document.getElementById("reader-root");
  const BOOK = Number(root.dataset.book);
  const TOTAL = Number(root.dataset.total);
  const ROOM = root.dataset.room ? Number(root.dataset.room) : null;
  const SYNC = root.dataset.mode === "sync";
  const ME = Number(root.dataset.me);
  const QUEUE_KEY = `saipr:events:${BOOK}`;
  const scroller = document.getElementById("scroll");
  const book = document.getElementById("book");
  const page = document.getElementById("page");
  const nextBtn = document.getElementById("load-next");
  const prevBtn = document.getElementById("load-prev");

  let verified = Number(root.dataset.verified);
  let first = Number(root.dataset.start);
  let last = first - 1;

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const COLORS = ["#3b82f6", "#22a06b", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#ec4899", "#64748b"];
  const color = (uid) => COLORS[uid % COLORS.length];

  // ── 설정: 글자 크기 4단계 · 배경 3종 (PRD READ-01) ──────────
  const SIZES = ["15px", "16.5px", "18.5px", "21px"];
  const pref = (() => { try { return JSON.parse(localStorage.getItem("saipr:reader") || "{}"); } catch (_) { return {}; } })();
  function applyPref() {
    book.style.setProperty("--fs", SIZES[pref.size ?? 1]);
    book.dataset.theme = pref.theme || "paper";
    document.querySelectorAll("#size-seg button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.size) === (pref.size ?? 1))));
    document.querySelectorAll("#theme-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.theme === (pref.theme || "paper"))));
    try { localStorage.setItem("saipr:reader", JSON.stringify(pref)); } catch (_) { /* 저장 불가 */ }
  }
  document.getElementById("size-seg").addEventListener("click", (e) => { const b = e.target.closest("[data-size]"); if (b) { pref.size = Number(b.dataset.size); applyPref(); } });
  document.getElementById("theme-seg").addEventListener("click", (e) => { const b = e.target.closest("[data-theme]"); if (b) { pref.theme = b.dataset.theme; applyPref(); } });
  document.getElementById("room-pick")?.addEventListener("change", (e) => { location.href = `/books/${BOOK}/read?room=${e.target.value}`; });
  applyPref();

  // ── 바텀 시트 ───────────────────────────────────
  const sheetBg = document.getElementById("sheet-bg");
  function openSheet(id) { sheetBg.hidden = false; document.getElementById(id).hidden = false; }
  function closeSheets() {
    sheetBg.hidden = true;
    document.querySelectorAll(".sheet").forEach((s) => (s.hidden = true));
    page.querySelectorAll(".para.active").forEach((p) => p.classList.remove("active"));
  }
  sheetBg.onclick = closeSheets;
  document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeSheets));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheets(); });
  document.getElementById("settings-btn").onclick = () => openSheet("set-sheet");

  // ── 청크 불러오기 ────────────────────────────────
  function paragraphHTML(i, a, text) {
    let body = esc(text).replace(/\n/g, "<br>");
    let cls = "para";
    if (i === 0 && a === 0) {
      // 첫 문단은 시안처럼 첫 글자를 크게 (드롭캡)
      const ch = text.charAt(0);
      body = `<span class="dc">${esc(ch)}</span>` + esc(text.slice(1)).replace(/\n/g, "<br>");
      cls += " first";
    }
    return `<p class="${cls}" data-chunk="${i}" data-anchor="${a}">${body}</p><div data-notes="${i}:${a}"></div>`;
  }

  async function loadChunk(i, prepend = false) {
    const data = await api("GET", `/books/${BOOK}/chunk/${i}`);
    const sec = document.createElement("section");
    sec.dataset.chunk = i;
    sec.innerHTML = data.paragraphs.map((p, a) => paragraphHTML(i, a, p)).join("") +
      `<div class="here" data-here="${i}" hidden><i></i><span></span></div>` +
      `<div class="folio" data-folio="${i}">${i + 1} &nbsp;/&nbsp; ${TOTAL}${i <= verified ? '<span class="ok">✓ 읽음</span>' : ""}</div>`;
    if (prepend) {
      const anchor = page.firstElementChild;
      const before = anchor ? anchor.getBoundingClientRect().top : 0;
      page.insertBefore(sec, anchor);
      if (anchor) scrollBy(anchor.getBoundingClientRect().top - before);
    } else {
      page.appendChild(sec);
    }
    renderNotes();
    renderHere();
  }
  function scrollBy(dy) { if (scroller.scrollHeight > scroller.clientHeight + 1) scroller.scrollTop += dy; else window.scrollBy(0, dy); }

  async function loadNext() {
    if (last + 1 >= TOTAL) return;
    last += 1;
    await loadChunk(last);
    nextBtn.hidden = last + 1 >= TOTAL;
  }
  nextBtn.onclick = loadNext;
  prevBtn?.addEventListener("click", async () => {
    if (first <= 0) return;
    first -= 1;
    await loadChunk(first, true);
    if (first <= 0) prevBtn.remove();
  });
  // 끝에 가까워지면 다음 청크를 자동으로 붙인다
  new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) loadNext(); }, { rootMargin: "600px" }).observe(nextBtn);

  // ── 체류시간 측정 ────────────────────────────────
  let current = null, segStart = null;

  function visibleCenter() {
    const r = scroller.getBoundingClientRect();
    return (Math.max(r.top, 0) + Math.min(r.bottom, window.innerHeight)) / 2;
  }
  function chunkAtCenter() {
    const y = visibleCenter();
    for (const sec of page.children) {
      const r = sec.getBoundingClientRect();
      if (r.top <= y && r.bottom >= y) return Number(sec.dataset.chunk);
    }
    return null;
  }
  function closeSegment() {
    if (current === null || segStart === null) return;
    const dwell = Math.round(performance.now() - segStart);
    if (dwell >= 300) enqueue({ chunk_index: current, dwell_ms: dwell, occurred_at: new Date().toISOString() });
    segStart = document.hidden ? null : performance.now();
  }
  function tick() {
    const c = document.hidden ? null : chunkAtCenter();
    if (c !== current) {
      closeSegment();
      current = c;
      segStart = c === null ? null : performance.now();
      if (SYNC && c !== null && room) room.send({ type: "presence", chunk_index: c });
    }
  }
  window.addEventListener("scroll", tick, { passive: true });
  scroller.addEventListener("scroll", tick, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { closeSegment(); segStart = null; flush(); }
    else { segStart = current === null ? null : performance.now(); tick(); }
  });
  setInterval(closeSegment, 10000);

  // ── 로컬 큐 · 배치 전송 ───────────────────────────
  function readQueue() { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]"); } catch (_) { return []; } }
  function writeQueue(q) { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q.slice(-500))); } catch (_) { /* 저장 불가 */ } }
  let queue = readQueue();
  function enqueue(ev) { queue.push(ev); writeQueue(queue); }

  let sending = false, slowShown = false, doneShown = false;
  async function flush() {
    if (sending || !queue.length || !navigator.onLine) return;
    sending = true;
    const batch = queue.slice(0, 200);
    try {
      const r = await api("POST", `/api/v1/books/${BOOK}/events`, { events: batch });
      queue = queue.slice(batch.length);
      writeQueue(queue);
      onProgress(r);
    } catch (e) {
      // 4xx는 다시 보내도 같으므로 버린다. 5xx·네트워크 오류는 남겨 두고 다음에 다시 보낸다
      if (e.status && e.status < 500 && e.status !== 401) { queue = queue.slice(batch.length); writeQueue(queue); }
    } finally {
      sending = false;
    }
  }
  setInterval(flush, 10000);
  window.addEventListener("online", flush);
  window.addEventListener("pagehide", closeSegment);

  function onProgress(r) {
    verified = r.verified_chunk;
    document.getElementById("pct").textContent = r.progress_pct + "%";
    document.getElementById("pbar").style.width = r.progress_pct + "%";
    for (const i of r.newly_verified) {
      const f = page.querySelector(`[data-folio="${i}"]`);
      if (f && !f.querySelector(".ok")) f.insertAdjacentHTML("beforeend", '<span class="ok">✓ 읽음</span>');
    }
    if (r.newly_verified.length) loadReactions(); // 가드가 풀린 반응을 다시 본다
    if (r.points_awarded) toast(`+${r.points_awarded}P`);
    if (r.slow_down && !slowShown) { slowShown = true; toast("천천히 읽어도 괜찮아요. 빠르게 넘긴 쪽은 점수에 들어가지 않아요.", 6000); }
    if (r.suggest_done && !doneShown) { doneShown = true; toast("다 읽었어요! 책 화면에서 ‘완독’으로 옮겨 주세요.", 7000); }
  }

  // ── 반응 (문단 옆 메모 · 잠금 알약) ─────────────────
  let byPara = {};
  async function loadReactions() {
    const q = ROOM ? `?room_id=${ROOM}` : "";
    let feed;
    try { feed = await api("GET", `/api/v1/books/${BOOK}/reactions${q}`); } catch (_) { return; }
    byPara = {};
    for (const r of feed.visible) (byPara[`${r.chunk_index}:${r.anchor}`] ||= []).push(r);
    renderNotes();
    const guard = document.getElementById("guard");
    guard.hidden = !feed.locked_total;
    document.getElementById("guard-text").textContent = `앞에서 ${feed.locked_total}개의 반응이 기다리고 있어요`;
  }

  function renderNotes() {
    page.querySelectorAll("[data-notes]").forEach((el) => {
      const list = byPara[el.dataset.notes] || [];
      const comments = list.filter((r) => r.kind === "comment");
      const emojis = list.filter((r) => r.kind === "emoji");
      const counts = {};
      emojis.forEach((r) => (counts[r.body] = (counts[r.body] || 0) + 1));
      el.innerHTML =
        comments.slice(-2).map((r, idx, arr) => {
          const others = idx === arr.length - 1 && comments.length > 2 ? ` <span class="meta">· 외 ${comments.length - 2}개</span>` : "";
          return `<div class="note" data-open="${el.dataset.notes}"><span class="av" style="background:${color(r.user_id)}">${esc(r.nickname.slice(0, 1))}</span><span>${esc(r.body)} <span class="meta">· ${esc(r.nickname)}</span>${others}</span></div>`;
        }).join("") +
        (emojis.length ? `<div class="emo" data-open="${el.dataset.notes}">${Object.entries(counts).map(([e, n]) => `${e} ${n}`).join(" &nbsp;")}</div>` : "");
    });
  }

  let target = null;
  function openReactions(key) {
    target = key;
    const [c, a] = key.split(":").map(Number);
    page.querySelectorAll(".para.active").forEach((p) => p.classList.remove("active"));
    page.querySelector(`.para[data-chunk="${c}"][data-anchor="${a}"]`)?.classList.add("active");
    document.getElementById("rx-title").textContent = `${c + 1}쪽 · ${a + 1}번째 문단`;
    const list = byPara[key] || [];
    document.getElementById("rx-list").innerHTML = list.length
      ? list.map((r) => `<div class="reaction"><span class="tiny" style="opacity:.6">${esc(r.nickname)}</span>${r.kind === "emoji" ? `<span style="font-size:22px">${r.body}</span>` : esc(r.body)}</div>`).join("")
      : `<span class="tiny" style="opacity:.6">아직 반응이 없어요. 첫 반응을 남겨 보세요.</span>`;
    openSheet("rx-sheet");
  }
  page.addEventListener("click", (e) => {
    const n = e.target.closest("[data-open]");
    if (n) return openReactions(n.dataset.open);
    const p = e.target.closest(".para");
    if (p && !window.getSelection().toString()) openReactions(`${p.dataset.chunk}:${p.dataset.anchor}`);
  });
  async function react(kind, body) {
    const [c, a] = target.split(":").map(Number);
    try {
      await api("POST", `/api/v1/books/${BOOK}/reactions`, { chunk_index: c, anchor: a, kind, body });
      await loadReactions();
      openReactions(target);
    } catch (e) { toast(e.message); }
  }
  document.getElementById("emoji-row").addEventListener("click", (e) => { const b = e.target.closest("[data-emoji]"); if (b) react("emoji", b.dataset.emoji); });
  document.getElementById("comment-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("comment");
    if (input.value.trim()) { react("comment", input.value.trim()); input.value = ""; }
  });

  // ── 친구 위치 ("서연님이 이 쪽을 함께 읽고 있어요") ─────
  const friends = {};
  document.querySelectorAll("[data-member]").forEach((el) => {
    friends[el.dataset.member] = { nickname: el.dataset.nick, chunk: Math.min(TOTAL - 1, Number(el.dataset.chunk)) };
  });
  function renderHere() {
    page.querySelectorAll("[data-here]").forEach((el) => {
      const i = Number(el.dataset.here);
      const names = Object.values(friends).filter((f) => f.chunk === i).map((f) => f.nickname);
      el.hidden = !names.length;
      if (names.length) el.querySelector("span").textContent = `${names.slice(0, 2).join(", ")}님${names.length > 2 ? ` 외 ${names.length - 2}명` : ""}이 이 쪽을 함께 읽고 있어요`;
    });
  }

  let room = null;
  if (ROOM) {
    room = socket(`/ws/rooms/${ROOM}`, (ev) => {
      const d = ev.data || {};
      if (d.user_id === ME) return;
      if (ev.type === "progress.updated" || ev.type === "member.joined") {
        friends[d.user_id] = { nickname: d.nickname, chunk: Math.min(TOTAL - 1, d.verified_chunk + 1) };
        renderHere();
        if (ev.type === "progress.updated") toast(`${d.nickname}님 ${d.progress_pct}%`, 2000);
      } else if (ev.type === "presence.changed") {
        friends[d.user_id] = { nickname: d.nickname, chunk: d.chunk_index };
        renderHere();
      } else if (ev.type === "reaction.created") {
        loadReactions();
        toast(`${d.nickname}님이 반응을 남겼어요`, 2000);
      } else if (ev.type === "member.left") {
        delete friends[d.user_id];
        renderHere();
      }
    });
  }

  loadNext().then(() => { loadReactions(); tick(); flush(); });
})();
