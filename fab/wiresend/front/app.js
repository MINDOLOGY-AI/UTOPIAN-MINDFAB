// === wiresend chat view: channels with the user + agents ===
// one websocket for events (channels list, messages, live-append), HTTP for file bytes.
// ported from old_fab chat.js — minus auth and the tasks popup, plus the readonly toggle.

const md = makeMarkdownRenderer();
const USER = "__user__";

let ws = null;
let channels = [];
let currentChannel = null;
let pendingFiles = [];

// page always sits on a trailing-slash url (StaticFiles redirects), so relative urls work
const BASE = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";

const channelList = document.getElementById("channel-list");
const chatHeader = document.getElementById("chat-header");
const chatMessages = document.getElementById("chat-messages");
const fileBrowser = document.getElementById("file-browser-content");
const fileBrowserHeader = document.getElementById("file-browser-header");
const chatInput = document.getElementById("chat-input");
const attachChips = document.getElementById("attach-chips");
const mainEl = document.querySelector(".chat-main") || document.getElementById("chat-main");

// ---- ws ----

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}${BASE}ws`);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "channels") {
      channels = msg.channels;
      renderChannels();
      renderHeader();
    }
    if (msg.type === "messages" && msg.channel === currentChannel) {
      chatMessages.innerHTML = "";
      msg.messages.forEach(addMessage);
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    if (msg.type === "chat_message" && msg.channel === currentChannel) {
      addMessage(msg.message);
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    if (msg.type === "error") {
      chatHeader.textContent = "error — " + msg.msg;
    }
  };
  ws.onopen = () => send({ cmd: "list_channels" });
  ws.onclose = () => setTimeout(connect, 2000);
}

function send(cmd) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(cmd));
}

// ---- channels ----

function renderChannels() {
  channelList.innerHTML = "";
  const sorted = [...channels].sort((a, b) => (b.dm - a.dm) || a.name.localeCompare(b.name));
  for (const ch of sorted) {
    const row = document.createElement("div");
    row.className = "channel-row" + (ch.id === currentChannel ? " active" : "");
    row.textContent = (ch.dm ? "✉ " : "# ") + ch.name;
    row.onclick = () => selectChannel(ch);
    channelList.appendChild(row);
  }
}

function renderHeader() {
  const ch = channels.find(c => c.id === currentChannel);
  chatHeader.innerHTML = "";
  if (!ch) {
    chatHeader.textContent = "select a channel";
    return;
  }
  const span = document.createElement("span");
  span.textContent = (ch.dm ? "" : "#") + ch.name +
    ` — ${ch.members.map(m => m === USER ? "you" : m).join(", ")}`;
  chatHeader.appendChild(span);
  // readonly members get a visible tag in the header
  for (const a of ch.readonly || []) {
    const tag = document.createElement("span");
    tag.className = "ro-tag";
    tag.textContent = `${a}: read-only`;
    chatHeader.appendChild(tag);
  }
  const agents = () => ch.members.filter(m => m !== USER);
  if (ch.dm) return;
  // the buttons live on the right side of the header
  const btns = document.createElement("span");
  btns.className = "hdr-btns";
  chatHeader.appendChild(btns);

  btns.appendChild(dropBtn("+ agent", "add an agent to this channel", async () =>
    (await fetchAgents()).filter(a => !ch.members.includes(a)).map(a => ({ label: a, value: a })),
    (name) => send({ cmd: "set_members", channel: ch.id, agents: [...agents(), name] })));

  btns.appendChild(dropBtn("− agent", "remove an agent from this channel", async () =>
    agents().map(a => ({ label: a, value: a })),
    (name) => send({ cmd: "set_members", channel: ch.id, agents: agents().filter(m => m !== name) })));

  // access — every member with its level; clicking toggles read-only (read + download only)
  btns.appendChild(dropBtn("access", "member access levels — click to toggle read-only", async () =>
    agents().map(a => ({ label: `${a} — ${(ch.readonly || []).includes(a) ? "read-only" : "member"}`, value: a })),
    (name) => send({ cmd: "set_readonly", channel: ch.id, agent: name,
                     readonly: !(ch.readonly || []).includes(name) })));

  btns.appendChild(hdrBtn("rename", "rename this channel", () => {
    const name = prompt("rename channel to:", ch.name);
    if (name && name !== ch.name) send({ cmd: "rename_channel", channel: ch.id, name });
  }));
  btns.appendChild(hdrBtn("delete", "delete this channel and its files", () => {
    if (confirm(`delete channel "${ch.name}" and all its messages/files?`)) {
      currentChannel = null;
      chatMessages.innerHTML = "";
      send({ cmd: "delete_channel", channel: ch.id });
    }
  }));
}

function hdrBtn(text, title, onclick) {
  const b = document.createElement("button");
  b.className = "member-btn";
  b.textContent = text;
  b.title = title;
  b.onclick = onclick;
  return b;
}

// the user's agents, fetched once per page load (the dropdowns read this)
let agentList = [];
async function fetchAgents() {
  if (!agentList.length) {
    const res = await fetch(`${BASE}agents`);
    agentList = (await res.json()).agents;
  }
  return agentList;
}

// a button that opens a small menu under itself; items are computed at open time
function dropBtn(text, title, itemsFn, onPick) {
  const wrap = document.createElement("span");
  wrap.className = "drop-wrap";
  const b = hdrBtn(text, title, async () => {
    const existing = wrap.querySelector(".drop-menu");
    if (existing) { existing.remove(); return; }
    const menu = document.createElement("div");
    menu.className = "drop-menu";
    for (const item of await itemsFn()) {
      const it = document.createElement("button");
      it.textContent = item.label;
      it.onclick = () => { menu.remove(); onPick(item.value); };
      menu.appendChild(it);
    }
    wrap.appendChild(menu);
  });
  wrap.appendChild(b);
  return wrap;
}

// clicking anywhere else closes open dropdown menus
document.addEventListener("click", (e) => {
  if (!e.target.closest(".drop-wrap"))
    document.querySelectorAll(".drop-menu").forEach(m => m.remove());
});

function selectChannel(ch) {
  currentChannel = ch.id;
  renderHeader();
  renderChannels();
  send({ cmd: "get_messages", channel: ch.id, limit: 200 });
  // tree state is per-channel — drop the previous channel's cache/expansions
  expandedFolders.clear();
  fileTreeCache = {};
  loadFileTree();
}

document.getElementById("new-channel-btn").onclick = () => {
  const name = prompt("channel name:");
  if (!name) return;
  const agents = prompt("agent members (comma separated, blank = none):") || "";
  send({ cmd: "create_channel", name, agents: agents.split(",").map(s => s.trim()).filter(Boolean) });
};

// ---- messages ----

function fmtSize(n) {
  return n < 1024 ? `${n}B` : n < 1048576 ? `${(n / 1024).toFixed(1)}KB` : `${(n / 1048576).toFixed(1)}MB`;
}

function addMessage(m) {
  const div = document.createElement("div");
  div.className = "chat-msg" + (m.sender === USER ? " mine" : "");
  const who = document.createElement("div");
  who.className = "chat-who";
  who.textContent = m.sender === USER ? "you" : m.sender;
  div.appendChild(who);
  if (m.text) {
    const body = document.createElement("div");
    body.className = "chat-body content md";
    body.innerHTML = md.render(m.text);
    div.appendChild(body);
  }
  if (m.type === "file" && m.file) {
    const a = document.createElement("a");
    a.className = "chat-file";
    a.href = `${BASE}chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(m.file.path)}`;
    a.textContent = `↓ ${m.file.name} (${fmtSize(m.file.size)})`;
    a.download = m.file.name;
    div.appendChild(a);
  }
  chatMessages.appendChild(div);
}

// ---- input + attachments ----

function renderChips() {
  attachChips.innerHTML = "";
  pendingFiles.forEach((f, i) => {
    const chip = document.createElement("span");
    chip.className = "attach-chip";
    chip.textContent = `${f.name} (${fmtSize(f.size)}) `;
    const x = document.createElement("button");
    x.textContent = "×";
    x.onclick = () => { pendingFiles.splice(i, 1); renderChips(); };
    chip.appendChild(x);
    attachChips.appendChild(chip);
  });
}

function addFiles(files) {
  for (const f of files) pendingFiles.push(f);
  renderChips();
}

mainEl.addEventListener("dragover", (e) => { e.preventDefault(); mainEl.classList.add("drag-over"); });
mainEl.addEventListener("dragleave", () => mainEl.classList.remove("drag-over"));
mainEl.addEventListener("drop", (e) => {
  e.preventDefault();
  mainEl.classList.remove("drag-over");
  if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});

chatInput.addEventListener("paste", (e) => {
  if (e.clipboardData.files.length) {
    e.preventDefault();
    addFiles(e.clipboardData.files);
  }
});

function uploadFile(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const progress = document.getElementById("upload-progress");
    const bar = document.getElementById("upload-bar");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100) + "%";
    };
    xhr.onloadstart = () => { bar.style.width = "0%"; progress.style.display = "block"; };
    xhr.onloadend = () => { progress.style.display = "none"; };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else reject(new Error(`${file.name}: upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error(`${file.name}: upload failed`));
    xhr.open("POST", `${BASE}chat/${encodeURIComponent(currentChannel)}/files?name=${encodeURIComponent(file.name)}`);
    xhr.send(file);
  });
}

