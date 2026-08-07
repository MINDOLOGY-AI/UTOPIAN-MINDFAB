// === fab-store: per-board state, API, geometry ===
//
// Coordinates: root nodes store absolute world coords; children store coords
// relative to their parent folder (same layout as the backend). Consequences:
// - dragging a folder moves its whole subtree for free (children are relative)
// - a folder's rendered rect is ALWAYS anchored at its stored position:
//   children are packed inside via folderContentOffsets so the top-left-most
//   child sits at the pad corner. Moving children never re-anchors the folder.

class FabStore extends EventTarget {
  constructor(boardId) {
    super();
    this.boardId = boardId;
    this.nodes = {};
    this.edges = {};
    this.types = {doc_types: {}, edge_types: {}, state_colors: {}};
    this.camera = {x: 80, y: 80, zoom: 1};
    this.selectedNodeIds = new Set();
    this.activeFolderId = null;
    this.selectedEdgeId = null;
    this.edgeMode = null;
    this.tempOffsets = {};
    this.folderContentOffsets = {};
    this.dragging = null;
  }

  emit() { this.dispatchEvent(new CustomEvent("change")); }

  async api(method, path, body) {
    const opts = {method, headers: {"Content-Type": "application/json"}};
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(`boards/${this.boardId}${path}`, opts);
    if (!r.ok) {
      let detail = `${method} ${path} -> ${r.status}`;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return r.json();
  }

  async loadGraph() {
    const data = await this.api("GET", "/graph");
    this.nodes = data.nodes;
    this.edges = data.edges;
    // expansion sizes are render-time only; reset on load
    for (const n of Object.values(this.nodes)) {
      if (n.kind === "doc" && n.expanded) {
        n.width = FabStore.EXPANDED_W;
        n.height = FabStore.EXPANDED_H;
      }
    }
    this.emit();
  }

  graphSignature() {
    return JSON.stringify([this.nodes, this.edges]);
  }

  async createNode(props) {
    const node = await this.api("POST", "/nodes", props);
    this.nodes[node.id] = node;
    this.emit();
    return node;
  }

  async updateNode(id, updates) {
    const node = await this.api("PUT", `/nodes/${id}`, updates);
    Object.assign(this.nodes[id], node);
    this.emit();
    return node;
  }

  async deleteNode(id) {
    const res = await this.api("DELETE", `/nodes/${id}`);
    for (const nid of res.deleted) {
      delete this.nodes[nid];
      this.selectedNodeIds.delete(nid);
      if (this.activeFolderId === nid) this.activeFolderId = null;
    }
    for (const eid in this.edges) {
      const e = this.edges[eid];
      if (res.deleted.includes(e.source) || res.deleted.includes(e.target)) delete this.edges[eid];
    }
    this.emit();
    return res;
  }

  async getContent(id) { return this.api("GET", `/nodes/${id}/content`); }

  async putContent(id, content) { return this.api("PUT", `/nodes/${id}/content`, {content}); }

  async createEdge(source, target, edgeType) {
    const edge = await this.api("POST", "/edges", {source, target, edge_type: edgeType});
    this.edges[edge.id] = edge;
    this.emit();
    return edge;
  }

  async updateEdge(id, edgeType) {
    const edge = await this.api("PUT", `/edges/${id}`, {edge_type: edgeType});
    this.edges[id] = edge;
    this.emit();
    return edge;
  }

  async deleteEdge(id) {
    await this.api("DELETE", `/edges/${id}`);
    delete this.edges[id];
    if (this.selectedEdgeId === id) this.selectedEdgeId = null;
    this.emit();
  }

  async loadTypes() {
    const r = await fetch("types");
    this.types = await r.json();
    this.emit();
  }

  async saveTypes() {
    await fetch("types", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(this.types),
    });
    this.emit();
  }

  typeColor(node) {
    if (node.color) return node.color;
    return (this.types.doc_types[node.node_type] || {}).color || "#E2E8F0";
  }

  edgeColor(edge) {
    return (this.types.edge_types[edge.edge_type] || {}).color || "#ffffff";
  }

  // ---- geometry / layout ----

