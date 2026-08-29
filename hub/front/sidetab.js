// sidebar collapse tab — a handle riding the sidebar's right edge.
// click toggles body.sidebar-collapsed; each page's css styles that state.
// phones (<=700px) start collapsed, bigger screens start expanded.
(function () {
  const sidebar = document.getElementById("sidebar");
  if (!sidebar) return;
  const tab = document.createElement("div");
  tab.id = "side-tab";
  const set = (collapsed) => {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    tab.textContent = collapsed ? "▶" : "◀";
  };
  tab.onclick = () => set(!document.body.classList.contains("sidebar-collapsed"));
  sidebar.appendChild(tab);
  set(window.matchMedia("(max-width: 700px)").matches);
})();
