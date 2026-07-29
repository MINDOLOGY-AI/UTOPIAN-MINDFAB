// === fab-board: top-level board controller ===

class FabBoard extends HTMLElement {
  constructor() {
    super();
    this.store = null;
    this.nodeEls = {};
    this.edgeEls = {};
    this.zoomIdx = FabStore.ZOOM_LEVELS.indexOf(1);
    this.wheelAccum = 0;
    this.wheelTimer = null;
    this.searchIdx = 0;
    this.selectedVersion = null;
    this.contentTimer = null;
    this.pollTimer = null;
  }

  static get observedAttributes() { return ["board-id"]; }

  async connectedCallback() {
    this.build();
    const listRes = await fetch("boards");
    const available = (await listRes.json()).boards || [];
    // restore the last board you were on, not always main
    const requested = localStorage.getItem("TH0UGHTGR4PH.boardId") || this.getAttribute("board-id") || "main";
    const boardId = available.includes(requested) ? requested
      : (available.includes("main") ? "main" : (available[0] || "main"));
    await this.initStore(boardId);
    this.attachEvents();
    this.pollTimer = setInterval(() => this.pollGraph(), 60000);

    // context management: /TH0UGHTGR4PH/?agent=<name> opens the agent's settings panel
    const agentName = new URLSearchParams(window.location.search).get("agent");
    if (agentName) this.ctxPanel = new CtxPanel(this, agentName);
  }

  disconnectedCallback() { clearInterval(this.pollTimer); }

  async initStore(boardId) {
    localStorage.setItem("TH0UGHTGR4PH.boardId", boardId);
    this.store = new FabStore(boardId);
    this.store.addEventListener("change", () => this.render());
    this.store.camera.zoom = FabStore.ZOOM_LEVELS[this.zoomIdx];
    this.nodeEls = {};
    this.edgeEls = {};
    this.nodesContainer.innerHTML = "";
    this.svg.querySelectorAll(".edge, .edge-arrow").forEach(el => el.remove());
    await this.loadBoards();
    await this.store.loadTypes();
    await this.store.loadGraph();
  }

  async pollGraph() {
    // pick up model-made board changes; never disturb an in-progress interaction
    if (!this.store || this.store.dragging || this.store.edgeMode) return;
    const before = this.store.graphSignature();
    const data = await this.store.api("GET", "/graph");
    if (JSON.stringify([data.nodes, data.edges]) !== before) {
      this.store.nodes = data.nodes;
      this.store.edges = data.edges;
      this.store.emit();
    }
  }

  build() {
    this.innerHTML = `
      <div id="toolbar">
        <a href="/" class="home-link" title="back to main page">←</a>
        <span class="brand">TH0UGHTGR4PH</span>
        <span class="sep"></span>
        <button id="add-obj">add obj</button>
        <button id="add-func">add func</button>
        <button id="add-folder">add folder</button>
        <button id="add-edge">add edge</button>
        <button id="meta-btn" class="hidden">meta</button>
        <span class="sep"></span>
        <span id="state-picker" class="hidden">
          <button class="state-btn" data-state="todo">todo</button>
          <button class="state-btn" data-state="doing">doing</button>
          <button class="state-btn" data-state="done">done</button>
        </span>
        <button id="delete-btn" class="hidden">delete</button>
        <span class="sep"></span>
        <button id="versions-btn">versions</button>
        <span class="sep" style="margin-left:auto"></span>
        <button id="search-btn">search</button>
        <button id="zoom-out">−</button>
        <button id="zoom-in">+</button>
      </div>
      <div id="sidebar">
        <div class="sidebar-scroll">
          <div class="side-section">
            <div class="side-title">board</div>
            <div class="board-controls">
              <select id="board-select"></select>
              <button id="new-board" title="new board">+</button>
              <button id="rename-board" title="rename board">✎</button>
              <button id="delete-board" title="delete board">🗑</button>
            </div>
          </div>
          <div class="side-section" id="type-section">
            <div class="side-title collapsible" data-collapse="obj-type-body">obj types <span class="caret">▸</span></div>
            <div id="obj-type-body" class="type-body collapsed">
              <div id="obj-type-list"></div>
              <div class="type-add">
                <input id="obj-type-name" placeholder="new obj type" spellcheck="false">
                <input type="color" id="obj-type-color" value="#6BC4FF">
                <button id="obj-type-add">+</button>
              </div>
            </div>
            <div class="side-title collapsible" data-collapse="func-type-body">func types <span class="caret">▸</span></div>
            <div id="func-type-body" class="type-body collapsed">
              <div id="func-type-list"></div>
              <div class="type-add">
                <input id="func-type-name" placeholder="new func type" spellcheck="false">
                <input type="color" id="func-type-color" value="#00FF41">
                <button id="func-type-add">+</button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div id="viewport">
        <div id="world">
          <div id="grid"></div>
          <svg id="edges-svg" xmlns="http://www.w3.org/2000/svg"></svg>
          <div id="nodes-container"></div>
        </div>
      </div>
      <div id="ctx-panel"></div>
      <div id="create-popup" class="popup hidden">
        <div class="popup-title" id="create-popup-title">new obj</div>
        <input id="create-title" placeholder="title" spellcheck="false" autocomplete="off">
        <div id="create-types"></div>
        <div class="popup-row">
          <button id="create-ok">create</button>
          <button id="create-cancel">cancel</button>
        </div>
      </div>
      <div id="meta-popup" class="popup hidden">
        <div class="popup-title">meta <button id="meta-close" class="x-btn">×</button></div>
        <input id="meta-title" placeholder="title" spellcheck="false" autocomplete="off">
        <div id="meta-types"></div>
        <div class="popup-row">
          <button id="meta-save">save</button>
        </div>
      </div>
      <div id="versions-panel" class="popup hidden">
        <div class="popup-title">versions <button id="versions-close" class="x-btn">×</button></div>
        <div class="popup-row">
          <button id="ver-save">save</button>
          <button id="ver-delete">delete</button>
          <button id="ver-restore">restore</button>
        </div>
        <div id="version-list"></div>
      </div>
      <div id="search-panel" class="popup hidden">
        <input id="search-input" placeholder="search titles..." spellcheck="false" autocomplete="off">
        <div id="search-results"></div>
      </div>
    `;
    this.viewport = this.querySelector("#viewport");
    this.world = this.querySelector("#world");
    this.svg = this.querySelector("#edges-svg");
    this.nodesContainer = this.querySelector("#nodes-container");
  }

