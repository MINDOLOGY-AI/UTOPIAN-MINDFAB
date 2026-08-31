// === fab-board: top-level board controller ===

// ---- setup: boot, board switching, dom skeleton, event wiring ----

class FabBoard extends HTMLElement {
  constructor() {
    super();
    this.store = null;
    this.nodeEls = {};
    this.edgeEls = {};
    this.wheelAccum = 0;
    this.wheelTimer = null;
    this.searchIdx = 0;
    this.pollTimer = null;
  }

  static get observedAttributes() { return ["board-id"]; }

  // boot: build the dom, reopen the last-used board, wire events, start polling
  async connectedCallback() {
    this.build();
    // events before the first render — initStore's expanded docs fire doc-expand,
    // and a listener attached afterwards means empty editors on page load
    this.attachEvents();
    const listRes = await fetch("boards");
    const available = (await listRes.json()).boards || [];
    // restore the last board you were on, not always main
    const requested = localStorage.getItem("thoughtgraph.boardId") || this.getAttribute("board-id") || "main";
    const boardId = available.includes(requested) ? requested
      : (available.includes("main") ? "main" : (available[0] || "main"));
    await this.initStore(boardId);
    this.pollTimer = setInterval(() => this.pollGraph(), 5000);
  }

  disconnectedCallback() { clearInterval(this.pollTimer); }

  // switch boards: fresh store + wiped dom, but the zoom survives
  async initStore(boardId) {
    localStorage.setItem("thoughtgraph.boardId", boardId);
    const zoom = this.store ? this.store.camera.zoom : 1;  // zoom survives board switches
    this.store = new FabStore(boardId);
    this.store.addEventListener("change", () => this.render());
    this.store.camera.zoom = zoom;
    this.nodeEls = {};
    this.edgeEls = {};
    this.nodesContainer.innerHTML = "";
    this.svg.querySelectorAll(".edge, .edge-hit, .edge-arrow").forEach(el => el.remove());
    await this.loadBoards();
    await this.store.loadTypes();
    await this.store.loadGraph();
  }

  // 5s poll: picks up every write made outside this tab (agents, neovim, other
  // windows) — the server's load_meta reconciles the disk tree on each call, so
  // hand-edited files land here too. never disturb an in-progress interaction
  async pollGraph() {
    if (!this.store || this.store.dragging || this.store.edgeMode) return;
    const before = this.store.graphSignature();
    const data = await this.store.api("GET", "/graph");
    if (JSON.stringify([data.nodes, data.edges]) !== before) {
      this.store.nodes = data.nodes;
      this.store.edges = data.edges;
      this.store.emit();
    }
    // refresh the text of every expanded doc
    for (const n of Object.values(this.store.nodes)) {
      if (n.kind !== "doc" || !n.expanded) continue;
      const ed = this.nodeEls[n.id]?.querySelector(".md-editor");
      if (!ed) continue;
      // an open textarea means someone is typing — swapping now would roll the
      // editor back to the last save (the debounced PUT hasn't landed yet)
      if (ed.textarea && ed.textarea.style.display !== "none") continue;
      const c = await this.store.getContent(n.id);
      if (ed.content !== c.content) ed.content = c.content;
    }
  }

