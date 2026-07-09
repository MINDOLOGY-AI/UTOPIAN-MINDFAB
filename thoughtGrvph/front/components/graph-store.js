// === graph-store: per-board state, API, geometry, layout ===

class GraphStore extends EventTarget {
  constructor(boardId) {
    super();
    this.boardId = boardId;
    this.nodes = {};
    this.edges = {};
    this.camera = {x: 80, y: 80, zoom: 1};
    this.selectedNodeId = null;
    this.selectedEdgeId = null;
    this.edgeMode = null;
    this.tempOffsets = {};
    this.folderContentOffsets = {};
    this.dragging = null;
  }

  async api(method, path, body) {
    const opts = {method, headers: {"Content-Type": "application/json"}};
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(`boards/${this.boardId}${path}`, opts);
    if (!r.ok) throw new Error(`${method} ${path} -> ${r.status}`);
    return r.json();
  }

  async loadGraph() {
    const data = await this.api("GET", "/graph");
    this.nodes = data.nodes;
    this.edges = data.edges;
    // expansion sizes are temporary; reset on load
    for (const n of Object.values(this.nodes)) {
      if (n.type === "file" && n.expanded) {
        n.width = GraphStore.DEFAULT_DOC_EXPANDED.w;
        n.height = GraphStore.DEFAULT_DOC_EXPANDED.h;
      }
    }
    this.dispatchEvent(new CustomEvent("load"));
    this.dispatchEvent(new CustomEvent("change"));
  }

  async createNode({title, type, parent, x, y}) {
    const node = await this.api("POST", "/nodes", {title, type, parent, x, y});
    this.nodes[node.id] = node;
    this.dispatchEvent(new CustomEvent("change"));
    return node;
  }

  async updateNode(id, updates) {
    const node = await this.api("PUT", `/nodes/${id}`, updates);
    Object.assign(this.nodes[id], node);
    this.dispatchEvent(new CustomEvent("change"));
    return node;
  }

  async updateNodePositions(updates) {
    // updates: [{id, x, y}, ...]
    for (const u of updates) {
      await this.api("PUT", `/nodes/${u.id}`, {x: u.x, y: u.y});
      Object.assign(this.nodes[u.id], {x: u.x, y: u.y});
    }
    this.dispatchEvent(new CustomEvent("change"));
  }

  async deleteNode(id) {
    await this.api("DELETE", `/nodes/${id}`);
    const toDelete = new Set();
    const stack = [id];
    while (stack.length) {
      const cur = stack.pop();
      toDelete.add(cur);
      for (const n of Object.values(this.nodes)) {
        if (n.parent === cur && !toDelete.has(n.id)) stack.push(n.id);
      }
    }
    for (const nid of toDelete) delete this.nodes[nid];
    for (const eid in this.edges) {
      const e = this.edges[eid];
      if (toDelete.has(e.source) || toDelete.has(e.target)) delete this.edges[eid];
    }
    if (this.selectedNodeId === id || toDelete.has(this.selectedNodeId)) this.selectedNodeId = null;
    this.dispatchEvent(new CustomEvent("change"));
  }

  async getContent(id) {
    return this.api("GET", `/nodes/${id}/content`);
  }

  async putContent(id, content) {
    const res = await this.api("PUT", `/nodes/${id}/content`, {content});
    Object.assign(this.edges, res.edges);
    this.dispatchEvent(new CustomEvent("change"));
    return res;
  }

  async createEdge(source, target) {
    const edge = await this.api("POST", "/edges", {source, target});
    this.edges[edge.id] = edge;
    this.dispatchEvent(new CustomEvent("change"));
    return edge;
  }

  async updateEdge(id, color) {
    const edge = await this.api("PUT", `/edges/${id}`, {color});
    this.edges[id].color = edge.color;
    this.dispatchEvent(new CustomEvent("change"));
  }

  async deleteEdge(id) {
    await this.api("DELETE", `/edges/${id}`);
    delete this.edges[id];
    if (this.selectedEdgeId === id) this.selectedEdgeId = null;
    this.dispatchEvent(new CustomEvent("change"));
  }

  async listVersions() {
    const data = await this.api("GET", "/versions");
    return data.versions;
  }

  async saveVersion() {
    const data = await this.api("POST", "/versions");
    return data.name;
  }

  async deleteVersion(name) {
    await this.api("DELETE", `/versions/${name}`);
  }

