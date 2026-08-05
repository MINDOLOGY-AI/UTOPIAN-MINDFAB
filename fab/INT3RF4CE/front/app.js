// === agent view: docker agents, noVNC screen, per-agent dm stream ===
// one websocket for everything; agents/state come as broadcasts, commands go
// out as {cmd: ...} json. the right panel merges the dm channel with the
// agent's context extras (tools, reasoning, images) into one timeline.

// WebSocket connection
let ws = null;
let agents = {};
let selectedAgent = null;
let chatMode = false;
let apiStatus = {};
let lastModelUsed = {};
let menuAgent = null;
let modelCapabilities = {}; // {model_id: {supported_attachment_types: [...]}}

// DOM elements
const agentList = document.getElementById('agent-list');
const newAgentName = document.getElementById('new-agent-name');
const createBtn = document.getElementById('create-btn');
const chatInput = document.getElementById('chat-input');
const dockerBtn = document.getElementById('docker-btn');
const modelBtn = document.getElementById('model-btn');
const chatModeBtn = document.getElementById('chat-mode-btn');
const contextMessages = document.getElementById('context-messages');
const vncPlaceholder = document.getElementById('vnc-placeholder');
const vncFrame = document.getElementById('vnc-frame');
const statusBar = document.getElementById('status-bar');
const modelSelect = document.getElementById('model-select');
const agentMenu = document.getElementById('agent-menu');
const agentMenuRename = document.getElementById('agent-menu-rename');
const agentMenuDelete = document.getElementById('agent-menu-delete');

// auth: when true, the server rejected us for not being logged in — stop reconnecting
let authBlocked = false;

// shared markdown renderer (hub component) — same stack as thoughtgraph nodes.
// user + assistant chat text renders as markdown; tool results stay plain.
const md = makeMarkdownRenderer();

function showAuthOverlay(show) {
    document.getElementById('auth-overlay').style.display = show ? 'flex' : 'none';
}

function connect() {
    if (authBlocked) return;
    ws = new WebSocket('ws');

    ws.onopen = () => {
        console.log('Connected to server');
        send({ cmd: 'list_models' });
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
    };

    ws.onclose = () => {
        if (authBlocked) return;
        console.log('Disconnected, reconnecting in 2s...');
        setTimeout(connect, 2000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };
}

function send(cmd) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(cmd));
    }
}

function handleMessage(msg) {
    switch (msg.type) {
        case 'models':
            // populate the model dropdown from the server registry (kimi, deepseek, hierarchy, ...)
            {
                const current = selectedAgent && agents[selectedAgent]
                    ? (agents[selectedAgent].model || modelSelect.value)
                    : modelSelect.value;
                modelSelect.innerHTML = '';
                for (const [display, id] of Object.entries(msg.models || {})) {
                    const opt = document.createElement('option');
                    opt.value = id;
                    opt.textContent = display;
                    if (id === current) opt.selected = true;
                    modelSelect.appendChild(opt);
                }
                modelCapabilities = msg.capabilities || {};
            }
            break;

        case 'agents':
            agents = msg.agents;
            // preselect agent from ?agent= query param (used by F4B teleport links),
            // otherwise just select the first agent so the page is never empty
            if (!selectedAgent) {
                const want = new URLSearchParams(window.location.search).get('agent');
                if (want && agents[want]) selectAgent(want);
                else {
                    const first = Object.keys(agents)[0];
                    if (first) selectAgent(first);
                }
            }
            renderAgentList();
            updateButtons();
            updateVnc();
            if (selectedAgent && agents[selectedAgent]) {
                modelSelect.value = agents[selectedAgent].model || 'kimi-k3';
                // sync chat button with the agent's persisted mode
                chatMode = !!agents[selectedAgent].chat_mode;
                chatModeBtn.classList.toggle('on', chatMode);
            }
            break;

        case 'context':
            if (msg.name === selectedAgent) {
                lastContextMessages = msg.messages;
                // the render happens when the DM log arrives
                send({ cmd: 'get_messages', channel: `dm-${selectedAgent}`, limit: 200 });
            }
            break;

        case 'messages':
            if (msg.channel === `dm-${selectedAgent}`) {
                dmMsgs = msg.messages || [];
                renderContext(lastContextMessages);
            }
            break;

        case 'chat_message':
            if (msg.channel === `dm-${selectedAgent}`) {
                dmMsgs.push(msg.message);
                renderContext(lastContextMessages);
            }
            break;

        case 'status':
            if (msg.name && msg.phase === 'api_call') {
                apiStatus[msg.name] = msg.state;
                updateStatusBar();
            }
            // hierarchy: which provider actually answered
            if (msg.name && msg.phase === 'model_used') {
                lastModelUsed[msg.name] = msg.state;
                updateStatusBar();
            }
            // agent started/stopped its own docker (DOCKER_START/DOCKER_STOP)
            if (msg.name && msg.phase === 'container' && agents[msg.name]) {
                agents[msg.name].container_on = msg.state === 'started';
                renderAgentList();
                updateButtons();
                updateVnc();
            }
            break;

        case 'error':
            alert('Error: ' + msg.msg);
            break;

        case 'auth_required':
            authBlocked = true;
            showAuthOverlay(true);
            break;
    }
}

