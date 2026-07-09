// === graph-board: top-level board component ===

class GraphBoard extends HTMLElement {
  constructor() {
    super();
    this.store = null;
    this.nodeEls = {};     // {id: HTMLElement}
    this.edgeEls = {};     // {id: GraphEdge}
    this.selectedVersion = null;
    this.searchActiveIdx = 0;
    this.zoomLevelIdx = GraphStore.ZOOM_LEVELS.indexOf(1);
    this.wheelAccum = 0;
    this.wheelTimer = null;
  }

  static get observedAttributes() {
    return ["board-id"];
  }

  async connectedCallback() {
    this.build();

    // fetch the list of boards first so we can default to one that actually exists
    const listRes = await fetch("boards");
    const listData = await listRes.json();
    const available = listData.boards || [];
    const requestedId = this.getAttribute("board-id") || "main";
    const boardId = available.includes(requestedId) ? requestedId
      : (available.includes("main") ? "main" : (available[0] || "main"));

    this.store = new GraphStore(boardId);
    this.router = new GraphRouter(this.store);
    this.store.addEventListener("change", () => this.render());
    this.store.addEventListener("load", () => this.render());
    this.store.camera.zoom = GraphStore.ZOOM_LEVELS[this.zoomLevelIdx];

    this.attachEvents();
    await this.loadBoards();
    try {
      await this.store.loadGraph();
    } catch (err) {
      console.error("failed to load initial board:", err);
    }
  }

  build() {
    this.innerHTML = `
      <div id="toolbar">
        <span class="brand">thoughtgrvph</span>
        <span class="sep"></span>
        <button id="add-folder">add folder</button>
        <button id="add-doc">add doc</button>
        <button id="add-edge">add edge</button>
        <span class="sep"></span>
        <button id="rename-btn">rename</button>
        <button id="delete-btn">delete</button>
        <span class="sep"></span>
        <button id="export-btn">export</button>
        <span class="sep"></span>
        <button id="versions-btn">versions</button>
        <span class="sep" style="margin-left: auto;"></span>
        <button id="zoom-out">−</button>
        <button id="zoom-in">+</button>
      </div>
      <div id="search-panel" class="hidden">
        <input id="search-input" type="text" placeholder="search titles..." spellcheck="false" autocomplete="off">
        <div id="search-results"></div>
      </div>
      <div id="versions-panel" class="hidden">
        <div class="vp-buttons">
          <button id="ver-save">save</button>
          <button id="ver-delete">delete</button>
          <button id="ver-restore">restore</button>
        </div>
        <div id="version-list"></div>
      </div>
      <div id="sidebar">
        <div class="side-section" id="board-section">
          <div class="side-title">board</div>
          <div id="current-board"></div>
          <div class="board-controls">
            <button id="new-board" title="new board">+</button>
            <button id="rename-board" title="rename board">✎</button>
            <button id="delete-board" title="delete board from UI only">🗑</button>
          </div>
          <select id="board-select"></select>
        </div>
        <div class="side-section">
          <div class="side-title">folders</div>
          <div id="folder-list"></div>
        </div>
        <div id="edge-panel" class="hidden">
          <div class="side-title">edge color</div>
          <div id="edge-swatches">
            <button class="swatch" data-color="gray"></button>
            <button class="swatch" data-color="green"></button>
            <button class="swatch" data-color="red"></button>
            <button class="swatch" data-color="blue"></button>
          </div>
        </div>
      </div>
      <div id="viewport">
        <div id="world">
          <div id="grid"></div>
          <svg id="edges-svg" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <marker id="arrow-gray" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="#B8A0FF"/>
              </marker>
              <marker id="arrow-green" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="#00FF41"/>
              </marker>
              <marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="#FF0055"/>
              </marker>
              <marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="#6BC4FF"/>
              </marker>
            </defs>
          </svg>
          <div id="nodes-container"></div>
        </div>
      </div>
    `;

    this.viewport = this.querySelector("#viewport");
    this.world = this.querySelector("#world");
    this.svg = this.querySelector("#edges-svg");
    this.nodesContainer = this.querySelector("#nodes-container");
  }