  isVisible(node) {
    let p = node.parent;
    while (p) {
      const par = this.nodes[p];
      if (!par) return true;
      if (!par.expanded) return false;
      p = par.parent;
    }
    return true;
  }

  isDescendantOf(id, ancestorId) {
    let p = this.nodes[id]?.parent;
    while (p) {
      if (p === ancestorId) return true;
      p = this.nodes[p]?.parent;
    }
    return false;
  }

  nodeDepth(node) {
    let d = 0;
    for (let p = node.parent; p; p = this.nodes[p]?.parent) d++;
    return d;
  }

  // world-space position: own coords + every ancestor's content offset and
  // coords + any push-aside offsets on the path up.
  renderPos(node) {
    const p = this.nodes[node.parent];
    let base;
    if (!p) {
      base = {x: node.x, y: node.y};
    } else {
      const coff = this.folderContentOffsets[p.id] || {dx: 0, dy: 0};
      const pp = this.renderPos(p);
      base = {x: pp.x + coff.dx + node.x, y: pp.y + coff.dy + node.y};
    }
    const off = this.tempOffsets[node.id];
    return off ? {x: base.x + off.dx, y: base.y + off.dy} : base;
  }

  nodeRect(node) {
    const p = this.renderPos(node);
    if (node.kind === "folder") {
      if (node.expanded) return this.folderBounds(node);
      const m = FabStore.MARGIN;
      const s = FabStore.COLLAPSED;
      return {x: p.x + m, y: p.y + m, w: s, h: s};
    }
    if (node.expanded) {
      const w = node.width || FabStore.EXPANDED_W;
      const h = node.height || FabStore.EXPANDED_H;
      const m = FabStore.MARGIN;
      return {x: p.x + m, y: p.y + m, w, h};
    }
    const m = FabStore.MARGIN;
    const s = FabStore.COLLAPSED;
    return {x: p.x + m, y: p.y + m, w: s, h: s};
  }

  collapsedRect(node) {
    const p = this.renderPos(node);
    const m = FabStore.MARGIN;
    const s = FabStore.COLLAPSED;
    return {x: p.x + m, y: p.y + m, w: s, h: s};
  }

