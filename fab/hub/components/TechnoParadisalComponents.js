// cybersec: escape &, <, >, ", ' before putting attribute text into innerHTML — without this a crafted attribute value could break out and inject script
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// cybersec: only allow relative and http(s) hrefs — without this a javascript: URL would run script when the link is clicked
function safeHref(href) {
  if (href.startsWith("/") || href.startsWith("./") ||
      href.startsWith("https://") || href.startsWith("http://")) {
    return href;
  }
  return "#";
}

class CyberLink extends HTMLElement {
  static get observedAttributes() {
    return ["href", "status", "heading"];
  }

  connectedCallback() {
    this.render();
  }

  attributeChangedCallback() {
    this.render();
  }

  render() {
    const href = safeHref(this.getAttribute("href") || "#");
    const status = this.getAttribute("status");
    const heading = this.getAttribute("heading") || "";
    // cybersec: escape status/heading before innerHTML so an attribute containing < or " can't inject markup
    const statusAttr = status ? `data-status="${escapeHtml(status)}"` : "";

    this.innerHTML = `
      <a class="cyber-link" href="${escapeHtml(href)}" ${statusAttr}>
        <span class="cyber-link__bg"></span>
        <span class="cyber-link__content">
          <span class="cyber-link__heading">${escapeHtml(heading)}</span>
        </span>
      </a>
    `;
  }
}

class CyberButton extends HTMLElement {
  static get observedAttributes() {
    return ["status", "heading"];
  }

  connectedCallback() {
    this.render();
    this.addPressFx();
  }

  attributeChangedCallback() {
    this.render();
  }

  render() {
    const status = this.getAttribute("status") || "";
    const heading = this.getAttribute("heading") || "";

    // cybersec: escape status/heading before innerHTML so an attribute containing < or " can't inject markup
    this.innerHTML = `
      <button class="cyber-button" type="button" data-status="${escapeHtml(status)}">
        <span class="cyber-button__face">
          <span class="cyber-button__heading">${escapeHtml(heading)}</span>
        </span>
      </button>
    `;
  }

  addPressFx() {
    const btn = this.querySelector(".cyber-button");
    if (!btn) return;

    const press = () => btn.classList.add("pressed");
    const release = () => btn.classList.remove("pressed");

    btn.addEventListener("mousedown", press);
    btn.addEventListener("mouseup", release);
    btn.addEventListener("mouseleave", release);
    btn.addEventListener("touchstart", press, { passive: true });
    btn.addEventListener("touchend", release);
  }
}

class CyberUl extends HTMLElement {
  connectedCallback() {
    const text = this.textContent.trim();
    // cybersec: escape text before innerHTML so markup in the element's content renders as text, not HTML
    this.innerHTML = `
      <div class="category-header">
        <span class="led"></span>
        <h2 class="category-title">${escapeHtml(text)}</h2>
      </div>
    `;
  }
}

class CyberHome extends HTMLElement {
  connectedCallback() {
    const homeIcon = `<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12L12 3l9 9"/><path d="M5 10v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9"/></svg>`;
    this.innerHTML = `
      <a class="cyber-link cyber-link--nav" href="/" title="home">
        <span class="cyber-link__bg"></span>
        <span class="cyber-link__content">${homeIcon}</span>
      </a>
    `;
  }
}

class CyberBack extends HTMLElement {
  connectedCallback() {
    const backIcon = `<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>`;
    this.innerHTML = `
      <button class="cyber-link cyber-link--nav" type="button" title="back">
        <span class="cyber-link__bg"></span>
        <span class="cyber-link__content">${backIcon}</span>
      </button>
    `;
    const btn = this.querySelector(".cyber-link--nav");
    if (btn) btn.addEventListener("click", () => history.back());
  }
}

customElements.define("cyber-link", CyberLink);
customElements.define("cyber-button", CyberButton);
customElements.define("cyber-ul", CyberUl);
customElements.define("cyber-home", CyberHome);
customElements.define("cyber-back", CyberBack);