  attachEvents() {
    this.querySelector("#add-folder").addEventListener("click", () => this.addNode("folder"));
    this.querySelector("#add-doc").addEventListener("click", () => this.addNode("file"));
    this.querySelector("#add-edge").addEventListener("click", () => this.toggleEdgeMode());
    this.querySelector("#rename-btn").addEventListener("click", () => this.renameSelected());
    this.querySelector("#delete-btn").addEventListener("click", () => this.deleteSelected());
    this.querySelector("#export-btn").addEventListener("click", () => this.exportDocs());
    this.querySelector("#versions-btn").addEventListener("click", () => this.toggleVersions());
    this.querySelector("#zoom-in").addEventListener("click", () => this.zoomIn());
    this.querySelector("#zoom-out").addEventListener("click", () => this.zoomOut());
    this.querySelector("#ver-save").addEventListener("click", () => this.saveVersion());
    this.querySelector("#ver-delete").addEventListener("click", () => this.deleteVersion());
    this.querySelector("#ver-restore").addEventListener("click", () => this.restoreVersion());
    this.querySelector("#new-board").addEventListener("click", () => this.createBoard());
    this.querySelector("#rename-board").addEventListener("click", () => this.renameBoard());
    this.querySelector("#delete-board").addEventListener("click", () => this.deleteBoard());
    this.querySelector("#board-select").addEventListener("change", (e) => this.switchBoard(e.target.value));

    for (const el of this.querySelectorAll("#edge-swatches .swatch")) {
      el.style.background = GraphStore.EDGE_COLORS[el.dataset.color];
      el.addEventListener("click", () => this.setEdgeColor(el.dataset.color));
    }

    this.viewport.addEventListener("mousedown", (e) => this.onViewportMouseDown(e));
    document.addEventListener("mousemove", (e) => this.onMouseMove(e));
    document.addEventListener("mouseup", (e) => this.onMouseUp(e));
    this.viewport.addEventListener("wheel", (e) => this.onWheel(e), {passive: false});

    const searchInput = this.querySelector("#search-input");
    searchInput.addEventListener("input", () => { this.searchActiveIdx = 0; this.renderSearch(); });
    searchInput.addEventListener("keydown", (e) => this.onSearchKey(e));
    document.addEventListener("mousedown", (e) => {
      const panel = this.querySelector("#search-panel");
      if (!panel.classList.contains("hidden") && !panel.contains(e.target)) {
        this.closeSearch();
      }
    });

    document.addEventListener("keydown", (e) => this.onKeyDown(e));

    this.nodesContainer.addEventListener("node-mousedown", (e) => this.onNodeMouseDown(e.detail.originalEvent, e.detail.node.id));
    this.nodesContainer.addEventListener("node-dblclick", (e) => this.onNodeDblClick(e.detail.node.id));
    this.nodesContainer.addEventListener("node-resize", (e) => this.onNodeResize(e.detail.node.id, e.detail.width, e.detail.height));
    this.nodesContainer.addEventListener("doc-expand", (e) => this.onDocExpand(e.detail.node.id, e.detail.editor));
    this.nodesContainer.addEventListener("content-change", (e) => {
      const doc = e.target.closest("doc-node");
      if (doc && doc.node) this.onDocContentChange(doc.node.id, e.detail);
    });
    this.nodesContainer.addEventListener("wikilink-click", (e) => this.onWikiLinkClick(e.detail));
    this.nodesContainer.addEventListener("edge-under-node", (e) => this.selectEdge(e.detail.edgeId));
  }

  render() {
    this.applyCamera();
    this.store.computeFolderContentOffsets();
    this.store.resolveCollisions();
    this.syncNodes();
    this.syncEdges();
    this.renderSidebar();
  }

  applyCamera() {
    this.world.style.transform = `translate(${this.store.camera.x}px, ${this.store.camera.y}px) scale(${this.store.camera.zoom})`;
  }

  syncNodes() {
    const store = this.store;
    const seen = new Set();
    for (const node of Object.values(store.nodes)) {
      if (!store.isVisible(node)) continue;
      seen.add(node.id);
      if (!this.nodeEls[node.id]) {
        const el = document.createElement(node.type === "folder" ? "folder-node" : "doc-node");
        el.setAttribute("node-id", node.id);
        this.nodeEls[node.id] = el;
        this.nodesContainer.appendChild(el);
      }
      const el = this.nodeEls[node.id];
      el.node = node;
      el.rect = store.nodeRect(node);
      el.selected = node.id === store.selectedNodeId;
    }
    for (const id in this.nodeEls) {
      if (!seen.has(id)) {
        this.nodeEls[id].remove();
        delete this.nodeEls[id];
      }
    }
  }

