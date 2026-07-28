// <auth-box> — site-wide login/register/logout, fixed top-right.
// talks to /auth/* (hub/auth/routes.py). fires `auth-changed` on document
// with detail.user after login/logout so apps can react (e.g. reconnect).

class AuthBox extends HTMLElement {
  connectedCallback() {
    this.user = null;
    this.mode = 'login'; // 'login' | 'register'
    this.modalOpen = false;
    this.addEventListener('click', (e) => this.onClick(e));
    this.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.matches('.auth-username, .auth-password')) this.submit();
    });
    this.render();
    this.checkSession();
  }

  async checkSession() {
    try {
      const res = await fetch('/auth/me', { credentials: 'same-origin' });
      this.user = res.ok ? (await res.json()).user : null;
    } catch {
      this.user = null;
    }
    this.render();
  }

  setUser(user) {
    this.user = user;
    this.modalOpen = false;
    this.render();
    document.dispatchEvent(new CustomEvent('auth-changed', { detail: { user } }));
  }

  onClick(e) {
    const action = e.target.dataset.action;
    if (action === 'open') { this.modalOpen = true; this.render(); this.querySelector('.auth-username').focus(); }
    if (action === 'close') { this.modalOpen = false; this.render(); }
    if (action === 'tab') { this.mode = e.target.dataset.mode; this.render(); }
    if (action === 'submit') this.submit();
    if (action === 'logout') this.logout();
    if (e.target.classList.contains('auth-overlay')) { this.modalOpen = false; this.render(); }
  }

  async submit() {
    const username = this.querySelector('.auth-username').value.trim();
    const password = this.querySelector('.auth-password').value;
    const errorEl = this.querySelector('.auth-error');
    const res = await fetch(`/auth/${this.mode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      errorEl.textContent = data.error || 'something went wrong';
      return;
    }
    this.setUser(data.user);
  }

  async logout() {
    await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
    this.setUser(null);
  }

  render() {
    const chip = this.user
      ? `<span class="auth-user">${this.user}</span><span class="auth-pop"><button class="auth-btn auth-logout" data-action="logout">logout</button></span>`
      : `<button class="auth-btn" data-action="open">login</button>`;
    this.innerHTML = `
      <div class="auth-box ${this.user ? 'logged-in' : ''}">${chip}</div>
      <div class="auth-overlay" style="display:${this.modalOpen ? 'flex' : 'none'};">
        <div class="auth-modal">
          <button class="auth-close" data-action="close">×</button>
          <div class="auth-tabs">
            <button class="auth-tab ${this.mode === 'login' ? 'active' : ''}" data-action="tab" data-mode="login">login</button>
            <button class="auth-tab ${this.mode === 'register' ? 'active' : ''}" data-action="tab" data-mode="register">register</button>
          </div>
          <input class="auth-username" type="text" placeholder="username" autocomplete="username">
          <input class="auth-password" type="password" placeholder="password">
          <div class="auth-error"></div>
          <button class="auth-submit" data-action="submit">${this.mode}</button>
        </div>
      </div>
    `;
  }
}

customElements.define('auth-box', AuthBox);