  // stamp the whole dom skeleton: toolbar, sidebar, viewport, popups
  build() {
    this.innerHTML = `
      <div id="toolbar">
        <button id="add-doc">add doc</button>
        <button id="add-folder">add folder</button>
        <button id="add-edge">add edge</button>
        <button id="delete-btn" class="hidden">delete</button>
        <button id="meta-btn" class="hidden">meta</button>
        <span class="sep" style="margin-left:auto"></span>
        <button id="search-btn">search</button>
        <button id="zoom-out">−</button>
        <button id="zoom-in">+</button>
        <label id="doc-font-label" title="text size inside doc nodes (px)">text <input id="doc-font-size" type="number" min="8" max="32" step="1"></label>
        <span class="sep"></span>
        <button id="download-board" title="download board (zip)">↓</button>
        <button id="upload-board" title="upload board (zip)">↑</button>
        <span class="sep"></span>
        <button id="access-btn" title="agent access panel">access</button>
        <input type="file" id="upload-input" accept=".zip,application/zip" hidden>
      </div>
      <fab-sidebar id="sidebar">
        <div class="sidebar-scroll">
          <div class="side-section">
            <button id="new-board">+ board</button>
            <div id="board-list"></div>
          </div>
          <div class="side-section" id="file-view-section">
            <div class="side-title collapsible" data-collapse="file-view-body">file view <span class="caret">▸</span></div>
            <div id="file-view-body" class="type-body collapsed">
              <div id="file-view-list"></div>
            </div>
          </div>
          <div class="side-section" id="type-section">
            <div class="side-title collapsible" data-collapse="doc-type-body">doc types <span class="caret">▸</span></div>
            <div id="doc-type-body" class="type-body collapsed">
              <div id="doc-type-list"></div>
              <div class="type-add">
                <input id="doc-type-name" placeholder="new doc type" spellcheck="false">
                <input type="color" id="doc-type-color" value="#6BC4FF">
                <button id="doc-type-add">+</button>
              </div>
            </div>
            <div class="side-title collapsible" data-collapse="edge-type-body">edge types <span class="caret">▸</span></div>
            <div id="edge-type-body" class="type-body collapsed">
              <div id="edge-type-list"></div>
              <div class="type-add">
                <input id="edge-type-name" placeholder="new edge type" spellcheck="false">
                <input type="color" id="edge-type-color" value="#00FF41">
                <button id="edge-type-add">+</button>
              </div>
            </div>
          </div>
        </div>
        <div id="board-menu" style="display:none;">
          <button id="menu-board-rename">rename</button>
          <button id="menu-board-delete">delete</button>
        </div>
      </fab-sidebar>
      <div id="viewport">
        <div id="world">
          <div id="grid"></div>
          <svg id="edges-svg" xmlns="http://www.w3.org/2000/svg"></svg>
          <div id="nodes-container"></div>
        </div>
      </div>
      <div id="create-popup" class="popup hidden">
        <div class="popup-title" id="create-popup-title">new doc</div>
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
      <div id="edge-popup" class="popup hidden">
        <div class="popup-title">edge type <button id="edge-cancel" class="x-btn">×</button></div>
        <div id="edge-types"></div>
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

  // wire every button, input, mouse, wheel and key listener
  attachEvents() {
    const $ = (s) => this.querySelector(s);
    $("#add-doc").addEventListener("click", () => this.openCreatePopup("doc"));
    $("#add-folder").addEventListener("click", () => this.createFolder());
    $("#add-edge").addEventListener("click", () => this.toggleEdgeMode());
    $("#zoom-in").addEventListener("click", () => this.zoomIn());
    $("#zoom-out").addEventListener("click", () => this.zoomOut());
    // doc text size: scales ONLY the markdown inside doc nodes (not ui, not titles).
    // stored as a css var so preview + editor scale together; persisted per user.
    const fontInput = $("#doc-font-size");
    const applyDocFont = (v) => {
      const px = Math.min(32, Math.max(8, Number(v) || 13.5));
      document.documentElement.style.setProperty("--doc-font-size", px + "px");
      if (String(px) !== fontInput.value) fontInput.value = px;
      localStorage.setItem("tg-doc-font-size", String(px));
    };
    fontInput.value = localStorage.getItem("tg-doc-font-size") || "13.5";
    applyDocFont(fontInput.value);
    fontInput.addEventListener("change", () => applyDocFont(fontInput.value));
    $("#search-btn").addEventListener("click", () => this.openSearch());
    $("#access-btn").addEventListener("click", () => this.toggleAccess());
    $("#new-board").addEventListener("click", () => this.createBoard());
    $("#menu-board-rename").addEventListener("click", () => this.renameBoard());
    $("#menu-board-delete").addEventListener("click", () => this.deleteBoard());
    // click anywhere else closes the board menu
    document.addEventListener("click", (e) => {
      const menu = this.querySelector("#board-menu");
      if (!menu.contains(e.target) && !e.target.classList.contains("board-menu-btn")) menu.style.display = "none";
    });
    $("#download-board").addEventListener("click", () => this.downloadBoard());
    $("#upload-board").addEventListener("click", () => this.querySelector("#upload-input").click());
    $("#upload-input").addEventListener("change", (e) => {
      if (e.target.files[0]) this.uploadBoard(e.target.files[0]);
      e.target.value = "";
    });
    $("#create-ok").addEventListener("click", () => this.confirmCreate());
    $("#create-cancel").addEventListener("click", () => this.hidePanel("create-popup"));
    $("#create-title").addEventListener("keydown", (e) => { if (e.key === "Enter") this.confirmCreate(); });
    $("#meta-btn").addEventListener("click", () => this.openMeta());
    $("#meta-save").addEventListener("click", () => this.saveMeta());
    $("#meta-close").addEventListener("click", () => this.hidePanel("meta-popup"));
    $("#meta-title").addEventListener("keydown", (e) => { if (e.key === "Enter") this.saveMeta(); });
    $("#delete-btn").addEventListener("click", () => this.deleteSelected());
    $("#doc-type-add").addEventListener("click", () => this.addType("doc"));
    $("#edge-type-add").addEventListener("click", () => this.addType("edge"));
    $("#edge-cancel").addEventListener("click", () => this.hidePanel("edge-popup"));

    // collapsible sidebar sections (file view / doc types / edge types)
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
    this.nodesContainer.addEventListener("node-resize-start", (e) => this.onResizeStart(e.detail));
    this.nodesContainer.addEventListener("doc-expand", (e) => this.onDocExpand(e.detail.node.id, e.detail.editor));
    this.nodesContainer.addEventListener("content-change", (e) => {
      const el = e.target.closest("doc-node");
      if (el && el.node) this.onDocContentChange(el.node.id, e.detail);
    });
    this.nodesContainer.addEventListener("wikilink-click", (e) => this.onWikiLinkClick(e.detail));
  }

  // ---- rendering ----

  // full redraw: camera -> layout -> node/edge dom diff -> sidebar
  render() {
    this.applyCamera();
    this.store.computeFolderContentOffsets();
    this.store.resolveCollisions();
    this.syncNodes();
    this.syncEdges();
    this.renderSidebar();
    this.renderDeleteButton();
  }

  // delete/meta buttons only make sense with a selection; meta covers nodes AND edges
  renderDeleteButton() {
    const hasSelection = !!this.store.selectedEdgeId || this.store.selectedNodeIds.size > 0;
    this.querySelector("#delete-btn").classList.toggle("hidden", !hasSelection);
    this.querySelector("#meta-btn").classList.toggle("hidden", !this.primarySelection() && !this.store.selectedEdgeId);
  }

  // push the camera into the world's css transform
  applyCamera() {
    this.world.style.transform = `translate(${this.store.camera.x}px, ${this.store.camera.y}px) scale(${this.store.camera.zoom})`;
  }

  // diff store nodes against the dom: create missing els, update the rest, drop stale ones
  syncNodes() {
    const store = this.store;
    const seen = new Set();
    const ladder = store.folderTitleLadder();
    for (const node of Object.values(store.nodes)) {
      if (!store.isVisible(node)) continue;
      seen.add(node.id);
      if (!this.nodeEls[node.id]) {
        const tag = node.kind === "folder" ? "folder-node" : "doc-node";
        const el = document.createElement(tag);
        el.store = store;
        this.nodeEls[node.id] = el;
        this.nodesContainer.appendChild(el);
      }
      const el = this.nodeEls[node.id];
      el.node = node;
      el.rect = store.nodeRect(node);
      el.ladderIndex = ladder[node.id] || 0;
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

  // same diff for edges; routes recomputed from scratch each render
  syncEdges() {
    const store = this.store;
    this.routes = computeRoutes(store);
    const seen = new Set();
    for (const edge of Object.values(store.edges)) {
      const s = store.nodes[edge.source], t = store.nodes[edge.target];
      if (!s || !t || !store.isVisible(s) || !store.isVisible(t)) continue;
      seen.add(edge.id);
      // refresh the element's edge object — store swaps in fresh objects on every
      // poll/mutation, and a stale one would render the old edge_type color forever
      if (!this.edgeEls[edge.id]) this.edgeEls[edge.id] = new FabEdge(this, edge);
      else this.edgeEls[edge.id].edge = edge;
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

  // the folder new nodes and drops go into, or null
  activeFolder() {
    const id = this.store.activeFolderId;
    return id && this.store.nodes[id]?.kind === "folder" ? id : null;
  }

  // last-clicked node of the selection (drives meta btn, arrows, edge-mode source)
  primarySelection() {
    const ids = [...this.store.selectedNodeIds];
    return ids.length ? ids[ids.length - 1] : null;
  }

  // ---- create popup: new doc / folder ----

  // viewport center in world coords — where new root nodes appear
  viewportCenterWorld() {
    const r = this.viewport.getBoundingClientRect();
    return {
      x: (r.width / 2 - this.store.camera.x) / this.store.camera.zoom,
      y: (r.height / 2 - this.store.camera.y) / this.store.camera.zoom,
    };
  }

  // free spot for a new node: inside the folder if one's active, else near screen center
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
    const titleInput = this.querySelector("#create-title");
    titleInput.value = "";
    const typesDiv = this.querySelector("#create-types");
    typesDiv.innerHTML = "";
    for (const [name, spec] of Object.entries(this.store.types.doc_types)) {
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
    titleInput.focus();
  }

  // read the popup, find a non-overlapping spot, create + select the node
  async confirmCreate() {
    const nodeType = this.createType || Object.keys(this.store.types.doc_types)[0] || "doc";
    const title = this.querySelector("#create-title").value.trim();
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

  // ---- meta popup: rename + retype the selected node, retype the selected edge ----

  openMeta() {
    const popup = this.querySelector("#meta-popup");
    const titleInput = this.querySelector("#meta-title");
    const typesDiv = this.querySelector("#meta-types");
    const saveBtn = this.querySelector("#meta-save");
    for (const p of this.querySelectorAll(".popup")) p.classList.add("hidden");
    // an edge's only meta is its type — no title, no save button, chips apply instantly
    const edge = this.store.edges[this.store.selectedEdgeId];
    if (edge) {
      this.metaId = null;
      titleInput.classList.add("hidden");
      saveBtn.classList.add("hidden");
      typesDiv.classList.remove("hidden");
      typesDiv.innerHTML = "";
      for (const [name, spec] of Object.entries(this.store.types.edge_types)) {
        const chip = document.createElement("button");
        chip.className = "type-chip" + (name === edge.edge_type ? " active" : "");
        chip.textContent = name;
        chip.style.setProperty("--nc", spec.color || "#fff");
        chip.addEventListener("click", () => {
          this.store.updateEdge(edge.id, name);
          this.hidePanel("meta-popup");
        });
        typesDiv.appendChild(chip);
      }
      popup.classList.remove("hidden");
      return;
    }
    titleInput.classList.remove("hidden");
    saveBtn.classList.remove("hidden");
    const id = this.primarySelection();
    const node = id && this.store.nodes[id];
    if (!node) return;
    this.metaId = id;
    this.metaType = node.node_type;
    // folders have a title but no type; docs have both
    titleInput.value = node.title;
    typesDiv.innerHTML = "";
    typesDiv.classList.toggle("hidden", node.kind === "folder");
    if (node.kind === "doc") {
      for (const [name, spec] of Object.entries(this.store.types.doc_types)) {
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
    popup.classList.remove("hidden");
    titleInput.focus();
    titleInput.select();
  }

  async saveMeta() {
    const node = this.store.nodes[this.metaId];
    if (!node) { this.hidePanel("meta-popup"); return; }  // edge meta applies on chip click, nothing to save
    const updates = {};
    const title = this.querySelector("#meta-title").value.trim();
    if (title && title !== node.title) updates.title = title;
    if (node.kind === "doc" && this.metaType && this.metaType !== node.node_type) {
      updates.node_type = this.metaType;
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

  // ---- edges + edge mode ----

  toggleEdgeMode() {
    this.store.edgeMode = this.store.edgeMode ? null : {source: this.primarySelection()};
    this.viewport.classList.toggle("edge-mode", !!this.store.edgeMode);
    this.querySelector("#add-edge").classList.toggle("active", !!this.store.edgeMode);
  }

  // node clicked in edge mode: first click sets the source, second opens the type popup
  async edgeModePick(id) {
    if (!this.store.edgeMode.source) {
      this.store.edgeMode = {source: id};
      this.selectNode(id);
      return;
    }
    if (this.store.edgeMode.source !== id) {
      this.openEdgePopup(this.store.edgeMode.source, id);
      return;
    }
    this.exitEdgeMode();
  }

  exitEdgeMode() {
    this.store.edgeMode = null;
    this.viewport.classList.remove("edge-mode");
    this.querySelector("#add-edge").classList.remove("active");
  }

  openEdgePopup(source, target) {
    const popup = this.querySelector("#edge-popup");
    const typesDiv = this.querySelector("#edge-types");
    typesDiv.innerHTML = "";
    for (const [name, spec] of Object.entries(this.store.types.edge_types)) {
      const chip = document.createElement("button");
      chip.className = "type-chip";
      chip.textContent = name;
      chip.style.setProperty("--nc", spec.color || "#fff");
      chip.addEventListener("click", () => this.createTypedEdge(source, target, name));
      typesDiv.appendChild(chip);
    }
    for (const p of this.querySelectorAll(".popup")) p.classList.add("hidden");
    popup.classList.remove("hidden");
  }

  async createTypedEdge(source, target, edgeType) {
    try {
      await this.store.createEdge(source, target, edgeType);
    } catch (err) {
      alert(err.message);
    }
    this.hidePanel("edge-popup");
    this.exitEdgeMode();
  }

  // ---- node drag / resize / expand ----

  // mousedown on a node: select it and arm a potential drag (or feed edge mode)
  onNodeMouseDown(e, id, customEvent) {
    // an armed access list turns node clicks into grants — no selection, no drag
    if (this.accessPanel?.armed) {
      this.accessPanel.addEntry(this.accessPanel.armed, this.store.boardId, id);
      return;
    }
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

  // bottom-right grip drag on an expanded doc: width/height persist on mouseup
  // (snapped to whole grid cells)
  onResizeStart({node, originalEvent: e}) {
    this.store.dragging = {
      resize: true,
      nodeId: node.id,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      origX: node.x,
      origY: node.y,
      origW: node.width || FabStore.EXPANDED_W,
      origH: node.height || FabStore.EXPANDED_H,
    };
  }

  // dblclick toggles expanded; collapsing a folder collapses its whole subtree
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
    const wasExpanded = node.expanded;
    if (!wasExpanded) this.expandAncestors(id);
    node.expanded = !wasExpanded;
    // no width/height reset on expand: nodes are created at the default size
    // anyway, and a user's custom resize should survive collapse→expand
    await this.store.updateNode(id, {expanded: node.expanded});
    this.render();
  }

  // a doc just expanded: fetch its markdown into the editor, wire wikilink resolution
  async onDocExpand(id, editor) {
    const data = await this.store.getContent(id);
    editor.content = data.content;
    editor.resolveLink = (title) => {
      const n = Object.values(this.store.nodes).find(x => x.kind === "doc" && x.title === title);
      return n ? n.id : null;
    };
  }

  onDocContentChange(id, content) {
    // the markdown editor debounces on its side; every change event PUTs straight through
    this.store.putContent(id, content);
  }

  // [[wikilink]] clicked: reveal the target doc and center the camera on it
  async onWikiLinkClick(id) {
    const node = this.store.nodes[id];
    if (!node) return;
    await this.expandAncestors(id);
    this.selectNode(id);
    this.render();
    this.centerCameraOn(this.store.nodes[id]);
  }

  async expandAncestors(id) {
    const updates = [];
    for (let p = this.store.nodes[id].parent; p; p = this.store.nodes[p].parent) {
      if (!this.store.nodes[p].expanded) updates.push(this.store.updateNode(p, {expanded: true}));
    }
    // wait for the expansions to land so content offsets are final before
    // anyone reads positions (e.g. centerCameraOn after search navigation)
    await Promise.all(updates);
  }

  centerCameraOn(node) {
    const c = this.store.nodeCenter(node);
    const r = this.viewport.getBoundingClientRect();
    this.store.camera.x = r.width / 2 - c.x * this.store.camera.zoom;
    this.store.camera.y = r.height / 2 - c.y * this.store.camera.zoom;
    this.applyCamera();
  }

  // ---- viewport pan / zoom ----

  onViewportMouseDown(e) {
    // the interior of an expanded folder is empty ground (pan/deselect) —
    // only its frame/title bar is grabbable (see FolderNode._onFrame)
    const folderEl = e.target?.closest?.(".fab-node.kind-folder");
    const folderInterior = folderEl && folderEl.classList.contains("expanded") && !folderEl._onFrame(e);
    if (e.target !== this.viewport && e.target !== this.world && e.target.id !== "grid" && !folderInterior) return;
    if (this.store.edgeMode) {
      this.exitEdgeMode();
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

  // one handler for all drag kinds: pan, resize, node move — switched by the drag shape
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
    if (drag.resize) {
      const node = this.store.nodes[drag.nodeId];
      // raw pixels mid-drag so the stretch glides with the cursor;
      // the snap to whole grid cells happens on mouseup
      node.width = Math.max(FabStore.MIN_EXPANDED_W, Math.round(drag.origW + dx / this.store.camera.zoom));
      node.height = Math.max(FabStore.MIN_EXPANDED_H, Math.round(drag.origH + dy / this.store.camera.zoom));
      // re-run layout so siblings get pushed aside as the doc grows
      this.store.computeFolderContentOffsets();
      this.store.resolveCollisions();
      this.syncNodes();
      this.syncEdges();
      return;
    }
    if (!drag.moved) return;
    const wdx = dx / this.store.camera.zoom, wdy = dy / this.store.camera.zoom;
    const node = this.store.nodes[drag.nodeId];
    node.x = drag.origX + wdx;
    node.y = drag.origY + wdy;
    // children of a dragged folder follow automatically (relative coords)
    this.syncNodes();
    this.syncEdges();
  }

  // drop: snap to grid, resolve the target (folder / escape), persist
  async onMouseUp(e) {
    const drag = this.store?.dragging;
    if (!drag) return;
    this.viewport.classList.remove("panning");
    if (drag.pan) {
      this.store.dragging = null;
      return;
    }
    if (drag.resize) {
      // snap the result to whole grid cells (footprint = integer multiple of
      // GRID) so the board lands back in alignment, then persist — otherwise the
      // poll sees local≠server forever and clobbers the custom size
      const node = this.store.nodes[drag.nodeId];
      const M = FabStore.MARGIN;
      const snapCells = (v, min) => Math.max(min, FabStore.snap(v + 2 * M) - 2 * M);
      node.width = snapCells(node.width, FabStore.MIN_EXPANDED_W);
      node.height = snapCells(node.height, FabStore.MIN_EXPANDED_H);
      this.store.dragging = null;
      this.store.updateNode(drag.nodeId, {width: node.width, height: node.height});
      this.render();
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

  // plain scroll pans; ctrl/alt+wheel zooms (trackpad pinch arrives as ctrl+wheel).
  // an expanded doc's editor scrolls natively ONLY if it can still scroll that way —
  // otherwise the scroll falls through and pans the board (no dead zones)
  onWheel(e) {
    if (e.target.closest(".popup, #sidebar")) return;
    if (e.ctrlKey || e.altKey) {
      e.preventDefault();
      // zoom: trackpad pinch arrives as ctrl+wheel; alt+scroll zooms too.
      // small deltas accumulate and only step once |sum| hits 60; resets after 150ms silence
      this.wheelAccum += e.deltaY;
      if (this.wheelTimer) clearTimeout(this.wheelTimer);
      this.wheelTimer = setTimeout(() => { this.wheelAccum = 0; }, 150);
      if (Math.abs(this.wheelAccum) < 60) return;
      const r = this.viewport.getBoundingClientRect();
      const v = {x: e.clientX - r.left, y: e.clientY - r.top};
      if (this.wheelAccum < 0) this.zoomIn(v);
      else this.zoomOut(v);
      this.wheelAccum = 0;
      return;
    }
    // scrollable element: the textarea in edit mode, the editor itself in preview
    const ed = e.target.closest(".md-editor");
    if (ed) {
      const ta = ed.querySelector("textarea");
      const sc = ta && ta.style.display !== "none" ? ta : ed;
      const canVert = (e.deltaY > 0 && sc.scrollTop + sc.clientHeight < sc.scrollHeight - 1) ||
                      (e.deltaY < 0 && sc.scrollTop > 0);
      const canHoriz = e.deltaX !== 0 && sc.scrollWidth > sc.clientWidth + 1;
      // no preventDefault — the editor takes this scroll natively
      if (canVert || canHoriz) return;
    }
    e.preventDefault();
    // plain scroll pans the board (two-finger trackpad scroll gives deltaX + deltaY)
    this.store.camera.x -= e.deltaX;
    this.store.camera.y -= e.deltaY;
    this.applyCamera();
  }

  // clamp the zoom and keep the world point under the cursor stationary
  setZoom(z, v) {
    z = Math.max(FabStore.ZOOM_MIN, Math.min(FabStore.ZOOM_MAX, z));
    if (z === this.store.camera.zoom) return;
    const wx = (v.x - this.store.camera.x) / this.store.camera.zoom;
    const wy = (v.y - this.store.camera.y) / this.store.camera.zoom;
    this.store.camera.x = v.x - wx * z;
    this.store.camera.y = v.y - wy * z;
    this.store.camera.zoom = z;
    this.applyCamera();
  }

  zoomIn(v) { this.setZoom(this.store.camera.zoom + FabStore.ZOOM_STEP, v || this.viewportCenter()); }
  zoomOut(v) { this.setZoom(this.store.camera.zoom - FabStore.ZOOM_STEP, v || this.viewportCenter()); }

  viewportCenter() {
    const r = this.viewport.getBoundingClientRect();
    return {x: r.width / 2, y: r.height / 2};
  }

  // ---- keyboard ----

  // ctrl+f search; del deletes; esc cancels; arrows nudge the selected node one cell
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
      this.exitEdgeMode();
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
    this.renderBoardList();
    this.renderFileView();
    this.renderTypeList("doc");
    this.renderTypeList("edge");
  }

  renderFileView() {
    // the graph IS a tree (parent pointers) — this is just the indented projection of it.
    // nav-only: click jumps to the node on the canvas (same flow as search results)
    const list = this.querySelector("#file-view-list");
    list.innerHTML = "";
    const children = {};
    for (const n of Object.values(this.store.nodes)) {
      (children[n.parent] = children[n.parent] || []).push(n);
    }
    const byTitle = (a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase());
    const walk = (parentId, depth) => {
      for (const n of (children[parentId] || []).sort(byTitle)) {
        const row = document.createElement("div");
        row.className = "fv-row" + (this.store.selectedNodeIds.has(n.id) ? " active" : "");
        row.style.paddingLeft = `${6 + depth * 14}px`;
        const label = document.createElement("span");
        label.textContent = n.kind === "folder" ? `${n.title}/` : n.title;
        if (n.kind === "folder") label.className = "fv-folder";
        row.appendChild(label);
        row.addEventListener("click", async () => {
          await this.expandAncestors(n.id);
          this.selectNode(n.id);
          this.render();
          this.centerCameraOn(this.store.nodes[n.id]);
        });
        list.appendChild(row);
        if (n.kind === "folder") walk(n.id, depth + 1);
      }
    };
    walk(null, 0);
  }

  // ---- boards: sidebar list + create / rename / upload / download / delete ----

  // one row per board; click switches, ⋮ opens the rename/delete menu for that row
  async renderBoardList() {
    const r = await fetch("boards");
    const data = await r.json();
    const list = this.querySelector("#board-list");
    list.innerHTML = "";
    for (const id of data.boards) {
      const row = document.createElement("div");
      row.className = "board-row" + (id === this.store.boardId ? " active" : "");
      const label = document.createElement("span");
      label.textContent = id;
      label.onclick = () => this.initStore(id);
      const menuBtn = document.createElement("button");
      menuBtn.className = "board-menu-btn";
      menuBtn.textContent = "⋮";
      menuBtn.onclick = (e) => {
        e.stopPropagation();
        const menu = this.querySelector("#board-menu");
        const reopen = menu.style.display !== "flex" || this.menuBoard !== id;
        this.menuBoard = id;
        menu.style.display = reopen ? "flex" : "none";
        menu.style.left = e.clientX + "px";
        menu.style.top = e.clientY + "px";
      };
      row.append(label, menuBtn);
      list.appendChild(row);
    }
  }

  async createBoard() {
    const id = (prompt("new board name:") || "").trim();
    if (!id) return;
    const r = await fetch("boards", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({board_id: id}),
    });
    if (!r.ok) return alert("could not create board");
    await this.initStore(id);
  }

  async renameBoard() {
    const oldId = this.menuBoard;
    const newId = prompt(`rename "${oldId}" to:`, oldId);
    if (!newId || newId === oldId) return;
    const r = await fetch(`boards/${oldId}`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({board_id: newId}),
    });
    if (!r.ok) return alert("could not rename board");
    if (oldId === this.store.boardId) await this.initStore(newId);
    else await this.renderBoardList();
  }

  downloadBoard() {
    // plain navigation: browser handles the zip save dialog
    window.location.href = `boards/${encodeURIComponent(this.store.boardId)}/download`;
  }

  // zip a board in; a 409 means the name's taken — confirm, then resend with override
  async uploadBoard(file) {
    const send = (override) =>
      fetch(`boards/upload${override ? "?override=1" : ""}`, {
        method: "POST",
        headers: {"Content-Type": "application/zip"},
        body: file,
      });
    let r = await send(false);
    if (r.status === 409) {
      const detail = (await r.json()).detail;
      if (!confirm(`${detail} — overwrite the current board?`)) return;
      r = await send(true);
    }
    if (!r.ok) {
      const detail = (await r.json().catch(() => ({}))).detail || r.status;
      return alert(`upload failed: ${detail}`);
    }
    const {id} = await r.json();
    await this.initStore(id);
  }

  // delete the menu-target board; if it was the current one, fall back to main (recreating it if it was the last)
  async deleteBoard() {
    const id = this.menuBoard;
    if (!confirm(`delete board "${id}" and all its nodes permanently?`)) return;
    const r = await fetch(`boards/${id}`, {method: "DELETE"});
    if (!r.ok) return alert("could not delete board");
    if (id !== this.store.boardId) return this.renderBoardList();
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

  // ---- sidebar type lists ----

  // rebuild a type list (doc or edge): color swatch + delete button per row
  renderTypeList(kind) {
    const list = this.querySelector(`#${kind}-type-list`);
    const registry = kind === "edge" ? this.store.types.edge_types : this.store.types.doc_types;
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

  // create a doc/edge type from the sidebar name+color inputs
  addType(kind) {
    const nameInput = this.querySelector(`#${kind}-type-name`);
    const colorInput = this.querySelector(`#${kind}-type-color`);
    const name = nameInput.value.trim().replace(/\s+/g, "_");
    if (!name) return;
    const registry = kind === "edge" ? this.store.types.edge_types : this.store.types.doc_types;
    if (registry[name]) return alert(`type ${name} exists`);
    registry[name] = {color: colorInput.value};
    nameInput.value = "";
    this.store.saveTypes();
  }

  // ---- panels ----

  hidePanel(id) { this.querySelector(`#${id}`).classList.add("hidden"); }

  // access panel: body-level sidebar (skeleton in index.html), created on first toggle
  toggleAccess() {
    if (!this.accessPanel) this.accessPanel = new AccessPanel(this);
    this.accessPanel.toggle();
    this.querySelector("#access-btn").classList.toggle("active", this.accessPanel.isOpen);
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

  // filter titles by the query and render the top 50 rows
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
      row.addEventListener("click", async () => {
        this.hidePanel("search-panel");
        await this.expandAncestors(n.id);
        this.selectNode(n.id);
        this.render();
        this.centerCameraOn(this.store.nodes[n.id]);
      });
      results.appendChild(row);
    });
  }

  // arrows move the highlight, enter jumps, esc closes
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