  async restoreVersion(name) {
    await this.api("POST", `/versions/${name}/restore`);
    await this.loadGraph();
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

  ancestorOffset(node) {
    let dx = 0, dy = 0;
    let cur = node;
    while (cur) {
      const off = this.tempOffsets[cur.id];
      if (off) { dx += off.dx; dy += off.dy; }
      cur = cur.parent ? this.nodes[cur.parent] : null;
    }
    return {dx, dy};
  }

  folderContentOffset(node) {
    let dx = 0, dy = 0;
    let cur = node.parent ? this.nodes[node.parent] : null;
    while (cur) {
      const off = this.folderContentOffsets[cur.id];
      if (off) { dx += off.dx; dy += off.dy; }
      cur = cur.parent ? this.nodes[cur.parent] : null;
    }
    return {dx, dy};
  }

  renderPos(node) {
    const off = this.ancestorOffset(node);
    const foff = this.folderContentOffset(node);
    return {x: node.x + off.dx + foff.dx, y: node.y + off.dy + foff.dy};
  }

  nodeRect(node) {
    const p = this.renderPos(node);
    if (node.type === "folder") {
      if (node.expanded) return this.folderBounds(node);
      const m = GraphStore.NODE_MARGIN;
      const s = GraphStore.COLLAPSED_FOLDER_SIZE;
      return {x: p.x + m, y: p.y + m, w: s.w, h: s.h};
    }
    if (node.expanded) {
      const w = node.width || GraphStore.DEFAULT_DOC_EXPANDED.w;
      const h = node.height || GraphStore.DEFAULT_DOC_EXPANDED.h;
      const m = GraphStore.NODE_MARGIN;
      return {x: p.x + m, y: p.y + m, w, h};
    }
    const m = GraphStore.NODE_MARGIN;
    const s = GraphStore.COLLAPSED_FILE_SIZE;
    return {x: p.x + m, y: p.y + m, w: s.w, h: s.h};
  }

  collapsedRect(node) {
    const p = this.renderPos(node);
    const sz = node.type === "folder" ? GraphStore.COLLAPSED_FOLDER_SIZE : GraphStore.COLLAPSED_FILE_SIZE;
    const m = GraphStore.NODE_MARGIN;
    return {x: p.x + m, y: p.y + m, w: sz.w, h: sz.h};
  }

  naturalRect(node) {
    if (node.type === "folder") {
      if (node.expanded) return this.folderBounds(node);
      return this.collapsedRect(node);
    }
    if (node.expanded) {
      const p = this.renderPos(node);
      const w = node.width || GraphStore.DEFAULT_DOC_EXPANDED.w;
      const h = node.height || GraphStore.DEFAULT_DOC_EXPANDED.h;
      const m = GraphStore.NODE_MARGIN;
      return {x: p.x + m, y: p.y + m, w, h};
    }
    return this.collapsedRect(node);
  }

  gridRect(node) {
    // grid-aligned bounding box of a node (used for folder bounds and overlap checks)
    const p = this.renderPos(node);
    const G = GraphStore.GRID_SIZE;
    if (node.type === "folder") {
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
      w = Math.ceil((node.width || GraphStore.DEFAULT_DOC_EXPANDED.w) / G) * G;
      h = Math.ceil((node.height || GraphStore.DEFAULT_DOC_EXPANDED.h) / G) * G;
    } else {
      w = G; h = G;
    }
    return {x: p.x, y: p.y, w, h};
  }

  folderBounds(folder) {
    // expanded folder engulfs the grid-aligned bounds of its children (no extra padding)
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
      const off = this.ancestorOffset(folder);
      const foff = this.folderContentOffset(folder);
      return {
        x: folder.x + off.dx + foff.dx,
        y: folder.y + off.dy + foff.dy,
        w: GraphStore.EMPTY_FOLDER_SIZE.w,
        h: GraphStore.EMPTY_FOLDER_SIZE.h,
      };
    }
    return {
      x: minX - GraphStore.FOLDER_PAD.left,
      y: minY - GraphStore.FOLDER_PAD.top,
      w: maxX - minX + GraphStore.FOLDER_PAD.left + GraphStore.FOLDER_PAD.right,
      h: maxY - minY + GraphStore.FOLDER_PAD.top + GraphStore.FOLDER_PAD.bottom,
    };
  }

  nodeCenter(node) {
    const r = this.nodeRect(node);
    return {x: r.x + r.w / 2, y: r.y + r.h / 2};
  }

