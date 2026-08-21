// === chat view: channels with the user + agents ===
// one websocket, channels on the left, message stream + attachments on the right.

const md = makeMarkdownRenderer();
const USER = "__user__";

let ws = null;
let channels = [];
let agentStatus = {}; // agent name -> {working, container_on, ...}
let currentChannel = null;
let pendingFiles = [];

const channelList = document.getElementById('channel-list');
const chatHeader = document.getElementById('chat-header');
const chatMessages = document.getElementById('chat-messages');
const fileBrowser = document.getElementById('file-browser-content');
const fileBrowserHeader = document.getElementById('file-browser-header');
const fileBrowserPanel = document.querySelector('.file-browser');
const chatInput = document.getElementById('chat-input');
const attachChips = document.getElementById('attach-chips');
const mainEl = document.querySelector('.chat-main');

// ---- ws ----

function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/INT3RF4CE/ws`);
    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'auth_required') {
            document.getElementById('auth-overlay').style.display = 'flex';
            return;
        }
        if (msg.type === 'agents') {
            agentStatus = msg.agents;
            renderChannels();
            renderHeader();
            if (tasksOpen) send({ cmd: 'get_agent_tasks' }); // live-refresh the popup
        }
        if (msg.type === 'agent_tasks') {
            renderTasks(msg.tasks || {});
        }
        if (msg.type === 'channels') {
            channels = msg.channels;
            renderChannels();
            renderHeader();
        }
        if (msg.type === 'messages' && msg.channel === currentChannel) {
            chatMessages.innerHTML = '';
            msg.messages.forEach(addMessage);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        if (msg.type === 'chat_message' && msg.channel === currentChannel) {
            addMessage(msg.message);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    };
    ws.onopen = () => send({ cmd: 'list_channels' });
    ws.onclose = () => setTimeout(connect, 2000);
}

// ---- tasks popup: what each agent is working on (their to-do queues) ----

const tasksBtn = document.getElementById('tasks-btn');
const tasksPopup = document.getElementById('tasks-popup');
let tasksOpen = false;

function renderTasks(tasks) {
    tasksPopup.innerHTML = '';
    const names = Object.keys(tasks).sort();
    if (!names.length) {
        const hint = document.createElement('div');
        hint.className = 'tasks-empty';
        hint.textContent = 'no tasks assigned — drag nodes into an agent\'s to do section on the board';
        tasksPopup.appendChild(hint);
        return;
    }
    for (const name of names) {
        const head = document.createElement('div');
        head.className = 'tasks-agent';
        head.textContent = name;
        tasksPopup.appendChild(head);
        for (const t of tasks[name]) {
            const row = document.createElement('div');
            row.className = `tasks-row tasks-${t.state}`;
            const dot = document.createElement('span');
            dot.className = 'tasks-dot';
            row.appendChild(dot);
            const label = document.createElement('span');
            label.textContent = t.path + (t.state === 'doing' && t.assignee ? ` — ${t.assignee}` : '');
            row.appendChild(label);
            row.title = `${t.state} · ${t.board}`;
            tasksPopup.appendChild(row);
        }
    }
}

tasksBtn.onclick = () => {
    tasksOpen = !tasksOpen;
    tasksPopup.style.display = tasksOpen ? 'block' : 'none';
    tasksBtn.classList.toggle('on', tasksOpen);
    if (tasksOpen) send({ cmd: 'get_agent_tasks' });
};

function send(cmd) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(cmd));
}

// ---- channels ----

function renderChannels() {
    channelList.innerHTML = '';
    const sorted = [...channels].sort((a, b) => (b.dm - a.dm) || a.name.localeCompare(b.name));
    for (const ch of sorted) {
        const li = document.createElement('li');
        li.className = 'channel-row' + (ch.id === currentChannel ? ' active' : '');
        if (ch.dm) {
            // dm channels are named after the agent — show whether the model is on
            const dot = document.createElement('span');
            dot.className = 'status-dot' + (agentStatus[ch.name]?.working ? ' on' : '');
            dot.title = agentStatus[ch.name]?.working ? 'model is working' : 'model is off';
            li.appendChild(dot);
        }
        li.appendChild(document.createTextNode((ch.dm ? '✉ ' : '# ') + ch.name));
        li.onclick = () => selectChannel(ch);
        channelList.appendChild(li);
    }
}

function renderHeader() {
    const ch = channels.find(c => c.id === currentChannel);
    chatHeader.innerHTML = '';
    if (!ch) {
        chatHeader.textContent = 'select a channel';
        return;
    }
    let text = (ch.dm ? '' : '#') + ch.name +
        ` — ${ch.members.map(m => m === USER ? 'you' : m).join(', ')}`;
    if (ch.dm) text += agentStatus[ch.name]?.working ? ' · on' : ' · off';
    const span = document.createElement('span');
    span.textContent = text;
    chatHeader.appendChild(span);
    const agents = () => ch.members.filter(m => m !== USER);
    if (!ch.dm) {
        // + agent — button that opens a popup of agents NOT in this channel
        const addBtn = document.createElement('button');
        addBtn.className = 'member-btn';
        addBtn.textContent = '+ agent';
        addBtn.title = 'add an agent to this channel';
        addBtn.onclick = () => {
            const popup = showAgentPopup(addBtn, Object.keys(agentStatus).sort().filter(a => !ch.members.includes(a)), (name) => {
                send({ cmd: 'set_members', channel: ch.id, agents: [...agents(), name] });
                hideAgentPopup();
            });
        };
        chatHeader.appendChild(addBtn);

        // − agent — button that opens a popup of agents IN this channel
        const rmBtn = document.createElement('button');
        rmBtn.className = 'member-btn';
        rmBtn.textContent = '− agent';
        rmBtn.title = 'remove an agent from this channel';
        rmBtn.onclick = () => {
            if (!agents().length) return;
            showAgentPopup(rmBtn, agents().sort(), (name) => {
                send({ cmd: 'set_members', channel: ch.id, agents: agents().filter(m => m !== name) });
                hideAgentPopup();
            });
        };
        chatHeader.appendChild(rmBtn);
    }
    const rename = document.createElement('button');
    rename.className = 'member-btn';
    rename.textContent = 'rename';
    rename.title = 'rename this channel';
    rename.onclick = () => {
        const name = prompt('rename channel to:', ch.name);
        if (name && name !== ch.name) send({ cmd: 'rename_channel', channel: ch.id, name });
    };
    const del = document.createElement('button');
    del.className = 'member-btn';
    del.textContent = 'delete';
    del.title = 'delete this channel and its files';
    del.onclick = () => {
        if (confirm(`delete channel "${ch.name}" and all its messages/files?`)) {
            currentChannel = null;
            chatMessages.innerHTML = '';
            send({ cmd: 'delete_channel', channel: ch.id });
        }
    };
    chatHeader.appendChild(rename);
    chatHeader.appendChild(del);
}

function selectChannel(ch) {
    currentChannel = ch.id;
    renderHeader();
    renderChannels();
    send({ cmd: 'get_messages', channel: ch.id, limit: 200 });
    // tree state is per-channel — drop the previous channel's cache/expansions
    expandedFolders.clear();
    fileTreeCache = {};
    loadFileTree();
}

document.getElementById('new-channel-btn').onclick = () => {
    const name = prompt('channel name:');
    if (!name) return;
    const agents = prompt('agent members (comma separated, blank = none):') || '';
    send({ cmd: 'create_channel', name, agents: agents.split(',').map(s => s.trim()).filter(Boolean) });
};

// ---- messages ----

function fmtSize(n) {
    return n < 1024 ? `${n}B` : n < 1048576 ? `${(n / 1024).toFixed(1)}KB` : `${(n / 1048576).toFixed(1)}MB`;
}

function addMessage(m) {
    const div = document.createElement('div');
    div.className = 'chat-msg' + (m.sender === USER ? ' mine' : '');
    const who = document.createElement('div');
    who.className = 'chat-who';
    who.textContent = m.sender === USER ? 'you' : m.sender;
    div.appendChild(who);
    if (m.text) {
        const body = document.createElement('div');
        body.className = 'chat-body content md';
        body.innerHTML = md.render(m.text);
        div.appendChild(body);
    }
    if (m.type === 'file' && m.file) {
        const a = document.createElement('a');
        a.className = 'chat-file';
        a.href = `chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(m.file.path)}`;
        a.textContent = `↓ ${m.file.name} (${fmtSize(m.file.size)})`;
        a.download = m.file.name;
        div.appendChild(a);
    }
    chatMessages.appendChild(div);
}

// ---- input + attachments ----

function renderChips() {
    attachChips.innerHTML = '';
    pendingFiles.forEach((f, i) => {
        const chip = document.createElement('span');
        chip.className = 'attach-chip';
        chip.textContent = `${f.name} (${fmtSize(f.size)}) `;
        const x = document.createElement('button');
        x.textContent = '×';
        x.onclick = () => { pendingFiles.splice(i, 1); renderChips(); };
        chip.appendChild(x);
        attachChips.appendChild(chip);
    });
}

function addFiles(files) {
    for (const f of files) pendingFiles.push(f);
    renderChips();
}

mainEl.addEventListener('dragover', (e) => { e.preventDefault(); mainEl.classList.add('drag-over'); });
mainEl.addEventListener('dragleave', () => mainEl.classList.remove('drag-over'));
mainEl.addEventListener('drop', (e) => {
    e.preventDefault();
    mainEl.classList.remove('drag-over');
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});

chatInput.addEventListener('paste', (e) => {
    if (e.clipboardData.files.length) {
        e.preventDefault();
        addFiles(e.clipboardData.files);
    }
});

function uploadFile(file) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const progress = document.getElementById('upload-progress');
        const bar = document.getElementById('upload-bar');
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                bar.style.width = (e.loaded / e.total * 100) + '%';
            }
        };
        xhr.onloadstart = () => { bar.style.width = '0%'; progress.style.display = 'block'; };
        xhr.onloadend = () => { progress.style.display = 'none'; };
        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
            else reject(new Error(`${file.name}: upload failed (${xhr.status})`));
        };
        xhr.onerror = () => reject(new Error(`${file.name}: upload failed`));
        xhr.open('POST', `chat/${encodeURIComponent(currentChannel)}/files?name=${encodeURIComponent(file.name)}`);
        xhr.send(file);
    });
}

chatInput.onkeydown = async (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
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
        if (text) send({ cmd: 'chat_send', channel: currentChannel, text });
        chatInput.value = '';
    }
};

connect();

// ---- file browser ----

let expandedFolders = new Set(); // {"path", ...}
let fileTreeCache = {}; // {path: [{name, path, size, is_dir}, ...]}

async function loadFileTree() {
    if (!currentChannel) return;
    expandedFolders.add('__root__');
    try {
        const res = await fetch(`chat/${encodeURIComponent(currentChannel)}/files-list`, { credentials: 'same-origin' });
        if (!res.ok) { renderFileTree(); return; }
        const data = await res.json();
        fileTreeCache[''] = data.files || [];
        renderFileTree();
    } catch {
        fileBrowser.innerHTML = '<div style="color:var(--light-gray);padding:10px;">error loading files</div>';
    }
}

async function fetchChildren(path) {
    if (fileTreeCache[path]) return fileTreeCache[path];
    try {
        const res = await fetch(`chat/${encodeURIComponent(currentChannel)}/files-list?path=${encodeURIComponent(path)}`, { credentials: 'same-origin' });
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
    fileBrowserHeader.textContent = ch ? ch.name : 'files';
    fileBrowser.innerHTML = '';

    // toolbar at top — operates on root
    const toolbar = buildToolbar('');
    fileBrowser.appendChild(toolbar);

    // drag/drop on the whole panel
    fileBrowser.ondragover = (e) => { e.preventDefault(); fileBrowser.classList.add('drag-over'); };
    fileBrowser.ondragleave = () => fileBrowser.classList.remove('drag-over');
    fileBrowser.ondrop = async (e) => {
        e.preventDefault();
        fileBrowser.classList.remove('drag-over');
        if (!e.dataTransfer.files.length) return;
        for (const f of e.dataTransfer.files) {
            try { await uploadToChannel(f.name, f); } catch (err) { alert(err.message); }
        }
        expandedFolders.clear();
        fileTreeCache = {};
        loadFileTree();
    };

    const rootFiles = fileTreeCache[''] || [];
    const rootName = ch ? ch.name : '';

    // root folder row — always shown, toggles children visibility
    const rootExpanded = expandedFolders.has('__root__');
    const rootRow = document.createElement('div');
    rootRow.className = 'file-tree-row file-tree-root';
    const rootIcon = document.createElement('span');
    rootIcon.className = 'file-tree-icon';
    rootIcon.textContent = rootExpanded ? '▾' : '▸';
    rootIcon.style.cursor = 'pointer';
    rootIcon.onclick = () => {
        if (expandedFolders.has('__root__')) {
            expandedFolders.delete('__root__');
        } else {
            expandedFolders.add('__root__');
        }
        renderFileTree();
    };
    rootRow.appendChild(rootIcon);
    const rootLabel = document.createElement('span');
    rootLabel.className = 'file-tree-name';
    rootLabel.textContent = rootName + '/';
    rootLabel.style.cursor = 'pointer';
    rootLabel.style.color = 'var(--mint)';
    rootLabel.onclick = () => {
        if (expandedFolders.has('__root__')) {
            expandedFolders.delete('__root__');
        } else {
            expandedFolders.add('__root__');
        }
        renderFileTree();
    };
    rootRow.appendChild(rootLabel);
    fileBrowser.appendChild(rootRow);

    if (!rootExpanded) return;

    if (!rootFiles.length) {
        const empty = document.createElement('div');
        empty.className = 'file-tree-empty';
        empty.style.paddingLeft = '18px';
        empty.textContent = '— empty —';
        fileBrowser.appendChild(empty);
        return;
    }

    const list = document.createElement('div');
    list.className = 'file-tree-list';
    for (const f of rootFiles) {
        renderFileTreeRow(list, f, '', 1); // depth 1 under root
    }
    fileBrowser.appendChild(list);
}

function renderFileTreeRow(parent, f, parentPath, depth) {
    const isDir = f.is_dir;
    const fullPath = parentPath ? `${parentPath}/${f.name}` : f.name;
    const isExpanded = isDir && expandedFolders.has(fullPath);

    const row = document.createElement('div');
    row.className = 'file-tree-row';
    row.style.paddingLeft = `${depth * 16 + 4}px`;

    const icon = document.createElement('span');
    icon.className = 'file-tree-icon';
    if (isDir) {
        icon.textContent = isExpanded ? '▾' : '▸';
        icon.style.cursor = 'pointer';
    } else {
        icon.textContent = '';
    }
    row.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'file-tree-name';
    name.title = fullPath;
    if (isDir) {
        name.textContent = f.name + '/';
        name.style.cursor = 'pointer';
        name.onclick = async () => toggleFolder(fullPath);
        icon.onclick = async () => toggleFolder(fullPath);
    } else {
        const a = document.createElement('a');
        a.href = `chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(fullPath)}`;
        a.textContent = f.name;
        a.download = f.name;
        name.appendChild(a);
    }
    row.appendChild(name);

    if (!isDir) {
        const size = document.createElement('span');
        size.className = 'file-tree-size';
        size.textContent = fmtSize(f.size);
        row.appendChild(size);
    }

    const actions = document.createElement('span');
    actions.className = 'file-tree-actions';
    const renameBtn = document.createElement('button');
    renameBtn.textContent = '✎';
    renameBtn.title = 'rename';
    renameBtn.onclick = async (e) => {
        e.stopPropagation();
        const newName = prompt('rename to:', f.name);
        if (!newName || newName === f.name) return;
        const parent = parentPath ? parentPath + '/' : '';
        await fetch(`chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(fullPath)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: parent + newName }),
            credentials: 'same-origin',
        });
        expandedFolders.clear();
        fileTreeCache = {};
        loadFileTree();
    };
    actions.appendChild(renameBtn);
    const delBtn = document.createElement('button');
    delBtn.textContent = '×';
    delBtn.title = 'delete';
    delBtn.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm(`delete ${isDir ? 'folder' : 'file'} "${f.name}"?`)) return;
        await fetch(`chat/${encodeURIComponent(currentChannel)}/files/${encodeURIComponent(fullPath)}`, {
            method: 'DELETE',
            credentials: 'same-origin',
        });
        expandedFolders.delete(fullPath);
        delete fileTreeCache[fullPath];
        if (parentPath) {
            delete fileTreeCache[parentPath];
            await fetchChildren(parentPath);
        } else {
            delete fileTreeCache[''];
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
            if (p.startsWith(path + '/')) expandedFolders.delete(p);
        }
        for (const key of Object.keys(fileTreeCache)) {
            if (key === path || key.startsWith(path + '/')) delete fileTreeCache[key];
        }
    } else {
        // expand: lazy-fetch just this folder's children, no parent/root refetch
        expandedFolders.add(path);
        await fetchChildren(path);
    }
    renderFileTree();
}

