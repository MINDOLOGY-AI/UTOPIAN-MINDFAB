// === fab-store: per-board state, API, geometry ===

class FabStore extends EventTarget {
  constructor(boardId) {
    super();
    this.boardId = boardId;
    this.nodes = {};
    this.edges = {};
    this.types = {obj_types: {}, func_types: {}, state_colors: {}};
    this.camera = {x: 80, y: 80, zoom: 1};
    this.selectedNodeIds = new Set();
    this.selectedEdgeId = null;
    this.edgeMode = null;
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
    this.nodes[id] = node;
    this.emit();
    return node;
  }

  async deleteNode(id) {
    const res = await this.api("DELETE", `/nodes/${id}`);
    for (const nid of res.deleted) {
      delete this.nodes[nid];
      this.selectedNodeIds.delete(nid);
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

  async createEdge(source, target) {
    const edge = await this.api("POST", "/edges", {source, target});
    this.edges[edge.id] = edge;
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
    const reg = node.kind === "func" ? this.types.func_types : this.types.obj_types;
    return (reg[node.node_type] || {}).color || "#E2E8F0";
  }

  // ---- geometry ----

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

  descendants(id) {
    const out = [];
    const stack = [id];
    while (stack.length) {
      const cur = stack.pop();
      for (const n of Object.values(this.nodes)) {
        if (n.parent === cur) { out.push(n.id); stack.push(n.id); }
      }
    }
    return out;
  }

  // ---- expansion push-aside (ported from TH0UGHTGR4PH graph-store) ----
  // expanding a node shifts everything below it down by the height increase and
  // everything right of it right by the width increase, instead of covering them.
  // offsets are render-time only — saved positions are never rewritten.

  addOffset(id, dx, dy) {
    if (!this.tempOffsets[id]) this.tempOffsets[id] = {dx: 0, dy: 0};
    this.tempOffsets[id].dx += dx;
    this.tempOffsets[id].dy += dy;
  }

  nodeDepth(node) {
    let d = 0;
    for (let p = node.parent; p; p = this.nodes[p]?.parent) d++;
    return d;
  }

  computeTempOffsets() {
    this.tempOffsets = {};
    const visible = Object.values(this.nodes).filter(n => this.isVisible(n));
    const G = FabStore.GRID;
    // deepest first, then top-left — earlier expanders stay put while later ones make room
    const expanded = visible.filter(n => n.expanded).sort((a, b) => {
      const da = this.nodeDepth(a), db = this.nodeDepth(b);
      if (da !== db) return db - da;
      if (a.y !== b.y) return a.y - b.y;
      return a.x - b.x;
    });
    for (const a of expanded) {
      const after = this.gridRect(a);
      const dW = Math.ceil((after.w - G) / G) * G;
      const dH = Math.ceil((after.h - G) / G) * G;
      if (dW === 0 && dH === 0) continue;
      const oldRight = a.x + G;
      const oldBottom = a.y + G;
      for (const b of visible) {
        if (b.id === a.id || b.parent !== a.parent) continue;
        if (this.isDescendantOf(b.id, a.id)) continue;
        if (dH !== 0 && b.y >= oldBottom) this.addOffset(b.id, 0, dH);
        if (dW !== 0 && b.x >= oldRight) this.addOffset(b.id, dW, 0);
      }
    }
  }

  renderPos(node) {
    let dx = 0, dy = 0;
    let cur = node;
    while (cur) {
      const off = (this.tempOffsets || {})[cur.id];
      if (off) { dx += off.dx; dy += off.dy; }
      cur = cur.parent ? this.nodes[cur.parent] : null;
    }
    return {x: node.x + dx, y: node.y + dy};
  }

  nodeRect(node) {
    const G = FabStore.GRID, M = FabStore.MARGIN;
    const p = this.renderPos(node);
    if (node.kind === "folder") {
      if (node.expanded) return this.folderBounds(node);
      return {x: p.x + M, y: p.y + M, w: FabStore.COLLAPSED, h: FabStore.COLLAPSED};
    }
    if (node.kind === "func") {
      const s = FabStore.FUNC_SIZE;
      return {x: p.x + G / 2 - s / 2, y: p.y + G / 2 - s / 2, w: s, h: s};
    }
    if (node.expanded) {
      return {x: p.x + M, y: p.y + M, w: node.width || FabStore.EXPANDED_W, h: node.height || FabStore.EXPANDED_H};
    }
    return {x: p.x + M, y: p.y + M, w: FabStore.COLLAPSED, h: FabStore.COLLAPSED};
  }

  gridRect(node) {
    const G = FabStore.GRID;
    const p = this.renderPos(node);
    if (node.kind === "folder" && node.expanded) return this.folderBounds(node);
    if (node.kind === "obj" && node.expanded) {
      return {
        x: p.x, y: p.y,
        w: Math.ceil((node.width || FabStore.EXPANDED_W) / G) * G,
        h: Math.ceil((node.height || FabStore.EXPANDED_H) / G) * G,
      };
    }
    return {x: p.x, y: p.y, w: G, h: G};
  }

  folderBounds(folder) {
    const kids = Object.values(this.nodes).filter(n => n.parent === folder.id);
    if (!kids.length) {
      return {x: folder.x, y: folder.y, w: FabStore.GRID, h: FabStore.GRID};
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const k of kids) {
      const r = this.gridRect(k);
      minX = Math.min(minX, r.x); minY = Math.min(minY, r.y);
      maxX = Math.max(maxX, r.x + r.w); maxY = Math.max(maxY, r.y + r.h);
    }
    const P = FabStore.FOLDER_PAD;
    return {x: minX - P.left, y: minY - P.top, w: maxX - minX + P.left + P.right, h: maxY - minY + P.top + P.bottom};
  }

  nodeCenter(node) {
    const r = this.nodeRect(node);
    return {x: r.x + r.w / 2, y: r.y + r.h / 2};
  }

  freePositionNear(x, y) {
    // first grid cell at-or-after (x, y) whose footprint doesn't overlap existing nodes
    const G = FabStore.GRID;
    let cx = Math.round(x / G), cy = Math.round(y / G);
    const taken = new Set(Object.values(this.nodes).map(n => `${Math.round(n.x / G)},${Math.round(n.y / G)}`));
    while (taken.has(`${cx},${cy}`)) cy += 1;
    return {x: cx * G, y: cy * G};
  }
}

FabStore.GRID = 200;
FabStore.MARGIN = 20;
FabStore.COLLAPSED = 160;
FabStore.FUNC_SIZE = 80;
FabStore.EXPANDED_W = 560;
FabStore.EXPANDED_H = 360;
FabStore.FOLDER_PAD = {left: 12, top: 44, right: 12, bottom: 12};
FabStore.ZOOM_LEVELS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];
FabStore.snap = v => Math.round(v / FabStore.GRID) * FabStore.GRID;