chatInput.onkeydown = async (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!currentChannel) return;
    const text = chatInput.value.trim();
    if (!text && !pendingFiles.length) return;
    try {
      await Promise.all(pendingFiles.map(uploadFile));
    } catch (err) {
      alert(err.message);
      return;
    }
    pendingFiles = [];
    renderChips();
    if (text) send({ cmd: "chat_send", channel: currentChannel, text });
    chatInput.value = "";
  }
};

// ---- file browser ----

let expandedFolders = new Set(); // {"path", ...}
let fileTreeCache = {}; // {path: [{name, path, size, is_dir}, ...]}

async function loadFileTree() {
  if (!currentChannel) return;
  expandedFolders.add("__root__");
  try {
    const res = await fetch(`${BASE}chat/${encodeURIComponent(currentChannel)}/files-list`);
    if (!res.ok) { renderFileTree(); return; }
    const data = await res.json();
    fileTreeCache[""] = data.files || [];
    renderFileTree();
  } catch {
    fileBrowser.innerHTML = '<div style="color:var(--border);padding:10px;">error loading files</div>';
  }
}

async function fetchChildren(path) {
  if (fileTreeCache[path]) return fileTreeCache[path];
  try {
    const res = await fetch(`${BASE}chat/${encodeURIComponent(currentChannel)}/files-list?path=${encodeURIComponent(path)}`);
    if (!res.ok) return [];
    const data = await res.json();
    fileTreeCache[path] = data.files || [];
    return fileTreeCache[path];
  } catch {
    return [];
  }
}

