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
    const add = document.createElement('button');
    add.className = 'member-btn';
    add.textContent = '+ agent';
    add.title = 'add an agent to this channel';
    add.onclick = () => {
        const name = prompt('add which agent?');
        if (name) send({ cmd: 'set_members', channel: ch.id, agents: [...agents(), name] });
    };
    const rm = document.createElement('button');
    rm.className = 'member-btn';
    rm.textContent = '− agent';
    rm.title = 'remove an agent from this channel';
    rm.onclick = () => {
        const name = prompt('remove which agent?');
        if (name) send({ cmd: 'set_members', channel: ch.id, agents: agents().filter(m => m !== name) });
    };
    chatHeader.appendChild(add);
    chatHeader.appendChild(rm);
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
