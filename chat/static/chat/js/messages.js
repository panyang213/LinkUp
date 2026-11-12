(() => {
  const $ = (s) => document.querySelector(s);
  const withUid = JSON.parse($("#dm-with").textContent);
  const list = $("#messages"), input = $("#composer-input"), sendBtn = $("#send-btn");
  const me = JSON.parse($("#dm-me").textContent);
  let typingOff, iTyping = false;

  const convRow = (uid) => document.querySelector(`[data-conv="${uid}"]`);
  const scroll = () => { if (list) list.scrollTop = list.scrollHeight; };
  function bubble(m) {
    const mine = m.sender === me;
    const wrap = document.createElement("div"); wrap.className = `msg ${mine ? "me" : "them"}`; wrap.dataset.id = m.id;
    const b = document.createElement("div"); b.className = `bubble bubble-${mine ? "me" : "them"}`; b.textContent = m.text;
    const t = document.createElement("time"); t.textContent = LU.time(m.ts);
    wrap.append(b, t); list.appendChild(wrap); scroll();
  }
  function touchRow(uid, text, mine, unreadDelta) {
    const row = convRow(uid); if (!row) { if (!mine) location.reload(); return; }
    row.querySelector("[data-preview]").textContent = (mine ? "You: " : "") + text;
    row.parentElement.querySelector("h1").after(row);
    const c = row.querySelector("[data-unread]");
    const n = Number(c.textContent || 0) + unreadDelta;
    c.textContent = n; c.hidden = n <= 0;
  }

  async function init() {
    if (withUid) {
      const d = await LU.api(`/api/messages/${withUid}/`);
      d.messages.forEach(bubble);
      if (!d.messages.length) list.innerHTML = '<div class="sys">Say hello — messages here are saved for both of you.</div>';
      const row = convRow(withUid);
      if (row) { const c = row.querySelector("[data-unread]"); c.textContent = 0; c.hidden = true; }
    }
  }
  function sendMessage() {
    const text = input.value.trim(); if (!text) return;
    LU.send({ type: "dm", to: withUid, text }); input.value = ""; input.style.height = "auto"; stopTyping();
  }
  function stopTyping() { if (iTyping) { iTyping = false; LU.send({ type: "typing", to: withUid, on: false }); } }

  LU.on((m) => {
    if (m.type === "dm") {
      const mine = m.message.sender === me;
      if (m.with === withUid && list) {
        const empty = list.querySelector(".sys"); if (empty) empty.remove();
        if (!list.querySelector(`[data-id="${m.message.id}"]`)) bubble(m.message);
        $("#typing").hidden = true;
        if (m.message.sender !== me) LU.send({ type: "read", with: withUid });
        touchRow(m.with, m.message.text, mine, 0);
      } else {
        touchRow(m.with, m.message.text, m.message.sender === me, m.message.sender === me ? 0 : 1);
      }
    } else if (m.type === "typing" && m.uid === withUid) {
      $("#typing").hidden = !m.on; clearTimeout(typingOff); if (m.on) typingOff = setTimeout(() => ($("#typing").hidden = true), 4000);
    } else if (m.type === "presence" && m.uid === withUid) {
      $("#peer-dot").classList.toggle("on", m.online); $("#peer-status").textContent = m.online ? "Online" : "Offline";
    } else if (m.type === "error") LU.toast(m.message);
  });

  if (input) {
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    input.addEventListener("input", () => {
      input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px";
      if (!iTyping) { iTyping = true; LU.send({ type: "typing", to: withUid, on: true }); }
      clearTimeout(stopTyping.t); stopTyping.t = setTimeout(stopTyping, 1500);
    });
    sendBtn.addEventListener("click", sendMessage);
  }
  const del = $("#delete-conv");
  if (del) del.addEventListener("click", async () => {
    if (!confirm("Delete this conversation from your account? Your friend keeps their copy.")) return;
    try { await LU.api(`/api/messages/${withUid}/delete/`, {}); location.href = "/messages/"; } catch (e) { LU.toast(e.message); }
  });
  init().catch((e) => LU.toast(e.message));
})();
