// 읽기방: 멤버 마커가 눈금자 위에서 실시간으로 움직이고, 활동 로그가 쌓인다 (PRD ROOM-02)
(function () {
  "use strict";
  const { socket, toast } = window.saipr;
  const root = document.getElementById("room-root");
  const ROOM = Number(root.dataset.room);
  const TOTAL = Number(root.dataset.total) || 1;
  const ME = Number(root.dataset.me);
  const ruler = document.getElementById("ruler");
  const log = document.getElementById("log");

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  function hhmm() { return new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }); }
  function addLog(text) {
    log.querySelector(".muted")?.remove(); // "아직 조용해요." 자리표시 제거
    const li = document.createElement("li");
    li.textContent = `${hhmm()} · ${text}`;
    log.prepend(li);
    while (log.children.length > 12) log.lastChild.remove();
  }
  function clampPct(p) { return Math.max(2, Math.min(98, p)); }

  function marker(uid, nickname) {
    let m = ruler.querySelector(`[data-uid="${uid}"]`);
    if (!m) {
      m = document.createElement("div");
      m.className = "marker" + (uid === ME ? " me" : "");
      m.dataset.uid = uid;
      m.innerHTML = `<b>${esc(nickname.slice(0, 1))}</b><small>${esc(nickname)} <span data-pct>0</span>%</small>`;
      ruler.appendChild(m);
    }
    return m;
  }

  function move(uid, nickname, pct) {
    const m = marker(uid, nickname);
    m.style.left = clampPct(pct) + "%";
    m.querySelector("[data-pct]").textContent = Math.round(pct);
  }

  // 점수가 바뀌면 순위표를 다시 정렬하고 1위 행을 강조한다
  function rerank() {
    const body = document.querySelector("#race tbody");
    const rows = [...body.rows].sort((x, y) =>
      Number(y.querySelector("[data-count]").textContent) - Number(x.querySelector("[data-count]").textContent));
    rows.forEach((tr, i) => {
      tr.cells[0].textContent = String(i + 1);
      tr.classList.toggle("first", i === 0 && Number(tr.querySelector("[data-count]").textContent) > 0);
      body.appendChild(tr);
    });
  }

  socket(`/ws/rooms/${ROOM}`, (ev) => {
    const d = ev.data || {};
    if (ev.type === "progress.updated") {
      move(d.user_id, d.nickname, d.progress_pct);
      addLog(`${d.nickname} → ${d.progress_pct}% (CH${String(d.verified_chunk + 1).padStart(2, "0")})`);
      const row = document.querySelector(`#race tr[data-uid="${d.user_id}"] [data-count]`);
      if (row && root.dataset.fulltext) {
        row.textContent = String(Number(row.textContent) + (d.new_chunks || 0));
        rerank();
      }
    } else if (ev.type === "member.joined") {
      move(d.user_id, d.nickname, d.progress_pct || 0);
      addLog(`${d.nickname}님이 들어왔어요`);
      if (d.user_id !== ME) toast(`${d.nickname}님이 들어왔어요`);
    } else if (ev.type === "presence.changed") {
      move(d.user_id, d.nickname, ((d.chunk_index + 0.5) / TOTAL) * 100);
    } else if (ev.type === "reaction.created") {
      addLog(`${d.nickname} · CH${String(d.chunk_index + 1).padStart(2, "0")} ¶${d.anchor + 1}에 반응`);
    }
  });

  document.getElementById("copy")?.addEventListener("click", async () => {
    const input = document.getElementById("invite");
    try { await navigator.clipboard.writeText(input.value); toast("초대 링크를 복사했어요"); }
    catch (_) { input.select(); toast("링크를 길게 눌러 복사해 주세요"); }
  });
})();
