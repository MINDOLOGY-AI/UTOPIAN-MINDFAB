// WebSocket connection
let ws = null;
// {name: {container_on, working, novnc_port}} — same format as backend
let agents = {};
let selectedAgent = null;
let chatMode = false;
let promptOpen = false;

// DOM elements
const agentList = document.getElementById('agent-list');
const newAgentName = document.getElementById('new-agent-name');
const createBtn = document.getElementById('create-btn');
const chatInput = document.getElementById('chat-input');
const startBtn = document.getElementById('start-btn');
const pauseBtn = document.getElementById('pause-btn');
const deleteBtn = document.getElementById('delete-btn');
const chatModeBtn = document.getElementById('chat-mode-btn');
const contextMessages = document.getElementById('context-messages');
const vncPlaceholder = document.getElementById('vnc-placeholder');
const vncFrame = document.getElementById('vnc-frame');
const promptBtn = document.getElementById('prompt-btn');
const promptPopup = document.getElementById('prompt-popup');
const promptInput = document.getElementById('prompt-input');

// Connect to WebSocket
function connect() {
    // base href is /intvrface/, so relative 'ws' resolves to /intvrface/ws
    ws = new WebSocket('ws');

    ws.onopen = () => {
        console.log('Connected to server');
    };

    // incoming messages
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
    };

    // auto reconnects when connection lost
    ws.onclose = () => {
        console.log('Disconnected, reconnecting in 2s...');
        setTimeout(connect, 2000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };
}

// Handle incoming messages
function handleMessage(msg) {
    switch (msg.type) {
        case 'agents':
            agents = msg.agents;
            renderAgentList();
            updateButtons();
            updateVnc();
            break;

        case 'context':
            if (msg.name === selectedAgent) {
                renderContext(msg.messages);
            }
            break;

        case 'user_prompt':
            if (msg.name === selectedAgent) {
                promptInput.value = msg.text || '';
            }
            break;

        case 'error':
            alert('Error: ' + msg.msg);
            break;
    }
}

// Send command to server
function send(cmd) {
    if (ws && ws.readyState === WebSocket.OPEN){ //WEBSOCKET.OPEN is a class constant 1 
        ws.send(JSON.stringify(cmd));
    }
}

// Render agent list
function renderAgentList() {
    agentList.innerHTML = '';
    for (const [name, info] of Object.entries(agents)) {
        const li = document.createElement('li');
        const status = info.working ? 'working' : info.container_on ? 'paused' : 'stopped';
        const statusClass = info.working ? 'working' : info.container_on ? 'paused' : '';
        li.innerHTML = `
            <div>${name}</div>
            <div class="status ${statusClass}">
                ${status} | port ${info.novnc_port}
            </div>
        `;
        if (name === selectedAgent) {
            li.classList.add('selected');
        }
        li.onclick = () => selectAgent(name);
        agentList.appendChild(li);
    }
}

// Select an agent
function selectAgent(name) {
    selectedAgent = name;
    renderAgentList();
    updateButtons();
    updateVnc();
    send({ cmd: 'get_context', name: name });
    send({ cmd: 'get_user_prompt', name: name });
}

// Update VNC iframe based on selected agent's state
function updateVnc() {
    const agent = selectedAgent ? agents[selectedAgent] : null;
    if (agent && agent.container_on) {
        // only reload iframe if src changed (avoid reconnecting on every update)
        const url = `http://${window.location.hostname}:${agent.novnc_port}/vnc.html?autoconnect=true`;
        if (vncFrame.src !== url) vncFrame.src = url;
        vncFrame.style.display = 'block';
        vncPlaceholder.style.display = 'none';
    } else {
        vncPlaceholder.textContent = agent ? 'container stopped' : 'select an agent to view';
        vncPlaceholder.style.display = 'block';
        vncFrame.style.display = 'none';
        vncFrame.src = '';
    }
}

// Update button states
function updateButtons() {
    const agent = selectedAgent ? agents[selectedAgent] : null;
    const hasSelection = !!agent; //converts to boolean
    const isWorking = agent?.working || false; // ?. is a javascript query that could return undefined. || in javascript is a hierachy of truthyness.
    const containerOn = agent?.container_on || false;

    startBtn.disabled = !hasSelection || isWorking;
    pauseBtn.disabled = !hasSelection || !isWorking;
    deleteBtn.disabled = !hasSelection;
    chatInput.disabled = !hasSelection || !containerOn;
}

// Render context messages
// render a thin collapsed row (for tool_use / tool_result blocks)
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

// render a normal text row for user/assistant text blocks
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
        const role = msg.role;  // 'user' | 'assistant'
        (msg.content || []).forEach(block => {
            if (block.type === 'text') {
                // user text -> purple, assistant text -> orange
                addTextBlock(role, role, block.text || '');
            } else if (block.type === 'tool_use') {
                // yellow command row
                const args = block.input ? JSON.stringify(block.input) : '';
                addThinBlock('command', block.name, `${block.name} ${args}`);
            } else if (block.type === 'tool_result') {
                // green environment row — content is string OR list of sub-blocks
                const inner = block.content;
                if (typeof inner === 'string') {
                    const label = inner.startsWith('[TERM]') ? 'TERM'
                        : inner.startsWith('[READ') ? 'READ'
                        : inner.startsWith('[WRITE') ? 'WRITE'
                        : inner.startsWith('[EDIT') ? 'EDIT'
                        : inner === 'ok' ? 'OK' : 'RESULT';
                    addThinBlock('environment', label, inner);
                } else if (Array.isArray(inner)) {
                    inner.forEach(sub => {
                        if (sub.type === 'image') {
                            const img = document.createElement('img');
                            img.src = `data:${sub.source.media_type};base64,${sub.source.data}`;
                            img.className = 'context-img';
                            addThinBlock('environment', 'LOOK', img);
                        } else if (sub.type === 'text') {
                            addThinBlock('environment', 'RESULT', sub.text || '');
                        }
                    });
                }
            } else if (block.type === 'image') {
                // bare image (rare — usually images live inside tool_result)
                const img = document.createElement('img');
                img.src = `data:${block.source.media_type};base64,${block.source.data}`;
                img.className = 'context-img';
                addThinBlock('environment', 'IMG', img);
            }
        });
    });

    contextMessages.scrollTop = contextMessages.scrollHeight;
}

// Event listeners
createBtn.onclick = () => {
    const name = newAgentName.value.trim();
    if (!name) {
        alert('Please enter agent name');
        return;
    }
    send({ cmd: 'create', name: name });
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

deleteBtn.onclick = () => {
    if (selectedAgent && confirm(`Delete agent "${selectedAgent}"?`)) {
        send({ cmd: 'delete', name: selectedAgent });
        selectedAgent = null;
        contextMessages.innerHTML = '';
    }
};

chatModeBtn.onclick = () => {
    if (!selectedAgent) return;
    chatMode = !chatMode;
    chatModeBtn.classList.toggle('active', chatMode);
    send({ cmd: 'chat_mode', name: selectedAgent, enabled: chatMode });
};

// prompt button: toggle popup, send on close
promptBtn.onclick = () => {
    if (!selectedAgent) return;
    promptOpen = !promptOpen;
    promptPopup.style.display = promptOpen ? 'block' : 'none';
    chatInput.style.display = promptOpen ? 'none' : 'block';
    promptBtn.classList.toggle('active', promptOpen);
    // closing: send current text to backend
    if (!promptOpen) {
        send({ cmd: 'set_user_prompt', name: selectedAgent, text: promptInput.value });
    }
};

// Enter to send (Shift+Enter for newline)
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

// Start connection
connect();