  clipToBoundary(node, towardX, towardY) {
    const r = this.nodeRect(node);
    const halfW = r.w / 2, halfH = r.h / 2;
    const cx = r.x + halfW, cy = r.y + halfH;
    const dx = towardX - cx, dy = towardY - cy;
    if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) return {x: cx, y: cy};
    let t;
    if (node.type === "folder" && !node.expanded) {
      t = 1 / Math.sqrt(dx * dx / (halfW * halfW) + dy * dy / (halfH * halfH));
    } else {
      t = Math.min(
        Math.abs(dx) > 1e-6 ? halfW / Math.abs(dx) : Infinity,
        Math.abs(dy) > 1e-6 ? halfH / Math.abs(dy) : Infinity
      );
    }
    const clamped = Math.min(t, 1);
    return {x: cx + clamped * dx, y: cy + clamped * dy};
  }

  computeFolderContentOffsets() {
    this.folderContentOffsets = {};
    const draggedId = this.dragging?.nodeId;
    const draggedOrigs = this.dragging?.descendantOrigs || {};
    for (const folder of Object.values(this.nodes)) {
      if (folder.type !== "folder" || !folder.expanded) continue;
      let minX = Infinity, minY = Infinity;
      for (const n of Object.values(this.nodes)) {
        if (n.parent !== folder.id) continue;
        let x = n.x, y = n.y;
        if (n.id === draggedId) { x = this.dragging.origX; y = this.dragging.origY; }
        else if (draggedOrigs[n.id]) { x = draggedOrigs[n.id].x; y = draggedOrigs[n.id].y; }
        if (x < minX) minX = x;
        if (y < minY) minY = y;
      }
      if (minX === Infinity) continue;
      this.folderContentOffsets[folder.id] = {
        dx: folder.x + GraphStore.FOLDER_PAD.left - minX,
        dy: folder.y + GraphStore.FOLDER_PAD.top - minY,
      };
    }
  }

  applyTempOffset(id, dx, dy) {
    if (!this.tempOffsets[id]) this.tempOffsets[id] = {dx: 0, dy: 0};
    this.tempOffsets[id].dx += dx;
    this.tempOffsets[id].dy += dy;
  }

  resolveCollisions() {
    this.tempOffsets = {};
    const visible = Object.values(this.nodes).filter(n => this.isVisible(n));
    const expanded = visible.filter(n => n.expanded).sort((a, b) => {
      const da = this.nodeDepth(a), db = this.nodeDepth(b);
      if (da !== db) return db - da;
      const ra = this.naturalRect(a), rb = this.naturalRect(b);
      if (ra.y !== rb.y) return ra.y - rb.y;
      return ra.x - rb.x;
    });

    const G = GraphStore.GRID_SIZE;
    for (const a of expanded) {
      const p = this.renderPos(a);
      const collapsed = {x: p.x, y: p.y, w: G, h: G};
      const after = this.gridRect(a);
      const dW = Math.ceil((after.w - collapsed.w) / G) * G;
      const dH = Math.ceil((after.h - collapsed.h) / G) * G;
      if (dW === 0 && dH === 0) continue;
      const oldRight = collapsed.x + collapsed.w;
      const oldBottom = collapsed.y + collapsed.h;
      const insideFolder = a.parent !== null;
      for (const b of visible) {
        if (b.id === a.id) continue;
        if (a.parent !== b.parent) continue;
        const br = this.gridRect(b);
        if (dH !== 0 && br.y >= oldBottom) {
          if (insideFolder) {
            const xOverlap = Math.min(br.x + br.w, after.x + after.w) - Math.max(br.x, after.x);
            if (xOverlap > 0) this.applyTempOffset(b.id, 0, dH);
          } else {
            this.applyTempOffset(b.id, 0, dH);
          }
        }
        if (dW !== 0 && br.x >= oldRight) {
          if (insideFolder) {
            const yOverlap = Math.min(br.y + br.h, after.y + after.h) - Math.max(br.y, after.y);
            if (yOverlap > 0) this.applyTempOffset(b.id, dW, 0);
          } else {
            this.applyTempOffset(b.id, dW, 0);
          }
        }
      }
    }
  }

  resolveOverlap(candidates, excludeIds = new Set()) {
    // candidates: node-like objects with x, y, type, parent, expanded, width, height.
    // Returns the same array with y shifted down by grid multiples until no overlap.
    const G = GraphStore.GRID_SIZE;
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

  nodePathStr(node) {
    const parts = [node.title];
    for (let p = node.parent; p; p = this.nodes[p].parent) parts.unshift(this.nodes[p].title);
    return parts.join("/");
  }
}

GraphStore.EDGE_COLORS = {gray: "#B8A0FF", green: "#00FF41", red: "#FF0055", blue: "#6BC4FF"};
GraphStore.FOLDER_PAD = {left: 0, top: 0, right: 0, bottom: 0};
GraphStore.EMPTY_FOLDER_SIZE = {w: 200, h: 200};
GraphStore.COLLAPSED_FOLDER_SIZE = {w: 160, h: 160};
GraphStore.COLLAPSED_FILE_SIZE = {w: 160, h: 160};
GraphStore.GRID_SIZE = 200;
GraphStore.NODE_MARGIN = 20; // natural margin inside each grid cell
GraphStore.DEFAULT_DOC_EXPANDED_CELLS = {w: 3, h: 2};
GraphStore.DEFAULT_DOC_EXPANDED = {
  w: GraphStore.DEFAULT_DOC_EXPANDED_CELLS.w * GraphStore.GRID_SIZE - 2 * GraphStore.NODE_MARGIN,
  h: GraphStore.DEFAULT_DOC_EXPANDED_CELLS.h * GraphStore.GRID_SIZE - 2 * GraphStore.NODE_MARGIN,
};
GraphStore.ESCAPE_MARGIN = 80;
GraphStore.ZOOM_LEVELS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];

GraphStore.snapToGrid = function(value) {
  return Math.round(value / GraphStore.GRID_SIZE) * GraphStore.GRID_SIZE;
};