function renderAgentList() {
    agentList.innerHTML = '';
    for (const [name, info] of Object.entries(agents)) {
        const li = document.createElement('li');
        // cybersec: build the row with textContent instead of innerHTML — agent names come from the server, and innerHTML would let a crafted name inject script into the page (XSS)
        const row = document.createElement('div');
        row.className = 'agent-row';
        const nameDiv = document.createElement('div');
        nameDiv.className = 'agent-name';
        nameDiv.textContent = name;
        row.appendChild(nameDiv);
        const menuBtn = document.createElement('button');
        menuBtn.className = 'agent-menu-btn';
        menuBtn.dataset.name = name;
        menuBtn.textContent = '⋮';
        row.appendChild(menuBtn);
        li.appendChild(row);
        if (name === selectedAgent) {
            li.classList.add('selected');
        }
        li.onclick = (e) => {
            if (e.target.classList.contains('agent-menu-btn')) {
                openAgentMenu(name, e.target);
                return;
            }
            selectAgent(name);
        };
        agentList.appendChild(li);
    }
}

function openAgentMenu(name, target) {
    menuAgent = name;
    const rect = target.getBoundingClientRect();
    agentMenu.style.display = 'flex';
    agentMenu.style.left = rect.left + 'px';
    agentMenu.style.top = (rect.bottom + 4) + 'px';
}

function hideAgentMenu() {
    menuAgent = null;
    agentMenu.style.display = 'none';
}

function selectAgent(name) {
    selectedAgent = name;
    dmMsgs = [];
    lastContextMessages = [];
    hideAgentMenu();
    renderAgentList();
    updateButtons();
    updateVnc();
    send({ cmd: 'get_context', name: name });
    if (agents[name]) {
        modelSelect.value = agents[name].model || 'kimi-k3';
        chatMode = !!agents[name].chat_mode;
        chatModeBtn.classList.toggle('on', chatMode);
    }
}

function updateVnc() {
    const agent = selectedAgent ? agents[selectedAgent] : null;
    if (agent && agent.container_on) {
        // cybersec: load noVNC through the authenticated app proxy — the container port is localhost-only now, and 'path' tells noVNC to open its websocket through the proxy too
        const url = `/INT3RF4CE/vnc/${agent.novnc_port}/vnc.html?autoconnect=true&resize=scale&path=INT3RF4CE/vnc/${agent.novnc_port}/websockify`;
        const absUrl = new URL(url, window.location.origin).href;
        if (vncFrame.src !== absUrl) vncFrame.src = url;
        vncFrame.style.display = 'block';
        vncPlaceholder.style.display = 'none';
        startVncRetry();
    } else {
        stopVncRetry();
        vncPlaceholder.textContent = agent ? 'container stopped' : 'select an agent to view';
        vncPlaceholder.style.display = 'block';
        vncFrame.style.display = 'none';
        vncFrame.src = '';
    }
}

// noVNC never retries on its own: if the container's websockify wasn't up yet
// (or the server reloaded mid-connect) it shows "failed to connect" forever.
// reload the iframe while its status element reports an error.
let vncRetryTimer = null;

function startVncRetry() {
    if (vncRetryTimer) return;
    vncRetryTimer = setInterval(() => {
        try {
            const status = vncFrame.contentDocument?.getElementById('noVNC_status');
            if (status && status.classList.contains('noVNC_status_error')) {
                vncFrame.src = vncFrame.src;
            }
        } catch (e) { /* frame mid-navigation, retry next tick */ }
    }, 3000);
}

function stopVncRetry() {
    clearInterval(vncRetryTimer);
    vncRetryTimer = null;
}

