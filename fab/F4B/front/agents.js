// === fab-agents: WebSocket client to /INT3RF4CE/ws ===
// tracks live agent info and provides request/response helpers for settings commands.

class AgentLink {
  constructor() {
    this.ws = null;
    this.agents = {};
    this.handlers = [];
    this.pending = {}; // msgType -> [{filter, resolve}, ...]
    this.authBlocked = false;
    this.connect();
  }

  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/INT3RF4CE/ws`);

    this.ws.onopen = () => this.send({cmd: "list"});

    this.ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      if (msg.type === "agents") this.agents = msg.agents || {};
      if (msg.type === "auth_required") this.authBlocked = true;
      const waiters = this.pending[msg.type];
      if (waiters && waiters.length) {
        this.pending[msg.type] = waiters.filter(w => {
          if (!w.filter || w.filter(msg)) { w.resolve(msg); return false; }
          return true;
        });
      }
      this.handlers.forEach(h => h(msg));
    };

    this.ws.onclose = () => {
      if (this.authBlocked) return;
      setTimeout(() => this.connect(), 2000);
    };

    this.ws.onerror = () => {};
  }

  send(cmd) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(cmd));
    }
  }

  // resolve with the next message of `type` passing `filter`
  once(type, filter, timeoutMs = 5000) {
    return new Promise((resolve, reject) => {
      const waiter = {filter, resolve};
      this.pending[type] = this.pending[type] || [];
      this.pending[type].push(waiter);
      setTimeout(() => {
        const arr = this.pending[type] || [];
        const i = arr.indexOf(waiter);
        if (i >= 0) { arr.splice(i, 1); reject(new Error(`timeout waiting for ${type}`)); }
      }, timeoutMs);
    });
  }

  onMessage(handler) { this.handlers.push(handler); }

  agentInfo(name) { return this.agents[name] || null; }

  listModels() {
    this.send({cmd: "list_models"});
    return this.once("models").then(m => m.models);
  }

  listPrompts() {
    this.send({cmd: "list_prompts"});
    return this.once("prompts").then(m => m.prompts);
  }

  getSelectedPrompts(name) {
    this.send({cmd: "get_selected_prompts", name});
    return this.once("selected_prompts", m => m.name === name).then(m => m.selected);
  }

  setSelectedPrompts(name, selected) { this.send({cmd: "set_selected_prompts", name, selected}); }

  setModel(name, model) { this.send({cmd: "set_model", name, model}); }

  attachGraph(name, board, node) { this.send({cmd: "attach_graph", name, board, node}); }

  detachGraph(name) { this.send({cmd: "detach_graph", name}); }

  // create the INT3RF4CE agent; ok even if it already exists
  async createAgent(name) {
    const created = this.once("agents", m => m.agents && m.agents[name], 3000).then(() => true).catch(() => false);
    const errored = this.once("error", null, 3000).then(m => m.msg).catch(() => null);
    this.send({cmd: "create", name});
    const [ok, err] = await Promise.all([created, errored]);
    if (ok) return {ok: true};
    if (err && err.includes("already exists")) return {ok: true, existed: true};
    if (this.agents[name]) return {ok: true};
    return {ok: false, msg: err || "create failed"};
  }
}
