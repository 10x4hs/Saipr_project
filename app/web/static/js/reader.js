// 인앱 리더 (PRD READ-01) — 시안 Glass v2의 종이 시트
// 측정: 지금 보이는 영역 가운데의 청크 하나에만 시간을 쌓고, 탭이 숨겨지면 멈춘다 (EXC-04).
//       같은 책을 탭 여러 개로 열어도 Web Locks로 '보고 있는 탭 하나'만 시간을 잰다.
//       10초마다 묶어 보내고, 오프라인이면 기기에 모았다가 연결되면 보낸다 (EXC-05). 판정은 서버가 한다.
// 기술: 화면 꺼짐 방지(Wake Lock) · 한국어 읽어 주기(speechSynthesis) · 내 속도를 배우는 남은 시간 ·
//       타이포그래피/테마 설정 · 집중 모드 · 끌어서 닫는 바텀 시트 · 이정표 축하.
(function () {
  "use strict";
  const { api, toast, socket } = window.saipr;
  const M = window.motion || { haptic() {}, confetti() {}, bump() {}, reduce: true };
  const root = document.getElementById("reader-root");
  const BOOK = Number(root.dataset.book);
  const TOTAL = Number(root.dataset.total);
  const ROOM = root.dataset.room ? Number(root.dataset.room) : null;
  const SYNC = root.dataset.mode === "sync";
  const ME = Number(root.dataset.me);
  const QUEUE_KEY = `saipr:events:${BOOK}`;
  const scroller = document.getElementById("scroll");
  const screenEl = document.querySelector(".screen");
  const book = document.getElementById("book");
  const page = document.getElementById("page");
  const nextBtn = document.getElementById("load-next");
  const prevBtn = document.getElementById("load-prev");

  let verified = Number(root.dataset.verified);
  let pct = Number(document.getElementById("pct").textContent.replace("%", "")) || 0;
  let first = Number(root.dataset.start);
  let last = first - 1;
  const chars = {}; // 청크별 글자 수 (남은 시간 계산용)

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const COLORS = ["#3b82f6", "#22a06b", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#ec4899", "#64748b"];
  const color = (uid) => COLORS[uid % COLORS.length];
  const store = {
    get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* 저장 불가 */ } },
  };

  // ── 설정: 글자 크기 · 글꼴 · 간격 · 배경 · 읽어 주기 속도 ───────
  const SIZES = ["15px", "16.5px", "18.5px", "21px"];
  const SPACING = [{ lh: 1.7, gap: "4px" }, { lh: 1.9, gap: "10px" }, { lh: 2.15, gap: "18px" }];
  const pref = { size: 1, font: "serif", lh: 1, theme: "paper", rate: 1, ...store.get("saipr:reader", {}) };
  if (pref.theme === "white" || pref.theme === "night") pref.theme = pref.theme === "night" ? "dark" : "paper"; // 예전 값
  function pressed(segId, attr, value) {
    document.querySelectorAll(`#${segId} button`).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset[attr] === String(value))));
  }
  function applyPref() {
    book.style.setProperty("--fs", SIZES[pref.size]);
    book.style.setProperty("--lh", SPACING[pref.lh].lh);
    book.style.setProperty("--pgap", SPACING[pref.lh].gap);
    book.dataset.theme = pref.theme;
    book.dataset.font = pref.font;
    pressed("size-seg", "size", pref.size); pressed("font-seg", "font", pref.font);
    pressed("lh-seg", "lh", pref.lh); pressed("theme-seg", "theme", pref.theme); pressed("rate-seg", "rate", pref.rate);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", pref.theme === "dark" ? "#1c1b19" : "#6f767f");
    store.set("saipr:reader", pref);
  }
  const bindSeg = (id, attr, key, cast = (v) => v) =>
    document.getElementById(id).addEventListener("click", (e) => {
      const b = e.target.closest(`[data-${attr}]`);
      if (b) { pref[key] = cast(b.dataset[attr]); applyPref(); M.haptic(8); }
    });
  bindSeg("size-seg", "size", "size", Number);
  bindSeg("font-seg", "font", "font");
  bindSeg("lh-seg", "lh", "lh", Number);
  bindSeg("theme-seg", "theme", "theme");
  bindSeg("rate-seg", "rate", "rate", Number);
  document.getElementById("room-pick")?.addEventListener("change", (e) => { location.href = `/books/${BOOK}/read?room=${e.target.value}`; });
  applyPref();

  // ── 바텀 시트: 스프링으로 올라오고, 손잡이를 끌어내리면 닫힌다 ─────
  const sheetBg = document.getElementById("sheet-bg");
  function openSheet(id) {
    const sheet = document.getElementById(id);
    sheet.classList.remove("closing"); sheetBg.classList.remove("closing");
    sheet.style.transform = "";
    sheetBg.hidden = false; sheet.hidden = false;
  }
  function closeSheets() {
    const open = [...document.querySelectorAll(".sheet")].filter((s) => !s.hidden);
    if (!open.length) return;
    page.querySelectorAll(".para.active").forEach((p) => p.classList.remove("active"));
    const done = () => { open.forEach((s) => { s.hidden = true; s.classList.remove("closing"); s.style.transform = ""; }); sheetBg.hidden = true; sheetBg.classList.remove("closing"); };
    if (M.reduce) return done();
    open.forEach((s) => s.classList.add("closing")); sheetBg.classList.add("closing");
    setTimeout(done, 300);
  }
  sheetBg.onclick = closeSheets;
  document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeSheets));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeSheets(); setFocus(false); } });
  document.getElementById("settings-btn").onclick = () => openSheet("set-sheet");

  document.querySelectorAll(".sheet .grab").forEach((grab) => {
    const sheet = grab.closest(".sheet");
    grab.addEventListener("pointerdown", (e) => {
      const y0 = e.clientY; let last = y0, tLast = e.timeStamp, v = 0;
      grab.setPointerCapture(e.pointerId);
      sheet.classList.add("dragging");
      const move = (ev) => {
        const dy = Math.max(0, ev.clientY - y0);
        v = (ev.clientY - last) / Math.max(1, ev.timeStamp - tLast); last = ev.clientY; tLast = ev.timeStamp;
        sheet.style.transform = `translateY(${dy}px)`;
      };
      const up = (ev) => {
        grab.removeEventListener("pointermove", move);
        sheet.classList.remove("dragging");
        const dy = ev.clientY - y0;
        // 1/3 넘게 끌었거나 빠르게 튕기면 닫는다
        if (dy > sheet.offsetHeight * 0.33 || v > 0.6) closeSheets(); else sheet.style.transform = "";
      };
      grab.addEventListener("pointermove", move);
      grab.addEventListener("pointerup", up, { once: true });
      grab.addEventListener("pointercancel", up, { once: true });
    });
  });

  // ── 청크 불러오기 ────────────────────────────────
  // 읽어 주기에서 문장 단위로 강조하려고 문장마다 <span class="s">로 감싼다
  // 아무것도 버리지 않는 분할: 문장부호(+닫는 따옴표) 뒤 공백까지를 한 문장으로
  const SENTENCE = /[^]*?(?:[.!?…。]+["”」']?\s+|$)/g;
  function sentences(text) {
    const parts = (text.match(SENTENCE) || []).filter(Boolean);
    return (parts.length ? parts : [text]).map((t) => `<span class="s">${esc(t).replace(/\n/g, "<br>")}</span>`).join("");
  }
  function paragraphHTML(i, a, text) {
    let body = sentences(text), cls = "para";
    if (i === 0 && a === 0) {
      // 첫 문단은 시안처럼 첫 글자를 크게 (드롭캡)
      body = `<span class="dc">${esc(text.charAt(0))}</span>` + sentences(text.slice(1));
      cls += " first";
    }
    return `<p class="${cls}" data-chunk="${i}" data-anchor="${a}">${body}</p><div data-notes="${i}:${a}"></div>`;
  }
  async function loadChunk(i, prepend = false) {
    const data = await api("GET", `/books/${BOOK}/chunk/${i}`);
    chars[i] = data.paragraphs.join("").replace(/\s/g, "").length;
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
    renderNotes(); renderHere(); updateEta();
  }
  const scrollable = () => scroller.scrollHeight > scroller.clientHeight + 1;
  function scrollBy(dy) { if (scrollable()) scroller.scrollTop += dy; else window.scrollBy(0, dy); }
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
  new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) loadNext(); }, { rootMargin: "600px" }).observe(nextBtn);

  // ── 탭 하나만 시간 재기 (Web Locks) ──────────────────
  // 보이는 탭이 잠금을 '빼앗아' 가지므로, 창을 두 개 띄워도 시간이 두 배로 쌓이지 않는다.
  let owner = !("locks" in navigator);
  let releaseLock = null;
  function takeLock() {
    if (!("locks" in navigator) || document.hidden) return;
    navigator.locks.request(`saipr-reader-${BOOK}`, { steal: true }, () => new Promise((resolve) => {
      owner = true; releaseLock = resolve; tick();
    })).catch(() => { owner = false; });
  }
  function dropLock() { if (releaseLock) { releaseLock(); releaseLock = null; } owner = !("locks" in navigator); }

  // ── 화면 꺼짐 방지 (Wake Lock) ──────────────────────
  let wake = null;
  async function keepAwake() {
    if (!("wakeLock" in navigator) || document.hidden) return;
    try { wake = await navigator.wakeLock.request("screen"); } catch (_) { wake = null; }
  }

  // ── 체류시간 측정 ────────────────────────────────
  let current = null, segStart = null, currentPara = null;
  const dwellByChunk = {}; // 이 기기에서 잰 청크별 시간 (속도 학습용)
  function visibleBand() {
    const r = scroller.getBoundingClientRect();
    return [Math.max(r.top, 0), Math.min(r.bottom, window.innerHeight)];
  }
  function atCenter() {
    const [top, bottom] = visibleBand();
    const y = (top + bottom) / 2;
    let chunk = null, para = null;
    for (const sec of page.children) {
      const r = sec.getBoundingClientRect();
      if (r.top <= y && r.bottom >= y) { chunk = Number(sec.dataset.chunk); break; }
    }
    if (chunk !== null) {
      for (const p of page.querySelectorAll(`.para[data-chunk="${chunk}"]`)) {
        const r = p.getBoundingClientRect();
        if (r.top <= y + 40 && r.bottom >= y - 40) { para = p; break; }
      }
    }
    return { chunk, para };
  }
  function closeSegment() {
    if (current === null || segStart === null) return;
    const dwell = Math.round(performance.now() - segStart);
    if (dwell >= 300 && owner) {
      enqueue({ chunk_index: current, dwell_ms: dwell, occurred_at: new Date().toISOString() });
      if (dwell < 120000) dwellByChunk[current] = (dwellByChunk[current] || 0) + dwell; // 2분 넘게 멈춘 구간은 딴짓으로 보고 제외
    }
    segStart = document.hidden ? null : performance.now();
  }
  function tick() {
    const { chunk, para } = document.hidden ? { chunk: null, para: null } : atCenter();
    if (para !== currentPara) {
      currentPara?.classList.remove("current");
      para?.classList.add("current");
      currentPara = para;
    }
    if (chunk !== current) {
      closeSegment();
      current = chunk;
      segStart = chunk === null ? null : performance.now();
      if (SYNC && chunk !== null && room) room.send({ type: "presence", chunk_index: chunk });
      updateEta();
    }
  }
  window.addEventListener("scroll", tick, { passive: true });
  scroller.addEventListener("scroll", tick, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { closeSegment(); segStart = null; flush(true); dropLock(); }
    else { segStart = current === null ? null : performance.now(); takeLock(); keepAwake(); tick(); }
  });
  setInterval(closeSegment, 10000);

  // ── 로컬 큐 · 배치 전송 ───────────────────────────
  let queue = store.get(QUEUE_KEY, []);
  const writeQueue = () => store.set(QUEUE_KEY, queue.slice(-500));
  function enqueue(ev) { queue.push(ev); writeQueue(); }
  let sending = false, slowShown = false, doneShown = false;
  async function flush(leaving = false) {
    if (sending || !queue.length || !navigator.onLine) return;
    sending = true;
    // 떠날 때는 keepalive 본문 한도(64KB) 안에 들도록 조금만
    const batch = queue.slice(0, leaving ? 60 : 200);
    try {
      const r = await api("POST", `/api/v1/books/${BOOK}/events`, { events: batch }, { keepalive: leaving });
      queue = queue.slice(batch.length); writeQueue();
      onProgress(r);
    } catch (e) {
      // 4xx는 다시 보내도 같으므로 버린다. 5xx·네트워크 오류는 남겨 두고 다음에 다시 보낸다
      if (e.status && e.status < 500 && e.status !== 401) { queue = queue.slice(batch.length); writeQueue(); }
    } finally { sending = false; }
  }
  setInterval(flush, 10000);
  window.addEventListener("online", () => { toast("다시 연결됐어요. 읽은 기록을 보내요"); flush(); });
  window.addEventListener("offline", () => toast("오프라인이에요. 읽은 기록은 기기에 모아 둘게요", 4000));
  window.addEventListener("pagehide", () => { closeSegment(); flush(true); });

  const MILESTONES = { 25: "4분의 1 왔어요!", 50: "절반 왔어요! 🎉", 75: "거의 다 왔어요!", 100: "다 읽었어요! 📚" };
  function onProgress(r) {
    const before = pct;
    verified = r.verified_chunk; pct = r.progress_pct;
    document.getElementById("pct").textContent = pct + "%";
    M.bump(document.getElementById("pct"));
    document.getElementById("pbar").style.width = pct + "%";
    for (const i of r.newly_verified) {
      const f = page.querySelector(`[data-folio="${i}"]`);
      if (f && !f.querySelector(".ok")) f.insertAdjacentHTML("beforeend", '<span class="ok">✓ 읽음</span>');
      learnSpeed(i);
    }
    if (r.newly_verified.length) loadReactions(); // 가드가 풀린 반응을 다시 본다
    const crossed = Object.keys(MILESTONES).map(Number).filter((m) => before < m && pct >= m).pop();
    if (crossed) { M.confetti(); M.haptic([20, 40, 20]); toast(MILESTONES[crossed], 3500); }
    else if (r.points_awarded) toast(`+${r.points_awarded}P`);
    if (r.slow_down && !slowShown) { slowShown = true; toast("천천히 읽어도 괜찮아요. 빠르게 넘긴 쪽은 점수에 들어가지 않아요.", 6000); }
    if (r.suggest_done && !doneShown) { doneShown = true; setTimeout(() => toast("책 화면에서 ‘완독’으로 옮겨 주세요", 5000), 3600); }
    updateEta();
  }

  // ── 남은 시간: 내 읽기 속도를 배운다 (Kindle 방식) ─────────
  let cpm = store.get("saipr:cpm", 500); // 분당 글자 수, 처음엔 한국어 평균에 가깝게
  function learnSpeed(i) {
    const ms = dwellByChunk[i];
    if (!ms || !chars[i]) return;
    const sample = Math.min(3000, Math.max(150, chars[i] / (ms / 60000)));
    cpm = Math.round(cpm * 0.7 + sample * 0.3);
    store.set("saipr:cpm", cpm);
  }
  function updateEta() {
    const el = document.getElementById("eta");
    const known = Object.values(chars);
    if (!known.length || current === null || !chars[current]) { el.textContent = ""; return; }
    const avg = known.reduce((a, b) => a + b, 0) / known.length;
    const here = Math.max(1, Math.round(chars[current] / cpm));
    const restChars = chars[current] + avg * Math.max(0, TOTAL - 1 - current);
    const rest = Math.max(here, Math.round(restChars / cpm));
    el.textContent = `이 쪽 약 ${here}분 · 끝까지 약 ${rest >= 60 ? `${Math.floor(rest / 60)}시간 ${rest % 60}분` : `${rest}분`}`;
  }

  // ── 반응 (문단 아래 메모 · 잠금 알약) ─────────────────
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
    if (screenEl.classList.contains("focus-mode")) return setFocus(false); // 집중 모드에서는 탭하면 빠져나온다
    const n = e.target.closest("[data-open]");
    if (n) return openReactions(n.dataset.open);
    const p = e.target.closest(".para");
    if (p && !window.getSelection().toString()) openReactions(`${p.dataset.chunk}:${p.dataset.anchor}`);
  });
  async function react(kind, body) {
    const [c, a] = target.split(":").map(Number);
    try {
      await api("POST", `/api/v1/books/${BOOK}/reactions`, { chunk_index: c, anchor: a, kind, body });
      M.haptic(15);
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

  // ── 집중 모드 ───────────────────────────────────
  function setFocus(on) {
    screenEl.classList.toggle("focus-mode", on);
    if (on) { closeSheets(); toast("집중 모드 — 화면을 탭하면 돌아와요", 2200); }
  }
  document.getElementById("focus-btn").onclick = () => setFocus(true);

  // ── 읽어 주기 (Web Speech API, 한국어) ───────────────────
  // 'boundary' 이벤트는 기기마다 불안정해서, 문장 하나씩 발화하고 시작할 때 강조한다.
  const ttsBtn = document.getElementById("tts-btn");
  const tts = "speechSynthesis" in window;
  let speaking = false, voice = null;
  function pickVoice() {
    const vs = speechSynthesis.getVoices();
    voice = vs.find((v) => v.lang === "ko-KR" && /Yuna|Google|유나/.test(v.name)) || vs.find((v) => v.lang?.startsWith("ko")) || null;
  }
  if (tts) { pickVoice(); speechSynthesis.addEventListener?.("voiceschanged", pickVoice); } else ttsBtn.hidden = true;
  function startFrom(el) {
    const all = [...page.querySelectorAll(".s")];
    let i = Math.max(0, all.indexOf(el));
    let silent = 0; // 시작도 안 하고 끝난 문장 수 — 음성 엔진이 없는 기기 감지
    const speakNext = () => {
      if (!speaking || i >= all.length) return stopTTS();
      const s = all[i];
      const u = new SpeechSynthesisUtterance(s.textContent);
      u.lang = "ko-KR"; if (voice) u.voice = voice; u.rate = pref.rate;
      let started = false;
      u.onstart = () => {
        started = true; silent = 0;
        page.querySelector(".s.speaking")?.classList.remove("speaking");
        s.classList.add("speaking");
        s.scrollIntoView({ block: "center", behavior: M.reduce ? "auto" : "smooth" });
      };
      u.onend = () => {
        if (!speaking) return;
        if (!started && ++silent >= 2) { stopTTS(); toast("이 기기에서는 소리를 낼 수 없어요. 음량이나 음성 설정을 확인해 주세요", 4000); return; }
        i += 1; if (i >= all.length - 3) loadNext(); speakNext();
      };
      u.onerror = (e) => {
        if (e.error === "interrupted" || e.error === "canceled") return; // 멈춤 버튼·다음 문장으로 넘어갈 때
        stopTTS();
        toast(e.error === "not-allowed" ? "화면을 한 번 탭한 뒤 다시 눌러 주세요" : "읽어 주기를 시작하지 못했어요", 3500);
      };
      speechSynthesis.speak(u);
    };
    speakNext();
  }
  function stopTTS() {
    speaking = false;
    if (tts) speechSynthesis.cancel();
    page.querySelector(".s.speaking")?.classList.remove("speaking");
    ttsBtn.textContent = "▶︎"; ttsBtn.setAttribute("aria-pressed", "false");
  }
  ttsBtn.onclick = () => {
    if (speaking) return stopTTS();
    if (!voice) toast("이 기기에는 한국어 음성이 없을 수 있어요. 기본 음성으로 읽을게요", 3000);
    speaking = true;
    ttsBtn.textContent = "❚❚"; ttsBtn.setAttribute("aria-pressed", "true");
    const startEl = currentPara?.querySelector(".s") || page.querySelector(".s");
    startFrom(startEl);
  };

  // 설정 시트에 이 기기에서 켜진 기술을 보여 준다 (시연용)
  const techs = [
    ["locks" in navigator, "탭 하나만 시간 재기"], ["wakeLock" in navigator, "화면 꺼짐 방지"],
    [tts, "읽어 주기"], ["serviceWorker" in navigator, "오프라인 읽기"],
    [!!document.startViewTransition, "화면 전환 애니메이션"], [!!window.liquid?.refract, "유리 굴절"],
  ].filter(([ok]) => ok).map(([, n]) => n);
  document.getElementById("tech-note").textContent = techs.length ? `이 기기에서 켜진 기능: ${techs.join(" · ")}` : "";

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
        loadReactions(); M.haptic(10);
        toast(`${d.nickname}님이 반응을 남겼어요`, 2000);
      } else if (ev.type === "member.left") {
        delete friends[d.user_id]; renderHere();
      }
    });
  }

  takeLock(); keepAwake();
  loadNext().then(() => { loadReactions(); tick(); flush(); });
})();