function updateButtons() {
    const agent = selectedAgent ? agents[selectedAgent] : null;
    const hasSelection = !!agent;

    dockerBtn.disabled = !hasSelection;
    modelBtn.disabled = !hasSelection;
    // both buttons mirror backend state (agents broadcast): grey play = off,
    // purple pause = on. click toggles.
    dockerBtn.textContent = agent?.container_on ? '⏸ docker' : '▶ docker';
    dockerBtn.title = agent?.container_on ? 'stop the docker container' : 'start the docker container';
    dockerBtn.classList.toggle('on', !!agent?.container_on);
    modelBtn.textContent = agent?.working ? '⏸ model' : '▶ model';
    modelBtn.title = agent?.working ? 'stop the model' : 'start the model';
    modelBtn.classList.toggle('on', !!agent?.working);
    chatInput.disabled = !hasSelection;

    updateStatusBar();
}

function updateStatusBar() {
    const isGenerating = selectedAgent && apiStatus[selectedAgent] === 'started';
    if (isGenerating) {
        statusBar.textContent = 'generating...';
        statusBar.style.display = 'block';
    } else if (selectedAgent && lastModelUsed[selectedAgent]) {
        // hierarchy: show which provider actually answered last
        statusBar.textContent = `answered by ${lastModelUsed[selectedAgent]}`;
        statusBar.style.display = 'block';
    } else {
        statusBar.style.display = 'none';
    }
}

function addThinBlock(cssClass, label, content) {
    const div = document.createElement('div');
    div.className = `message ${cssClass}`;
    const roleDiv = document.createElement('div');
    roleDiv.className = 'role';
    roleDiv.textContent = label;
    roleDiv.style.cursor = 'pointer';
    const contentDiv = document.createElement('div');
    contentDiv.className = 'content collapsed';
    if (typeof content === 'string') {
        contentDiv.textContent = content;
    } else {
        contentDiv.appendChild(content);
    }
    roleDiv.onclick = () => contentDiv.classList.toggle('collapsed');
    div.appendChild(roleDiv);
    div.appendChild(contentDiv);
    contextMessages.appendChild(div);
}

function addTextBlock(cssClass, label, text) {
    const div = document.createElement('div');
    div.className = `message ${cssClass}`;
    const roleDiv = document.createElement('div');
    roleDiv.className = 'role';
    roleDiv.textContent = label;
    const contentDiv = document.createElement('div');
    contentDiv.className = 'content md';
    contentDiv.innerHTML = md.render(text);
    div.appendChild(roleDiv);
    div.appendChild(contentDiv);
    contextMessages.appendChild(div);
}

// agent view stream = the DM channel conversation (text + file chips) merged
// with context extras (tools, reasoning, images, non-chat texts) by timestamp.
// texts the channel already covers are skipped from context — no duplicates.
let dmMsgs = [];
let lastContextMessages = [];

function renderDmMessage(m) {
    if (m.type === 'file' && m.file) {
        const div = document.createElement('div');
        div.className = 'message environment';
        const roleDiv = document.createElement('div');
        roleDiv.className = 'role';
        roleDiv.textContent = m.sender === '__user__' ? 'you' : m.sender;
        const a = document.createElement('a');
        a.className = 'chat-file';
        a.href = `chat/${encodeURIComponent(`dm-${selectedAgent}`)}/files/${encodeURIComponent(m.file.path)}`;
        a.textContent = `↓ ${m.file.name} (${fmtSize(m.file.size)})`;
        a.download = m.file.name;
        div.appendChild(roleDiv);
        div.appendChild(a);
        contextMessages.appendChild(div);
        return;
    }
    if (m.sender === '__user__') addTextBlock('user', 'you', m.text || '');
    else addTextBlock('assistant', m.sender, m.text || '');
}