  syncEdges() {
    const store = this.store;
    const seen = new Set();
    for (const edge of Object.values(store.edges)) {
      const s = store.nodes[edge.source], t = store.nodes[edge.target];
      if (!s || !t || !store.isVisible(s) || !store.isVisible(t)) continue;
      seen.add(edge.id);
      if (!this.edgeEls[edge.id]) {
        this.edgeEls[edge.id] = new GraphEdge(this, edge);
      }
      this.edgeEls[edge.id].update();
    }
    for (const id in this.edgeEls) {
      if (!seen.has(id)) {
        this.edgeEls[id].remove();
        delete this.edgeEls[id];
      }
    }
  }

  // ---- toolbar commands ----

  async addNode(type) {
    const title = prompt(`${type === "file" ? "doc" : "folder"} name:`);
    if (!title) return;
    const sel = this.store.nodes[this.store.selectedNodeId];
    const parent = sel && sel.type === "folder" ? sel.id : null;
    let wx, wy;
    if (parent) {
      wx = sel.x + GraphStore.GRID_SIZE;
      wy = sel.y + GraphStore.GRID_SIZE;
      this.expandAncestors(parent);
      if (!sel.expanded) {
        sel.expanded = true;
        await this.store.updateNode(parent, {expanded: true});
      }
    } else {
      const r = this.viewport.getBoundingClientRect();
      wx = (r.width / 2 - this.store.camera.x) / this.store.camera.zoom;
      wy = (r.height / 2 - this.store.camera.y) / this.store.camera.zoom;
    }
    wx = GraphStore.snapToGrid(wx);
    wy = GraphStore.snapToGrid(wy);
    const candidate = {
      type, parent, expanded: false,
      x: wx, y: wy,
      width: GraphStore.DEFAULT_DOC_EXPANDED.w,
      height: GraphStore.DEFAULT_DOC_EXPANDED.h,
    };
    this.store.resolveOverlap([candidate]);
    wx = candidate.x; wy = candidate.y;
    try {
      const node = await this.store.createNode({title, type, parent, x: wx, y: wy});
      this.selectNode(node.id);
    } catch (err) {
      alert(`could not create "${title}": ${err.message}`);
    }
  }

  async deleteSelected() {
    if (this.store.selectedNodeId) {
      await this.store.deleteNode(this.store.selectedNodeId);
    } else if (this.store.selectedEdgeId) {
      await this.store.deleteEdge(this.store.selectedEdgeId);
    }
  }

  async renameSelected() {
    const id = this.store.selectedNodeId;
    if (!id) return;
    const node = this.store.nodes[id];
    const newTitle = prompt(`rename "${node.title}" to:`, node.title);
    if (!newTitle || newTitle === node.title) return;
    try {
      await this.store.updateNode(id, {title: newTitle});
    } catch (err) {
      alert(`could not rename: ${err.message}`);
    }
  }

  toggleEdgeMode() {
    if (this.store.edgeMode) {
      this.store.edgeMode = null;
    } else {
      this.store.edgeMode = {source: this.store.selectedNodeId};
    }
    this.viewport.classList.toggle("edge-mode", !!this.store.edgeMode);
    this.querySelector("#add-edge").classList.toggle("active", !!this.store.edgeMode);
  }

  async setEdgeColor(color) {
    if (!this.store.selectedEdgeId) return;
    await this.store.updateEdge(this.store.selectedEdgeId, color);
  }

