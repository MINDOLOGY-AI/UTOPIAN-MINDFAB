// === fab-nodes: doc / folder node elements ===

// ---- base node element: position, selection, drag/dblclick bubbling ----

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

  // reflect node+rect into classes and inline position/size
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

  // subclass hook: rebuild the inner dom
  updateContent(node) {}

  // clicks on buttons/textarea stay local; everything else bubbles up as node-mousedown
  onMouseDown(e) {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "BUTTON") return;
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("node-mousedown", {
      detail: {node: this._node, originalEvent: e}, bubbles: true,
    }));
  }

  // dblclick bubbles up as node-dblclick unless it landed in the editor or grip
  onDblClick(e) {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "BUTTON") return;
    // double-clicking inside the editor must not collapse the node
    if (e.target.closest(".md-editor")) return;
    // gripping the corner is not a collapse
    if (e.target.closest(".resize-grip")) return;
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("node-dblclick", {
      detail: {node: this._node}, bubbles: true,
    }));
  }
}

// ---- doc node: typed rectangle, ref badge; expands into markdown editor ----

class DocNode extends FabNode {
  // title + type label; expanded also mounts the markdown editor and resize grip
  updateContent(node) {
    // store is always set by the board before the first render; typeColor
    // itself falls back to #E2E8F0 for unknown types
    const color = this.store.typeColor(node);
    this.style.setProperty("--nc", color);
    if (this.querySelector(".title") && node.expanded === this.__wasExpanded) {
      this.querySelector(".title").textContent = node.title;
      return;
    }
    this.__wasExpanded = node.expanded;
    this.innerHTML = "";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = node.title;
    this.appendChild(title);
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
      // bottom-right grip: stretch the expanded doc (glides mid-drag, snaps to
      // whole grid cells on release); the size lives on node.width/height
      const grip = document.createElement("div");
      grip.className = "resize-grip";
      grip.addEventListener("mousedown", (e) => {
        e.stopPropagation();
        e.preventDefault();
        this.dispatchEvent(new CustomEvent("node-resize-start", {
          detail: {node: this._node, originalEvent: e}, bubbles: true,
        }));
      });
      this.appendChild(grip);
      this.dispatchEvent(new CustomEvent("doc-expand", {
        detail: {node, editor}, bubbles: true,
      }));
    }
  }
}

// ---- folder node: collapsed dashed square / expanded container ----

class FolderNode extends FabNode {
  // expanded folders are grabbable only by the frame + floating title —
  // interior clicks fall through to the viewport (pan / deselect), so working
  // inside a folder never accidentally activates it or collapses it via a
  // double-click. the top band is MARGIN deep: exactly the exposed strip
  // between the frame line and the top row of children
  _onFrame(e) {
    const r = this.getBoundingClientRect();
    const B = 14;
    return e.clientY - r.top < FabStore.MARGIN ||
           r.bottom - e.clientY < B ||
           e.clientX - r.left < B ||
           r.right - e.clientX < B;
  }

  // expanded folder: only frame clicks count; interior falls through to the viewport
  onMouseDown(e) {
    if (this._node?.expanded && !this._onFrame(e)) return;
    super.onMouseDown(e);
  }

  onDblClick(e) {
    if (this._node?.expanded && !this._onFrame(e)) return;
    super.onDblClick(e);
  }

  // just the title text; floated above the frame when expanded (see applyLadder)
  updateContent(node) {
    this.style.setProperty("--nc", "var(--text)");
    const existing = this.querySelector(".title");
    if (existing) {
      existing.textContent = node.title;
      this.applyLadder(existing, node);
      return;
    }
    this.innerHTML = "";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = node.title;
    this.applyLadder(title, node);
    this.appendChild(title);
  }

  // expanded folder titles float above the frame line as pure text; a shared
  // corner stacks them: deepest right above the line, each outer level higher
  applyLadder(title, node) {
    if (!node.expanded) {
      title.classList.remove("floating");
      title.style.top = "";
      return;
    }
    const idx = this.ladderIndex || 0;
    title.classList.add("floating");
    title.style.top = `${-24 - idx * 20}px`;
  }
}

customElements.define("doc-node", DocNode);
customElements.define("folder-node", FolderNode);
