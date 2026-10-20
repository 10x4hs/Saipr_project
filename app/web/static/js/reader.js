// 인앱 리더 (PRD READ-01)
// - 지금 화면 가운데에 걸친 청크 하나에만 시간을 쌓는다. 탭이 숨겨진 동안은 세지 않는다 (EXC-04).
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
  const page = document.getElementById("page");
  const nextBtn = document.getElementById("load-next");
  const prevBtn = document.getElementById("load-prev");

  let verified = Number(root.dataset.verified);
  let first = Number(root.dataset.start);
  let last = first - 1;
  const minDwell = {};
  const friends = {}; // user_id → {nickname, chunk}

  // ── 설정: 글자 크기 4단계 · 배경 3종 ─────────────────
  const SIZES = ["16px", "18px", "20px", "23px"];
  const THEMES = ["white", "parchment", "dark"];
  const pref = (() => { try { return JSON.parse(localStorage.getItem("saipr:reader") || "{}"); } catch (_) { return {}; } })();
  function applyPref() {
    root.parentElement.style.setProperty("--fs", SIZES[pref.size ?? 1]);
    root.parentElement.dataset.theme = THEMES[pref.theme ?? 0];
    try { localStorage.setItem("saipr:reader", JSON.stringify(pref)); } catch (_) { /* 저장 불가 */ }
  }
  document.getElementById("font-btn").onclick = () => { pref.size = ((pref.size ?? 1) + 1) % SIZES.length; applyPref(); };
  document.getElementById("theme-btn").onclick = () => { pref.theme = ((pref.theme ?? 0) + 1) % THEMES.length; applyPref(); };
  applyPref();
  document.getElementById("room-pick")?.addEventListener("change", (e) => {
    location.href = `/books/${BOOK}/read?room=${e.target.value}`;
  });

  // ── 청크 불러오기 ────────────────────────────────
  function chunkHead(i) {
    const ok = i <= verified;
    return `<div class="chunk-head" id="h${i}"><span>CHUNK ${String(i + 1).padStart(2, "0")} / ${String(TOTAL).padStart(2, "0")}</span>
      <span class="dots" data-dots="${i}"></span>
      <span class="state ${ok ? "ok" : ""}" data-state="${i}">${ok ? "✓ 검증됨" : "읽는 중"}</span></div>`;
  }

  function esc(s) { return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

  async function loadChunk(i, prepend = false) {
    const data = await api("GET", `/books/${BOOK}/chunk/${i}`);
    minDwell[i] = data.min_dwell_ms;
    const wrap = document.createElement("section");
    wrap.className = "chunk";
    wrap.dataset.chunk = i;
    wrap.innerHTML = chunkHead(i) + data.paragraphs.map((p, a) =>
      `<span class="pno">¶${a + 1}</span><p class="para" data-chunk="${i}" data-anchor="${a}">${esc(p).replace(/\n/g, "<br>")}</p>
       <div class="side" data-side="${i}:${a}"></div>`).join("") + `<div class="locked-note" data-locked="${i}" hidden></div>`;
    if (prepend) {
      const anchor = page.querySelector(".chunk");
      const before = anchor ? anchor.getBoundingClientRect().top : 0;
      page.insertBefore(wrap, anchor || null);
      if (anchor) window.scrollBy(0, anchor.getBoundingClientRect().top - before);
    } else {
      page.appendChild(wrap);
    }
    renderDots();
    loadReactions(i, i);
  }

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
  const sentinel = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) loadNext();
  }, { rootMargin: "600px" });
  sentinel.observe(nextBtn.parentElement);

  // ── 체류시간 측정 ────────────────────────────────
  let current = null, segStart = null;

  function chunkAtCenter() {
    const y = window.innerHeight / 2;
    for (const sec of page.querySelectorAll(".chunk")) {
      const els = sec.querySelectorAll(".chunk-head, .para");
      if (!els.length) continue;
      const top = els[0].getBoundingClientRect().top;
      const bottom = els[els.length - 1].getBoundingClientRect().bottom;
      if (top <= y && bottom >= y) return Number(sec.dataset.chunk);
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
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { closeSegment(); segStart = null; flush(); }
    else { segStart = current === null ? null : performance.now(); tick(); }
  });
  setInterval(() => { closeSegment(); }, 10000);

  // ── 로컬 큐 · 배치 전송 ───────────────────────────
  function readQueue() { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]"); } catch (_) { return []; } }
  function writeQueue(q) { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q.slice(-500))); } catch (_) { /* 저장 불가 */ } }
  let memQueue = readQueue();
  function enqueue(ev) { memQueue.push(ev); writeQueue(memQueue); }

  let sending = false, slowShown = false, doneShown = false;
  async function flush() {
    if (sending || !memQueue.length || !navigator.onLine) return;
    sending = true;
    const batch = memQueue.slice(0, 200);
    try {
      const r = await api("POST", `/api/v1/books/${BOOK}/events`, { events: batch });
      memQueue = memQueue.slice(batch.length);
      writeQueue(memQueue);
      onProgress(r);
    } catch (e) {
      if (e.status && e.status < 500 && e.status !== 401) { memQueue = memQueue.slice(batch.length); writeQueue(memQueue); }
    } finally {
      sending = false;
    }
  }
  setInterval(flush, 10000);
  window.addEventListener("online", flush);
  window.addEventListener("pagehide", () => { closeSegment(); });

  function onProgress(r) {
    verified = r.verified_chunk;
    document.getElementById("pct").textContent = r.progress_pct + "%";
    document.getElementById("pbar").style.width = r.progress_pct + "%";
    for (const i of r.newly_verified) {
      const s = page.querySelector(`[data-state="${i}"]`);
      if (s) { s.textContent = "✓ 검증됨"; s.classList.add("ok"); }
    }
    if (r.newly_verified.length) loadReactions(Math.min(...r.newly_verified), last); // 가드가 풀린 반응을 다시 본다
    if (r.points_awarded) toast(`+${r.points_awarded}P`);
    if (r.slow_down && !slowShown) { slowShown = true; toast("천천히 읽어도 괜찮아요 🙂 넘기기만 한 구간은 레이스에 반영되지 않아요.", 6000); }
    if (r.suggest_done && !doneShown) { doneShown = true; toast("다 읽었어요! 책 화면에서 ‘완독’을 눌러 +50P를 받으세요.", 7000); }
  }

  // ── 반응 ────────────────────────────────────────
  const byPara = {}; // "chunk:anchor" → [reactions]

  async function loadReactions(from, to) {
    const q = new URLSearchParams({ chunk_from: from, chunk_to: to });
    if (ROOM) q.set("room_id", ROOM);
    let feed;
    try { feed = await api("GET", `/api/v1/books/${BOOK}/reactions?${q}`); } catch (_) { return; }
    for (let i = from; i <= to; i++) for (const k of Object.keys(byPara)) if (k.startsWith(i + ":")) delete byPara[k];
    for (const r of feed.visible) (byPara[`${r.chunk_index}:${r.anchor}`] ||= []).push(r);
    for (let i = from; i <= to; i++) {
      page.querySelectorAll(`[data-side^="${i}:"]`).forEach((el) => {
        const list = byPara[el.dataset.side] || [];
        el.innerHTML = list.length ? `<button class="rx" data-open="${el.dataset.side}">[+${list.length}]</button>` : "";
      });
      const lock = page.querySelector(`[data-locked="${i}"]`);
      const n = feed.locked[i] || 0;
      if (lock) { lock.hidden = !n; lock.textContent = `🔒 앞에서 ${n}개의 반응이 기다리고 있어요`; }
    }
  }

  const sheet = document.getElementById("sheet");
  let target = null;
  function openSheet(key) {
    target = key;
    const [c, a] = key.split(":").map(Number);
    page.querySelectorAll(".para.active").forEach((p) => p.classList.remove("active"));
    page.querySelector(`.para[data-chunk="${c}"][data-anchor="${a}"]`)?.classList.add("active");
    document.getElementById("sheet-title").textContent = `CHUNK ${c + 1} · ¶${a + 1}`;
    const list = byPara[key] || [];
    document.getElementById("sheet-list").innerHTML = list.length
      ? list.map((r) => `<li><span class="label">${esc(r.nickname)} · ${new Date(r.created_at + (r.created_at.endsWith("Z") || r.created_at.includes("+") ? "" : "Z")).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</span><br>${r.kind === "emoji" ? `<span style="font-size:22px">${r.body}</span>` : esc(r.body)}</li>`).join("")
      : `<li class="muted">아직 반응이 없어요. 첫 반응을 남겨 보세요.</li>`;
    sheet.hidden = false;
  }
  page.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-open]");
    if (btn) return openSheet(btn.dataset.open);
    const p = e.target.closest(".para");
    if (p && !window.getSelection().toString()) openSheet(`${p.dataset.chunk}:${p.dataset.anchor}`);
  });
  document.getElementById("sheet-close").onclick = () => { sheet.hidden = true; page.querySelectorAll(".para.active").forEach((p) => p.classList.remove("active")); };

  async function react(kind, body) {
    const [c, a] = target.split(":").map(Number);
    try {
      await api("POST", `/api/v1/books/${BOOK}/reactions`, { chunk_index: c, anchor: a, kind, body });
      await loadReactions(c, c);
      openSheet(target);
    } catch (e) { toast(e.message); }
  }
  document.getElementById("emoji-row").addEventListener("click", (e) => {
    const b = e.target.closest("[data-emoji]");
    if (b) react("emoji", b.dataset.emoji);
  });
  document.getElementById("comment-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("comment");
    if (input.value.trim()) { react("comment", input.value.trim()); input.value = ""; }
  });

  // ── 친구 위치 (방) ───────────────────────────────
  function renderDots() {
    page.querySelectorAll("[data-dots]").forEach((el) => {
      const i = Number(el.dataset.dots);
      el.innerHTML = Object.entries(friends)
        .filter(([, f]) => f.chunk === i)
        .map(([, f]) => `<span class="dot" title="${esc(f.nickname)}">${esc(f.nickname.slice(0, 1))}</span>`).join("");
    });
  }
  document.querySelectorAll("[data-member]").forEach((el) => {
    const uid = Number(el.dataset.member);
    if (uid === ME) return;
    // 검증 위치 + 1 = 지금 읽고 있을 청크
    friends[uid] = { nickname: el.dataset.nick, chunk: Math.min(TOTAL - 1, Number(el.dataset.chunk)) };
  });

  let room = null;
  if (ROOM) {
    room = socket(`/ws/rooms/${ROOM}`, (ev) => {
      const d = ev.data || {};
      if (ev.type === "progress.updated" || ev.type === "member.joined") {
        const chip = document.querySelector(`[data-member="${d.user_id}"] [data-pct]`);
        if (chip) chip.textContent = d.progress_pct;
        if (d.user_id !== ME) {
          friends[d.user_id] = { nickname: d.nickname, chunk: Math.min(TOTAL - 1, d.verified_chunk + 1) };
          renderDots();
          if (ev.type === "progress.updated") toast(`${d.nickname}님 ${d.progress_pct}%`, 2000);
        }
      } else if (ev.type === "presence.changed" && d.user_id !== ME) {
        friends[d.user_id] = { nickname: d.nickname, chunk: d.chunk_index };
        renderDots();
      } else if (ev.type === "reaction.created" && d.user_id !== ME) {
        if (d.chunk_index >= first && d.chunk_index <= last) loadReactions(d.chunk_index, d.chunk_index);
        toast(`${d.nickname}님이 반응을 남겼어요`, 2000);
      }
    });
  }

  // ── 상단 바: 아래로 스크롤하면 숨김 ──────────────────
  let lastY = window.scrollY;
  const top = document.getElementById("reader-top");
  window.addEventListener("scroll", () => {
    const y = window.scrollY;
    top.classList.toggle("hide", y > lastY && y > 120);
    lastY = y;
  }, { passive: true });

  loadNext().then(() => { tick(); flush(); });
})();
