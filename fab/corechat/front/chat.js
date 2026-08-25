const agent = new URLSearchParams(location.search).get("agent"); // null when no agent picked yet
const msgs = document.getElementById("msgs");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");

// shared markdown renderer (katex, raw html escaped) from the hub component
const md = makeMarkdownRenderer();

// one-liner dom builder: make element, set class and text if given (textContent, never html)
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// chat text renders as markdown, tool/reasoning stays plain
function mdDiv(text) {
  const div = el("div", "content md");
  div.innerHTML = md.render(text);
  return div;
}

// expanded block for real conversation text (you / assistant)
function addTextBlock(cssClass, label, text) {
  const div = el("div", `msg ${cssClass}`);
  div.appendChild(el("div", "role", label));
  div.appendChild(mdDiv(text));
  msgs.appendChild(div);
}

// thin block for extras (reasoning, tool calls, tool results) — collapsed by default, click anywhere to expand
function addThinBlock(cssClass, label, text, useMd) {
  const div = el("div", `msg thin ${cssClass}`);
  const roleDiv = el("div", "role", label);
  const contentDiv = useMd ? mdDiv(text) : el("div", "content", text);
  contentDiv.classList.add("collapsed");
  div.onclick = () => contentDiv.classList.toggle("collapsed");
  div.appendChild(roleDiv);
  div.appendChild(contentDiv);
  msgs.appendChild(div);
}

function render(m) {
  if (m.role === "user") {
    // user content is always content blocks
    const div = el("div", "msg user");
    div.appendChild(el("div", "role", "you"));
    for (const b of m.content) {
      if (b.type === "text") div.appendChild(mdDiv(b.text));
      else if (b.type === "image_url") {
        const img = document.createElement("img");
        img.src = b.image_url.url;
        div.appendChild(img);
      }
    }
    msgs.appendChild(div);
  } else if (m.role === "assistant") {
    if (m.reasoning_content) addThinBlock("reasoning", "reasoning", m.reasoning_content, true);
    if (m.content) addTextBlock("assistant", "assistant", m.content);
    for (const tc of m.tool_calls || []) {
      const fn = tc.function || {};
      addThinBlock("command", fn.name || "tool", `${fn.name} ${fn.arguments || "{}"}`);
    }
  } else if (m.role === "tool") {
    addThinBlock("tool", m.name || "tool", typeof m.content === "string" ? m.content : "");
  }
}

function scrollDown() {
  msgs.scrollTop = msgs.scrollHeight;
}

let rendered = 0;
let pendingAttachments = []; // data url strings waiting to be sent

// frontend converts to content blocks: text block plus one image block per pending attachment
function toBlocks(text) {
  return [{ type: "text", text },
          ...pendingAttachments.map(url => ({ type: "image_url", image_url: { url } }))];
}

// thumbnail strip above the composer, × to remove
function renderAttachments() {
  const strip = document.getElementById("attachments");
  strip.innerHTML = "";
  pendingAttachments.forEach((url, i) => {
    const thumb = el("div", "attach-thumb");
    const img = document.createElement("img");
    img.src = url;
    const x = el("button", null, "×");
    x.onclick = () => { pendingAttachments.splice(i, 1); renderAttachments(); };
    thumb.appendChild(img);
    thumb.appendChild(x);
    strip.appendChild(thumb);
  });
}

// paste an image while typing: read it as a data url and stage it
input.addEventListener("paste", (e) => {
  for (const file of e.clipboardData.files) {
    if (!file.type.startsWith("image/")) continue;
    e.preventDefault();
    const reader = new FileReader();
    reader.onload = () => { pendingAttachments.push(reader.result); renderAttachments(); };
    reader.readAsDataURL(file);
  }
});