function renderCtxBlock(role, b) {
    if (role === 'user') {
        if (b.type === 'text') {
            addTextBlock('user', 'you', b.text || '');
        } else if (b.type === 'image') {
            const src = b.source || {};
            const img = document.createElement('img');
            img.src = `data:${src.media_type || 'image/png'};base64,${src.data || ''}`;
            img.className = 'context-img';
            addThinBlock('environment', 'IMG', img);
        } else if (b.type === 'tool_result') {
            const label = b.name || 'tool';
            const content = b.content;
            if (typeof content === 'string') {
                addThinBlock('environment', label, content);
            } else if (Array.isArray(content)) {
                content.forEach(sub => {
                    if (sub.type === 'image') {
                        const src = sub.source || {};
                        const img = document.createElement('img');
                        img.src = `data:${src.media_type || 'image/png'};base64,${src.data || ''}`;
                        img.className = 'context-img';
                        addThinBlock('environment', label, img);
                    } else if (sub.type === 'text') {
                        addThinBlock('environment', label, sub.text || '');
                    }
                });
            }
        }
    } else if (role === 'assistant') {
        if (b.type === 'text') {
            const text = b.text || '';
            // reasoning content arrives as a text block prefixed [reasoning] — collapse it
            if (text.startsWith('[reasoning]')) {
                addThinBlock('reasoning', 'reasoning', text.slice('[reasoning]'.length).trim());
            } else {
                addTextBlock('assistant', 'assistant', text);
            }
        } else if (b.type === 'tool_use') {
            const name = b.name || 'tool';
            // CHAT_SEND to a non-DM channel isn't covered by the dm stream —
            // show it as a normal text block labeled with the channel it went to
            if (name === 'CHAT_SEND') {
                const args = b.arguments || {};
                const ch = args.channel || '';
                if (ch !== `dm-${selectedAgent}` && ch !== selectedAgent) {
                    const text = args.text || (args.file ? `↓ file: ${args.file}` : '');
                    if (text) {
                        addTextBlock('assistant', `#${ch}`, text);
                        return;
                    }
                }
            }
            const args = JSON.stringify(b.arguments || {});
            addThinBlock('command', name, `${name} ${args}`);
        }
    }
}

function renderContext(messages) {
    contextMessages.innerHTML = '';
    // merge the DM channel conversation with context extras by timestamp
    const channelAgentTexts = dmMsgs.filter(m => m.sender !== '__user__' && m.text).map(m => m.text);
    const items = [];
    for (const m of dmMsgs) items.push({ ts: m.ts, kind: 'dm', m });
    for (const msg of messages) {
        const blocks = Array.isArray(msg.content) ? msg.content : [];
        for (const b of blocks) {
            // chat injections and mirrored replies are covered by the channel
            if (msg.role === 'user' && b.type === 'text' && b.text.startsWith('[chat #')) continue;
            if (msg.role === 'assistant' && b.type === 'text' && !b.text.startsWith('[reasoning]')
                && channelAgentTexts.some(t => t.includes(b.text))) continue;
            items.push({ ts: msg.ts || 0, kind: 'ctx', role: msg.role, b });
        }
    }
    items.sort((a, b) => a.ts - b.ts);
    for (const it of items) {
        if (it.kind === 'dm') renderDmMessage(it.m);
        else renderCtxBlock(it.role, it.b);
    }
    contextMessages.scrollTop = contextMessages.scrollHeight;
}


// Event listeners
function createAgentFlow(name) {
    if (!name) return;
    send({ cmd: 'create', name: name, model: modelSelect.value });
}

createBtn.onclick = () => {
    const name = newAgentName.value.trim();
    if (!name) {
        alert('Please enter agent name');
        return;
    }
    createAgentFlow(name);
    newAgentName.value = '';
};

dockerBtn.onclick = () => {
    if (selectedAgent) {
        const on = agents[selectedAgent]?.container_on;
        send({ cmd: on ? 'docker_stop' : 'docker_start', name: selectedAgent });
    }
};

modelBtn.onclick = () => {
    if (selectedAgent) {
        const working = agents[selectedAgent]?.working;
        send({ cmd: working ? 'pause' : 'start', name: selectedAgent });
    }
};

agentMenuRename.onclick = () => {
    if (!menuAgent) return;
    const newName = prompt(`Rename "${menuAgent}" to:`, menuAgent);
    if (newName && newName !== menuAgent) {
        send({ cmd: 'rename', name: menuAgent, new_name: newName });
    }
    hideAgentMenu();
};

agentMenuDelete.onclick = () => {
    if (!menuAgent) return;
    if (confirm(`Delete agent "${menuAgent}"? This removes its container, workspace, and context.`)) {
        send({ cmd: 'delete', name: menuAgent });
        if (selectedAgent === menuAgent) {
            selectedAgent = null;
            contextMessages.innerHTML = '';
        }
    }
    hideAgentMenu();
};

document.addEventListener('click', (e) => {
    if (!agentMenu.contains(e.target) && !e.target.classList.contains('agent-menu-btn')) {
        hideAgentMenu();
    }
});

chatModeBtn.onclick = () => {
    if (!selectedAgent) return;
    chatMode = !chatMode;
    chatModeBtn.classList.toggle('on', chatMode);
    send({ cmd: 'chat_mode', name: selectedAgent, enabled: chatMode });
};


