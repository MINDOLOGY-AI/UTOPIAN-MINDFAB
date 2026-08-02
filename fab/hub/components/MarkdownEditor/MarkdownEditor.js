// === markdown-editor: render + edit markdown with [[wikilinks]] and math ===
// Depends on the global `markdownit` (markdown-it), `markdownItKatex`, and `katex` objects.

class MarkdownEditor extends HTMLElement {
  constructor() {
    super();
    this._content = "";
    this._resolveLink = null; // fn(title) -> nodeId | null
    this._saveTimer = null;
    this._md = null;
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

  getMd() {
    if (this._md) return this._md;
    // shared renderer (markdown-render.js) + this component's wikilink plugin
    this._md = makeMarkdownRenderer().use(wikilinkPlugin);
    return this._md;
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
      this.dispatchEvent(new CustomEvent("content-change", { detail: this._content, bubbles: true }));
    }, 400);
  }

  onPreviewClick(e) {
    const link = e.target.closest("a.wikilink");
    if (link) {
      const id = link.dataset.id;
      if (id) this.dispatchEvent(new CustomEvent("wikilink-click", { detail: id, bubbles: true }));
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
    const html = this.getMd().render(this._content, { resolveLink: this._resolveLink });
    this.preview.innerHTML = html;
  }
}

// cybersec: escape &, <, >, ", ' before putting text into an HTML string — without this a wikilink title like [[x"><img onerror=...>]] breaks out of the attribute and runs script
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// === markdown-it plugin for [[wikilinks]] ===
// Registered before the built-in link rule so [[...]] is captured first.
function wikilinkPlugin(md) {
  md.inline.ruler.before('link', 'wikilink', function (state, silent) {
    if (state.src.charCodeAt(state.pos) !== 0x5B /* [ */ ||
        state.src.charCodeAt(state.pos + 1) !== 0x5B /* [ */) {
      return false;
    }

    var end = state.src.indexOf(']]', state.pos + 2);
    if (end === -1) return false;

    if (!silent) {
      var token = state.push('wikilink', '', 0);
      token.content = state.src.slice(state.pos + 2, end);
    }

    state.pos = end + 2;
    return true;
  });

  md.renderer.rules.wikilink = function (tokens, idx, options, env) {
    var title = tokens[idx].content;
    var resolveLink = env && env.resolveLink;
    var id = resolveLink ? resolveLink(title) : null;
    return id
      ? '<a class="wikilink" data-id="' + escapeHtml(id) + '">' + escapeHtml(title) + '</a>'
      : '<span class="wikilink broken">' + escapeHtml(title) + '</span>';
  };
}

customElements.define("markdown-editor", MarkdownEditor);
