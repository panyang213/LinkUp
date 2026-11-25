// LinkUp anonymous chat client.
(() => {
  const $ = (s) => document.querySelector(s);
  const on = (sel, ev, fn) => { const el = $(sel); if (el) el.addEventListener(ev, fn); };
  const cfg = JSON.parse($("#client-config").textContent);
  const panels = { idle: $("#panel-idle"), searching: $("#panel-searching"), chat: $("#panel-chat") };
  const messagesEl = $("#messages"), input = $("#composer-input"), sendBtn = $("#send-btn");
  const typingEl = $("#typing"), startBtn = $("#start-btn");
  const tips = ["Be kind — there’s a real person on the other side.", "Stuck? Tap the lightbulb for a topic.", "Don’t share personal details with strangers."];
  let ws, partner = null, peerPresent = false, typingOff = null, iTyping = false, tipTimer = null;

  const show = (name) => Object.entries(panels).forEach(([k, el]) => (el.hidden = k !== name));
  const send = (obj) => ws && ws.readyState === 1 && ws.send(JSON.stringify(obj));
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const fmtTime = (ts) => new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/chat/`);
    
    // FIX 1: Show loading state and disable button until connected
    startBtn.disabled = true;
    if (startBtn.textContent !== "Connecting...") {
        startBtn.textContent = "Connecting...";
    }

    ws.onopen = () => {
      startBtn.disabled = false;
      startBtn.textContent = "Start random chat"; // Restore text
    };
    
    ws.onmessage = (e) => {
      try {
        handle(JSON.parse(e.data));
      } catch (error) {
        console.error("LinkUp received an invalid WebSocket message:", error);
      }
    };
    
    ws.onerror = (error) => {
      console.error("LinkUp WebSocket error:", error);
    };
    
    ws.onclose = (e) => {
      startBtn.disabled = true;
      peerPresent = false;
      partner = null;
      hideTyping();
      setComposer(false);
      document.dispatchEvent(new CustomEvent("linkup:event", { detail: { type: "socket_closed" } }));
      
      if (e.code === 4401) {
        location.href = "/";
        return;
      }
      
      show("idle");
      flash("Connection lost. Reconnecting...");
      setTimeout(connect, 3000);
    };
  }

  function handle(m) {
    document.dispatchEvent(new CustomEvent("linkup:event", { detail: m }));
    switch (m.type) {
      case "online": document.querySelectorAll("[data-online-count]").forEach((el) => (el.textContent = m.count)); break;
      case "searching": enterSearching(); break;
      case "matched": enterChat(m.partner); break;
      case "message": hideTyping(); addMessage("them", m.text, m.ts); break;
      case "typing": m.on ? showTyping() : hideTyping(); break;
      case "partner_left": partnerGone(`${partner ? partner.nickname : "They"} left the chat.`); break;
      case "ended": goIdle(); break;
      case "blocked": goIdle("Person blocked. You won’t be matched with them again."); break;
      case "reported": goIdle("Thanks — your report was sent and you’ve been disconnected."); break;
      case "error": addSystem(m.message); break;
    }
  }

  // ----- state transitions -----
  function enterSearching() {
    clearMessages(); 
    show("searching");
    
    // FIX 2: Re-enable the cancel button so users can leave the queue
    const cancelBtn = $("#cancel-btn");
    if (cancelBtn) cancelBtn.disabled = false;

    clearInterval(tipTimer); let i = 0;
    tipTimer = setInterval(() => { $("#search-tip").textContent = tips[++i % tips.length]; }, 4000);
  }

  function enterChat(p) {
    clearInterval(tipTimer);
    partner = p; peerPresent = true; clearMessages(); show("chat");
    $("#peer-name").textContent = p.nickname;
    $("#peer-dot").className = "dot on";
    const bits = [];
    const mood = $(`label[for="mood-${p.mood}"]`);
    if (mood) bits.push(`Feeling ${mood.textContent.toLowerCase()}`);
    if (p.shared && p.shared.length) bits.push(`You both like ${p.shared.join(", ")}`);
    $("#peer-meta").textContent = bits.join(" · ") || "Connected";
    setComposer(true);
    addSystem(`You’re chatting with ${p.nickname}. Say hi! Try: “${pick(cfg.icebreakers)}”`);
    input.focus();
  }

  function partnerGone(text) {
    peerPresent = false; hideTyping(); setComposer(false);
    $("#peer-dot").className = "dot";
    $("#peer-meta").textContent = "Offline";
    const el = addSystem(text + " ");
    const b = document.createElement("button");
    b.className = "btn btn-sm btn-accent"; b.type = "button"; b.textContent = "Find someone new";
    b.onclick = findNext; el.appendChild(b);
  }

  function goIdle(notice) {
    clearInterval(tipTimer); partner = null; clearMessages(); show("idle");
    
    // FIX 3: Re-enable the start button when returning to idle
    startBtn.disabled = false;
    startBtn.textContent = "Start random chat";

    if (notice) { $("#search-tip").textContent = ""; flash(notice); }
  }

  function flash(text) {
    const el = document.createElement("div");
    el.className = "alert alert-info"; el.setAttribute("role", "status"); el.textContent = text;
    panels.idle.prepend(el); setTimeout(() => el.remove(), 6000);
  }
  function clearMessages() { messagesEl.replaceChildren(); typingEl.hidden = true; input.value = ""; }

  // ----- messages -----
  function addMessage(who, text, ts) {
    const wrap = document.createElement("div"); wrap.className = `msg ${who}`;
    const bubble = document.createElement("div"); bubble.className = `bubble bubble-${who === "me" ? "me" : "them"}`;
    bubble.textContent = text;
    const time = document.createElement("time"); time.textContent = fmtTime(ts || Date.now());
    wrap.append(bubble, time); messagesEl.appendChild(wrap); scrollDown();
  }
  function addSystem(text) {
    const el = document.createElement("div"); el.className = "sys"; el.textContent = text;
    messagesEl.appendChild(el); scrollDown(); return el;
  }
  const scrollDown = () => (messagesEl.scrollTop = messagesEl.scrollHeight);
  function setComposer(enabled) { input.disabled = !enabled; sendBtn.disabled = !enabled; const t = $("#topic-btn"); if (t) t.disabled = !enabled; }

  function submitMessage() {
    const text = input.value.trim();
    if (!text || !peerPresent) return;
    send({ type: "message", text }); addMessage("me", text);
    input.value = ""; autoGrow(); stopTyping();
  }
  function autoGrow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; }

  // ----- typing -----
  function showTyping() { $("#typing-name").textContent = partner ? partner.nickname : "They"; typingEl.hidden = false; clearTimeout(typingOff); typingOff = setTimeout(hideTyping, 4000); }
  function hideTyping() { typingEl.hidden = true; clearTimeout(typingOff); }
  function stopTyping() { if (iTyping) { iTyping = false; send({ type: "typing", on: false }); } clearTimeout(stopTyping.t); }
  
  input.addEventListener("input", () => {
    autoGrow();
    if (!iTyping) { iTyping = true; send({ type: "typing", on: true }); }
    clearTimeout(stopTyping.t); stopTyping.t = setTimeout(stopTyping, 1500);
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitMessage(); } });
  sendBtn.addEventListener("click", submitMessage);

  // ----- actions -----
  function startSearch() {
    // FIX 4: Prevent double-clicking and spamming the matchmaker
    if (startBtn.disabled) return; 
    startBtn.disabled = true; 
    
    const mood = (document.querySelector('input[name="mood"]:checked') || {}).value;
    const interests = $("#interests").value.split(",").map((s) => s.trim()).filter(Boolean);
    send({ type: "find", mood, interests });
  }

  function findNext() { 
    const nextBtn = $("#next-btn");
    if (nextBtn && nextBtn.disabled) return; // Prevent spamming Next
    send({ type: "next" }); 
  }

  startBtn.addEventListener("click", startSearch);
  on("#cancel-btn", "click", () => send({ type: "end" }));
  on("#next-btn", "click", findNext);
  on("#end-btn", "click", () => send({ type: "end" }));
  on("#block-btn", "click", () => { if (confirm("Block this person? You won’t be matched again.")) send({ type: "block" }); });
  on("#topic-btn", "click", () => { input.value = pick(cfg.topics); autoGrow(); input.focus(); });
  on("#use-daily", "click", () => { startSearch(); const q = $(".daily-q").textContent; const once = (e) => { if (e.detail.type === "matched") { input.value = q; autoGrow(); document.removeEventListener("linkup:event", once); } }; document.addEventListener("linkup:event", once); });
  on("#report-submit", "click", () => {
    send({ type: "report", reason: $("#report-reason").value, details: $("#report-details").value });
    $("#report-details").value = "";
    const modal = $("#reportModal"); if (modal && window.bootstrap) bootstrap.Modal.getInstance(modal)?.hide();
  });

  // used by call.js (voice / video calls)
  window.LinkUpChat = { send, connected: () => !!ws && ws.readyState === 1, notice: addSystem };

  setComposer(false);
  connect();
})();