  gridRect(node) {
    // grid-aligned bounding box (used for folder bounds and overlap checks)
    const p = this.renderPos(node);
    const G = FabStore.GRID;
    if (node.kind === "folder") {
      if (node.expanded) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const n of Object.values(this.nodes)) {
          if (n.parent !== node.id) continue;
          const r = this.gridRect(n);
          minX = Math.min(minX, r.x);
          minY = Math.min(minY, r.y);
          maxX = Math.max(maxX, r.x + r.w);
          maxY = Math.max(maxY, r.y + r.h);
        }
        if (minX === Infinity) return {x: p.x, y: p.y, w: G, h: G};
        return {x: minX, y: minY, w: maxX - minX, h: maxY - minY};
      }
      return {x: p.x, y: p.y, w: G, h: G};
    }
    let w, h;
    if (node.expanded) {
      w = Math.ceil((node.width || FabStore.EXPANDED_W) / G) * G;
      h = Math.ceil((node.height || FabStore.EXPANDED_H) / G) * G;
    } else { w = G; h = G; }
    return {x: p.x, y: p.y, w, h};
  }

  folderBounds(folder) {
    // expanded folder engulfs its children. children are grid-aligned and the
    // title floats above the frame, so the frame needs NO padding — its edges
    // land exactly on grid lines and never bleed into adjacent cells
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of Object.values(this.nodes)) {
      if (n.parent !== folder.id) continue;
      const r = this.gridRect(n);
      minX = Math.min(minX, r.x);
      minY = Math.min(minY, r.y);
      maxX = Math.max(maxX, r.x + r.w);
      maxY = Math.max(maxY, r.y + r.h);
    }
    if (minX === Infinity) {
      // empty folder: exactly its one home cell
      const p = this.renderPos(folder);
      return {x: p.x, y: p.y, w: FabStore.GRID, h: FabStore.GRID};
    }
    return {x: minX, y: minY, w: maxX - minX, h: maxY - minY};
  }

  nodeCenter(node) {
    const r = this.nodeRect(node);
    return {x: r.x + r.w / 2, y: r.y + r.h / 2};
  }

  computeFolderContentOffsets() {
    // pack each expanded folder's children so the top-left-most child sits at
    // the folder's stored position. NO padding here — padding belongs to the
    // folder's border only; children stay grid-aligned and centered in their
    // cells. a directly-dragged child keeps its pre-drag spot here so the
    // folder doesn't chase it around mid-drag.
    this.folderContentOffsets = {};
    const drag = this.dragging;
    for (const folder of Object.values(this.nodes)) {
      if (folder.kind !== "folder" || !folder.expanded) continue;
      let minX = Infinity, minY = Infinity;
      for (const n of Object.values(this.nodes)) {
        if (n.parent !== folder.id) continue;
        const x = (drag && n.id === drag.nodeId) ? drag.origX : n.x;
        const y = (drag && n.id === drag.nodeId) ? drag.origY : n.y;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
      }
      if (minX === Infinity) continue;
      this.folderContentOffsets[folder.id] = {dx: -minX, dy: -minY};
    }
  }

  applyTempOffset(id, dx, dy) {
    if (!this.tempOffsets[id]) this.tempOffsets[id] = {dx: 0, dy: 0};
    this.tempOffsets[id].dx += dx;
    this.tempOffsets[id].dy += dy;
  }

  folderTitleLadder() {
    // expanded folder titles float above the frame line. folders whose frames
    // share the exact same top-left corner pixel (nested or aligned) would
    // pile their titles onto each other, so within a shared corner each level
    // gets a step: the DEEPEST folder sits right above the line (step 0),
    // each outer level one step higher. lone folders are untouched (step 0).
    const ladder = {};
    const groups = new Map();
    for (const n of Object.values(this.nodes)) {
      if (n.kind !== "folder" || !n.expanded || !this.isVisible(n)) continue;
      const r = this.nodeRect(n);
      const key = `${Math.round(r.x)},${Math.round(r.y)}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    }
    for (const group of groups.values()) {
      if (group.length < 2) continue;
      group.sort((a, b) => this.nodeDepth(b) - this.nodeDepth(a));
      group.forEach((n, i) => { ladder[n.id] = i; });
    }
    return ladder;
  }

  resolveCollisions() {
    // grid-stretch shifts: an expanded node claims extra room past its home
    // cell. every sibling at/past the cell's right edge shifts right by the
    // extra width; every sibling at/past the bottom edge shifts down by the
    // extra height; corner siblings get both. amounts are EXACT pixels (no
    // grid rounding) so grip-resizes glide; offsets recompute fresh every
    // render, so collapsing or shrinking back restores the grid exactly.
    this.tempOffsets = {};
    const visible = Object.values(this.nodes).filter(n => this.isVisible(n));
    // deepest first: inner shifts settle before outer folders read bounds
    const expanded = visible.filter(n => n.expanded).sort((a, b) => {
      const da = this.nodeDepth(a), db = this.nodeDepth(b);
      if (da !== db) return db - da;
      if (a.y !== b.y) return a.y - b.y;
      return a.x - b.x;
    });
    const G = FabStore.GRID, M = FabStore.MARGIN;
    for (const a of expanded) {
      const p = this.renderPos(a);
      // full visual footprint (node + its margins) measured from the home cell
      let fw, fh;
      if (a.kind === "folder") {
        const b = this.folderBounds(a);
        fw = b.x + b.w - p.x;
        fh = b.y + b.h - p.y;
      } else {
        fw = M + (a.width || FabStore.EXPANDED_W) + M;
        fh = M + (a.height || FabStore.EXPANDED_H) + M;
      }
      const dW = fw - G, dH = fh - G;
      if (dW <= 0 && dH <= 0) continue;
      const right = p.x + G, bottom = p.y + G;
      for (const b of visible) {
        if (b.id === a.id || b.parent !== a.parent) continue;
        const br = this.gridRect(b);
        if (dW > 0 && br.x >= right) this.applyTempOffset(b.id, dW, 0);
        if (dH > 0 && br.y >= bottom) this.applyTempOffset(b.id, 0, dH);
      }
    }
  }

  resolveOverlap(candidates, excludeIds = new Set()) {
    // candidates: node-like objects with x, y, kind, parent, expanded, width, height.
    // shifts them down by grid multiples until no overlap with siblings.
    const G = FabStore.GRID;
    const parents = new Set(candidates.map(n => n.parent));
    const siblings = Object.values(this.nodes).filter(
      n => !excludeIds.has(n.id) && parents.has(n.parent) && this.isVisible(n)
    );
    let offset = 0;
    while (true) {
      for (const n of candidates) n.y += offset;
      let overlap = false;
      for (const n of candidates) {
        const r = this.gridRect(n);
        for (const sib of siblings) {
          const sr = this.gridRect(sib);
          if (r.x < sr.x + sr.w && r.x + r.w > sr.x && r.y < sr.y + sr.h && r.y + r.h > sr.y) {
            overlap = true;
            break;
          }
        }
        if (overlap) break;
      }
      for (const n of candidates) n.y -= offset;
      if (!overlap) {
        for (const n of candidates) n.y += offset;
        return candidates;
      }
      offset += G;
    }
  }

  // does node id, at its current coords, overlap any sibling (same parent)?
  overlapsSiblings(id) {
    const node = this.nodes[id];
    if (!node) return false;
    const r = this.gridRect(node);
    for (const sib of Object.values(this.nodes)) {
      if (sib.id === id || sib.parent !== node.parent) continue;
      if (!this.isVisible(sib)) continue;
      const sr = this.gridRect(sib);
      if (r.x < sr.x + sr.w && r.x + r.w > sr.x && r.y < sr.y + sr.h && r.y + r.h > sr.y) return true;
    }
    return false;
  }

  // probe: would node id overlap a sibling if placed at (x, y, parent)?
  // temporarily moves the node to find out, then restores it.
  wouldOverlap(id, x, y, parent) {
    const n = this.nodes[id];
    const ox = n.x, oy = n.y, op = n.parent;
    n.x = x; n.y = y; n.parent = parent;
    this.computeFolderContentOffsets();
    const hit = this.overlapsSiblings(id);
    n.x = ox; n.y = oy; n.parent = op;
    this.computeFolderContentOffsets();
    return hit;
  }

  freePositionNear(x, y) {
    const G = FabStore.GRID;
    let cx = Math.round(x / G), cy = Math.round(y / G);
    const taken = new Set(Object.values(this.nodes)
      .filter(n => n.parent === null)
      .map(n => `${Math.round(n.x / G)},${Math.round(n.y / G)}`));
    while (taken.has(`${cx},${cy}`)) cy += 1;
    return {x: cx * G, y: cy * G};
  }

  freeChildPosition(folder) {
    // folder-relative coords for a new child, grid-aligned from the origin
    const G = FabStore.GRID;
    let x = 0, y = 0;
    const taken = new Set(Object.values(this.nodes)
      .filter(n => n.parent === folder.id)
      .map(n => `${Math.round(n.x / G)},${Math.round(n.y / G)}`));
    while (taken.has(`${Math.round(x / G)},${Math.round(y / G)}`)) y += G;
    return {x, y};
  }
}

FabStore.GRID = 200;
FabStore.MARGIN = 20;
FabStore.COLLAPSED = 160;
FabStore.EXPANDED_W = 560;
FabStore.EXPANDED_H = 360;
FabStore.MIN_EXPANDED_W = 360; // 2 grid cells minus margins
FabStore.MIN_EXPANDED_H = 160; // 1 grid cell minus margins
FabStore.ESCAPE_MARGIN = 80;
FabStore.ZOOM_MIN = 0.02;
FabStore.ZOOM_MAX = 5;
FabStore.ZOOM_STEP = 0.1;  // additive step — one wheel notch moves the same amount at every zoom
FabStore.snap = v => Math.round(v / FabStore.GRID) * FabStore.GRID;

if (typeof module !== "undefined") module.exports = {FabStore};
