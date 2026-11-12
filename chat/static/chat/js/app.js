// Shared client code for signed-in pages: API helper, live socket, notifications, quick actions.
(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const LU = (window.LU = { csrf, handlers: [], ws: null });

  LU.api = async (url, body) => {
    const res = await fetch(url, {
      method: body === undefined ? "GET" : "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    return data;
  };
  LU.toast = (msg) => {
    const el = document.createElement("div");
    el.className = "lu-toast"; el.setAttribute("role", "status"); el.textContent = msg;
    document.body.appendChild(el); setTimeout(() => el.remove(), 3500);
  };
  LU.avatar = (p, big) => {
    if (p.photo_url) { const i = document.createElement("img"); i.className = "avatar" + (big ? " lg" : ""); i.src = p.photo_url; i.alt = ""; return i; }
    const s = document.createElement("span"); s.className = "avatar" + (big ? " lg" : ""); s.setAttribute("aria-hidden", "true");
    s.textContent = (p.nickname || "?").charAt(0).toUpperCase(); return s;
  };
  LU.time = (ts) => new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  LU.on = (fn) => LU.handlers.push(fn);

  // ---- live socket (private messages, presence, notifications) ----
  let delay = 1000;
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = (LU.ws = new WebSocket(`${proto}://${location.host}/ws/dm/`));
    ws.onopen = () => { delay = 1000; };
    ws.onmessage = (e) => { const m = JSON.parse(e.data); LU.handlers.forEach((h) => h(m)); };
    ws.onclose = (e) => { if (e.code !== 4401) { setTimeout(connect, delay); delay = Math.min(delay * 2, 15000); } };
  }
  LU.send = (obj) => LU.ws && LU.ws.readyState === 1 && LU.ws.send(JSON.stringify(obj));
  connect();

  // ---- notifications bell ----
  const badge = document.getElementById("bell-badge"), list = document.getElementById("notif-list");
  const setBadge = (n) => { badge.hidden = n <= 0; };
  function renderNotifs(items) {
    list.replaceChildren();
    if (!items.length) { list.innerHTML = '<div class="muted p-3">You’re all caught up.</div>'; return; }
    items.forEach((n) => {
      const a = document.createElement("a");
      a.className = "notif-item" + (n.read ? "" : " unread");
      a.href = n.type === "friend_request" ? "/friends/" : `/u/${n.from_uid}/`;
      a.textContent = n.text; list.appendChild(a);
    });
  }
  async function loadNotifs(markRead) {
    try {
      const { notifications } = await LU.api("/api/notifications/");
      renderNotifs(notifications);
      setBadge(notifications.filter((n) => !n.read).length);
      if (markRead) { await LU.api("/api/notifications/read/", {}); setBadge(0); }
    } catch (e) { /* ignore */ }
  }
  document.getElementById("bell-btn").addEventListener("show.bs.dropdown", () => loadNotifs(false));
  document.getElementById("bell-btn").addEventListener("hide.bs.dropdown", () => loadNotifs(true));
  loadNotifs(false);
  LU.on((m) => { if (m.type === "notification") { setBadge(1); LU.toast(m.notification.text); } });

  // ---- report modal + quick actions (data-action buttons) ----
  const reportModal = document.getElementById("reportModal");
  let reportUid = null;
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const uid = btn.dataset.uid, act = btn.dataset.action;
    try {
      if (act === "report" && reportModal) { reportUid = uid; bootstrap.Modal.getOrCreateInstance(reportModal).show(); }
      else if (act === "add") { await LU.api("/api/friends/request/", { uid }); location.reload(); }
      else if (act === "remove" && confirm("Remove this friend?")) { await LU.api("/api/friends/remove/", { uid }); location.reload(); }
      else if (act === "block" && confirm("Block this person? They won’t be able to contact you.")) { await LU.api("/api/block/", { uid }); location.href = "/friends/"; }
    } catch (err) { LU.toast(err.message); }
  });
  const submit = document.getElementById("report-submit");
  if (submit) submit.addEventListener("click", async () => {
    try {
      await LU.api("/api/report/", { uid: reportUid, reason: document.getElementById("report-reason").value, details: document.getElementById("report-details").value });
      bootstrap.Modal.getInstance(reportModal).hide(); LU.toast("Report sent. Thank you.");
      document.getElementById("report-details").value = "";
    } catch (err) { LU.toast(err.message); }
  });
})();
