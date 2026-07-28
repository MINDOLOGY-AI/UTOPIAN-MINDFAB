// === GraphNode: reusable graph node custom elements ===
//
// Intended parent: a graph-board-like controller that sets:
//   el.node    = { id, type, title, expanded, ... }
//   el.rect    = { x, y, w, h }
//   el.selected = boolean
// and listens for:
//   node-mousedown  { node, originalEvent }
//   node-dblclick   { node }
//   node-resize     { node, width, height }   (DocNode only)
//   content-change  { detail: content }       (bubbled from DocNode)
//   wikilink-click  { detail: nodeId }        (bubbled from DocNode)

class GraphNode extends HTMLElement {
  constructor() {
    super();
    this._node = null;
    this._rect = null;
  }

  static get observedAttributes() {
    return ["selected"];
  }

  set node(value) {
    this._node = value;
    this.render();
  }

  get node() {
    return this._node;
  }

  set rect(value) {
    this._rect = value;
    this.render();
  }

  get rect() {
    return this._rect;
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (name === "selected") this.render();
  }

  get selected() {
    return this.hasAttribute("selected");
  }

  set selected(value) {
    if (value) this.setAttribute("selected", "");
    else this.removeAttribute("selected");
  }

  connectedCallback() {
    this.addEventListener("mousedown", (e) => this.onMouseDown(e));
    this.addEventListener("dblclick", (e) => this.onDblClick(e));
    this.render();
  }

  render() {
    const node = this._node;
    const r = this._rect;
    if (!node || !r) return;

    this.className = `node ${node.type}`;
    this.dataset.id = node.id;
    if (this.selected) this.classList.add("selected");
    if (node.expanded) this.classList.add("expanded");

    this.style.left = r.x + "px";
    this.style.top = r.y + "px";
    this.style.width = r.w + "px";
    this.style.height = r.h + "px";

    if (node.color) this.style.setProperty("--node-color", node.color);
    else this.style.removeProperty("--node-color");

    this.updateContent(node);
  }

  updateContent(node) {
    // subclasses override
  }

  onMouseDown(e) {
    if (e.target.tagName === "TEXTAREA") return;
    const node = this._node;
    if (!node) return;

    // If clicking on an expanded folder background, let the parent decide whether
    // an edge underneath was clicked instead.
    if (node.type === "folder" && node.expanded && e.target === this) {
      const edgeId = this.edgeUnder(e.clientX, e.clientY);
      if (edgeId) {
        this.dispatchEvent(new CustomEvent("edge-under-node", {
          detail: { node, edgeId, originalEvent: e },
          bubbles: true,
        }));
        return;
      }
    }

    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("node-mousedown", {
      detail: { node, originalEvent: e },
      bubbles: true,
    }));
  }

  onDblClick(e) {
    if (e.target.tagName === "TEXTAREA") return;
    e.stopPropagation();
    const node = this._node;
    if (!node) return;
    this.dispatchEvent(new CustomEvent("node-dblclick", {
      detail: { node },
      bubbles: true,
    }));
  }

  edgeUnder(x, y) {
    let seenThis = false;
    for (const el of document.elementsFromPoint(x, y)) {
      if (el === this) { seenThis = true; continue; }
      if (!seenThis) continue;
      if (el.classList && el.classList.contains("node")) return null;
      if (el.tagName === "polyline") {
        const g = el.closest("#edges-svg > g");
        if (g) return g.dataset.id;
      }
    }
    return null;
  }
}

class DocNode extends GraphNode {
  constructor() {
    super();
    this.resizeObserver = null;
  }

  connectedCallback() {
    super.connectedCallback();
    if (!this.resizeObserver) {
      this.resizeObserver = new ResizeObserver(() => this.onResize());
      this.resizeObserver.observe(this);
    }
  }

  disconnectedCallback() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
  }

  onResize() {
    const node = this._node;
    if (!node || !node.expanded) return;
    const w = this.offsetWidth;
    const h = this.offsetHeight;
    this.dispatchEvent(new CustomEvent("node-resize", {
      detail: { node, width: w, height: h },
      bubbles: true,
    }));
  }

  updateContent(node) {
    const isExp = node.type === "file" && node.expanded;
    const hasTitle = !!this.querySelector(".title");
    const hasEditor = !!this.querySelector("markdown-editor");
    if (hasTitle && isExp === hasEditor) {
      const titleEl = this.querySelector(".title");
      if (titleEl) titleEl.textContent = node.title;
      return;
    }
    this.innerHTML = "";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = node.title;
    this.appendChild(title);

    if (isExp) {
      const editor = document.createElement("markdown-editor");
      editor.className = "md-editor";
      editor.setAttribute("content", "");
      this.appendChild(editor);
      this.dispatchEvent(new CustomEvent("doc-expand", {
        detail: { node, editor },
        bubbles: true,
      }));
    }
  }
}

class FolderNode extends GraphNode {
  updateContent(node) {
    let title = this.querySelector(".title");
    if (!title) {
      this.innerHTML = "";
      title = document.createElement("div");
      title.className = "title";
      this.appendChild(title);
    }
    title.textContent = node.title;
  }
}

customElements.define("graph-node", GraphNode);
customElements.define("doc-node", DocNode);
customElements.define("folder-node", FolderNode);
