// === fab-nodes: obj / func / folder node elements ===

class FabNode extends HTMLElement {
  constructor() {
    super();
    this._node = null;
    this._rect = null;
  }

  static get observedAttributes() { return ["selected", "active"]; }

  set node(v) { this._node = v; this.render(); }
  get node() { return this._node; }
  set rect(v) { this._rect = v; this.render(); }
  get rect() { return this._rect; }

  attributeChangedCallback(name, oldV, newV) { if (name === "selected" || name === "active") this.render(); }

  get selected() { return this.hasAttribute("selected"); }
  set selected(v) { v ? this.setAttribute("selected", "") : this.removeAttribute("selected"); }
  get active() { return this.hasAttribute("active"); }
  set active(v) { v ? this.setAttribute("active", "") : this.removeAttribute("active"); }

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
    if (this.active) this.classList.add("active");
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

// ---- doc node: typed rectangle, state dot, ref badge; expands into markdown editor ----

class DocNode extends FabNode {
  updateContent(node) {
    // store is always set by the board before the first render; typeColor
    // itself falls back to #E2E8F0 for unknown types
    const color = this.store.typeColor(node);
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
  }
}

// ---- folder node: collapsed dashed square / expanded container ----

class FolderNode extends FabNode {
  // expanded folders are grabbable only by the frame + title bar — interior
  // clicks fall through to the viewport (pan / deselect), so working inside a
  // folder never accidentally activates it or collapses it via a double-click
  _onFrame(e) {
    const r = this.getBoundingClientRect();
    const B = 14;
    return e.clientY - r.top < FabStore.FOLDER_PAD.top ||
           r.bottom - e.clientY < B ||
           e.clientX - r.left < B ||
           r.right - e.clientX < B;
  }

  onMouseDown(e) {
    if (this._node?.expanded && !this._onFrame(e)) return;
    super.onMouseDown(e);
  }

  onDblClick(e) {
    if (this._node?.expanded && !this._onFrame(e)) return;
    super.onDblClick(e);
  }

  updateContent(node) {
    this.style.setProperty("--nc", "var(--near-white, #C5C5C5)");
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

customElements.define("doc-node", DocNode);
customElements.define("folder-node", FolderNode);