function buildToolbar(parentPath) {
    const toolbar = document.createElement('div');
    toolbar.className = 'file-tree-toolbar';

    const uploadInput = document.createElement('input');
    uploadInput.type = 'file';
    uploadInput.multiple = true;
    uploadInput.style.display = 'none';
    uploadInput.onchange = async () => {
        for (const f of uploadInput.files) {
            const relPath = parentPath ? `${parentPath}/${f.name}` : f.name;
            try { await uploadToChannel(relPath, f); } catch (err) { alert(err.message); }
        }
        uploadInput.value = '';
        expandedFolders.clear();
        fileTreeCache = {};
        loadFileTree();
    };
    toolbar.appendChild(uploadInput);

    const uploadBtn = document.createElement('button');
    uploadBtn.textContent = 'upload';
    uploadBtn.title = 'select files to upload';
    uploadBtn.onclick = () => uploadInput.click();
    toolbar.appendChild(uploadBtn);

    const folderInput = document.createElement('input');
    folderInput.type = 'file';
    folderInput.webkitdirectory = true;
    folderInput.style.display = 'none';
    folderInput.onchange = async () => {
        for (const f of folderInput.files) {
            const relPath = parentPath ? `${parentPath}/${f.webkitRelativePath}` : f.webkitRelativePath;
            try { await uploadToChannel(relPath, f); } catch (err) { alert(err.message); }
        }
        folderInput.value = '';
        expandedFolders.clear();
        fileTreeCache = {};
        loadFileTree();
    };
    toolbar.appendChild(folderInput);

    const folderBtn = document.createElement('button');
    folderBtn.textContent = 'upload folder';
    folderBtn.title = 'select a folder to upload';
    folderBtn.onclick = () => folderInput.click();
    toolbar.appendChild(folderBtn);

    const newFolderBtn = document.createElement('button');
    newFolderBtn.textContent = '+ folder';
    newFolderBtn.onclick = () => {
        const name = prompt('folder name:');
        if (!name) return;
        const fullPath = parentPath ? `${parentPath}/${name}` : name;
        fetch(`chat/${encodeURIComponent(currentChannel)}/mkdir`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dir_name: fullPath }),
            credentials: 'same-origin',
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
        xhr.open('POST', `chat/${encodeURIComponent(currentChannel)}/files?name=${encodeURIComponent(relPath)}`);
        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
            else reject(new Error(`${file.name}: upload failed (${xhr.status})`));
        };
        xhr.onerror = () => reject(new Error(`${file.name}: upload failed`));
        xhr.send(file);
    });
}

// ---- agent popup for +/− in channel header ----

let agentPopupEl = null;

function hideAgentPopup() {
    if (agentPopupEl) {
        agentPopupEl.remove();
        agentPopupEl = null;
    }
}

function showAgentPopup(anchor, names, onSelect) {
    hideAgentPopup();
    if (!names.length) return;
    const popup = document.createElement('div');
    popup.className = 'agent-popup';
    names.forEach(name => {
        const row = document.createElement('button');
        row.textContent = name;
        row.onclick = () => onSelect(name);
        popup.appendChild(row);
    });
    const rect = anchor.getBoundingClientRect();
    popup.style.left = rect.left + 'px';
    popup.style.top = (rect.bottom + 4) + 'px';
    popup.onclick = (e) => e.stopPropagation();
    document.body.appendChild(popup);
    agentPopupEl = popup;
    setTimeout(() => {
        document.addEventListener('click', hideAgentPopup, { once: true });
    }, 0);
}
