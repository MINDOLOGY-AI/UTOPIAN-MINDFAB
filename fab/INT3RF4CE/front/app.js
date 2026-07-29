// WebSocket connection
let ws = null;
let agents = {};
let selectedAgent = null;
let chatMode = false;
let apiStatus = {};
let lastModelUsed = {};
let menuAgent = null;

// DOM elements
const agentList = document.getElementById('agent-list');
const newAgentName = document.getElementById('new-agent-name');
const createBtn = document.getElementById('create-btn');
const chatInput = document.getElementById('chat-input');
const startBtn = document.getElementById('start-btn');
const pauseBtn = document.getElementById('pause-btn');
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
            // populate the model dropdown from the server registry (kimi, glm, hierarchy, ...)
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
            }
            break;

        case 'agents':
            agents = msg.agents;
            // preselect agent from ?agent= query param (used by F4B teleport links)
            if (!selectedAgent) {
                const want = new URLSearchParams(window.location.search).get('agent');
                if (want && agents[want]) selectAgent(want);
            }
            renderAgentList();
            updateButtons();
            updateVnc();
            if (selectedAgent && agents[selectedAgent]) {
                modelSelect.value = agents[selectedAgent].model || 'kimi-k3';
                // sync chat button with the agent's persisted mode
                chatMode = !!agents[selectedAgent].chat_mode;
                chatModeBtn.classList.toggle('active', chatMode);
            }
            break;

        case 'context':
            if (msg.name === selectedAgent) {
                renderContext(msg.messages);
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
    hideAgentMenu();
    renderAgentList();
    updateButtons();
    updateVnc();
    send({ cmd: 'get_context', name: name });
    if (agents[name]) {
        modelSelect.value = agents[name].model || 'kimi-k3';
        chatMode = !!agents[name].chat_mode;
        chatModeBtn.classList.toggle('active', chatMode);
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
    const isWorking = agent?.working || false;

    startBtn.disabled = !hasSelection || isWorking;
    pauseBtn.disabled = !hasSelection || !isWorking;
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
    contentDiv.className = 'content';
    contentDiv.textContent = text;
    div.appendChild(roleDiv);
    div.appendChild(contentDiv);
    contextMessages.appendChild(div);
}

function renderContext(messages) {
    contextMessages.innerHTML = '';
    messages.forEach(msg => {
        const role = msg.role;
        const blocks = Array.isArray(msg.content) ? msg.content : [];

        if (role === 'user') {
            blocks.forEach(b => {
                if (b.type === 'text') {
                    addTextBlock('user', 'user', b.text || '');
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
            });
        } else if (role === 'assistant') {
            blocks.forEach(b => {
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
                    const args = JSON.stringify(b.arguments || {});
                    addThinBlock('command', name, `${name} ${args}`);
                }
            });
        }
    });

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

startBtn.onclick = () => {
    if (selectedAgent) {
        send({ cmd: 'start', name: selectedAgent });
    }
};

pauseBtn.onclick = () => {
    if (selectedAgent) {
        send({ cmd: 'pause', name: selectedAgent });
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
    chatModeBtn.classList.toggle('active', chatMode);
    send({ cmd: 'chat_mode', name: selectedAgent, enabled: chatMode });
};


modelSelect.onchange = () => {
    if (selectedAgent) {
        send({ cmd: 'set_model', name: selectedAgent, model: modelSelect.value });
    }
};

chatInput.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (text && selectedAgent) {
            send({ cmd: 'chat', name: selectedAgent, text: text });
            chatInput.value = '';
        }
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