function renderFileTree() {
  const ch = channels.find(c => c.id === currentChannel);
  fileBrowserHeader.textContent = ch ? ch.name : "files";
  fileBrowser.innerHTML = "";

  // toolbar at top — operates on root
  const toolbar = buildToolbar("");
  fileBrowser.appendChild(toolbar);

  // drag/drop on the whole panel
  fileBrowser.ondragover = (e) => { e.preventDefault(); fileBrowser.classList.add("drag-over"); };
  fileBrowser.ondragleave = () => fileBrowser.classList.remove("drag-over");
  fileBrowser.ondrop = async (e) => {
    e.preventDefault();
    fileBrowser.classList.remove("drag-over");
    if (!e.dataTransfer.files.length) return;
    for (const f of e.dataTransfer.files) {
      try { await uploadToChannel(f.name, f); } catch (err) { alert(err.message); }
    }
    expandedFolders.clear();
    fileTreeCache = {};
    loadFileTree();
  };

  const rootFiles = fileTreeCache[""] || [];
  const rootName = ch ? ch.name : "";

  // root folder row — always shown, toggles children visibility
  const rootExpanded = expandedFolders.has("__root__");
  const rootRow = document.createElement("div");
  rootRow.className = "file-tree-row file-tree-root";
  const rootIcon = document.createElement("span");
  rootIcon.className = "file-tree-icon";
  rootIcon.textContent = rootExpanded ? "▾" : "▸";
  rootIcon.style.cursor = "pointer";
  rootIcon.onclick = () => {
    expandedFolders.has("__root__") ? expandedFolders.delete("__root__") : expandedFolders.add("__root__");
    renderFileTree();
  };
  rootRow.appendChild(rootIcon);
  const rootLabel = document.createElement("span");
  rootLabel.className = "file-tree-name";
  rootLabel.textContent = rootName + "/";
  rootLabel.style.cursor = "pointer";
  rootLabel.onclick = rootIcon.onclick;
  rootRow.appendChild(rootLabel);
  fileBrowser.appendChild(rootRow);

  if (!rootExpanded) return;

  if (!rootFiles.length) {
    const empty = document.createElement("div");
    empty.className = "file-tree-empty";
    empty.style.paddingLeft = "18px";
    empty.textContent = "— empty —";
    fileBrowser.appendChild(empty);
    return;
  }

  const list = document.createElement("div");
  list.className = "file-tree-list";
  for (const f of rootFiles) {
    renderFileTreeRow(list, f, "", 1); // depth 1 under root
  }
  fileBrowser.appendChild(list);
}