  async exportDocs() {
    const store = this.store;
    const docs = Object.values(store.nodes).filter(n => n.type === "file" && store.isVisible(n));
    docs.sort((a, b) => store.nodePathStr(a).localeCompare(store.nodePathStr(b)));
    const chunks = [];
    for (const d of docs) {
      const data = await store.getContent(d.id);
      chunks.push(`=== ${store.nodePathStr(d)}.md ===\n${data.content.trim()}\n`);
    }
    const exportedIds = new Set(docs.map(d => d.id));
    const edgeLines = Object.values(store.edges)
      .filter(e => exportedIds.has(e.source) && exportedIds.has(e.target))
      .map(e => `${store.nodePathStr(store.nodes[e.source])} -[${e.color}]- ${store.nodePathStr(store.nodes[e.target])}`);
    if (edgeLines.length) chunks.push(`=== edges ===\n${edgeLines.join("\n")}\n`);
    await navigator.clipboard.writeText(chunks.join("\n"));
    const btn = this.querySelector("#export-btn");
    btn.textContent = `copied ${docs.length} docs`;
    setTimeout(() => btn.textContent = "export", 1500);
  }

  // ---- versions ----

  toggleVersions() {
    const panel = this.querySelector("#versions-panel");
    panel.classList.toggle("hidden");
    if (!panel.classList.contains("hidden")) this.renderVersions();
  }

  async saveVersion() {
    await this.store.saveVersion();
    this.renderVersions();
  }

  async deleteVersion() {
    if (!this.selectedVersion) return;
    await this.store.deleteVersion(this.selectedVersion);
    this.selectedVersion = null;
    this.renderVersions();
  }

  async restoreVersion() {
    if (!this.selectedVersion) return;
    if (!confirm(`restore to ${this.selectedVersion}?`)) return;
    await this.store.restoreVersion(this.selectedVersion);
    this.selectedVersion = null;
  }

  async renderVersions() {
    const versions = await this.store.listVersions();
    const list = this.querySelector("#version-list");
    list.innerHTML = "";
    if (!versions.includes(this.selectedVersion)) this.selectedVersion = null;
    for (const name of versions) {
      const row = document.createElement("div");
      row.className = "version-row" + (name === this.selectedVersion ? " selected" : "");
      row.textContent = name;
      row.addEventListener("click", () => {
        this.selectedVersion = name === this.selectedVersion ? null : name;
        this.renderVersions();
      });
      list.appendChild(row);
    }
  }

  // ---- board switching ----

