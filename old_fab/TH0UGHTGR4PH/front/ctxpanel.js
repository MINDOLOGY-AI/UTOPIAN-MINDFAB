// === ctx-panel: context management for an INT3RF4CE agent, on the board page ===
// opened via /TH0UGHTGR4PH/?agent=<name>. right sidebar on top of the normal board.
// settings = {prompt_docs, read, write, time, folders} of {"board": b, "id": nid} entries,
// stored in INT3RF4CE config/specific/{agent}/graph.json via its websocket.
// folders = total control: the agent can read/create/edit/move/link everything inside.
// time = to-do access: the agent may flip task states (todo/doing/done) on those
// nodes. write does NOT imply time.
// secrets: names dragged from the pool into the granted list, stored in
// config/specific/{agent}/secrets.json — the agent reads them with READ_SECRETS.
// compute: click a free machine in the pool to assign it to the agent
// (assign_compute/unassign_compute over the same websocket).
// dropping a FOLDER into the to-do list expands to every stateful node inside it.

class CtxPanel {
  constructor(board, agentName) {
    this.board = board;          // FabBoard instance
    this.agent = agentName;
    this.settings = {prompt_docs: [], read: [], write: [], time: [], folders: []};
    this.files = [];
    this.secretNames = [];       // every secret name in the user's store
    this.secretGrants = [];      // names granted to this agent
    this.computes = [];          // [{name, ssh_command, used_by}] from list_computes
    this.graphs = {};            // board_id -> meta (for titles across boards)
    this.ws = null;
    this.el = document.getElementById("ctx-panel");
    this.el.classList.add("open");
    this._wire();
    this.connect();
  }

