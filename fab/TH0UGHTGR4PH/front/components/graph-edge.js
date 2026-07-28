// === graph-edge: manages an SVG edge group (Manhattan polyline) ===

const NS = "http://www.w3.org/2000/svg";

class GraphEdge {
  constructor(board, edge) {
    this.board = board;
    this.edge = edge;
    this.g = document.createElementNS(NS, "g");
    this.g.dataset.id = edge.id;
    this.g.style.cursor = "pointer";

    this.hit = document.createElementNS(NS, "polyline");
    this.hit.setAttribute("stroke", "transparent");
    this.hit.setAttribute("stroke-width", "20");
    this.hit.setAttribute("fill", "none");
    this.hit.setAttribute("pointer-events", "stroke");
    this.hit.style.cursor = "pointer";

    this.outline = document.createElementNS(NS, "polyline");
    this.outline.setAttribute("stroke", "#00FF41");
    this.outline.setAttribute("stroke-width", "12");
    this.outline.setAttribute("stroke-linecap", "round");
    this.outline.setAttribute("stroke-linejoin", "round");
    this.outline.setAttribute("fill", "none");
    this.outline.setAttribute("pointer-events", "none");
    this.outline.style.opacity = "0";

    this.line = document.createElementNS(NS, "polyline");
    this.line.setAttribute("stroke-linecap", "round");
    this.line.setAttribute("stroke-linejoin", "round");
    this.line.setAttribute("fill", "none");
    this.line.setAttribute("pointer-events", "stroke");
    this.line.style.cursor = "pointer";

    this.g.appendChild(this.hit);
    this.g.appendChild(this.outline);
    this.g.appendChild(this.line);
    const select = (e) => { e.stopPropagation(); this.board.selectEdge(this.edge.id); };
    this.hit.addEventListener("mousedown", select);
    this.hit.addEventListener("click", select);
    this.line.addEventListener("mousedown", select);
    this.line.addEventListener("click", select);
    board.svg.appendChild(this.g);
  }

  remove() {
    this.g.remove();
  }

  update() {
    const store = this.board.store;
    const s = store.nodes[this.edge.source];
    const t = store.nodes[this.edge.target];
    if (!s || !t) return;

    const points = this.board.router.route(this.edge);
    if (!points || points.length < 2) return;

    const ptsStr = points.map(p => `${p.x},${p.y}`).join(" ");
    this.hit.setAttribute("points", ptsStr);
    this.outline.setAttribute("points", ptsStr);
    this.line.setAttribute("points", ptsStr);

    const color = GraphStore.EDGE_COLORS[this.edge.color] || this.edge.color;
    this.line.setAttribute("stroke", color);
    this.line.setAttribute("marker-end", `url(#${this.ensureArrowMarker(color)})`);

    const connected = store.selectedNodeId &&
      (this.edge.source === store.selectedNodeId || this.edge.target === store.selectedNodeId);
    const selected = this.edge.id === store.selectedEdgeId;
    this.line.setAttribute("stroke-width", connected ? 4 : 2);
    this.line.setAttribute("stroke-opacity", selected || connected ? 1 : 0.55);
    this.outline.style.opacity = selected ? "0.9" : "0";
  }

  ensureArrowMarker(color) {
    const safeId = "arrow-" + color.replace(/[^a-zA-Z0-9]/g, "");
    let marker = this.board.svg.querySelector(`#${safeId}`);
    if (marker) return safeId;

    const NS = "http://www.w3.org/2000/svg";
    marker = document.createElementNS(NS, "marker");
    marker.setAttribute("id", safeId);
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "9");
    marker.setAttribute("refY", "5");
    marker.setAttribute("markerUnits", "userSpaceOnUse");
    marker.setAttribute("markerWidth", "14");
    marker.setAttribute("markerHeight", "14");
    marker.setAttribute("orient", "auto");

    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", "M0,0 L10,5 L0,10 z");
    path.setAttribute("fill", color);
    marker.appendChild(path);

    this.board.svg.querySelector("defs").appendChild(marker);
    return safeId;
  }

  onClick(e) {
    e.stopPropagation();
    this.board.selectEdge(this.edge.id);
  }
}
