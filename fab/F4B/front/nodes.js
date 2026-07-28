// === fab-nodes: obj / func / agent / folder node elements ===

class FabNode extends HTMLElement {
  constructor() {
    super();
    this._node = null;
    this._rect = null;
  }

  static get observedAttributes() { return ["selected"]; }

  set node(v) { this._node = v; this.render(); }
  get node() { return this._node; }
  set rect(v) { this._rect = v; this.render(); }
  get rect() { return this._rect; }

  attributeChangedCallback(name, oldV, newV) { if (name === "selected") this.render(); }

  get selected() { return this.hasAttribute("selected"); }
  set selected(v) { v ? this.setAttribute("selected", "") : this.removeAttribute("selected"); }

  connectedCallback() {
    this.addEventListener("mousedown", (e) => this.onMouseDown(e));
    this.addEventListener("dblclick", (e) => this.onDblClick(e));
    this.render();
  }

  render() {
    const node = this._node, r = this._rect;
    if (!node || !r) return;
    this.className = `fab-node kind-${node.kind}`;
    this.dataset.id = node.id;
    if (this.selected) this.classList.add("selected");
    if (node.expanded) this.classList.add("expanded");
    this.style.left = r.x + "px";
    this.style.top = r.y + "px";
    this.style.width = r.w + "px";
    this.style.height = r.h + "px";
    this.updateContent(node);
  }

  updateContent(node) {}

  onMouseDown(e) {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "BUTTON") return;
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("node-mousedown", {
      detail: {node: this._node, originalEvent: e}, bubbles: true,
    }));
  }

  onDblClick(e) {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "BUTTON") return;
    if (e.target.closest(".md-editor")) return; // double-clicking inside the editor must not collapse the node
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("node-dblclick", {
      detail: {node: this._node}, bubbles: true,
    }));
  }
}

// ---- obj node: typed rectangle, state dot, ref badge; expands into markdown editor ----

class ObjNode extends FabNode {
  updateContent(node) {
    const color = this.store?.typeColor(node) || node.__color || "#E2E8F0";
    this.style.setProperty("--nc", color);
    if (this.querySelector(".title") && node.expanded === this.__wasExpanded) {
      this.querySelector(".title").textContent = node.title;
      this.renderStateDot(node);
      return;
    }
    this.__wasExpanded = node.expanded;
    this.innerHTML = "";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = node.title;
    this.appendChild(title);
    this.appendChild(this.makeStateDot(node));
    if (node.ref && !node.expanded) {
      const badge = document.createElement("div");
      badge.className = "ref-badge";
      badge.textContent = node.ref;
      badge.title = node.ref;
      this.appendChild(badge);
    }
    const typeLabel = document.createElement("div");
    typeLabel.className = "type-label";
    typeLabel.textContent = node.node_type;
    this.appendChild(typeLabel);
    if (node.expanded) {
      const editor = document.createElement("markdown-editor");
      editor.className = "md-editor";
      // empty docs have a zero-height preview — let a click anywhere in the
      // editor area (not just on text) open the textarea for typing
      editor.addEventListener("click", (e) => {
        if (e.target.closest("a.wikilink")) return;
        if (e.target.tagName === "TEXTAREA") return;
        editor.showEditor();
      });
      editor.addEventListener("mousedown", (e) => e.stopPropagation());
      this.appendChild(editor);
      this.dispatchEvent(new CustomEvent("doc-expand", {
        detail: {node, editor}, bubbles: true,
      }));
    }
  }

  makeStateDot(node) {
    const dot = document.createElement("div");
    dot.className = "state-dot" + (node.state ? ` state-${node.state}` : "");
    if (node.state) dot.title = node.state;
    return dot;
  }

  renderStateDot(node) {
    const old = this.querySelector(".state-dot");
    if (old) old.replaceWith(this.makeStateDot(node));
    this.querySelector(".title").textContent = node.title;
  }
}

// ---- func node: circle at grid intersection. funcs have NO names — only type + color ----

class FuncNode extends FabNode {
  updateContent(node) {
    const color = this.store?.typeColor(node) || node.__color || "#E2E8F0";
    this.style.setProperty("--nc", color);
    if (this.querySelector(".func-type")) {
      this.querySelector(".func-type").textContent = node.node_type;
      return;
    }
    this.innerHTML = "";
    const typeLabel = document.createElement("div");
    typeLabel.className = "func-type";
    typeLabel.textContent = node.node_type;
    this.appendChild(typeLabel);
  }
}

// ---- agent node: obj rectangle + live status LEDs + settings button ----

class AgentNode extends FabNode {
  updateContent(node) {
    this.style.setProperty("--nc", this.store?.typeColor(node) || "#00FF41");
    const info = (this.agentInfo || {})[node.ref] || {};
    const containerOn = !!info.container_on;
    const working = !!info.working;
    const key = `${node.title}|${containerOn}|${working}|${info.model || ""}`;
    if (this.__key === key) return;
    this.__key = key;
    this.innerHTML = "";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = node.title;
    this.appendChild(title);
    const leds = document.createElement("div");
    leds.className = "led-row";
    const cLed = document.createElement("span");
    cLed.className = "led" + (containerOn ? " led-on" : "");
    cLed.title = containerOn ? "container on" : "container off";
    leds.appendChild(cLed);
    const wLed = document.createElement("span");
    wLed.className = "led" + (working ? " led-working" : "");
    wLed.title = working ? "working" : "idle";
    leds.appendChild(wLed);
    this.appendChild(leds);
    const model = document.createElement("div");
    model.className = "type-label";
    model.textContent = info.model || (node.settings && node.settings.model) || "agent";
    this.appendChild(model);
    const gear = document.createElement("button");
    gear.className = "gear-btn";
    gear.textContent = "⚙";
    gear.title = "agent settings";
    gear.addEventListener("mousedown", (e) => e.stopPropagation());
    gear.addEventListener("dblclick", (e) => e.stopPropagation());
    gear.addEventListener("click", (e) => {
      e.stopPropagation();
      this.dispatchEvent(new CustomEvent("agent-settings", {
        detail: {node}, bubbles: true,
      }));
    });
    this.appendChild(gear);
  }
}

// ---- folder node: collapsed dashed square / expanded container ----

class FolderNode extends FabNode {
  updateContent(node) {
    this.style.setProperty("--nc", node.color || "#B8A0FF");
    if (this.querySelector(".title")) {
      this.querySelector(".title").textContent = node.title;
      return;
    }
    this.innerHTML = "";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = node.title;
    this.appendChild(title);
  }
}

customElements.define("obj-node", ObjNode);
customElements.define("func-node", FuncNode);
customElements.define("agent-node", AgentNode);
customElements.define("folder-node", FolderNode);
