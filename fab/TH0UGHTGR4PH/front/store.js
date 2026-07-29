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
    this.types = {obj_types: {}, func_types: {}, state_colors: {}};
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

  setActiveFolder(id) { this.activeFolderId = id; }
  clearActiveFolder() { this.activeFolderId = null; }

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
      if ((n.kind === "obj" || n.kind === "func") && n.expanded) {
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

  async updateNodePositions(updates) {
    // updates: [{id, x, y}, ...]
    for (const u of updates) {
      await this.api("PUT", `/nodes/${u.id}`, {x: u.x, y: u.y});
      Object.assign(this.nodes[u.id], {x: u.x, y: u.y});
    }
    this.emit();
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
    if (node.kind === "func") {
      const G = FabStore.GRID, s = FabStore.FUNC_SIZE;
      return {x: p.x + G / 2 - s / 2, y: p.y + G / 2 - s / 2, w: s, h: s};
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
    if (node.kind === "func") {
      const G = FabStore.GRID, s = FabStore.FUNC_SIZE;
      return {x: p.x + G / 2 - s / 2, y: p.y + G / 2 - s / 2, w: s, h: s};
    }
    const m = FabStore.MARGIN;
    const s = FabStore.COLLAPSED;
    return {x: p.x + m, y: p.y + m, w: s, h: s};
  }

  naturalRect(node) {
    // footprint used for push-aside and overlap checks
    if (node.kind === "folder") {
      if (node.expanded) return this.folderBounds(node);
      return this.collapsedRect(node);
    }
    if (node.kind === "func") return this.collapsedRect(node);
    if (node.expanded) {
      const p = this.renderPos(node);
      return {
        x: p.x + FabStore.MARGIN, y: p.y + FabStore.MARGIN,
        w: node.width || FabStore.EXPANDED_W, h: node.height || FabStore.EXPANDED_H,
      };
    }
    return this.collapsedRect(node);
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
    if (node.kind === "func") { w = G; h = G; }
    else if (node.expanded) {
      w = Math.ceil((node.width || FabStore.EXPANDED_W) / G) * G;
      h = Math.ceil((node.height || FabStore.EXPANDED_H) / G) * G;
    } else { w = G; h = G; }
    return {x: p.x, y: p.y, w, h};
  }

  folderBounds(folder) {
    // expanded folder engulfs its children; anchored at the folder's stored pos
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
      const p = this.renderPos(folder);
      const P = FabStore.FOLDER_PAD;
      return {x: p.x - P.left, y: p.y - P.top, w: FabStore.GRID + P.left + P.right, h: FabStore.GRID + P.top + P.bottom};
    }
    const P = FabStore.FOLDER_PAD;
    return {
      x: minX - P.left,
      y: minY - P.top,
      w: maxX - minX + P.left + P.right,
      h: maxY - minY + P.top + P.bottom,
    };
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

  resolveCollisions() {
    // expanding a node pushes its siblings below/right aside (render-time only)
    this.tempOffsets = {};
    const visible = Object.values(this.nodes).filter(n => this.isVisible(n));
    const expanded = visible.filter(n => n.expanded).sort((a, b) => {
      const da = this.nodeDepth(a), db = this.nodeDepth(b);
      if (da !== db) return db - da;
      const ra = this.naturalRect(a), rb = this.naturalRect(b);
      if (ra.y !== rb.y) return ra.y - rb.y;
      return ra.x - rb.x;
    });

    const G = FabStore.GRID;
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

  nodePathStr(node) {
    const parts = [node.title];
    for (let p = node.parent; p; p = this.nodes[p].parent) parts.unshift(this.nodes[p].title);
    return parts.join("/");
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
FabStore.FUNC_SIZE = 80;
FabStore.EXPANDED_W = 560;
FabStore.EXPANDED_H = 360;
FabStore.FOLDER_PAD = {left: 12, top: 44, right: 12, bottom: 12};
FabStore.ESCAPE_MARGIN = 80;
FabStore.ZOOM_LEVELS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];
FabStore.snap = v => Math.round(v / FabStore.GRID) * FabStore.GRID;

if (typeof module !== "undefined") module.exports = {FabStore};
