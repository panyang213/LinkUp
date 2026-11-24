const modalEl = document.getElementById("enterModal");
if (modalEl && modalEl.dataset.autoOpen) new bootstrap.Modal(modalEl).show();
if (modalEl) modalEl.addEventListener("shown.bs.modal", () => document.getElementById("id_nickname").focus());

async function refreshOnline() {
  try {
    const res = await fetch("/api/online/", { cache: "no-store" });
    const { count } = await res.json();
    document.querySelectorAll("[data-online-count]").forEach(el => (el.textContent = count));
  } catch (e) { /* ignore */ }
}
setInterval(refreshOnline, 15000);