modelSelect.onchange = () => {
    if (selectedAgent) {
        send({ cmd: 'set_model', name: selectedAgent, model: modelSelect.value });
    }
};

// ---- attachments: drag/paste files → base64 → inline with chat command ----

let pendingAttachments = []; // [{name, media_type, data}]

function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const dataUrl = reader.result;
            const comma = dataUrl.indexOf(',');
            resolve({
                name: file.name,
                media_type: file.type || 'application/octet-stream',
                data: dataUrl.slice(comma + 1),
            });
        };
        reader.onerror = () => reject(new Error(`failed to read ${file.name}`));
        reader.readAsDataURL(file);
    });
}

function mimeTypeFromExt(name) {
    const ext = name.split('.').pop().toLowerCase();
    const map = {
        png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
        gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml',
        zip: 'application/zip', tar: 'application/tar',
        gz: 'application/gzip', bz2: 'application/x-bzip2',
        json: 'application/json', csv: 'text/csv',
        pdf: 'application/pdf', pt: 'application/octet-stream',
        pth: 'application/octet-stream',
    };
    return map[ext] || 'application/octet-stream';
}

function supportedTypes() {
    const model = selectedAgent ? (agents[selectedAgent]?.model || modelSelect.value) : modelSelect.value;
    const caps = modelCapabilities[model];
    return caps ? new Set(caps.supported_attachment_types) : new Set();
}

function validateAttachments(attachments) {
    const types = supportedTypes();
    const bad = [];
    for (const a of attachments) {
        const mt = a.media_type || mimeTypeFromExt(a.name);
        a.media_type = mt;
        if (types.size > 0 && !types.has(mt)) bad.push(`${a.name} (${mt})`);
    }
    if (bad.length) {
        alert(`file type not accepted by selected model:\n${bad.join('\n')}`);
        return false;
    }
    return true;
}

function renderAttachChips() {
    attachChips.innerHTML = '';
    pendingAttachments.forEach((a, i) => {
        const chip = document.createElement('span');
        chip.className = 'attach-chip';
        chip.textContent = `${a.name} `;
        const x = document.createElement('button');
        x.textContent = '×';
        x.onclick = () => { pendingAttachments.splice(i, 1); renderAttachChips(); };
        chip.appendChild(x);
        attachChips.appendChild(chip);
    });
}

async function addFiles(files) {
    for (const f of files) {
        pendingAttachments.push(await fileToBase64(f));
    }
    renderAttachChips();
}

const rightPanel = document.querySelector('.right-panel');
rightPanel.addEventListener('dragover', (e) => { e.preventDefault(); rightPanel.classList.add('drag-over'); });
rightPanel.addEventListener('dragleave', () => rightPanel.classList.remove('drag-over'));
rightPanel.addEventListener('drop', (e) => {
    e.preventDefault();
    rightPanel.classList.remove('drag-over');
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});

chatInput.addEventListener('paste', (e) => {
    if (e.clipboardData.files.length) {
        e.preventDefault();
        addFiles(e.clipboardData.files);
    }
});

chatInput.onkeydown = async (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const text = chatInput.value.trim();
        if ((!text && !pendingAttachments.length) || !selectedAgent) return;
        if (pendingAttachments.length && !validateAttachments(pendingAttachments)) {
            pendingAttachments = [];
            renderAttachChips();
            return;
        }
        send({
            cmd: 'chat',
            name: selectedAgent,
            text: text,
            attachments: pendingAttachments,
        });
        pendingAttachments = [];
        renderAttachChips();
        chatInput.value = '';
    }
};

// login/logout from the auth-box component: unblock and reconnect, or lock down
document.addEventListener('auth-changed', (e) => {
    if (e.detail.user) {
        authBlocked = false;
        showAuthOverlay(false);
        connect();
    } else {
        authBlocked = true;
        showAuthOverlay(true);
        if (ws) ws.close();
    }
});

// initial auth check: don't even open the websocket when logged out
fetch('/auth/me', { credentials: 'same-origin' }).then(res => {
    if (res.ok) {
        connect();
    } else {
        authBlocked = true;
        showAuthOverlay(true);
    }
});


// settings = transport to the thoughtgraph board with this agent's context panel
const settingsBtn = document.getElementById('settings-btn');
settingsBtn.onclick = () => {
    if (!selectedAgent) return;
    window.location.href = `/TH0UGHTGR4PH/?agent=${encodeURIComponent(selectedAgent)}`;
};