  async loadBoards() {
    const r = await fetch("boards");
    const data = await r.json();
    const select = this.querySelector("#board-select");
    select.innerHTML = "";
    for (const id of data.boards) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      if (id === this.store.boardId) opt.selected = true;
      select.appendChild(opt);
    }
    const cur = this.querySelector("#current-board");
    if (cur) cur.textContent = this.store.boardId;
  }

  async createBoard() {
    const id = prompt("new board name:");
    if (!id) return;
    const r = await fetch("boards", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({board_id: id}),
    });
    if (!r.ok) return alert("could not create board");
    this.switchBoard(id);
  }

  async renameBoard() {
    const oldId = this.store.boardId;
    const newId = prompt(`rename "${oldId}" to:`, oldId);
    if (!newId || newId === oldId) return;
    const r = await fetch(`boards/${oldId}`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({board_id: newId}),
    });
    if (!r.ok) return alert("could not rename board");
    this.switchBoard(newId);
  }

  async deleteBoard() {
    const id = this.store.boardId;
    const confirmed = confirm(
      `delete board "${id}" and all its nodes, edges, and versions permanently? this cannot be undone.`
    );
    if (!confirmed) return;

    const r = await fetch(`boards/${id}`, {method: "DELETE"});
    if (!r.ok) return alert("could not delete board");

    const select = this.querySelector("#board-select");
    const opt = select.querySelector(`option[value="${id}"]`);
    if (opt) opt.remove();

    const remaining = Array.from(select.options).map(o => o.value);
    const next = remaining.includes("main") ? "main" : (remaining[0] || null);
    if (next) {
      this.switchBoard(next);
    } else {
      // no boards left; create a fresh empty main board
      await fetch("boards", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({board_id: "main"}),
      });
      this.switchBoard("main");
    }
  }

  switchBoard(id) {
    if (id === this.store.boardId) return;
    // rebuild store and reload
    this.zoomLevelIdx = GraphStore.ZOOM_LEVELS.indexOf(1);
    this.store = new GraphStore(id);
    this.router = new GraphRouter(this.store);
    this.store.camera.zoom = GraphStore.ZOOM_LEVELS[this.zoomLevelIdx];
    this.store.addEventListener("change", () => this.render());
    this.store.addEventListener("load", () => this.render());
    this.nodeEls = {};
    this.edgeEls = {};
    this.nodesContainer.innerHTML = "";
    while (this.svg.children.length > 1) this.svg.lastChild.remove(); // keep defs
    this.loadBoards();
    this.store.loadGraph();
  }

  // ---- selection ----

  selectNode(id) {
    this.store.selectedNodeId = id;
    this.store.selectedEdgeId = null;
    this.refreshSelection();
  }

  selectEdge(id) {
    this.store.selectedEdgeId = id;
    this.store.selectedNodeId = null;
    this.refreshSelection();
  }

  clearSelection() {
    this.store.selectedNodeId = null;
    this.store.selectedEdgeId = null;
    this.refreshSelection();
  }

  refreshSelection() {
    this.syncNodes();
    this.syncEdges();
    this.renderSidebar();
  }

  // ---- sidebar ----

  renderSidebar() {
    const store = this.store;
    const list = this.querySelector("#folder-list");
    list.innerHTML = "";
    const addRows = (parent, depth) => {
      for (const n of Object.values(store.nodes)) {
        if (n.type !== "folder" || n.parent !== parent) continue;
        const row = document.createElement("div");
        row.className = "folder-row" + (n.id === store.selectedNodeId ? " selected" : "");
        row.style.paddingLeft = (10 + depth * 16) + "px";
        const tog = document.createElement("span");
        tog.className = "tog";
        tog.textContent = n.expanded ? "\u2212" : "+";
        tog.addEventListener("click", (e) => { e.stopPropagation(); this.toggleFolder(n.id); });
        row.appendChild(tog);
        const name = document.createElement("span");
        name.className = "name";
        name.textContent = n.title;
        row.appendChild(name);
        row.addEventListener("click", () => this.focusNode(n.id));
        list.appendChild(row);
        if (n.expanded) addRows(n.id, depth + 1);
      }
    };
    addRows(null, 0);

    const panel = this.querySelector("#edge-panel");
    panel.classList.toggle("hidden", !store.selectedEdgeId);
    if (store.selectedEdgeId) {
      for (const b of panel.querySelectorAll(".swatch")) {
        b.classList.toggle("active", store.edges[store.selectedEdgeId].color === b.dataset.color);
      }
    }
  }

  async toggleFolder(id) {
    const node = this.store.nodes[id];
    const wasExpanded = node.expanded;
    if (!wasExpanded) this.expandAncestors(id);
    node.expanded = !wasExpanded;
    await this.store.updateNode(id, {expanded: node.expanded});
    if (wasExpanded) {
      for (const n of Object.values(this.store.nodes)) {
        if (this.store.isDescendantOf(n.id, id) && n.expanded) {
          n.expanded = false;
          this.store.updateNode(n.id, {expanded: false});
        }
      }
    }
    this.render();
  }

  focusNode(id) {
    this.expandAncestors(id);
    this.selectNode(id);
    this.render();
  }

  expandAncestors(nodeId) {
    for (let p = this.store.nodes[nodeId].parent; p; p = this.store.nodes[p].parent) {
      const par = this.store.nodes[p];
      if (!par.expanded) {
        par.expanded = true;
        this.store.updateNode(p, {expanded: true});
      }
    }
  }

  centerCameraOn(node) {
    const c = this.store.nodeCenter(node);
    const r = this.viewport.getBoundingClientRect();
    this.store.camera.x = r.width / 2 - c.x * this.store.camera.zoom;
    this.store.camera.y = r.height / 2 - c.y * this.store.camera.zoom;
    this.applyCamera();
  }

  onWikiLinkClick(id) {
    this.expandAncestors(id);
    const node = this.store.nodes[id];
    if (!node.expanded) {
      node.expanded = true;
      node.width = GraphStore.DEFAULT_DOC_EXPANDED.w;
      node.height = GraphStore.DEFAULT_DOC_EXPANDED.h;
      this.store.updateNode(id, {
        expanded: true,
        width: GraphStore.DEFAULT_DOC_EXPANDED.w,
        height: GraphStore.DEFAULT_DOC_EXPANDED.h,
      });
    }
    this.selectNode(id);
    this.render();
    this.centerCameraOn(node);
  }

  // ---- node interactions ----

  onNodeMouseDown(e, id) {
    if (this.store.edgeMode) {
      this.edgeModePick(id);
      return;
    }
    const node = this.store.nodes[id];
    if (node.type === "file" && node.expanded) {
      const r = this.nodeEls[id].getBoundingClientRect();
      if (e.clientX >= r.right - 18 && e.clientY >= r.bottom - 18) return;
    }
    const descendantOrigs = {};
    if (node.type === "folder") {
      for (const n of Object.values(this.store.nodes)) {
        if (this.store.isDescendantOf(n.id, id)) descendantOrigs[n.id] = {x: n.x, y: n.y};
      }
    }
    let parentBoundsAtStart = null;
    if (node.parent && node.parent === this.store.selectedNodeId) {
      parentBoundsAtStart = this.store.folderBounds(this.store.nodes[node.parent]);
    }
    this.store.dragging = {
      nodeId: id,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      origX: node.x,
      origY: node.y,
      descendantOrigs,
      parentBoundsAtStart,
      moved: false,
    };
  }

  async onNodeDblClick(id) {
    const node = this.store.nodes[id];
    if (node.type === "folder") {
      this.toggleFolder(id);
    } else {
      const wasExpanded = node.expanded;
      if (!wasExpanded) this.expandAncestors(id);
      node.expanded = !wasExpanded;
      const updates = {expanded: node.expanded};
      if (node.expanded) {
        updates.width = GraphStore.DEFAULT_DOC_EXPANDED.w;
        updates.height = GraphStore.DEFAULT_DOC_EXPANDED.h;
        node.width = updates.width;
        node.height = updates.height;
      }
      await this.store.updateNode(id, updates);
      this.render();
    }
  }

  onNodeResize(id, width, height) {
    const node = this.store.nodes[id];
    if (!node || !node.expanded) return;
    const G = GraphStore.GRID_SIZE;
    const M = GraphStore.NODE_MARGIN;
    const cellsW = Math.max(1, Math.round(width / G));
    const cellsH = Math.max(1, Math.round(height / G));
    const gw = cellsW * G - 2 * M;
    const gh = cellsH * G - 2 * M;
    if (gw === node.width && gh === node.height) return;
    node.width = gw;
    node.height = gh;
    this.render();
  }

  async onDocExpand(id, editor) {
    const data = await this.store.getContent(id);
    editor.content = data.content;
    editor.resolveLink = (title) => {
      const n = Object.values(this.store.nodes).find(x => x.type === "file" && x.title === title);
      return n ? n.id : null;
    };
  }

  async onDocContentChange(id, content) {
    await this.store.putContent(id, content);
  }

  async edgeModePick(id) {
    if (!this.store.edgeMode.source) {
      this.store.edgeMode = {source: id};
      this.selectNode(id);
      return;
    }
    if (this.store.edgeMode.source !== id) {
      await this.store.createEdge(this.store.edgeMode.source, id);
    }
    this.store.edgeMode = null;
    this.viewport.classList.remove("edge-mode");
    this.querySelector("#add-edge").classList.remove("active");
  }

  // ---- viewport interactions ----

  onViewportMouseDown(e) {
    if (e.target !== this.viewport && e.target !== this.world) return;
    if (this.store.edgeMode) {
      this.store.edgeMode = null;
      this.viewport.classList.remove("edge-mode");
      this.querySelector("#add-edge").classList.remove("active");
      return;
    }
    this.store.dragging = {
      pan: true,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      origCamX: this.store.camera.x,
      origCamY: this.store.camera.y,
      moved: false,
    };
    this.viewport.classList.add("panning");
    this.clearSelection();
  }

  onMouseMove(e) {
    const drag = this.store.dragging;
    if (!drag) return;
    const dx = e.clientX - drag.startMouseX;
    const dy = e.clientY - drag.startMouseY;
    if (Math.hypot(dx, dy) > 3) drag.moved = true;
    if (drag.pan) {
      this.store.camera.x = drag.origCamX + dx;
      this.store.camera.y = drag.origCamY + dy;
      this.applyCamera();
      return;
    }
    if (!drag.moved) return;
    const wdx = dx / this.store.camera.zoom, wdy = dy / this.store.camera.zoom;
    const node = this.store.nodes[drag.nodeId];
    node.x = drag.origX + wdx;
    node.y = drag.origY + wdy;
    for (const did in drag.descendantOrigs) {
      const o = drag.descendantOrigs[did];
      this.store.nodes[did].x = o.x + wdx;
      this.store.nodes[did].y = o.y + wdy;
    }
    this.syncNodes();
    this.syncEdges();
  }

  async onMouseUp(e) {
    const drag = this.store.dragging;
    if (!drag) return;
    this.store.dragging = null;
    this.viewport.classList.remove("panning");
    if (drag.pan) return;
    if (!drag.moved) {
      this.selectNode(drag.nodeId);
      return;
    }
    const node = this.store.nodes[drag.nodeId];
    // snap dragged node and descendants to grid before deciding parent/saving
    node.x = GraphStore.snapToGrid(node.x);
    node.y = GraphStore.snapToGrid(node.y);
    for (const did in drag.descendantOrigs) {
      const dn = this.store.nodes[did];
      dn.x = GraphStore.snapToGrid(dn.x);
      dn.y = GraphStore.snapToGrid(dn.y);
    }
    let newParent = node.parent;
    const hidden = [this.nodeEls[drag.nodeId], ...Object.keys(drag.descendantOrigs).map(d => this.nodeEls[d])].filter(Boolean);
    const prev = hidden.map(el => el.style.pointerEvents);
    hidden.forEach(el => { el.style.pointerEvents = "none"; });
    const target = document.elementFromPoint(e.clientX, e.clientY);
    hidden.forEach((el, i) => { el.style.pointerEvents = prev[i]; });

    const folderEl = target?.closest(".node.folder");
    const fid = folderEl?.dataset.id;
    if (fid && fid === this.store.selectedNodeId && fid !== drag.nodeId &&
        fid !== node.parent && !this.store.isDescendantOf(fid, drag.nodeId)) {
      newParent = fid;
      const folderNode = this.store.nodes[fid];
      if (folderNode && !folderNode.expanded) {
        folderNode.expanded = true;
        await this.store.updateNode(fid, {expanded: true});
      }
    } else if (drag.parentBoundsAtStart) {
      const b = drag.parentBoundsAtStart;
      const c = this.store.nodeCenter(node);
      if (c.x < b.x - GraphStore.ESCAPE_MARGIN || c.x > b.x + b.w + GraphStore.ESCAPE_MARGIN ||
          c.y < b.y - GraphStore.ESCAPE_MARGIN || c.y > b.y + b.h + GraphStore.ESCAPE_MARGIN) {
        newParent = this.store.nodes[node.parent].parent;
      }
    }

    const updates = {x: node.x, y: node.y};
    if (newParent !== node.parent) {
      updates.parent = newParent;
      node.parent = newParent;
    }

    // push the dragged group down if it overlaps any siblings
    this.store.tempOffsets = {};
    this.store.computeFolderContentOffsets();
    const groupIds = [drag.nodeId, ...Object.keys(drag.descendantOrigs)];
    this.store.resolveOverlap(groupIds.map(id => this.store.nodes[id]), new Set(groupIds));
    updates.x = node.x; updates.y = node.y;

    await this.store.updateNode(drag.nodeId, updates);
    const posUpdates = [];
    for (const did in drag.descendantOrigs) {
      const dn = this.store.nodes[did];
      posUpdates.push({id: did, x: dn.x, y: dn.y});
    }
    if (posUpdates.length) await this.store.updateNodePositions(posUpdates);
    this.render();
  }

  onWheel(e) {
    if (e.target.closest(".preview, .content")) return;
    e.preventDefault();
    this.wheelAccum += e.deltaY;
    if (this.wheelTimer) clearTimeout(this.wheelTimer);
    this.wheelTimer = setTimeout(() => { this.wheelAccum = 0; }, 150);
    if (Math.abs(this.wheelAccum) < 60) return;
    const r = this.viewport.getBoundingClientRect();
    const v = {x: e.clientX - r.left, y: e.clientY - r.top};
    if (this.wheelAccum < 0) this.zoomIn(v);
    else if (this.wheelAccum > 0) this.zoomOut(v);
    this.wheelAccum = 0;
  }

  setZoomLevel(newIdx, v) {
    const levels = GraphStore.ZOOM_LEVELS;
    newIdx = Math.max(0, Math.min(levels.length - 1, newIdx));
    if (newIdx === this.zoomLevelIdx) return;
    this.zoomLevelIdx = newIdx;
    const newZoom = levels[newIdx];
    const wx = (v.x - this.store.camera.x) / this.store.camera.zoom;
    const wy = (v.y - this.store.camera.y) / this.store.camera.zoom;
    this.store.camera.x = v.x - wx * newZoom;
    this.store.camera.y = v.y - wy * newZoom;
    this.store.camera.zoom = newZoom;
    this.applyCamera();
  }

  zoomIn(v) {
    const center = this.viewportCenter();
    this.setZoomLevel(this.zoomLevelIdx + 1, v || center);
  }

  zoomOut(v) {
    const center = this.viewportCenter();
    this.setZoomLevel(this.zoomLevelIdx - 1, v || center);
  }

  viewportCenter() {
    const r = this.viewport.getBoundingClientRect();
    return {x: r.width / 2, y: r.height / 2};
  }

  // ---- search ----

  openSearch() {
    const panel = this.querySelector("#search-panel");
    if (panel.classList.contains("hidden")) {
      panel.classList.remove("hidden");
      this.querySelector("#search-input").value = "";
      this.searchActiveIdx = 0;
      this.renderSearch();
    }
    this.querySelector("#search-input").focus();
    this.querySelector("#search-input").select();
  }

  closeSearch() {
    this.querySelector("#search-panel").classList.add("hidden");
  }

  renderSearch() {
    const store = this.store;
    const input = this.querySelector("#search-input");
    const results = this.querySelector("#search-results");
    const q = input.value.trim().toLowerCase();
    const matches = Object.values(store.nodes)
      .filter(n => !q || n.title.toLowerCase().includes(q))
      .sort((a, b) => a.title.localeCompare(b.title))
      .slice(0, 50);
    if (this.searchActiveIdx >= matches.length) this.searchActiveIdx = Math.max(0, matches.length - 1);
    results.innerHTML = "";
    matches.forEach((n, i) => {
      const row = document.createElement("div");
      row.className = "search-row" + (i === this.searchActiveIdx ? " active" : "");
      const icon = document.createElement("span");
      icon.className = "type-icon";
      icon.textContent = n.type === "folder" ? "\u25CB" : "\u25A2";
      const title = document.createElement("span");
      title.className = "row-title";
      title.textContent = n.title;
      const path = document.createElement("span");
      path.className = "row-path";
      const parts = [];
      for (let p = n.parent; p; p = store.nodes[p].parent) parts.unshift(store.nodes[p].title);
      path.textContent = parts.join("/");
      row.appendChild(icon);
      row.appendChild(title);
      row.appendChild(path);
      row.addEventListener("click", () => {
        this.closeSearch();
        this.focusNode(n.id);
        if (n.type === "file") this.onWikiLinkClick(n.id);
      });
      results.appendChild(row);
    });
  }

  onSearchKey(e) {
    const rows = this.querySelector("#search-results").children;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      this.searchActiveIdx = Math.min(this.searchActiveIdx + 1, rows.length - 1);
      this.renderSearch();
      rows[this.searchActiveIdx]?.scrollIntoView({block: "nearest"});
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      this.searchActiveIdx = Math.max(this.searchActiveIdx - 1, 0);
      this.renderSearch();
      rows[this.searchActiveIdx]?.scrollIntoView({block: "nearest"});
    } else if (e.key === "Enter") {
      e.preventDefault();
      rows[this.searchActiveIdx]?.click();
    } else if (e.key === "Escape") {
      e.preventDefault();
      this.closeSearch();
    }
  }

  onKeyDown(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "f") {
      e.preventDefault();
      this.openSearch();
      return;
    }
    if (["TEXTAREA", "INPUT", "SELECT"].includes(e.target.tagName)) return;
    if (e.key === "Delete" || e.key === "Backspace") {
      this.deleteSelected();
    } else if (e.key === "Escape") {
      this.store.edgeMode = null;
      this.viewport.classList.remove("edge-mode");
      this.querySelector("#add-edge").classList.remove("active");
      this.clearSelection();
    }
  }
}

customElements.define("graph-board", GraphBoard);
