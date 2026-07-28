// === fab-board: top-level board controller ===

class FabBoard extends HTMLElement {
  constructor() {
    super();
    this.store = null;
    this.nodeEls = {};
    this.edgeEls = {};
    this.agentLink = new AgentLink();
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
    const requested = localStorage.getItem("F4B.boardId") || this.getAttribute("board-id") || "main";
    const boardId = available.includes(requested) ? requested
      : (available.includes("main") ? "main" : (available[0] || "main"));
    await this.initStore(boardId);
    this.attachEvents();
    this.agentLink.onMessage((msg) => {
      if (msg.type === "agents" || msg.type === "status") this.renderAgentNodes();
    });
    this.pollTimer = setInterval(() => this.pollGraph(), 5000);
  }

  disconnectedCallback() { clearInterval(this.pollTimer); }

  async initStore(boardId) {
    localStorage.setItem("F4B.boardId", boardId);
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
        <span class="brand">F4B</span>
        <span class="sep"></span>
        <button id="add-obj">add obj</button>
        <button id="add-func">add func</button>
        <button id="add-agent">add agent</button>
        <button id="add-folder">add folder</button>
        <button id="add-edge">add edge</button>
        <span class="sep"></span>
        <span id="state-picker" class="hidden">
          <button class="state-btn" data-state="todo">todo</button>
          <button class="state-btn" data-state="doing">doing</button>
          <button class="state-btn" data-state="done">done</button>
        </span>
        <button id="delete-btn" class="hidden">delete</button>
        <span class="sep"></span>
        <button id="workflow-btn">workflow</button>
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
          <div class="side-section" id="workflow-section">
            <div class="side-title collapsible" data-collapse="workflow-body">workflows <span class="caret">▸</span></div>
            <div id="workflow-body" class="type-body collapsed">
              <div id="workflow-list"></div>
            </div>
          </div>
        </div>
        <div class="sidebar-account">
          <auth-box inline></auth-box>
        </div>
      </div>
      <div id="viewport">
        <div id="world">
          <div id="grid"></div>
          <svg id="edges-svg" xmlns="http://www.w3.org/2000/svg"></svg>
          <div id="nodes-container"></div>
        </div>
      </div>
      <div id="create-popup" class="popup hidden">
        <div class="popup-title" id="create-popup-title">new obj</div>
        <input id="create-title" placeholder="title" spellcheck="false" autocomplete="off">
        <div id="create-types"></div>
        <div class="popup-row">
          <button id="create-ok">create</button>
          <button id="create-cancel">cancel</button>
        </div>
      </div>
      <div id="agent-panel">
        <div class="ap-header">
          <span id="ap-name"></span>
          <button id="ap-close" class="x-btn">×</button>
        </div>
        <div class="ap-status" id="ap-status"></div>
        <div class="ap-section">
          <div class="ap-subtitle">model</div>
          <select id="ap-model"></select>
        </div>
        <div class="ap-section">
          <div class="ap-subtitle">prompts — drag docs from the board here</div>
          <div class="ap-drop" data-drop="prompt_docs"></div>
        </div>
        <div class="ap-section">
          <div class="ap-subtitle">read access — drag nodes here</div>
          <div class="ap-drop" data-drop="read"></div>
        </div>
        <div class="ap-section">
          <div class="ap-subtitle">write access — drag nodes here</div>
          <div class="ap-drop" data-drop="write"></div>
        </div>
        <button id="ap-open">open INT3RF4CE</button>
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
      <div id="workflow-panel" class="popup hidden">
        <div class="popup-title">workflow <button id="workflow-close" class="x-btn">×</button></div>
        <div id="workflow-info">save = capture selected nodes (with agent settings). insert = clone into this board.</div>
        <div class="popup-row">
          <button id="wf-save">save selection</button>
        </div>
        <div id="workflow-list-popup"></div>
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
    $("#add-agent").addEventListener("click", () => this.createAgentNode());
    $("#add-folder").addEventListener("click", () => this.createFolder());
    $("#add-edge").addEventListener("click", () => this.toggleEdgeMode());
    $("#zoom-in").addEventListener("click", () => this.zoomIn());
    $("#zoom-out").addEventListener("click", () => this.zoomOut());
    $("#search-btn").addEventListener("click", () => this.openSearch());
    $("#versions-btn").addEventListener("click", () => this.togglePanel("versions-panel", () => this.renderVersions()));
    $("#versions-close").addEventListener("click", () => this.hidePanel("versions-panel"));
    $("#workflow-btn").addEventListener("click", () => this.togglePanel("workflow-panel", () => this.renderWorkflows()));
    $("#workflow-close").addEventListener("click", () => this.hidePanel("workflow-panel"));
    $("#ap-close").addEventListener("click", () => this.closeAgentPanel());
    $("#ap-open").addEventListener("click", () => {
      if (this.panelAgent) window.open(`/INT3RF4CE/?agent=${encodeURIComponent(this.panelAgent.ref || this.panelAgent.title)}`, "_blank");
    });
    $("#ap-model").addEventListener("change", () => this.onAgentModelChange());
    $("#ver-save").addEventListener("click", () => this.saveVersion());
    $("#ver-delete").addEventListener("click", () => this.deleteVersion());
    $("#ver-restore").addEventListener("click", () => this.restoreVersion());
    $("#new-board").addEventListener("click", () => this.createBoard());
    $("#rename-board").addEventListener("click", () => this.renameBoard());
    $("#delete-board").addEventListener("click", () => this.deleteBoard());
    $("#board-select").addEventListener("change", (e) => this.initStore(e.target.value));
    $("#wf-save").addEventListener("click", () => this.saveWorkflow());
    $("#create-ok").addEventListener("click", () => this.confirmCreate());
    $("#create-cancel").addEventListener("click", () => this.hidePanel("create-popup"));
    $("#create-title").addEventListener("keydown", (e) => { if (e.key === "Enter") this.confirmCreate(); });
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
    this.nodesContainer.addEventListener("agent-settings", (e) => this.openAgentPanel(e.detail.node));
  }

