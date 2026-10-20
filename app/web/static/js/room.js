// 읽기방 (PRD ROOM-02): 멤버 진행률 막대와 최근 반응이 새로고침 없이 바뀐다
(function () {
  "use strict";
  const { socket, toast } = window.saipr;
  const root = document.getElementById("room-root");
  const ROOM = Number(root.dataset.room);
  const ME = Number(root.dataset.me);
  const members = document.getElementById("members");
  const recent = document.getElementById("recent");
  const COLORS = ["#3b82f6", "#22a06b", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#ec4899", "#64748b"];
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  function row(uid, nickname) {
    let r = members.querySelector(`[data-uid="${uid}"]`);
    if (!r) {
      r = document.createElement("div");
      r.className = "row";
      r.dataset.uid = uid;
      r.innerHTML = `<span class="av lg" style="background:${COLORS[uid % COLORS.length]}">${esc(nickname.slice(0, 1))}</span>
        <div class="col" style="flex:1;gap:6px;min-width:0"><div class="row"><span style="font-size:14px">${esc(nickname)}</span>
        <span class="muted tiny"><span data-pct>0</span>%</span></div><div class="bar soft"><b style="width:0%"></b></div></div>`;
      members.appendChild(r);
    }
    return r;
  }
  function addRecent(text) {
    recent.querySelector("[data-empty]")?.remove();
    const s = document.createElement("span");
    s.className = "cap";
    s.textContent = text;
    recent.prepend(s);
    while (recent.children.length > 5) recent.lastElementChild.remove();
  }

  socket(`/ws/rooms/${ROOM}`, (ev) => {
    const d = ev.data || {};
    if (ev.type === "progress.updated" || ev.type === "member.joined") {
      const r = row(d.user_id, d.nickname);
      r.querySelector("[data-pct]").textContent = d.progress_pct;
      // 바뀐 친구 줄이 잠깐 빛나고 숫자가 튄다
      r.classList.remove("flash-row"); void r.offsetWidth; r.classList.add("flash-row");
      window.motion?.bump(r.querySelector("[data-pct]"));
      r.querySelector(".bar > b").style.width = d.progress_pct + "%";
      const cnt = r.querySelector("[data-count]");
      if (cnt && d.new_chunks) cnt.textContent = String(Number(cnt.textContent) + d.new_chunks);
      if (d.user_id !== ME) {
        toast(ev.type === "member.joined" ? `${d.nickname}님이 들어왔어요` : `${d.nickname}님이 ${d.progress_pct}%까지 읽었어요`);
        window.motion?.haptic(ev.type === "member.joined" ? [15, 40, 15] : 10);
      }
    } else if (ev.type === "reaction.created" && d.user_id !== ME) {
      // 내용은 싣지 않는다 — 스포일러 가드를 거치도록 리더에서 확인
      addRecent(`${d.nickname} · 청크 ${d.chunk_index + 1}에 반응을 남겼어요`);
    } else if (ev.type === "member.left") {
      members.querySelector(`[data-uid="${d.user_id}"]`)?.remove();
    }
  });

  // 카카오톡 SDK 키가 없으므로 휴대폰 공유 시트(카카오톡 포함) → 안 되면 링크 복사
  document.getElementById("share")?.addEventListener("click", async (e) => {
    const { url, title } = e.currentTarget.dataset;
    if (navigator.share) {
      try { await navigator.share({ title: `함께읽기 · ${title}`, text: `「${title}」 같이 읽자!`, url }); return; }
      catch (err) { if (err && err.name === "AbortError") return; }
    }
    try { await navigator.clipboard.writeText(url); toast("초대 링크를 복사했어요. 카카오톡에 붙여 넣어 보내 주세요"); }
    catch (_) { toast(url, 6000); }
  });
})();