  attachEvents() {
    const $ = (s) => this.querySelector(s);
    $("#add-obj").addEventListener("click", () => this.openCreatePopup("obj"));
    $("#add-func").addEventListener("click", () => this.openCreatePopup("func"));
    $("#add-folder").addEventListener("click", () => this.createFolder());
    $("#add-edge").addEventListener("click", () => this.toggleEdgeMode());
    $("#zoom-in").addEventListener("click", () => this.zoomIn());
    $("#zoom-out").addEventListener("click", () => this.zoomOut());
    $("#search-btn").addEventListener("click", () => this.openSearch());
    $("#versions-btn").addEventListener("click", () => this.togglePanel("versions-panel", () => this.renderVersions()));
    $("#versions-close").addEventListener("click", () => this.hidePanel("versions-panel"));
    $("#ver-save").addEventListener("click", () => this.saveVersion());
    $("#ver-delete").addEventListener("click", () => this.deleteVersion());
    $("#ver-restore").addEventListener("click", () => this.restoreVersion());
    $("#new-board").addEventListener("click", () => this.createBoard());
    $("#rename-board").addEventListener("click", () => this.renameBoard());
    $("#delete-board").addEventListener("click", () => this.deleteBoard());
    $("#board-select").addEventListener("change", (e) => this.initStore(e.target.value));
    $("#create-ok").addEventListener("click", () => this.confirmCreate());
    $("#create-cancel").addEventListener("click", () => this.hidePanel("create-popup"));
    $("#create-title").addEventListener("keydown", (e) => { if (e.key === "Enter") this.confirmCreate(); });
    $("#meta-btn").addEventListener("click", () => this.openMeta());
    $("#meta-save").addEventListener("click", () => this.saveMeta());
    $("#meta-close").addEventListener("click", () => this.hidePanel("meta-popup"));
    $("#meta-title").addEventListener("keydown", (e) => { if (e.key === "Enter") this.saveMeta(); });
    $("#delete-btn").addEventListener("click", () => this.deleteSelected());
    $("#obj-type-add").addEventListener("click", () => this.addType("obj"));
    $("#func-type-add").addEventListener("click", () => this.addType("func"));

    for (const btn of this.querySelectorAll(".state-btn")) {
      btn.addEventListener("click", () => this.setSelectedState(btn.dataset.state));
    }

    // collapsible sidebar sections (obj types / func types)
    for (const title of this.querySelectorAll(".side-title.collapsible")) {
      title.addEventListener("click", () => {
        const body = this.querySelector(`#${title.dataset.collapse}`);
        const collapsed = body.classList.toggle("collapsed");
        title.querySelector(".caret").textContent = collapsed ? "▸" : "▾";
      });
    }

    this.viewport.addEventListener("mousedown", (e) => this.onViewportMouseDown(e));
    document.addEventListener("mousemove", (e) => this.onMouseMove(e));
    document.addEventListener("mouseup", (e) => this.onMouseUp(e));
    this.viewport.addEventListener("wheel", (e) => this.onWheel(e), {passive: false});
    document.addEventListener("keydown", (e) => this.onKeyDown(e));

    const searchInput = $("#search-input");
    searchInput.addEventListener("input", () => { this.searchIdx = 0; this.renderSearch(); });
    searchInput.addEventListener("keydown", (e) => this.onSearchKey(e));

    this.nodesContainer.addEventListener("node-mousedown", (e) => this.onNodeMouseDown(e.detail.originalEvent, e.detail.node.id, e));
    this.nodesContainer.addEventListener("node-dblclick", (e) => this.onNodeDblClick(e.detail.node.id));
    this.nodesContainer.addEventListener("doc-expand", (e) => this.onDocExpand(e.detail.node.id, e.detail.editor));
    this.nodesContainer.addEventListener("content-change", (e) => {
      const el = e.target.closest("obj-node");
      if (el && el.node) this.onDocContentChange(el.node.id, e.detail);
    });
    this.nodesContainer.addEventListener("wikilink-click", (e) => this.onWikiLinkClick(e.detail));
  }

