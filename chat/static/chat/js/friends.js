(() => {
  const $ = (s) => document.querySelector(s);
  const friendsEl = $("#friends-list"), inEl = $("#incoming-list"), outEl = $("#outgoing-list"), resEl = $("#search-results");

  function person(p, buttons) {
    const row = document.createElement("div"); row.className = "person";
    row.appendChild(LU.avatar(p));
    const info = document.createElement("div"); info.className = "grow min-w-0";
    const name = document.createElement("a"); name.className = "fw-semibold"; name.href = `/u/${p.uid}/`; name.textContent = p.nickname;
    if (p.online !== undefined) { const d = document.createElement("span"); d.className = "dot ms-2" + (p.online ? " on" : ""); d.title = p.online ? "Online" : "Offline"; name.after(d); }
    info.appendChild(name);
    if (p.full && p.interests && p.interests.length) { const t = document.createElement("div"); t.className = "muted small text-truncate"; t.textContent = p.interests.join(", "); info.appendChild(t); }
    row.appendChild(info);
    const actions = document.createElement("div"); actions.className = "d-flex gap-2";
    buttons.forEach(([label, cls, fn]) => { const b = document.createElement("button"); b.type = "button"; b.className = `btn btn-sm ${cls}`; b.textContent = label; if (fn) b.onclick = fn; else b.disabled = true; actions.appendChild(b); });
    row.appendChild(actions); return row;
  }
  const empty = (el, text) => { el.replaceChildren(Object.assign(document.createElement("div"), { className: "empty-lu", innerHTML: `<p>${text}</p>` })); };
  const act = async (fn) => { try { await fn(); await load(); const q = $("#search-input").value; if (q.trim().length >= 2) search(q); } catch (e) { LU.toast(e.message); } };

  async function load() {
    const d = await LU.api("/api/friends/");
    $("#n-friends").textContent = d.friends.length ? `(${d.friends.length})` : "";
    const nr = $("#n-requests"); nr.textContent = d.incoming.length; nr.hidden = !d.incoming.length;
    friendsEl.replaceChildren(...d.friends.map((p) => person(p, [
      ["Message", "btn-accent", () => (location.href = `/messages/?with=${p.uid}`)],
      ["Remove", "btn-outline-secondary", () => confirm(`Remove ${p.nickname}?`) && act(() => LU.api("/api/friends/remove/", { uid: p.uid }))],
    ])));
    if (!d.friends.length) empty(friendsEl, "No friends yet. Use “Find people” to search by nickname.");
    inEl.replaceChildren(...d.incoming.map((r) => person(r.profile, [
      ["Accept", "btn-accent", () => act(() => LU.api("/api/friends/respond/", { request_id: r.request_id, accept: true }))],
      ["Decline", "btn-outline-secondary", () => act(() => LU.api("/api/friends/respond/", { request_id: r.request_id, accept: false }))],
    ])));
    if (!d.incoming.length) empty(inEl, "No pending requests.");
    outEl.replaceChildren(...d.outgoing.map((r) => person(r.profile, [["Pending", "btn-outline-secondary", null]])));
    if (!d.outgoing.length) empty(outEl, "You haven’t sent any requests.");
  }

  async function search(q) {
    try {
      const { results } = await LU.api(`/api/users/search/?q=${encodeURIComponent(q)}`);
      if (!results.length) { empty(resEl, "No one found with that nickname."); return; }
      resEl.replaceChildren(...results.map((p) => {
        const rel = p.relationship;
        const btns = rel === "friends" ? [["Message", "btn-accent", () => (location.href = `/messages/?with=${p.uid}`)]]
          : rel === "request_sent" ? [["Request sent", "btn-outline-secondary", null]]
          : [[rel === "request_received" ? "Accept" : "Add friend", "btn-accent", () => act(() => LU.api("/api/friends/request/", { uid: p.uid }))]];
        return person(p, btns);
      }));
    } catch (e) { LU.toast(e.message); }
  }
  let t; $("#search-input").addEventListener("input", (e) => { clearTimeout(t); const q = e.target.value.trim(); if (q.length < 2) { resEl.replaceChildren(); return; } t = setTimeout(() => search(q), 300); });
  LU.on((m) => { if (m.type === "notification" || m.type === "presence" || m.type === "friend_removed") load(); });
  load();
})();
