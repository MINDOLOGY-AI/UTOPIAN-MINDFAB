// === ctx-panel: context management for an INT3RF4CE agent, on the board page ===
// opened via /TH0UGHTGR4PH/?agent=<name>. right sidebar on top of the normal board.
// settings = {prompt_docs, read, write} of {"board": b, "id": nid} entries,
// stored in INT3RF4CE config/specific/{agent}/graph.json via its websocket.

class CtxPanel {
  constructor(board, agentName) {
    this.board = board;          // FabBoard instance
    this.agent = agentName;
    this.settings = {prompt_docs: [], read: [], write: []};
    this.files = [];
    this.graphs = {};            // board_id -> meta (for titles across boards)
    this.ws = null;
    this.el = document.getElementById("ctx-panel");
    this.el.classList.add("open");
    this.build();
    this.connect();
  }

  build() {
    this.el.innerHTML = `
      <div class="ctx-header">
        <span class="ctx-agent">${this.agent}</span>
        <button id="ctx-close" class="x-btn">×</button>
      </div>
      <div class="ctx-sub">prompts — in order, part of the system prompt</div>
      <div class="ctx-list ctx-drop" data-key="prompt_docs" id="ctx-prompts"></div>
      <div class="ctx-sub">read access</div>
      <div class="ctx-list ctx-drop" data-key="read" id="ctx-read"></div>
      <div class="ctx-sub">write access (implies read)</div>
      <div class="ctx-list ctx-drop" data-key="write" id="ctx-write"></div>
      <div class="ctx-hint">drag docs from the board into a section</div>
      <div class="ctx-sub">settings file</div>
      <div class="ctx-file-row">
        <input id="ctx-file-name" placeholder="settings name" spellcheck="false">
        <button id="ctx-file-save">save</button>
      </div>
      <div class="ctx-file-row">
        <select id="ctx-file-select"></select>
        <button id="ctx-file-load">load</button>
      </div>
      <a id="ctx-done" href="/INT3RF4CE/?agent=${encodeURIComponent(this.agent)}">done →</a>
    `;
    this.el.querySelector("#ctx-close").addEventListener("click", () => this.close());
    this.el.querySelector("#ctx-file-save").addEventListener("click", () => {
      const name = this.el.querySelector("#ctx-file-name").value.trim();
      if (name) this.send({cmd: "save_settings_file", name: this.agent, file_name: name});
    });
    this.el.querySelector("#ctx-file-load").addEventListener("click", () => {
      const name = this.el.querySelector("#ctx-file-select").value;
      if (name) this.send({cmd: "load_settings_file", name: this.agent, file_name: name});
    });
  }

  close() {
    this.el.classList.remove("open");
    if (this.ws) this.ws.close();
    this.board.ctxPanel = null;
  }

  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/INT3RF4CE/ws`);
    this.ws.onopen = () => {
      this.send({cmd: "get_graph_settings", name: this.agent});
      this.send({cmd: "list_settings_files"});
    };
    this.ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      if (msg.type === "graph_settings" && msg.name === this.agent) {
        this.settings = msg.settings || {prompt_docs: [], read: [], write: []};
        for (const k of ["prompt_docs", "read", "write"]) this.settings[k] = this.settings[k] || [];
        this.loadGraphsThenRender();
      }
      if (msg.type === "settings_files") {
        this.files = msg.files || [];
        this.renderFiles();
      }
      if (msg.type === "error") {
        const hint = this.el.querySelector(".ctx-hint");
        if (hint) hint.textContent = msg.msg;
      }
    };
    this.ws.onclose = () => {
      if (this.board.ctxPanel === this) setTimeout(() => this.connect(), 2000);
    };
  }

  send(cmd) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(cmd));
  }

  save() {
    this.send({cmd: "set_graph_settings", name: this.agent, settings: this.settings});
  }

  async loadGraphsThenRender() {
    const boards = new Set();
    for (const k of ["prompt_docs", "read", "write"]) {
      for (const e of this.settings[k]) boards.add(e.board);
    }
    await Promise.all([...boards].map(async (b) => {
      if (this.graphs[b]) return;
      try {
        const r = await fetch(`boards/${encodeURIComponent(b)}/graph`);
        if (r.ok) this.graphs[b] = await r.json();
      } catch (e) {}
    }));
    this.render();
  }

  entryLabel(e) {
    // current board's nodes are already in the store; others come from fetched graphs
    if (e.board === this.board.store.boardId && this.board.store.nodes[e.id]) {
      return this.board.store.nodes[e.id].title;
    }
    const meta = this.graphs[e.board];
    const node = meta && meta.nodes && meta.nodes[e.id];
    return node ? node.title : e.id;
  }

  render() {
    for (const [key, elId] of [["prompt_docs", "#ctx-prompts"], ["read", "#ctx-read"], ["write", "#ctx-write"]]) {
      const list = this.el.querySelector(elId);
      list.innerHTML = "";
      const entries = this.settings[key];
      entries.forEach((e, idx) => {
        const chip = document.createElement("span");
        chip.className = "ctx-chip";
        const label = document.createElement("span");
        label.textContent = this.entryLabel(e);
        chip.appendChild(label);
        const btag = document.createElement("span");
        btag.className = "ctx-board-tag";
        btag.textContent = e.board;
        chip.appendChild(btag);
        if (key === "prompt_docs" && idx > 0) {
          const up = document.createElement("button");
          up.textContent = "↑";
          up.title = "move up";
          up.addEventListener("click", () => {
            [entries[idx - 1], entries[idx]] = [entries[idx], entries[idx - 1]];
            this.save();
            this.render();
          });
          chip.appendChild(up);
        }
        const x = document.createElement("button");
        x.textContent = "×";
        x.addEventListener("click", () => {
          this.settings[key] = entries.filter(o => !(o.board === e.board && o.id === e.id));
          this.save();
          this.render();
        });
        chip.appendChild(x);
        list.appendChild(chip);
      });
      if (!entries.length) {
        const hint = document.createElement("span");
        hint.className = "ctx-hint";
        hint.textContent = "empty";
        list.appendChild(hint);
      }
    }
  }

  renderFiles() {
    const sel = this.el.querySelector("#ctx-file-select");
    sel.innerHTML = "";
    for (const f of this.files) {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      sel.appendChild(opt);
    }
  }

  addEntry(key, boardId, nodeId) {
    const entries = this.settings[key];
    if (entries.some(e => e.board === boardId && e.id === nodeId)) return;
    entries.push({board: boardId, id: nodeId});
    this.save();
    this.loadGraphsThenRender();
  }

  setDropActive(active) {
    for (const z of this.el.querySelectorAll(".ctx-drop")) {
      z.classList.toggle("drag-active", active);
    }
  }
}
