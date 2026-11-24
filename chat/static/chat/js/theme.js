// Dark/light toggle. Only the theme preference is remembered.
document.getElementById("theme-toggle").addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-bs-theme", next);
    try { localStorage.setItem("linkup-theme", next); } catch (e) {}
  });