// one websocket for everything: commands go out as {cmd}, state comes back as {type}
let ws;
function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${location.pathname}ws`);
  ws.onopen = () => {
    msgs.innerHTML = "";
    rendered = 0;
    // no agent picked: just the sidebar until they click one or create one
    if (agent) sendCmd({ cmd: "get_messages", name: agent });
  };
  ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 2000);
}

function sendCmd(cmd) {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(cmd));
}

function handleMessage(msg) {
  if (msg.type === "agents") return renderAgentList(msg.agents);
  if (msg.type === "error") {
    // turn died server-side (api error, rate limit, ...) — show it where the reply would be
    if (msg.name === agent) addThinBlock("tool", "error", msg.msg);
    return;
  }
  if (msg.type === "messages" && msg.name === agent) {
    // compression rewrote history shorter than what we've drawn, wipe and re-render everything
    if (msg.messages.length < rendered) {
      msgs.innerHTML = "";
      rendered = 0;
    }
    for (; rendered < msg.messages.length; rendered++) render(msg.messages[rendered]);
    scrollDown();
  }
}

function send() {
  const text = input.value.trim();
  if ((!text && !pendingAttachments.length) || !agent) return;
  input.value = "";
  // show our message immediately, the reply streams in via the socket
  const blocks = toBlocks(text);
  render({ role: "user", content: blocks });
  rendered++;
  scrollDown();
  sendCmd({ cmd: "chat", name: agent, content: blocks });
  pendingAttachments = [];
  renderAttachments();
}

sendBtn.addEventListener("click", send);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});

// clicking anywhere outside the composer unfocuses it so the caret doesn't linger
document.addEventListener("click", (e) => {
  if (e.target !== input) input.blur();
});

// sidebar: pinned section on top, then the rest — name navigates, ⋮ opens pin/rename/delete
const agentMenu = document.getElementById("agent-menu");
const menuPinBtn = document.getElementById("menu-pin");
let menuAgent = null;
let pinnedAgents = new Set();

function renderAgentList(agentInfos) {
  pinnedAgents = new Set(agentInfos.filter(a => a.pinned).map(a => a.name));
  for (const [containerId, wantPinned] of [["pinned", true], ["agents", false]]) {
    const list = document.getElementById(containerId);
    list.innerHTML = "";
    for (const a of agentInfos.filter(x => x.pinned === wantPinned)) {
      const row = el("div", a.name === agent ? "agent-row active" : "agent-row");
      const link = el("a", null, a.name);
      link.href = `?agent=${a.name}`;
      const menuBtn = el("button", "menu-btn", "⋮");
      menuBtn.onclick = (e) => {
        menuAgent = a.name;
        menuPinBtn.textContent = pinnedAgents.has(a.name) ? "unpin" : "pin";
        const rect = e.target.getBoundingClientRect();
        agentMenu.style.display = "flex";
        agentMenu.style.left = rect.left + "px";
        agentMenu.style.top = rect.bottom + 4 + "px";
      };
      row.appendChild(link);
      row.appendChild(menuBtn);
      list.appendChild(row);
    }
  }
}

menuPinBtn.onclick = () => {
  agentMenu.style.display = "none";
  sendCmd({ cmd: "pin", name: menuAgent, pinned: !pinnedAgents.has(menuAgent) });
};

document.getElementById("menu-rename").onclick = () => {
  const newName = prompt(`rename "${menuAgent}" to:`, menuAgent);
  agentMenu.style.display = "none";
  if (!newName || newName === menuAgent) return;
  sendCmd({ cmd: "rename", name: menuAgent, new_name: newName });
  if (menuAgent === agent) location.search = `?agent=${newName}`;
};

document.getElementById("menu-delete").onclick = () => {
  agentMenu.style.display = "none";
  if (!confirm(`delete agent "${menuAgent}"?`)) return;
  sendCmd({ cmd: "delete", name: menuAgent });
  if (menuAgent === agent) location.href = location.pathname;
};

// click anywhere else closes the menu
document.addEventListener("click", (e) => {
  if (!agentMenu.contains(e.target) && !e.target.classList.contains("menu-btn")) {
    agentMenu.style.display = "none";
  }
});

// add button: create on the server, then jump to the new chat
document.getElementById("create").onclick = () => {
  const nameInput = document.getElementById("new-name");
  const name = nameInput.value.trim();
  if (!name) return;
  sendCmd({ cmd: "create", name: name });
  location.search = `?agent=${name}`;
};

connect();
