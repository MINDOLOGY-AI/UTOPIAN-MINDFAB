// === dockeruse watch page: container list, noVNC screen, lifecycle bar, assignment panel ===
// plain REST, no websocket — the page polls GET containers on its own tick.
// the human owns create/destroy; start/pause are shared with the agents' tools.

let containers = [];
let agents = [];
let selected = null; // selected container name

const listEl = document.getElementById("containers");
const vncFrame = document.getElementById("vnc-frame");
const vncPlaceholder = document.getElementById("vnc-placeholder");
const statusLine = document.getElementById("status-line");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const assignBtn = document.getElementById("assign-btn");
const assignPanel = document.getElementById("assign-panel");

// page always sits on a trailing-slash url (StaticFiles redirects), so relative fetches work
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = `${method} ${path} -> ${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return r.json();
}

// errors land on the bottom bar, red-ish, until the next action clears them
function flash(msg, isErr) {
  statusLine.textContent = msg;
  statusLine.style.color = isErr ? "var(--red)" : "var(--text)";
}

async function refresh() {
  try {
    containers = (await api("GET", "containers")).containers;
    renderList();
    updateScreen();
    updateBar();
  } catch (e) { flash(e.message, true); }
}

function sel() { return containers.find(c => c.name === selected) || null; }

// ---- left: container list ----

function renderList() {
  listEl.innerHTML = "";
  for (const c of containers) {
    const row = document.createElement("div");
    row.className = "c-row" + (c.name === selected ? " active" : "");
    const dot = document.createElement("span");
    dot.className = "dot" + (c.running ? " on" : "");
    row.appendChild(dot);
    const name = document.createElement("span");
    name.className = "c-name";
    name.textContent = c.name;
    row.appendChild(name);
    if (c.agent) {
      const tag = document.createElement("span");
      tag.className = "c-agent";
      tag.textContent = c.agent;
      row.appendChild(tag);
    }
    row.onclick = () => { selected = c.name; renderList(); updateScreen(); updateBar(); };
    listEl.appendChild(row);
  }
}

document.getElementById("create").onclick = async () => {
  const input = document.getElementById("new-name");
  const name = input.value.trim();
  if (!name) return;
  input.value = "";
  // create = entry + first boot: can take a long time if the image needs a build
  flash(`creating ${name}... (first boot can take minutes)`, false);
  try {
    await api("POST", "containers", { name });
    selected = name;
    flash("", false);
    refresh();
  } catch (e) { flash(e.message, true); }
};

// ---- middle: the noVNC screen ----

// base path with trailing slash ("/dockeruse/" mounted, "/" standalone)
const BASE = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";

function updateScreen() {
  const c = sel();
  if (c && c.running) {
    // noVNC loads through the app proxy; 'path' tells it where to open its websocket
    const wsPath = (BASE + `vnc/${c.novnc_port}/websockify`).replace(/^\//, "");
    const url = `${BASE}vnc/${c.novnc_port}/vnc.html?autoconnect=true&resize=scale&path=${wsPath}`;
    const absUrl = new URL(url, window.location.origin).href;
    if (vncFrame.src !== absUrl) vncFrame.src = url;
    vncFrame.style.display = "block";
    vncPlaceholder.style.display = "none";
    startVncRetry();
  } else {
    stopVncRetry();
    vncPlaceholder.textContent = c ? (c.running ? "" : "container paused") : "select a container";
    // flex, not block — the stylesheet centers the text with flexbox
    vncPlaceholder.style.display = "flex";
    vncFrame.style.display = "none";
    vncFrame.src = "";
  }
}

// noVNC never retries on its own: if the container's websockify wasn't up yet
// (or the server reloaded mid-connect) it shows "failed to connect" forever.
// reload the iframe while its status element reports an error — AND when it
// sits in "connecting/loading" for >12s without ever erroring (noVNC can hang
// there with the socket half-open; only a rebuild gets it out).
let vncRetryTimer = null;
let vncStuckSince = null;

function startVncRetry() {
  if (vncRetryTimer) return;
  vncRetryTimer = setInterval(() => {
    try {
      const status = vncFrame.contentDocument?.getElementById("noVNC_status");
      if (!status) return;
      if (status.classList.contains("noVNC_status_error")) {
        vncFrame.src = vncFrame.src;
        vncStuckSince = null;
        return;
      }
      // 'normal' = connected (or cleanly disconnected) — healthy, stop tracking
      if (status.classList.contains("noVNC_status_normal")) {
        vncStuckSince = null;
        return;
      }
      if (!vncStuckSince) { vncStuckSince = Date.now(); return; }
      if (Date.now() - vncStuckSince > 12000) {
        vncFrame.src = vncFrame.src;
        vncStuckSince = null;
      }
    } catch (e) { /* frame mid-navigation, retry next tick */ }
  }, 3000);
}

function stopVncRetry() {
  clearInterval(vncRetryTimer);
  vncRetryTimer = null;
  vncStuckSince = null;
}

// ---- bottom bar: start / pause / delete / assign ----

function updateBar() {
  const c = sel();
  startBtn.disabled = !c || c.running;
  stopBtn.disabled = !c || !c.running;
  document.getElementById("delete-btn").disabled = !c;
  assignBtn.disabled = !c;
}

startBtn.onclick = async () => {
  flash(`starting ${selected}...`, false);
  try { await api("POST", `containers/${selected}/start`); flash("", false); refresh(); }
  catch (e) { flash(e.message, true); }
};

stopBtn.onclick = async () => {
  try { await api("POST", `containers/${selected}/stop`); refresh(); }
  catch (e) { flash(e.message, true); }
};

// delete lives on the bottom bar, not on the rows: destroy the container,
// workspace dies only on the second explicit confirm
document.getElementById("delete-btn").onclick = async () => {
  const name = selected;
  if (!name) return;
  if (!confirm(`destroy container "${name}"? (docker rm — the workspace stays)`)) return;
  const wipe = confirm(`also delete the workspace "${name}" (all its files)?`);
  try {
    await api("DELETE", `containers/${name}${wipe ? "?workspace=1" : ""}`);
    selected = null;
    refresh();
  } catch (err) { flash(err.message, true); }
};

// ---- right: assignment panel ----

// the dropdown IS the whole control: pick an agent to assign, "none" to unassign — instant, no buttons
assignBtn.onclick = async () => {
  if (assignPanel.classList.contains("open")) {
    assignPanel.classList.remove("open");
    return;
  }
  assignPanel.classList.add("open");
  document.getElementById("assign-title").textContent = `assign ${selected}`;
  try {
    agents = (await api("GET", "agents")).agents;
  } catch (e) { flash(e.message, true); }
  renderAssignSelect();
};

function renderAssignSelect() {
  const c = sel();
  const select = document.getElementById("agent-select");
  select.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "none";
  select.appendChild(none);
  for (const a of agents) {
    const opt = document.createElement("option");
    opt.value = a;
    opt.textContent = a;
    select.appendChild(opt);
  }
  select.value = c && c.agent ? c.agent : "";
}

document.getElementById("assign-close").onclick = () => assignPanel.classList.remove("open");

document.getElementById("agent-select").onchange = async (e) => {
  const agent = e.target.value;
  try {
    if (agent) await api("POST", `containers/${selected}/assign`, { agent });
    else await api("POST", `containers/${selected}/unassign`);
    // refresh FIRST so both the list tag and the panel read the new assignment
    await refresh();
    renderAssignSelect();
  } catch (e) { flash(e.message, true); }
};

// the model can start/pause too — poll so the page notices tool-made changes
refresh();
setInterval(refresh, 4000);
