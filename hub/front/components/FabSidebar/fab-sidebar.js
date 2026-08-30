// fab-sidebar — shared sidebar chrome: hub chip + collapse tab + toggle logic.
// usage: <fab-sidebar id="sidebar"> ...page's sidebar content... </fab-sidebar>
// page css provides: body { --sbw } and the body.sidebar-collapsed #sidebar rule.
class FabSidebar extends HTMLElement {
  connectedCallback() {
    // collapse tab: fixed button right of the hub chip, slides to the screen corner on collapse
    const tab = document.createElement("div");
    tab.id = "side-tab";
    const set = (collapsed) => {
      document.body.classList.toggle("sidebar-collapsed", collapsed);
      tab.textContent = collapsed ? "▶" : "◀";
    };
    tab.onclick = () => set(!document.body.classList.contains("sidebar-collapsed"));
    document.body.appendChild(tab);
    const home = document.createElement("a");
    home.id = "home";
    home.href = "/";
    home.textContent = "hub";
    this.prepend(home);
    // phones start collapsed, bigger screens start expanded
    set(window.matchMedia("(max-width: 700px)").matches);
  }
}
customElements.define("fab-sidebar", FabSidebar);
