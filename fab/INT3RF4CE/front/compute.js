// === compute tab: named ssh targets with usage tracking ===
// store: fab/data/INT3RF4CE/{user}/compute.json — [{"name", "ssh_command", "password"}]
// usage: fab/data/INT3RF4CE/{user}/compute_usage.json — {"computer_name": "agent_name"}
// all data shown in plain text — no redaction.

let ws = null;
let computeEntries = []; // [{name, ssh_command, password?, used_by?}]
let myUser = null;

async function loadUser() {
    try {
        const res = await fetch('/auth/me', { credentials: 'same-origin' });
        myUser = res.ok ? (await res.json()).user : null;
    } catch {
        myUser = null;
    }
}

function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/INT3RF4CE/ws`);
    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'auth_required') {
            document.getElementById('auth-overlay').style.display = 'flex';
            return;
        }
        if (msg.type === 'computes') {
            computeEntries = msg.computes || [];
            const header = document.getElementById('chat-header');
            header.textContent = 'compute';
            header.classList.remove('error');
            render();
        }
        if (msg.type === 'error') {
            const header = document.getElementById('chat-header');
            header.textContent = 'compute — ' + msg.msg;
            header.classList.add('error');
        }
    };
    ws.onopen = () => send({ cmd: 'list_computes' });
    ws.onclose = () => setTimeout(connect, 2000);
}

function send(cmd) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(cmd));
}

function render() {
    const box = document.getElementById('cat-specific');
    box.innerHTML = '';

    if (!computeEntries.length) {
        const empty = document.createElement('div');
        empty.className = 'secrets-empty';
        empty.textContent = 'no computers';
        box.appendChild(empty);
    } else {
        for (const item of computeEntries) box.appendChild(computeRow(item));
    }
}

function computeRow(item) {
    const wrapper = document.createElement('div');
    wrapper.className = 'compute-entry';

    // grey bar: name, ssh, password
    const row = document.createElement('div');
    row.className = 'secret-row';

    const label = document.createElement('span');
    label.className = 'secret-name mono';
    label.textContent = item.name;
    row.appendChild(label);

    const sshSpan = document.createElement('span');
    sshSpan.className = 'secret-url mono';
    sshSpan.textContent = item.ssh_command || '';
    row.appendChild(sshSpan);

    const pwSpan = document.createElement('span');
    pwSpan.className = 'compute-password mono';
    pwSpan.textContent = item.password || '(none)';
    row.appendChild(pwSpan);

    wrapper.appendChild(row);

    // right side: status text + check toggle + delete button (outside grey bar)
    const right = document.createElement('div');
    right.className = 'compute-controls';

    const status = document.createElement('span');
    status.className = 'compute-status mono';
    if (item.used_by) {
        const isMe = item.used_by === myUser;
        status.textContent = isMe ? '*(you)*' : `in use by ${item.used_by}`;
        status.style.color = isMe ? 'var(--mint)' : 'var(--orange)';
    } else {
        status.textContent = 'unused';
        status.style.color = 'var(--green)';
    }
    right.appendChild(status);

    const claimedByMe = item.used_by === myUser;
    const claimedByOther = item.used_by && !claimedByMe;
    const checkBtn = document.createElement('button');
    checkBtn.className = 'compute-check';
    checkBtn.textContent = claimedByMe ? '✕' : '✓';
    checkBtn.title = claimedByMe ? `click to release ${item.name}` : claimedByOther ? `claimed by ${item.used_by}` : `click to claim ${item.name}`;
    checkBtn.disabled = claimedByOther;
    checkBtn.style.opacity = claimedByOther ? '0.3' : '1';
    checkBtn.onclick = () => {
        if (claimedByMe) send({ cmd: 'release_compute', name: item.name });
        else send({ cmd: 'claim_compute', name: item.name });
    };
    right.appendChild(checkBtn);

    const delBtn = document.createElement('button');
    delBtn.textContent = '×';
    delBtn.title = 'delete (also releases if claimed)';
    delBtn.className = 'secret-del';
    delBtn.onclick = () => {
        if (confirm(`delete compute "${item.name}"? it is also released from any agent using it.`)) {
            send({ cmd: 'delete_compute', name: item.name });
        }
    };
    right.appendChild(delBtn);

    wrapper.appendChild(right);
    return wrapper;
}

document.getElementById('add-compute-btn').onclick = () => {
    const name = document.getElementById('new-compute-name').value.trim();
    const ssh = document.getElementById('new-compute-ssh').value.trim();
    const password = document.getElementById('new-compute-password').value;
    if (!name || !ssh) return;
    send({ cmd: 'add_compute', name, ssh_command: ssh, password });
    document.getElementById('new-compute-name').value = '';
    document.getElementById('new-compute-ssh').value = '';
    document.getElementById('new-compute-password').value = '';
};

(async () => {
    await loadUser();
    connect();
})();