  // ---- rendering ----

  render() {
    this.applyCamera();
    this.store.computeFolderContentOffsets();
    this.store.resolveCollisions();
    this.syncNodes();
    this.syncEdges();
    this.renderSidebar();
    this.renderStatePicker();
    this.renderDeleteButton();
  }

  renderDeleteButton() {
    const hasSelection = !!this.store.selectedEdgeId || this.store.selectedNodeIds.size > 0;
    this.querySelector("#delete-btn").classList.toggle("hidden", !hasSelection);
    this.querySelector("#meta-btn").classList.toggle("hidden", !this.primarySelection());
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
        const tag = node.kind === "folder" ? "folder-node"
          : node.kind === "func" ? "func-node" : "obj-node";
        const el = document.createElement(tag);
        el.store = store;
        this.nodeEls[node.id] = el;
        this.nodesContainer.appendChild(el);
      }
      const el = this.nodeEls[node.id];
      el.node = node;
      el.rect = store.nodeRect(node);
      el.selected = store.selectedNodeIds.has(node.id);
      el.active = node.id === store.activeFolderId;
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
    this.routes = computeRoutes(store);
    const seen = new Set();
    for (const edge of Object.values(store.edges)) {
      const s = store.nodes[edge.source], t = store.nodes[edge.target];
      if (!s || !t || !store.isVisible(s) || !store.isVisible(t)) continue;
      seen.add(edge.id);
      if (!this.edgeEls[edge.id]) this.edgeEls[edge.id] = new FabEdge(this, edge);
      this.edgeEls[edge.id].update();
    }
    for (const id in this.edgeEls) {
      if (!seen.has(id)) {
        this.edgeEls[id].remove();
        delete this.edgeEls[id];
      }
    }
  }

  // ---- selection ----

  selectNode(id, additive = false) {
    // selection only — folder ACTIVATION happens on click (mouseup without
    // drag), so dragging a folder keeps the previous folder active as the
    // drop target. that's what makes folder-into-folder drags possible.
    if (!additive) this.store.selectedNodeIds.clear();
    if (additive && this.store.selectedNodeIds.has(id)) this.store.selectedNodeIds.delete(id);
    else this.store.selectedNodeIds.add(id);
    this.store.selectedEdgeId = null;
    this.store.emit();
  }

  selectEdge(id) {
    this.store.selectedNodeIds.clear();
    // selecting an edge does NOT deactivate the folder — only empty ground does
    this.store.selectedEdgeId = id;
    this.store.emit();
  }

  clearSelection() {
    this.store.selectedNodeIds.clear();
    this.store.activeFolderId = null;
    this.store.selectedEdgeId = null;
    this.store.emit();
  }

  activeFolder() {
    const id = this.store.activeFolderId;
    return id && this.store.nodes[id]?.kind === "folder" ? id : null;
  }

  primarySelection() {
    const ids = [...this.store.selectedNodeIds];
    return ids.length ? ids[ids.length - 1] : null;
  }

  renderStatePicker() {
    const picker = this.querySelector("#state-picker");
    const id = this.primarySelection();
    const node = id && this.store.nodes[id];
    const show = node && node.kind === "obj";
    picker.classList.toggle("hidden", !show);
    if (show) {
      for (const btn of picker.querySelectorAll(".state-btn")) {
        btn.classList.toggle("active", node.state === btn.dataset.state);
      }
    }
  }

  async setSelectedState(state) {
    const id = this.primarySelection();
    if (!id) return;
    const node = this.store.nodes[id];
    await this.store.updateNode(id, {state: node.state === state ? null : state});
  }

  // ---- create nodes ----

  viewportCenterWorld() {
    const r = this.viewport.getBoundingClientRect();
    return {
      x: (r.width / 2 - this.store.camera.x) / this.store.camera.zoom,
      y: (r.height / 2 - this.store.camera.y) / this.store.camera.zoom,
    };
  }

  createPosition(parentId = null) {
    const parent = parentId && this.store.nodes[parentId];
    if (parent && parent.kind === "folder") {
      return this.store.freeChildPosition(parent);
    }
    const c = this.viewportCenterWorld();
    return this.store.freePositionNear(c.x, c.y);
  }

  openCreatePopup(kind) {
    this.createKind = kind;
    this.createType = null;
    const popup = this.querySelector("#create-popup");
    this.querySelector("#create-popup-title").textContent = `new ${kind}`;
    // funcs have no names — only a type. hide the title input for them.
    const titleInput = this.querySelector("#create-title");
    titleInput.value = "";
    titleInput.classList.toggle("hidden", kind === "func");
    const typesDiv = this.querySelector("#create-types");
    typesDiv.innerHTML = "";
    const registry = kind === "func" ? this.store.types.func_types : this.store.types.obj_types;
    for (const [name, spec] of Object.entries(registry)) {
      const chip = document.createElement("button");
      chip.className = "type-chip";
      chip.textContent = name;
      chip.style.setProperty("--nc", spec.color || "#E2E8F0");
      chip.addEventListener("click", () => {
        this.createType = name;
        typesDiv.querySelectorAll(".type-chip").forEach(c => c.classList.toggle("active", c === chip));
      });
      typesDiv.appendChild(chip);
    }
    popup.classList.remove("hidden");
    if (kind === "func") {
      // preselect the first func type so Enter/click works immediately
      typesDiv.querySelector(".type-chip")?.click();
    } else {
      titleInput.focus();
    }
  }

  async confirmCreate() {
    const registry = this.createKind === "func" ? this.store.types.func_types : this.store.types.obj_types;
    const nodeType = this.createType || Object.keys(registry)[0] || (this.createKind === "func" ? "use" : "doc");
    // funcs are nameless: the type IS the title
    const title = this.createKind === "func" ? nodeType : this.querySelector("#create-title").value.trim();
    if (!title || !this.createKind) return;
    const parent = this.activeFolder();
    let pos = this.createPosition(parent);
    const candidate = {
      kind: this.createKind, node_type: nodeType, parent,
      x: pos.x, y: pos.y, expanded: false,
      width: FabStore.EXPANDED_W, height: FabStore.EXPANDED_H,
    };
    this.store.resolveOverlap([candidate]);
    pos = {x: candidate.x, y: candidate.y};
    try {
      const node = await this.store.createNode({
        title, kind: this.createKind, node_type: nodeType,
        parent, x: pos.x, y: pos.y,
      });
      if (parent && !this.store.nodes[parent].expanded) await this.store.updateNode(parent, {expanded: true});
      this.hidePanel("create-popup");
      this.selectNode(node.id);
    } catch (err) {
      alert(`could not create: ${err.message}`);
    }
  }

  async createFolder() {
    const title = prompt("folder name:");
    if (!title) return;
    const parent = this.activeFolder();
    let pos = this.createPosition(parent);
    const candidate = {
      kind: "folder", node_type: "folder", parent,
      x: pos.x, y: pos.y, expanded: false,
      width: FabStore.EXPANDED_W, height: FabStore.EXPANDED_H,
    };
    this.store.resolveOverlap([candidate]);
    pos = {x: candidate.x, y: candidate.y};
    try {
      const node = await this.store.createNode({title, kind: "folder", node_type: "folder", parent, x: pos.x, y: pos.y});
      if (parent && !this.store.nodes[parent].expanded) await this.store.updateNode(parent, {expanded: true});
      this.selectNode(node.id);
    } catch (err) {
      alert(`could not create folder: ${err.message}`);
    }
  }

  // ---- meta popup: rename + retype the selected node ----

  openMeta() {
    const id = this.primarySelection();
    const node = id && this.store.nodes[id];
    if (!node) return;
    this.metaId = id;
    this.metaType = node.node_type;
    const popup = this.querySelector("#meta-popup");
    const titleInput = this.querySelector("#meta-title");
    // funcs are nameless — only a type. folders have a title but no type.
    titleInput.value = node.kind === "func" ? "" : node.title;
    titleInput.classList.toggle("hidden", node.kind === "func");
    const typesDiv = this.querySelector("#meta-types");
    typesDiv.innerHTML = "";
    typesDiv.classList.toggle("hidden", node.kind === "folder");
    if (node.kind !== "folder") {
      const registry = node.kind === "func" ? this.store.types.func_types : this.store.types.obj_types;
      for (const [name, spec] of Object.entries(registry)) {
        const chip = document.createElement("button");
        chip.className = "type-chip" + (name === node.node_type ? " active" : "");
        chip.textContent = name;
        chip.style.setProperty("--nc", spec.color || "#E2E8F0");
        chip.addEventListener("click", () => {
          this.metaType = name;
          typesDiv.querySelectorAll(".type-chip").forEach(c => c.classList.toggle("active", c === chip));
        });
        typesDiv.appendChild(chip);
      }
    }
    for (const p of this.querySelectorAll(".popup")) p.classList.add("hidden");
    popup.classList.remove("hidden");
    if (node.kind !== "func") {
      titleInput.focus();
      titleInput.select();
    }
  }

  async saveMeta() {
    const node = this.store.nodes[this.metaId];
    if (!node) return;
    const updates = {};
    if (node.kind === "func") {
      // funcs are nameless: the type IS the title
      if (this.metaType && this.metaType !== node.node_type) {
        updates.node_type = this.metaType;
        updates.title = this.metaType;
      }
    } else {
      const title = this.querySelector("#meta-title").value.trim();
      if (title && title !== node.title) updates.title = title;
      if (node.kind === "obj" && this.metaType && this.metaType !== node.node_type) {
        updates.node_type = this.metaType;
      }
    }
    if (Object.keys(updates).length) {
      try {
        await this.store.updateNode(node.id, updates);
      } catch (err) {
        alert(err.message);
      }
    }
    this.hidePanel("meta-popup");
  }

  // ---- edges ----

  toggleEdgeMode() {
    this.store.edgeMode = this.store.edgeMode ? null : {source: this.primarySelection()};
    this.viewport.classList.toggle("edge-mode", !!this.store.edgeMode);
    this.querySelector("#add-edge").classList.toggle("active", !!this.store.edgeMode);
  }

  async edgeModePick(id) {
    if (!this.store.edgeMode.source) {
      this.store.edgeMode = {source: id};
      this.selectNode(id);
      return;
    }
    if (this.store.edgeMode.source !== id) {
      try {
        await this.store.createEdge(this.store.edgeMode.source, id);
      } catch (err) {
        alert(err.message);
      }
    }
    this.store.edgeMode = null;
    this.viewport.classList.remove("edge-mode");
    this.querySelector("#add-edge").classList.remove("active");
  }

  // ---- node interactions ----

  onNodeMouseDown(e, id, customEvent) {
    if (this.store.edgeMode) {
      this.edgeModePick(id);
      return;
    }
    const node = this.store.nodes[id];
    const wasSelected = this.store.selectedNodeIds.has(id);
    if (!e.shiftKey && !wasSelected) this.selectNode(id);
    else if (e.shiftKey) this.selectNode(id, true);

    let parentBoundsAtStart = null;
    if (node.parent && node.parent === this.store.activeFolderId) {
      parentBoundsAtStart = this.store.folderBounds(this.store.nodes[node.parent]);
    }
    this.store.dragging = {
      nodeId: id,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      origX: node.x,
      origY: node.y,
      origParent: node.parent,
      parentBoundsAtStart,
      moved: false,
    };
  }

  async onNodeDblClick(id) {
    const node = this.store.nodes[id];
    if (node.kind === "folder") {
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
      return;
    }
    if (node.kind !== "obj") return; // funcs never expand
    const wasExpanded = node.expanded;
    if (!wasExpanded) this.expandAncestors(id);
    node.expanded = !wasExpanded;
    const updates = {expanded: node.expanded};
    if (node.expanded) {
      updates.width = FabStore.EXPANDED_W;
      updates.height = FabStore.EXPANDED_H;
      node.width = updates.width;
      node.height = updates.height;
    }
    await this.store.updateNode(id, updates);
    this.render();
  }

  async onDocExpand(id, editor) {
    const data = await this.store.getContent(id);
    editor.content = data.content;
    editor.resolveLink = (title) => {
      const n = Object.values(this.store.nodes).find(x => x.kind === "obj" && x.title === title);
      return n ? n.id : null;
    };
  }

  onDocContentChange(id, content) {
    this.store.putContent(id, content);
    if (this.contentTimer) clearTimeout(this.contentTimer);
    this.contentTimer = setTimeout(() => {}, 500);
  }

  onWikiLinkClick(id) {
    const node = this.store.nodes[id];
    if (!node) return;
    this.expandAncestors(id);
    this.selectNode(id);
    this.centerCameraOn(node);
  }

  expandAncestors(id) {
    for (let p = this.store.nodes[id].parent; p; p = this.store.nodes[p].parent) {
      if (!this.store.nodes[p].expanded) this.store.updateNode(p, {expanded: true});
    }
  }

  centerCameraOn(node) {
    const c = this.store.nodeCenter(node);
    const r = this.viewport.getBoundingClientRect();
    this.store.camera.x = r.width / 2 - c.x * this.store.camera.zoom;
    this.store.camera.y = r.height / 2 - c.y * this.store.camera.zoom;
    this.applyCamera();
  }

  // ---- viewport interactions ----

  onViewportMouseDown(e) {
    if (e.target !== this.viewport && e.target !== this.world && e.target.id !== "grid") return;
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
    const drag = this.store?.dragging;
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
    if (this.ctxPanel) this.ctxPanel.setDropActive(true);
    const wdx = dx / this.store.camera.zoom, wdy = dy / this.store.camera.zoom;
    const node = this.store.nodes[drag.nodeId];
    node.x = drag.origX + wdx;
    node.y = drag.origY + wdy;
    // children of a dragged folder follow automatically (relative coords)
    this.syncNodes();
    this.syncEdges();
  }

  async onMouseUp(e) {
    const drag = this.store?.dragging;
    if (!drag) return;
    this.viewport.classList.remove("panning");
    if (this.ctxPanel) this.ctxPanel.setDropActive(false);
    if (drag.pan) {
      this.store.dragging = null;
      return;
    }
    const node = this.store.nodes[drag.nodeId];
    if (!drag.moved) {
      this.store.dragging = null;
      this.selectNode(drag.nodeId);
      // a click (no drag) on a folder makes it the active folder
      if (node.kind === "folder") {
        this.store.activeFolderId = node.id;
        this.store.emit();
      }
      return;
    }
    // snap to the grid before deciding parent / saving
    node.x = FabStore.snap(node.x);
    node.y = FabStore.snap(node.y);

    // dropped onto a ctx panel section? -> add to that access list, restore position
    const zone = document.elementFromPoint(e.clientX, e.clientY)?.closest(".ctx-drop");
    if (zone && this.ctxPanel) {
      node.x = drag.origX;
      node.y = drag.origY;
      this.store.dragging = null;
      this.render();
      this.ctxPanel.addEntry(zone.dataset.key, this.store.boardId, node.id);
      return;
    }

    // world position as displayed at drop time (content offsets are still
    // computed from the pre-drag layout, so this is where the user sees it)
    const wc = this.store.renderPos(node);

    let newParent = node.parent;
    let rel = null; // explicit new coords (folder-relative or root-absolute)

    const draggedEl = this.nodeEls[drag.nodeId];
    if (draggedEl) draggedEl.style.pointerEvents = "none";
    // scan the whole stack under the cursor: edge lines and sibling nodes
    // sitting on top of the folder must not swallow the drop
    const stack = document.elementsFromPoint(e.clientX, e.clientY);
    if (draggedEl) draggedEl.style.pointerEvents = "";
    let fid = null;
    for (const el of stack) {
      const f = el.closest?.(".fab-node.kind-folder");
      if (!f) continue;
      const id = f.dataset.id;
      if (id === drag.nodeId) continue;
      if (this.store.isDescendantOf(id, drag.nodeId)) continue;
      fid = id;
      break;
    }
    if (fid && fid === this.store.activeFolderId && fid !== drag.nodeId &&
        fid !== node.parent && !this.store.isDescendantOf(fid, drag.nodeId)) {
      // dropped onto the active folder -> becomes a child at a free spot
      newParent = fid;
      const folderNode = this.store.nodes[fid];
      if (!folderNode.expanded) {
        folderNode.expanded = true;
        await this.store.updateNode(fid, {expanded: true});
      }
      rel = this.store.freeChildPosition(folderNode);
    } else if (drag.parentBoundsAtStart) {
      // dragged far outside its active parent folder -> escapes one level up
      const b = drag.parentBoundsAtStart;
      const c = this.store.nodeCenter(node);
      if (c.x < b.x - FabStore.ESCAPE_MARGIN || c.x > b.x + b.w + FabStore.ESCAPE_MARGIN ||
          c.y < b.y - FabStore.ESCAPE_MARGIN || c.y > b.y + b.h + FabStore.ESCAPE_MARGIN) {
        newParent = this.store.nodes[node.parent].parent || null;
        if (newParent) {
          const gp = this.store.nodes[newParent];
          const gwc = this.store.renderPos(gp);
          const gcoff = this.store.folderContentOffsets[gp.id] || {dx: 0, dy: 0};
          rel = {
            x: Math.round(wc.x - gwc.x - gcoff.dx),
            y: Math.round(wc.y - gwc.y - gcoff.dy),
          };
        } else {
          rel = {x: FabStore.snap(wc.x), y: FabStore.snap(wc.y)};
        }
      }
    }

    const fx = rel ? rel.x : node.x;
    const fy = rel ? rel.y : node.y;
    this.store.dragging = null;
    if (this.store.wouldOverlap(drag.nodeId, fx, fy, newParent)) {
      // dropped on top of a sibling -> reject the move, back to pre-drag spot
      node.x = drag.origX;
      node.y = drag.origY;
      this.render();
      return;
    }
    node.x = fx;
    node.y = fy;
    const updates = {x: node.x, y: node.y};
    if (newParent !== node.parent) updates.parent = newParent;
    await this.store.updateNode(drag.nodeId, updates);
    this.render();
  }

  onWheel(e) {
    if (e.target.closest(".md-editor, .popup, #sidebar")) return;
    e.preventDefault();
    this.wheelAccum += e.deltaY;
    if (this.wheelTimer) clearTimeout(this.wheelTimer);
    this.wheelTimer = setTimeout(() => { this.wheelAccum = 0; }, 150);
    if (Math.abs(this.wheelAccum) < 60) return;
    const r = this.viewport.getBoundingClientRect();
    const v = {x: e.clientX - r.left, y: e.clientY - r.top};
    if (this.wheelAccum < 0) this.zoomIn(v);
    else this.zoomOut(v);
    this.wheelAccum = 0;
  }

  setZoom(idx, v) {
    const levels = FabStore.ZOOM_LEVELS;
    idx = Math.max(0, Math.min(levels.length - 1, idx));
    if (idx === this.zoomIdx) return;
    this.zoomIdx = idx;
    const z = levels[idx];
    const wx = (v.x - this.store.camera.x) / this.store.camera.zoom;
    const wy = (v.y - this.store.camera.y) / this.store.camera.zoom;
    this.store.camera.x = v.x - wx * z;
    this.store.camera.y = v.y - wy * z;
    this.store.camera.zoom = z;
    this.applyCamera();
  }

  zoomIn(v) { this.setZoom(this.zoomIdx + 1, v || this.viewportCenter()); }
  zoomOut(v) { this.setZoom(this.zoomIdx - 1, v || this.viewportCenter()); }

  viewportCenter() {
    const r = this.viewport.getBoundingClientRect();
    return {x: r.width / 2, y: r.height / 2};
  }

  // ---- keyboard ----

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
      for (const p of this.querySelectorAll(".popup")) p.classList.add("hidden");
    } else if (e.key.startsWith("Arrow")) {
      const id = this.primarySelection();
      if (!id) return;
      e.preventDefault();
      const node = this.store.nodes[id];
      const dx = e.key === "ArrowRight" ? FabStore.GRID : e.key === "ArrowLeft" ? -FabStore.GRID : 0;
      const dy = e.key === "ArrowDown" ? FabStore.GRID : e.key === "ArrowUp" ? -FabStore.GRID : 0;
      // children of a folder follow automatically (relative coords);
      // stacking on a sibling is rejected
      if (!this.store.wouldOverlap(id, node.x + dx, node.y + dy, node.parent)) {
        this.store.updateNode(id, {x: node.x + dx, y: node.y + dy});
      }
    }
  }

  async deleteSelected() {
    if (this.store.selectedEdgeId) {
      await this.store.deleteEdge(this.store.selectedEdgeId);
      return;
    }
    for (const id of [...this.store.selectedNodeIds]) {
      try { await this.store.deleteNode(id); } catch (err) { alert(err.message); }
    }
  }

  // ---- sidebar ----

  renderSidebar() {
    this.renderBoardSelect();
    this.renderTypeList("obj");
    this.renderTypeList("func");
  }

  async renderBoardSelect() {
    const select = this.querySelector("#board-select");
    if (select.options.length && select.value === this.store.boardId) return;
    await this.loadBoards();
  }

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
  }

  async createBoard() {
    const id = prompt("new board name:");
    if (!id) return;
    const r = await fetch("boards", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({board_id: id}),
    });
    if (!r.ok) return alert("could not create board");
    await this.initStore(id);
  }

  async renameBoard() {
    const oldId = this.store.boardId;
    const newId = prompt(`rename "${oldId}" to:`, oldId);
    if (!newId || newId === oldId) return;
    const r = await fetch(`boards/${oldId}`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({board_id: newId}),
    });
    if (!r.ok) return alert("could not rename board");
    await this.initStore(newId);
  }

  async deleteBoard() {
    const id = this.store.boardId;
    if (!confirm(`delete board "${id}" and all its nodes permanently?`)) return;
    const r = await fetch(`boards/${id}`, {method: "DELETE"});
    if (!r.ok) return alert("could not delete board");
    const listRes = await fetch("boards");
    const remaining = (await listRes.json()).boards || [];
    if (remaining.length) await this.initStore(remaining.includes("main") ? "main" : remaining[0]);
    else {
      await fetch("boards", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({board_id: "main"}),
      });
      await this.initStore("main");
    }
  }

  renderTypeList(kind) {
    const list = this.querySelector(`#${kind}-type-list`);
    const registry = kind === "func" ? this.store.types.func_types : this.store.types.obj_types;
    list.innerHTML = "";
    for (const [name, spec] of Object.entries(registry)) {
      const row = document.createElement("div");
      row.className = "type-row";
      const swatch = document.createElement("input");
      swatch.type = "color";
      swatch.value = spec.color || "#E2E8F0";
      swatch.title = `${name} color`;
      swatch.addEventListener("change", () => {
        registry[name].color = swatch.value;
        this.store.saveTypes();
      });
      row.appendChild(swatch);
      const label = document.createElement("span");
      label.className = "type-name";
      label.textContent = name;
      row.appendChild(label);
      const del = document.createElement("button");
      del.className = "x-btn";
      del.textContent = "×";
      del.title = `delete type ${name}`;
      del.addEventListener("click", () => {
        delete registry[name];
        this.store.saveTypes();
      });
      row.appendChild(del);
      list.appendChild(row);
    }
  }

  addType(kind) {
    const nameInput = this.querySelector(`#${kind}-type-name`);
    const colorInput = this.querySelector(`#${kind}-type-color`);
    const name = nameInput.value.trim().replace(/\s+/g, "_");
    if (!name) return;
    const registry = kind === "func" ? this.store.types.func_types : this.store.types.obj_types;
    if (registry[name]) return alert(`type ${name} exists`);
    registry[name] = {color: colorInput.value};
    nameInput.value = "";
    this.store.saveTypes();
  }

  // ---- panels ----

  togglePanel(id, onOpen) {
    const panel = this.querySelector(`#${id}`);
    const opening = panel.classList.contains("hidden");
    for (const p of this.querySelectorAll(".popup")) p.classList.add("hidden");
    if (opening) {
      panel.classList.remove("hidden");
      if (onOpen) onOpen();
    }
  }

  hidePanel(id) { this.querySelector(`#${id}`).classList.add("hidden"); }

  // ---- versions ----

  async renderVersions() {
    const r = await fetch(`boards/${this.store.boardId}/versions`);
    const versions = (await r.json()).versions || [];
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

  async saveVersion() {
    await fetch(`boards/${this.store.boardId}/versions`, {method: "POST"});
    this.renderVersions();
  }

  async deleteVersion() {
    if (!this.selectedVersion) return;
    await fetch(`boards/${this.store.boardId}/versions/${this.selectedVersion}`, {method: "DELETE"});
    this.selectedVersion = null;
    this.renderVersions();
  }

  async restoreVersion() {
    if (!this.selectedVersion) return;
    if (!confirm(`restore to ${this.selectedVersion}?`)) return;
    await fetch(`boards/${this.store.boardId}/versions/${this.selectedVersion}/restore`, {method: "POST"});
    await this.store.loadGraph();
    this.selectedVersion = null;
  }

  // ---- search ----

  openSearch() {
    const panel = this.querySelector("#search-panel");
    panel.classList.remove("hidden");
    this.querySelector("#search-input").value = "";
    this.searchIdx = 0;
    this.renderSearch();
    this.querySelector("#search-input").focus();
  }

  renderSearch() {
    const q = this.querySelector("#search-input").value.trim().toLowerCase();
    const matches = Object.values(this.store.nodes)
      .filter(n => !q || n.title.toLowerCase().includes(q))
      .sort((a, b) => a.title.localeCompare(b.title))
      .slice(0, 50);
    if (this.searchIdx >= matches.length) this.searchIdx = Math.max(0, matches.length - 1);
    const results = this.querySelector("#search-results");
    results.innerHTML = "";
    matches.forEach((n, i) => {
      const row = document.createElement("div");
      row.className = "search-row" + (i === this.searchIdx ? " active" : "");
      row.textContent = `${n.title}  ·  ${n.kind}/${n.node_type}`;
      row.addEventListener("click", () => {
        this.hidePanel("search-panel");
        this.expandAncestors(n.id);
        this.selectNode(n.id);
        this.centerCameraOn(n);
      });
      results.appendChild(row);
    });
  }

  onSearchKey(e) {
    const rows = this.querySelector("#search-results").children;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      this.searchIdx = Math.min(this.searchIdx + 1, rows.length - 1);
      this.renderSearch();
      rows[this.searchIdx]?.scrollIntoView({block: "nearest"});
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      this.searchIdx = Math.max(this.searchIdx - 1, 0);
      this.renderSearch();
      rows[this.searchIdx]?.scrollIntoView({block: "nearest"});
    } else if (e.key === "Enter") {
      e.preventDefault();
      rows[this.searchIdx]?.click();
    } else if (e.key === "Escape") {
      e.preventDefault();
      this.hidePanel("search-panel");
    }
  }
}

customElements.define("fab-board", FabBoard);
