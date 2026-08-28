// === access panel: per-agent thoughtgraph access, right slide-in sidebar on the board ===
// doc-level grants only, cross-board ({board, id} entries), PUT /access on every change.
// presets stamp a saved entry onto an agent. plain fetch, no websocket.

class AccessPanel {
  constructor(board) {
    this.board = board;        // FabBoard instance
    this.agent = null;
    this.access = {};          // whole access.json dict, keyed by agent
    this.presets = {};         // preset name -> access entry
    this.graphs = {};          // board id -> meta (titles for chips from other boards)
    this.armed = null;         // which list is armed ("read" | "write" | null) — board clicks grant to it
    this.el = document.getElementById("acc-panel");
    this._wire();
  }

  // ---- open / close ----

  get isOpen() { return this.el.classList.contains("open"); }

  toggle() { this.isOpen ? this.close() : this.open(); }

  // slide in + (re)load agents, access, and presets
  async open() {
    this.el.classList.add("open");
    // agents come from corechat's agents.json; access and presets are thoughtgraph's
    const [agents, access, presets] = await Promise.all([
      fetch("agents").then(r => r.json()),
      fetch("access").then(r => r.json()),
      fetch("presets").then(r => r.json()),
    ]);
    const names = agents.agents || [];
    this.access = access;
    this.presets = presets.presets || {};
    const sel = this.el.querySelector("#acc-agent");
    sel.innerHTML = "";
    for (const name of names) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    }
    // keep the current pick if the agent still exists, else take the first
    this.agent = names.includes(this.agent) ? this.agent : (names[0] || null);
    sel.value = this.agent || "";
    this.renderPresets();
    this.loadGraphsThenRender();
  }

  close() {
    // closing the panel always disarms
    this.armed = null;
    for (const z of this.el.querySelectorAll(".acc-list")) z.classList.remove("armed");
    this.el.classList.remove("open");
  }

  // ---- events ----

  // bind every control on the static skeleton (index.html)
  _wire() {
    this.el.querySelector("#acc-close").addEventListener("click", () => this.close());
    // clicking a list's empty area arms it: board clicks now grant docs to it
    for (const list of this.el.querySelectorAll(".acc-list")) {
      list.addEventListener("click", (e) => {
        if (e.target.closest(".acc-chip")) return;  // chips manage themselves
        this.toggleArm(list.dataset.key);
      });
    }
    this.el.querySelector("#acc-agent").addEventListener("change", (e) => {
      this.agent = e.target.value || null;
      this.renderPresets();
      this.loadGraphsThenRender();
    });
    this.el.querySelector("#acc-preset-save").addEventListener("click", async () => {
      const name = this.el.querySelector("#acc-preset-name").value.trim();
      if (!name || !this.agent) return;
      await fetch("presets/save", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, agent: this.agent}),
      });
      const r = await fetch("presets");
      this.presets = (await r.json()).presets || {};
      this.renderPresets();
      this.el.querySelector("#acc-preset-name").value = "";
    });
    this.el.querySelector("#acc-preset-load").addEventListener("click", async () => {
      const name = this.el.querySelector("#acc-preset-select").value;
      if (!name || !this.agent) return;
      await fetch("presets/load", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, agent: this.agent}),
      });
      // the server replaced the agent's entry — pull the fresh access dict
      const r = await fetch("access");
      this.access = await r.json();
      this.loadGraphsThenRender();
    });
  }

  // ---- state + fetching ----

  // the current agent's lists; missing entry = two empty lists
  entry() {
    if (!this.agent) return {read: [], write: []};
    if (!this.access[this.agent]) this.access[this.agent] = {read: [], write: []};
    return this.access[this.agent];
  }

  // PUT the whole access dict
  async save() {
    await fetch("access", {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(this.access),
    });
  }

  // fetch every board the chips reference once, then render (cross-board titles)
  async loadGraphsThenRender() {
    const boards = new Set();
    const entry = this.entry();
    for (const k of ["read", "write"]) {
      for (const e of entry[k]) boards.add(e.board);
    }
    await Promise.all([...boards].map(async (b) => {
      if (this.graphs[b]) return;
      const r = await fetch(`boards/${encodeURIComponent(b)}/graph`);
      if (r.ok) this.graphs[b] = await r.json();
    }));
    this.render();
  }

  // ---- rendering ----

  entryLabel(e) {
    // current board's nodes are already in the store; others come from fetched graphs
    if (e.board === this.board.store.boardId && this.board.store.nodes[e.id]) {
      return this.board.store.nodes[e.id].title;
    }
    const meta = this.graphs[e.board];
    const node = meta && meta.nodes && meta.nodes[e.id];
    return node ? node.title : e.id;
  }

  // rebuild the two chip lists (read / write)
  render() {
    const entry = this.entry();
    for (const [key, elId] of [["read", "#acc-read"], ["write", "#acc-write"]]) {
      const list = this.el.querySelector(elId);
      list.innerHTML = "";
      const entries = entry[key];
      entries.forEach((e, idx) => {
        const chip = document.createElement("span");
        chip.className = "acc-chip";
        const label = document.createElement("span");
        label.textContent = this.entryLabel(e);
        chip.appendChild(label);
        const btag = document.createElement("span");
        btag.className = "acc-board-tag";
        btag.textContent = e.board;
        chip.appendChild(btag);
        const x = document.createElement("button");
        x.textContent = "×";
        x.addEventListener("click", () => {
          entry[key] = entries.filter(o => !(o.board === e.board && o.id === e.id));
          this.save();
          this.render();
        });
        chip.appendChild(x);
        list.appendChild(chip);
      });
      if (!entries.length) {
        const hint = document.createElement("span");
        hint.className = "acc-hint";
        hint.textContent = "empty";
        list.appendChild(hint);
      }
    }
  }

  // ---- presets ----

  renderPresets() {
    const sel = this.el.querySelector("#acc-preset-select");
    sel.innerHTML = "";
    for (const name of Object.keys(this.presets)) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    }
    // everything below is a nop until an agent is picked
    const noAgent = !this.agent;
    this.el.querySelector("#acc-preset-name").disabled = noAgent;
    this.el.querySelector("#acc-preset-save").disabled = noAgent;
    this.el.querySelector("#acc-preset-select").disabled = noAgent;
    this.el.querySelector("#acc-preset-load").disabled = noAgent;
  }

  // ---- grants ----

  // arm/disarm a grant list: while armed, clicking board docs adds them to it
  toggleArm(key) {
    this.armed = this.armed === key ? null : key;
    for (const z of this.el.querySelectorAll(".acc-list")) {
      z.classList.toggle("armed", z.dataset.key === this.armed);
    }
  }

  // a board node clicked while armed: validate, append, save
  addEntry(key, boardId, nodeId) {
    const err = this.el.querySelector(".acc-error");
    if (!this.agent) {
      err.textContent = "pick an agent first";
      return;
    }
    const node = this.board.store.nodes[nodeId];
    if (node && node.kind === "folder") {
      err.textContent = "doc-level grants only — folders can't be granted";
      return;
    }
    const entries = this.entry()[key];
    if (entries.some(e => e.board === boardId && e.id === nodeId)) return;  // duplicates ignored
    entries.push({board: boardId, id: nodeId});
    err.textContent = "";  // the new chip is the confirmation
    this.save();
    this.loadGraphsThenRender();
  }
}