  // ---- rendering ----

  render() {
    this.applyCamera();
    this.store.computeTempOffsets();
    this.syncNodes();
    this.syncEdges();
    this.renderSidebar();
    this.renderStatePicker();
    this.renderDeleteButton();
  }

  renderDeleteButton() {
    const hasSelection = !!this.store.selectedEdgeId || this.store.selectedNodeIds.size > 0;
    this.querySelector("#delete-btn").classList.toggle("hidden", !hasSelection);
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
          : node.kind === "agent" || node.node_type === "agent" ? "agent-node"
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
    }
    for (const id in this.nodeEls) {
      if (!seen.has(id)) {
        this.nodeEls[id].remove();
        delete this.nodeEls[id];
      }
    }
    this.renderAgentNodes();
  }

  renderAgentNodes() {
    for (const id in this.nodeEls) {
      const el = this.nodeEls[id];
      if (el.tagName === "AGENT-NODE") {
        el.agentInfo = this.agentLink.agents;
        el.render();
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
    if (!additive) this.store.selectedNodeIds.clear();
    if (additive && this.store.selectedNodeIds.has(id)) this.store.selectedNodeIds.delete(id);
    else this.store.selectedNodeIds.add(id);
    this.store.selectedEdgeId = null;
    this.store.emit();
  }

  selectEdge(id) {
    this.store.selectedNodeIds.clear();
    this.store.selectedEdgeId = id;
    this.store.emit();
  }

  clearSelection() {
    this.store.selectedNodeIds.clear();
    this.store.selectedEdgeId = null;
    this.closeAgentPanel(); // deselecting closes the agent side panel
    this.store.emit();
  }

  primarySelection() {
    const ids = [...this.store.selectedNodeIds];
    return ids.length ? ids[ids.length - 1] : null;
  }

  renderStatePicker() {
    const picker = this.querySelector("#state-picker");
    const id = this.primarySelection();
    const node = id && this.store.nodes[id];
    const show = node && node.kind === "obj" && node.node_type !== "agent";
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

  createPosition() {
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
      if (kind === "obj" && name === "agent") continue; // agents are made via "add agent"
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
    const pos = this.createPosition();
    const sel = this.primarySelection();
    const selNode = sel && this.store.nodes[sel];
    const parent = selNode && selNode.kind === "folder" ? sel : null;
    try {
      const node = await this.store.createNode({
        title, kind: this.createKind, node_type: nodeType,
        parent, x: pos.x, y: pos.y,
      });
      if (parent && !selNode.expanded) await this.store.updateNode(parent, {expanded: true});
      this.hidePanel("create-popup");
      this.selectNode(node.id);
    } catch (err) {
      alert(`could not create: ${err.message}`);
    }
  }

  async createFolder() {
    const title = prompt("folder name:");
    if (!title) return;
    const pos = this.createPosition();
    try {
      const node = await this.store.createNode({title, kind: "folder", node_type: "folder", x: pos.x, y: pos.y});
      this.selectNode(node.id);
    } catch (err) {
      alert(`could not create folder: ${err.message}`);
    }
  }

  async createAgentNode() {
    const name = prompt("agent name (letters, digits, _ -):");
    if (!name) return;
    const res = await this.agentLink.createAgent(name);
    if (!res.ok) {
      alert(`could not create agent: ${res.msg}`);
      return;
    }
    const pos = this.createPosition();
    try {
      const node = await this.store.createNode({
        title: name, kind: "agent", node_type: "agent", ref: name,
        x: pos.x, y: pos.y,
      });
      await this.store.updateNode(node.id, {
        settings: {model: "kimi-k3", prompt_docs: [], read: [], write: [], computer: "local-docker"},
      });
      this.agentLink.attachGraph(name, this.store.boardId, node.id);
      this.selectNode(node.id);
    } catch (err) {
      alert(`could not create agent node: ${err.message}`);
    }
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
    if (e.target.closest(".gear-btn")) return;
    const node = this.store.nodes[id];
    const wasSelected = this.store.selectedNodeIds.has(id);
    if (!e.shiftKey && !wasSelected) this.selectNode(id);
    else if (e.shiftKey) this.selectNode(id, true);

    // clicking an agent node opens its side panel (stays open for drag-drop)
    if (node.kind === "agent" || node.node_type === "agent") this.openAgentPanel(node);

    const descendantOrigs = {};
    if (node.kind === "folder") {
      for (const did of this.store.descendants(id)) {
        const d = this.store.nodes[did];
        descendantOrigs[did] = {x: d.x, y: d.y};
      }
    }
    this.store.dragging = {
      nodeId: id,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      origX: node.x,
      origY: node.y,
      descendantOrigs,
      moved: false,
    };
  }

  async onNodeDblClick(id) {
    const node = this.store.nodes[id];
    if (node.kind === "folder") {
      await this.store.updateNode(id, {expanded: !node.expanded});
      return;
    }
    if (node.node_type === "agent") {
      window.open(`/INT3RF4CE/?agent=${encodeURIComponent(node.ref || node.title)}`, "_blank");
      return;
    }
    if (node.kind === "obj") {
      const updates = {expanded: !node.expanded};
      if (updates.expanded) {
        updates.width = FabStore.EXPANDED_W;
        updates.height = FabStore.EXPANDED_H;
      }
      await this.store.updateNode(id, updates);
    }
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
    // highlight agent-panel drop zones while dragging a node
    if (this.panelAgent) this.setDropZonesActive(true);
    const wdx = dx / this.store.camera.zoom, wdy = dy / this.store.camera.zoom;
    const node = this.store.nodes[drag.nodeId];
    node.x = drag.origX + wdx;
    node.y = drag.origY + wdy;
    for (const did in drag.descendantOrigs) {
      const o = drag.descendantOrigs[did];
      this.store.nodes[did].x = o.x + wdx;
      this.store.nodes[did].y = o.y + wdy;
    }
    this.store.computeTempOffsets();
    this.syncNodes();
    this.syncEdges();
  }

  async onMouseUp(e) {
    const drag = this.store?.dragging;
    if (!drag) return;
    this.store.dragging = null;
    this.viewport.classList.remove("panning");
    this.setDropZonesActive(false);
    if (drag.pan || !drag.moved) return;
    const node = this.store.nodes[drag.nodeId];

    // dropped onto an agent-panel section? -> add to that list, restore position
    const zone = document.elementFromPoint(e.clientX, e.clientY)?.closest(".ap-drop");
    if (zone && this.panelAgent) {
      node.x = drag.origX;
      node.y = drag.origY;
      for (const did in drag.descendantOrigs) {
        this.store.nodes[did].x = drag.descendantOrigs[did].x;
        this.store.nodes[did].y = drag.descendantOrigs[did].y;
      }
      await this.dropIntoAgentSection(node.id, zone.dataset.drop);
      this.render();
      return;
    }

    node.x = FabStore.snap(node.x);
    node.y = FabStore.snap(node.y);
    await this.store.updateNode(drag.nodeId, {x: node.x, y: node.y});
    const posUpdates = [];
    for (const did in drag.descendantOrigs) {
      const d = this.store.nodes[did];
      d.x = FabStore.snap(d.x);
      d.y = FabStore.snap(d.y);
      posUpdates.push(this.store.updateNode(did, {x: d.x, y: d.y}));
    }
    await Promise.all(posUpdates);
    this.render();
  }

  setDropZonesActive(active) {
    for (const z of this.querySelectorAll(".ap-drop")) {
      z.classList.toggle("drag-active", active);
    }
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
      this.store.updateNode(id, {x: node.x + dx, y: node.y + dy});
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

  // ---- workflows ----

  async saveWorkflow() {
    const ids = [...this.store.selectedNodeIds];
    if (!ids.length) return alert("select nodes first (shift+click for multi-select)");
    const name = prompt("workflow name:");
    if (!name) return;
    const minX = Math.min(...ids.map(id => this.store.nodes[id].x));
    const minY = Math.min(...ids.map(id => this.store.nodes[id].y));
    const nodes = ids.map(id => {
      const n = this.store.nodes[id];
      return {
        key: id, title: n.title, kind: n.kind, node_type: n.node_type,
        state: n.state, ref: n.ref, settings: n.settings,
        rel_x: n.x - minX, rel_y: n.y - minY,
        width: n.width, height: n.height,
        parent_key: ids.includes(n.parent) ? n.parent : null,
      };
    });
    const edges = Object.values(this.store.edges)
      .filter(e => ids.includes(e.source) && ids.includes(e.target))
      .map(e => ({source_key: e.source, target_key: e.target}));
    const r = await fetch("templates", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name, nodes, edges}),
    });
    if (!r.ok) return alert("could not save workflow");
    this.renderWorkflows();
  }

  async renderWorkflows() {
    const r = await fetch("templates");
    const templates = (await r.json()).templates || {};
    for (const listId of ["#workflow-list", "#workflow-list-popup"]) {
      const list = this.querySelector(listId);
      list.innerHTML = "";
      for (const name of Object.keys(templates)) {
        const row = document.createElement("div");
        row.className = "workflow-row";
        const label = document.createElement("span");
        label.className = "type-name";
        label.textContent = name;
        row.appendChild(label);
        const insert = document.createElement("button");
        insert.textContent = "insert";
        insert.addEventListener("click", () => this.insertWorkflow(name, templates[name]));
        row.appendChild(insert);
        const del = document.createElement("button");
        del.className = "x-btn";
        del.textContent = "×";
        del.addEventListener("click", async () => {
          await fetch(`templates/${encodeURIComponent(name)}`, {method: "DELETE"});
          this.renderWorkflows();
        });
        row.appendChild(del);
        list.appendChild(row);
      }
    }
  }

  async insertWorkflow(name, template) {
    const center = this.createPosition();
    const idMap = {};
    try {
      for (const tn of template.nodes) {
        const node = await this.store.createNode({
          title: tn.title, kind: tn.kind, node_type: tn.node_type,
          state: tn.state, ref: tn.ref,
          x: center.x + tn.rel_x, y: center.y + tn.rel_y,
        });
        idMap[tn.key] = node.id;
        if (tn.settings) await this.store.updateNode(node.id, {settings: tn.settings});
        if (tn.width) await this.store.updateNode(node.id, {width: tn.width, height: tn.height});
      }
      for (const tn of template.nodes) {
        if (tn.parent_key && idMap[tn.parent_key]) {
          await this.store.updateNode(idMap[tn.key], {parent: idMap[tn.parent_key]});
        }
      }
      for (const te of template.edges) {
        if (idMap[te.source_key] && idMap[te.target_key]) {
          await this.store.createEdge(idMap[te.source_key], idMap[te.target_key]);
        }
      }
      // attach live agents for agent nodes created from the template
      for (const tn of template.nodes) {
        if (tn.node_type === "agent" && tn.ref) {
          this.agentLink.attachGraph(tn.ref, this.store.boardId, idMap[tn.key]);
        }
      }
    } catch (err) {
      alert(`workflow insert failed: ${err.message}`);
    }
  }

  // ---- agent side panel ----

  openAgentPanel(node) {
    this.panelAgent = node;
    this.querySelector("#agent-panel").classList.add("open");
    this.renderAgentPanel();
  }

  closeAgentPanel() {
    this.panelAgent = null;
    this.querySelector("#agent-panel").classList.remove("open");
  }

  agentSettings(node) {
    return Object.assign({model: "kimi-k3", prompt_docs: [], read: [], write: [], computer: "local-docker"}, node.settings || {});
  }

  async renderAgentPanel() {
    const node = this.panelAgent;
    if (!node) return;
    // node may have been deleted while the panel is open
    if (!this.store.nodes[node.id]) return this.closeAgentPanel();
    const settings = this.agentSettings(node);
    const agentName = node.ref || node.title;
    const info = this.agentLink.agentInfo(agentName);

    this.querySelector("#ap-name").textContent = agentName;
    const status = this.querySelector("#ap-status");
    const containerOn = info && info.container_on;
    const working = info && info.working;
    status.innerHTML = "";
    for (const [on, label, cls] of [[containerOn, `container ${containerOn ? "on" : "off"}`, "led-on"], [working, working ? "working" : "idle", "led-working"]]) {
      const led = document.createElement("span");
      led.className = "led" + (on ? ` ${cls}` : "");
      status.appendChild(led);
      status.appendChild(document.createTextNode(" " + label + "  "));
    }

    // model dropdown
    const modelSelect = this.querySelector("#ap-model");
    modelSelect.innerHTML = "";
    let models = {};
    try { models = await this.agentLink.listModels(); } catch (e) {}
    if (this.panelAgent !== node) return; // panel switched while loading
    const currentModel = (info && info.model) || settings.model;
    const names = Object.keys(models).length ? Object.keys(models) : [currentModel];
    for (const display of names) {
      const opt = document.createElement("option");
      opt.value = display;
      opt.textContent = display;
      if (display === currentModel || models[display] === currentModel) opt.selected = true;
      modelSelect.appendChild(opt);
    }

    // drop zones
    for (const zone of this.querySelectorAll(".ap-drop")) {
      const key = zone.dataset.drop;
      zone.innerHTML = "";
      for (const nid of settings[key] || []) {
        const n = this.store.nodes[nid];
        if (!n) continue;
        const chip = document.createElement("span");
        chip.className = "ap-chip";
        chip.textContent = n.title;
        chip.title = `${n.kind}/${n.node_type} — click × to remove`;
        const x = document.createElement("button");
        x.className = "x-btn";
        x.textContent = "×";
        x.addEventListener("click", async () => {
          const s = this.agentSettings(node);
          s[key] = (s[key] || []).filter(id => id !== nid);
          node.settings = s;
          await this.store.updateNode(node.id, {settings: s});
          this.renderAgentPanel();
        });
        chip.appendChild(x);
        zone.appendChild(chip);
      }
      if (!(settings[key] || []).length) {
        const hint = document.createElement("span");
        hint.className = "ap-hint";
        hint.textContent = "empty — drag nodes here";
        zone.appendChild(hint);
      }
    }
  }

  async onAgentModelChange() {
    const node = this.panelAgent;
    if (!node) return;
    const modelSelect = this.querySelector("#ap-model");
    const display = modelSelect.value;
    let models = {};
    try { models = await this.agentLink.listModels(); } catch (e) {}
    const model = models[display] || display;
    const agentName = node.ref || node.title;
    if (this.agentLink.agentInfo(agentName)) this.agentLink.setModel(agentName, model);
    const s = this.agentSettings(node);
    s.model = model;
    node.settings = s;
    await this.store.updateNode(node.id, {settings: s});
  }

  async dropIntoAgentSection(nodeId, key) {
    const agentNode = this.panelAgent;
    if (!agentNode || nodeId === agentNode.id) return false;
    const s = this.agentSettings(agentNode);
    s[key] = s[key] || [];
    if (s[key].includes(nodeId)) return true;
    s[key].push(nodeId);
    agentNode.settings = s;
    await this.store.updateNode(agentNode.id, {settings: s});
    this.renderAgentPanel();
    return true;
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
