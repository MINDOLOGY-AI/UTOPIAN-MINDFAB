// === markdown-editor: render + edit markdown with [[wikilinks]] ===
// Depends on the global `marked` object (load marked before this component).

class MarkdownEditor extends HTMLElement {
  constructor() {
    super();
    this._content = "";
    this._resolveLink = null; // fn(title) -> nodeId | null
    this._saveTimer = null;
  }

  static get observedAttributes() {
    return ["content"];
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (name === "content" && newVal !== this._content) {
      this._content = newVal || "";
      if (this.preview) this.render();
      if (this.textarea) this.textarea.value = this._content;
    }
  }

  set content(value) {
    this._content = value || "";
    this.setAttribute("content", this._content);
    if (this.preview) this.render();
    if (this.textarea) this.textarea.value = this._content;
  }

  get content() {
    return this._content;
  }

  set resolveLink(fn) {
    this._resolveLink = fn;
    if (this.preview) this.render();
  }

  connectedCallback() {
    if (!this.preview) this.build();
    this.render();
  }

  build() {
    this.innerHTML = "";
    this.textarea = document.createElement("textarea");
    this.textarea.className = "content";
    this.textarea.spellcheck = false;
    this.textarea.style.display = "none";
    this.preview = document.createElement("div");
    this.preview.className = "preview";

    this.textarea.addEventListener("input", () => this.onInput());
    this.textarea.addEventListener("blur", () => this.showPreview());
    this.textarea.addEventListener("mousedown", (e) => e.stopPropagation());
    this.preview.addEventListener("mousedown", (e) => e.stopPropagation());
    this.preview.addEventListener("click", (e) => this.onPreviewClick(e));

    this.appendChild(this.preview);
    this.appendChild(this.textarea);
  }

  onInput() {
    this._content = this.textarea.value;
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      this.dispatchEvent(new CustomEvent("content-change", {detail: this._content, bubbles: true}));
    }, 400);
  }

  onPreviewClick(e) {
    const link = e.target.closest("a.wikilink");
    if (link) {
      const id = link.dataset.id;
      if (id) this.dispatchEvent(new CustomEvent("wikilink-click", {detail: id, bubbles: true}));
      return;
    }
    this.showEditor();
  }

  showEditor() {
    this.preview.style.display = "none";
    this.textarea.style.display = "";
    this.textarea.focus();
  }

  showPreview() {
    this._content = this.textarea.value;
    this.textarea.style.display = "none";
    this.preview.style.display = "";
    this.render();
  }

  render() {
    if (!this.preview) return;
    this.textarea.value = this._content;
    const md = this._content.replace(/\[\[([^\]\n]+)\]\]/g, (m, t) => {
      const id = this._resolveLink ? this._resolveLink(t) : null;
      return id
        ? `<a class="wikilink" data-id="${id}">${t}</a>`
        : `<span class="wikilink broken">${t}</span>`;
    });
    this.preview.innerHTML = marked.parse(md);
  }
}

customElements.define("markdown-editor", MarkdownEditor);