  // the skeleton lives in index.html; here we fill in the agent-specific bits + events
  _wire() {
    this.el.querySelector(".ctx-agent").textContent = this.agent;
    this.el.querySelector("#ctx-done").href = `/INT3RF4CE/?agent=${encodeURIComponent(this.agent)}`;
    this.el.querySelector("#ctx-close").addEventListener("click", () => this.close());
    this._wireSecretDrop(this.el.querySelector("#ctx-secrets"), "grants");
    this._wireSecretDrop(this.el.querySelector("#ctx-secret-pool"), "pool");
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
      this.send({cmd: "list_secrets"});
      this.send({cmd: "get_secret_grants", name: this.agent});
      this.send({cmd: "list_computes"});
    };
    this.ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      if (msg.type === "graph_settings" && msg.name === this.agent) {
        this.settings = msg.settings || {prompt_docs: [], read: [], write: [], time: [], folders: []};
        for (const k of ["prompt_docs", "read", "write", "time", "folders"]) this.settings[k] = this.settings[k] || [];
        this.loadGraphsThenRender();
      }
      if (msg.type === "settings_files") {
        this.files = msg.files || [];
        this.renderFiles();
      }
      if (msg.type === "secrets") {
        this.secretNames = (msg.secrets || []).map(s => s.name);
        this.renderSecrets();
      }
      if (msg.type === "secret_grants" && msg.name === this.agent) {
        this.secretGrants = msg.grants || [];
        this.renderSecrets();
      }
      if (msg.type === "computes") {
        this.computes = msg.computes || [];
        this.renderComputes();
      }
      if (msg.type === "error") {
        const err = this.el.querySelector(".ctx-error");
        if (err) err.textContent = msg.msg;
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
    for (const k of ["prompt_docs", "read", "write", "time", "folders"]) {
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
    for (const [key, elId] of [["prompt_docs", "#ctx-prompts"], ["read", "#ctx-read"], ["write", "#ctx-write"], ["time", "#ctx-time"], ["folders", "#ctx-folders"]]) {
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
        if ((key === "prompt_docs" || key === "time") && idx > 0) {
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

  _secretChip(name, from) {
    const chip = document.createElement("span");
    chip.className = "ctx-chip ctx-secret-chip";
    chip.draggable = true;
    chip.textContent = name;
    chip.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/secret", JSON.stringify({name, from}));
      e.stopPropagation(); // not a board-node drag
    });
    if (from === "grants") {
      const x = document.createElement("button");
      x.textContent = "×";
      x.addEventListener("click", () => {
        this.secretGrants = this.secretGrants.filter(g => g !== name);
        this.send({cmd: "set_secret_grants", name: this.agent, grants: this.secretGrants});
        this.renderSecrets();
      });
      chip.appendChild(x);
    }
    return chip;
  }

  _wireSecretDrop(zone, to) {
    zone.addEventListener("dragover", (e) => {
      if (e.dataTransfer.types.includes("text/secret")) {
        e.preventDefault();
        zone.classList.add("drag-active");
      }
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-active"));
    zone.addEventListener("drop", (e) => {
      zone.classList.remove("drag-active");
      const raw = e.dataTransfer.getData("text/secret");
      if (!raw) return; // not a secret chip — let other handlers deal with it
      e.preventDefault();
      e.stopPropagation();
      const {name} = JSON.parse(raw);
      if (to === "grants" && !this.secretGrants.includes(name)) this.secretGrants.push(name);
      if (to === "pool") this.secretGrants = this.secretGrants.filter(g => g !== name);
      this.send({cmd: "set_secret_grants", name: this.agent, grants: this.secretGrants});
      this.renderSecrets();
    });
  }

  renderSecrets() {
    const grantsEl = this.el.querySelector("#ctx-secrets");
    const poolEl = this.el.querySelector("#ctx-secret-pool");
    grantsEl.innerHTML = "";
    poolEl.innerHTML = "";
    for (const name of this.secretGrants) grantsEl.appendChild(this._secretChip(name, "grants"));
    for (const name of this.secretNames.filter(n => !this.secretGrants.includes(n))) {
      poolEl.appendChild(this._secretChip(name, "pool"));
    }
    if (!this.secretGrants.length) {
      const hint = document.createElement("span");
      hint.className = "ctx-hint";
      hint.textContent = "empty";
      grantsEl.appendChild(hint);
    }
    if (!this.secretNames.length) {
      const hint = document.createElement("span");
      hint.className = "ctx-hint";
      hint.textContent = "empty";
      poolEl.appendChild(hint);
    }
  }

  renderComputes() {
    const mineEl = this.el.querySelector("#ctx-compute");
    const poolEl = this.el.querySelector("#ctx-compute-pool");
    mineEl.innerHTML = "";
    poolEl.innerHTML = "";
    for (const c of this.computes) {
      const chip = document.createElement("span");
      chip.className = "ctx-chip";
      if (c.used_by === this.agent) {
        // assigned to this agent — × releases it
        chip.textContent = c.name;
        const x = document.createElement("button");
        x.textContent = "×";
        x.addEventListener("click", () => this.send({cmd: "unassign_compute", name: this.agent, compute: c.name}));
        chip.appendChild(x);
        mineEl.appendChild(chip);
      } else if (!c.used_by) {
        // free — click assigns it to this agent
        chip.textContent = c.name;
        chip.classList.add("ctx-chip-click");
        chip.title = "assign to " + this.agent;
        chip.addEventListener("click", () => this.send({cmd: "assign_compute", name: this.agent, compute: c.name}));
        poolEl.appendChild(chip);
      } else {
        // held by someone else — display only
        chip.textContent = `${c.name} (${c.used_by})`;
        chip.classList.add("ctx-chip-held");
        poolEl.appendChild(chip);
      }
    }
    for (const [el, list] of [[mineEl, this.computes.filter(c => c.used_by === this.agent)], [poolEl, this.computes]]) {
      if (!list.length) {
        const hint = document.createElement("span");
        hint.className = "ctx-hint";
        hint.textContent = "empty";
        el.appendChild(hint);
      }
    }
  }

  addEntry(key, boardId, nodeId) {
    const node = this.board.store.nodes[nodeId];
    if (key === "folders" && node && node.kind !== "folder") {
      const err = this.el.querySelector(".ctx-error");
      if (err) err.textContent = "total control only accepts folders";
      return;
    }
    if (key === "time" && node && node.kind === "folder") {
      // a folder dropped into to-do expands to every stateful node inside it (recursive)
      const nodes = this.board.store.nodes;
      const tasks = Object.values(nodes).filter(n => {
        if (!n.state) return false;
        let cur = n.parent;
        while (cur) {
          if (cur === nodeId) return true;
          cur = nodes[cur] ? nodes[cur].parent : null;
        }
        return false;
      });
      const err = this.el.querySelector(".ctx-error");
      if (!tasks.length) {
        if (err) err.textContent = "no task nodes inside that folder";
        return;
      }
      for (const t of tasks) {
        if (!this.settings.time.some(e => e.board === boardId && e.id === t.id)) {
          this.settings.time.push({board: boardId, id: t.id});
        }
      }
      if (err) err.textContent = "";
      this.save();
      this.loadGraphsThenRender();
      return;
    }
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
