// === secrets tab: user-level key-value store (fab/data/INT3RF4CE/{user}/secrets.json) ===
// three sections: llm apis (hardset names — the backend resolves them), compute ssh,
// accounts. values are write-only from the browser: names + categories come over the
// wire, never values.

let ws = null;
let secretItems = []; // [{name, cat}]

const CAT_IDS = { llm: 'cat-llm', git: 'cat-git', gitrepo: 'cat-gitrepo', computerent: 'cat-computerent', compute: 'cat-compute', account: 'cat-account' };

function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/INT3RF4CE/ws`);
    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'auth_required') {
            document.getElementById('auth-overlay').style.display = 'flex';
            return;
        }
        if (msg.type === 'secrets') {
            secretItems = msg.secrets || [];
            const header = document.getElementById('chat-header');
            header.textContent = 'secrets';
            header.classList.remove('error');
            render();
        }
        if (msg.type === 'error') {
            // sticky + red: validation errors (bad key format etc.) must not be missable
            const header = document.getElementById('chat-header');
            header.textContent = 'secrets — ' + msg.msg;
            header.classList.add('error');
        }
    };
    ws.onopen = () => send({ cmd: 'list_secrets' });
    ws.onclose = () => setTimeout(connect, 2000);
}

function send(cmd) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(cmd));
}

function render() {
    for (const cat of Object.keys(CAT_IDS)) {
        const box = document.getElementById(CAT_IDS[cat]);
        box.innerHTML = '';
        const items = secretItems.filter(s => s.cat === cat);
        if (!items.length) {
            const empty = document.createElement('div');
            empty.className = 'secrets-empty';
            empty.textContent = 'empty';
            box.appendChild(empty);
            continue;
        }
        for (const item of items) box.appendChild(secretRow(item));
    }
}

function secretRow(item) {
    const row = document.createElement('div');
    row.className = 'secret-row';

    const label = document.createElement('span');
    label.className = 'secret-name mono';
    label.textContent = item.name;
    row.appendChild(label);

    if (item.cat === 'gitrepo') {
        // repos are not secret: shown in plain text, delete + re-add to change
        const url = document.createElement('span');
        url.className = 'secret-url mono';
        url.textContent = item.value;
        row.appendChild(url);
    } else if (item.cat === 'git') {
        // account is visible; the private key stays write-only
        const account = document.createElement('span');
        account.className = 'secret-account mono';
        account.textContent = item.value.account;
        row.appendChild(account);
        const keyInput = document.createElement('textarea');
        keyInput.placeholder = '••• key saved — paste to overwrite';
        keyInput.spellcheck = false;
        row.appendChild(keyInput);
        const saveBtn = document.createElement('button');
        saveBtn.textContent = 'save';
        saveBtn.onclick = () => {
            if (!keyInput.value) return;
            send({ cmd: 'set_secret', key: item.name, value: { account: item.value.account, key: keyInput.value }, cat: 'git' });
            keyInput.value = '';
        };
        row.appendChild(saveBtn);
    } else {
        const input = document.createElement('input');
        input.placeholder = '••• saved — type to overwrite';
        input.spellcheck = false;
        row.appendChild(input);
        const saveBtn = document.createElement('button');
        saveBtn.textContent = 'save';
        saveBtn.onclick = () => {
            if (!input.value) return;
            send({ cmd: 'set_secret', key: item.name, value: input.value, cat: item.cat });
            input.value = '';
        };
        row.appendChild(saveBtn);
    }

    const delBtn = document.createElement('button');
    delBtn.textContent = '×';
    delBtn.title = 'delete (also removed from every agent\'s grants)';
    delBtn.className = 'secret-del';
    delBtn.onclick = () => {
        if (confirm(`delete secret "${item.name}"? it is also removed from every agent's grants.`)) {
            send({ cmd: 'delete_secret', key: item.name });
        }
    };
    row.appendChild(delBtn);

    return row;
}

for (const btn of document.querySelectorAll('.add-secret-btn')) {
    btn.onclick = () => {
        const cat = btn.dataset.cat;
        if (cat === 'git') {
            const name = document.getElementById('new-git-name').value.trim();
            const account = document.getElementById('new-git-account').value.trim();
            const key = document.getElementById('new-git-key').value;
            if (!name || !account || !key) return;
            send({ cmd: 'set_secret', key: name, value: { account, key }, cat: 'git' });
            document.getElementById('new-git-name').value = '';
            document.getElementById('new-git-account').value = '';
            document.getElementById('new-git-key').value = '';
            return;
        }
        // every non-git add row follows the new-{cat}-name / new-{cat}-value id pattern
        const nameEl = document.getElementById(`new-${cat}-name`);
        const valueEl = document.getElementById(`new-${cat}-value`);
        const name = nameEl.value.trim();
        const value = valueEl.value;
        if (!name || !value) return;
        send({ cmd: 'set_secret', key: name, value: value, cat: cat });
        valueEl.value = '';
        if (nameEl.tagName === 'INPUT') nameEl.value = '';
    };
}

connect();