function renderFileTreeRow(parent, f, parentPath, depth) {
  const isDir = f.is_dir;
  const fullPath = parentPath ? `${parentPath}/${f.name}` : f.name;
  const isExpanded = isDir && expandedFolders.has(fullPath);

  const row = document.createElement("div");
  row.className = "file-tree-row";
  row.style.paddingLeft = `${depth * 16 + 4}px`;

  const icon = document.createElement("span");
  icon.className = "file-tree-icon";
  if (isDir) {
    icon.textContent = isExpanded ? "▾" : "▸";
    icon.style.cursor = "pointer";
  }
  row.appendChild(icon);

  const name = document.createElement("span");
  name.className = "file-tree-name";
  name.title = fullPath;
  if (isDir) {
    name.textContent = f.name + "/";
    name.style.cursor = "pointer";
    name.onclick = async () => toggleFolder(fullPath);
    icon.onclick = async () => toggleFolder(fullPath);
  } else {
    const a = document.createElement("a");
    a.href = `${BASE}chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(fullPath)}`;
    a.textContent = f.name;
    a.download = f.name;
    name.appendChild(a);
  }
  row.appendChild(name);

  if (!isDir) {
    const size = document.createElement("span");
    size.className = "file-tree-size";
    size.textContent = fmtSize(f.size);
    row.appendChild(size);
  }

  const actions = document.createElement("span");
  actions.className = "file-tree-actions";
  const renameBtn = document.createElement("button");
  renameBtn.textContent = "✎";
  renameBtn.title = "rename";
  renameBtn.onclick = async (e) => {
    e.stopPropagation();
    const newName = prompt("rename to:", f.name);
    if (!newName || newName === f.name) return;
    const parent = parentPath ? parentPath + "/" : "";
    await fetch(`${BASE}chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(fullPath)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: parent + newName }),
    });
    expandedFolders.clear();
    fileTreeCache = {};
    loadFileTree();
  };
  actions.appendChild(renameBtn);
  const delBtn = document.createElement("button");
  delBtn.textContent = "×";
  delBtn.title = "delete";
  delBtn.onclick = async (e) => {
    e.stopPropagation();
    if (!confirm(`delete ${isDir ? "folder" : "file"} "${f.name}"?`)) return;
    await fetch(`${BASE}chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(fullPath)}`, {
      method: "DELETE",
    });
    expandedFolders.delete(fullPath);
    delete fileTreeCache[fullPath];
    if (parentPath) {
      delete fileTreeCache[parentPath];
      await fetchChildren(parentPath);
    } else {
      delete fileTreeCache[""];
    }
    loadFileTree();
  };
  actions.appendChild(delBtn);
  row.appendChild(actions);

  parent.appendChild(row);

  // render expanded children
  if (isExpanded && fileTreeCache[fullPath]) {
    for (const child of fileTreeCache[fullPath]) {
      renderFileTreeRow(parent, child, fullPath, depth + 1);
    }
  }
}

async function toggleFolder(path) {
  if (expandedFolders.has(path)) {
    // collapse: forget this folder's subtree — it refetches on next expand
    expandedFolders.delete(path);
    for (const p of [...expandedFolders]) {
      if (p.startsWith(path + "/")) expandedFolders.delete(p);
    }
    for (const key of Object.keys(fileTreeCache)) {
      if (key === path || key.startsWith(path + "/")) delete fileTreeCache[key];
    }
  } else {
    // expand: lazy-fetch just this folder's children, no parent/root refetch
    expandedFolders.add(path);
    await fetchChildren(path);
  }
  renderFileTree();
}

function buildToolbar(parentPath) {
  const toolbar = document.createElement("div");
  toolbar.className = "file-tree-toolbar";

  const uploadInput = document.createElement("input");
  uploadInput.type = "file";
  uploadInput.multiple = true;
  uploadInput.style.display = "none";
  uploadInput.onchange = async () => {
    for (const f of uploadInput.files) {
      const relPath = parentPath ? `${parentPath}/${f.name}` : f.name;
      try { await uploadToChannel(relPath, f); } catch (err) { alert(err.message); }
    }
    uploadInput.value = "";
    expandedFolders.clear();
    fileTreeCache = {};
    loadFileTree();
  };
  toolbar.appendChild(uploadInput);

  const uploadBtn = document.createElement("button");
  uploadBtn.textContent = "upload";
  uploadBtn.title = "select files to upload";
  uploadBtn.onclick = () => uploadInput.click();
  toolbar.appendChild(uploadBtn);

  const folderInput = document.createElement("input");
  folderInput.type = "file";
  folderInput.webkitdirectory = true;
  folderInput.style.display = "none";
  folderInput.onchange = async () => {
    for (const f of folderInput.files) {
      const relPath = parentPath ? `${parentPath}/${f.webkitRelativePath}` : f.webkitRelativePath;
      try { await uploadToChannel(relPath, f); } catch (err) { alert(err.message); }
    }
    folderInput.value = "";
    expandedFolders.clear();
    fileTreeCache = {};
    loadFileTree();
  };
  toolbar.appendChild(folderInput);

  const folderBtn = document.createElement("button");
  folderBtn.textContent = "upload folder";
  folderBtn.title = "select a folder to upload";
  folderBtn.onclick = () => folderInput.click();
  toolbar.appendChild(folderBtn);

  const newFolderBtn = document.createElement("button");
  newFolderBtn.textContent = "+ folder";
  newFolderBtn.onclick = () => {
    const name = prompt("folder name:");
    if (!name) return;
    const fullPath = parentPath ? `${parentPath}/${name}` : name;
    fetch(`${BASE}chat/${encodeURIComponent(currentChannel)}/mkdir`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir_name: fullPath }),
    }).then(() => {
      expandedFolders.clear();
      fileTreeCache = {};
      loadFileTree();
    });
  };
  toolbar.appendChild(newFolderBtn);

  return toolbar;
}

function uploadToChannel(relPath, file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}chat/${encodeURIComponent(currentChannel)}/files?name=${encodeURIComponent(relPath)}`);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else reject(new Error(`${file.name}: upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error(`${file.name}: upload failed`));
    xhr.send(file);
  });
}

connect();
