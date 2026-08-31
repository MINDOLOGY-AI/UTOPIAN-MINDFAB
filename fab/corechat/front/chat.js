const agent = new URLSearchParams(location.search).get("agent"); // null when no agent picked yet
const msgs = document.getElementById("msgs");
const input = document.getElementById("input");

// shared markdown renderer (katex, raw html escaped) from the hub component
// breaks: single newlines become <br>, so shift+enter in your own message shows as a newline
const md = makeMarkdownRenderer();
md.set({ breaks: true });

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
// content renders lazily on first expand: md+katex on hundreds of hidden blocks was the slow first load
function addThinBlock(cssClass, label, text, useMd) {
  const div = el("div", `msg thin ${cssClass}`);
  const roleDiv = el("div", "role", label);
  const contentDiv = el("div", "content collapsed");
  div.onclick = () => {
    if (!contentDiv.dataset.done) {
      if (useMd) contentDiv.innerHTML = md.render(text);
      else contentDiv.textContent = text;
      contentDiv.dataset.done = "1";
    }
    contentDiv.classList.toggle("collapsed");
  };
  div.appendChild(roleDiv);
  div.appendChild(contentDiv);
  msgs.appendChild(div);
}

let lastDrawn = null; // last message we rendered, optimistic or not

function render(m) {
  lastDrawn = m;
  if (m.role === "user") {
    // tool deposits arrive as user messages — render as a thin gray block, not a "you" bubble
    const firstText = m.content.find(b => b.type === "text")?.text || "";
    if (firstText.startsWith("[tool result]")) {
      addThinBlock("tool", "slow tool return", firstText);
      return;
    }
    // user content is always content blocks
    const div = el("div", "msg user");
    div.appendChild(el("div", "role", "you"));
    for (const b of m.content) {
      if (b.type === "text") div.appendChild(mdDiv(b.text));
      else if (b.type === "image_url") {
        const img = document.createElement("img");
        img.loading = "lazy"; // decode only when scrolled into view
        img.onload = scrollDown;
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

// rAF so layout (markdown, the generating bar, images) settles before we measure
function scrollDown() {
  requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
}

// context meter, bottom right of the composer: "context: 7% (62.9k/1M)"
let contextWords = 0;
let contextLimit = 0;
let agentMode = false;

// status line state: a turn in flight, and seconds if a WAIT tool is sleeping
let generating = false;
let waiting = 0;

// the one toggle: ▶ starts agent mode (and a turn), ⏹ cancels the live turn and parks it
const runBtn = document.getElementById("run-toggle");
runBtn.onclick = () => {
  if (!agent) return;
  sendCmd({ cmd: "toggle_run", name: agent });
};

function renderRunBtn() {
  runBtn.textContent = agentMode ? "⏹" : "▶";
  runBtn.classList.toggle("running", agentMode);
}

// always k, M only at 1M+; sub-1k floors to 0k
function fmtWords(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
  return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
}

function renderMeter() {
  const meter = document.getElementById("ctx-meter");
  if (!agent || !contextLimit) { meter.textContent = ""; return; }
  const pct = Math.round(contextWords / contextLimit * 100);
  meter.textContent = `context: ${pct}% (${fmtWords(contextWords)}/${fmtWords(contextLimit)})`;
}

let rendered = 0;
let renderGen = 0; // bumped on every messages payload so stale chunk loops stop
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
  // a tool changed agent state server-side (STOP parked itself) — re-ask for the list
  if (msg.type === "agents_changed") {
    sendCmd({ cmd: "list_agents" });
    return;
  }
  if (msg.type === "agents") {
    lastAgentInfos = msg.agents;
    renderAgentList(msg.agents);
    // keep the model bar in sync with the current agent's settings
    const cur = msg.agents.find(a => a.name === agent);
    // the agent this page is on got deleted (here or in another tab) — leave the dead page
    if (agent && !cur) { location.href = location.pathname; return; }
    document.getElementById("model-label").textContent = cur ? `${cur.model_name} · ${cur.reasoning_effort}` : "no agent";
    // don't clobber the box while the user is typing in it
    if (cur && document.activeElement !== ctxInput) ctxInput.value = cur.context_limit / 1000;
    contextLimit = cur ? cur.context_limit : 0;
    agentMode = cur ? cur.agent_mode : false;
    renderRunBtn();
    renderMeter();
    return;
  }
  if (msg.type === "status") {
    // the sidebar dots read every agent's status, not just the open one
    const st = statusByAgent[msg.name] || (statusByAgent[msg.name] = { generating: false, waiting: false });
    if (msg.generating !== undefined) st.generating = msg.generating;
    if (msg.waiting !== undefined) st.waiting = !!msg.waiting;
    // a finished (or cancelled) turn kills any wait display with it
    if (!st.generating) st.waiting = false;
    renderAgentList(lastAgentInfos);
    // one status line above the input: "waiting Ns..." while a WAIT runs, else "generating..." while a turn runs
    if (msg.name !== agent) return;
    if (msg.generating !== undefined) generating = msg.generating;
    if (msg.waiting !== undefined) waiting = msg.waiting || 0;
    if (!generating) waiting = 0;
    const statusEl = document.getElementById("generating");
    statusEl.textContent = waiting ? `waiting ${waiting}s...` : "generating...";
    statusEl.classList.toggle("on", generating);
    scrollDown();
    return;
  }
  if (msg.type === "error") {
    // turn died server-side (api error, rate limit, ...) — show it where the reply would be
    if (msg.name === agent) addThinBlock("tool", "error", msg.msg);
    return;
  }
  if (msg.type === "messages" && msg.name === agent) {
    // the drawn tail must match the server's tail — compression, repairs, or mid-context inserts
    // (optimistic draws make our count unreliable, so compare content, not length)
    if (rendered > 0 && JSON.stringify(msg.messages[rendered - 1]) !== JSON.stringify(lastDrawn)) {
      msgs.innerHTML = "";
      rendered = 0;
    }
    // render in chunks per frame so a long history doesn't freeze the page on load;
    // a newer payload bumps the generation and the stale chunk loop stops itself
    const gen = ++renderGen;
    const renderChunk = () => {
      if (gen !== renderGen) return;
      for (let n = 0; n < 10 && rendered < msg.messages.length; n++, rendered++) render(msg.messages[rendered]);
      scrollDown();
      if (rendered < msg.messages.length) requestAnimationFrame(renderChunk);
      else {
        contextWords = msg.words;
        renderMeter();
      }
    };
    renderChunk();
  }
}

function send() {
  const text = input.value.trim();
  if ((!text && !pendingAttachments.length) || !agent) return;
  input.value = "";
  input.style.height = "";
  // show our message immediately, the reply streams in via the socket
  const blocks = toBlocks(text);
  render({ role: "user", content: blocks });
  rendered++;
  scrollDown();
  sendCmd({ cmd: "chat", name: agent, content: blocks });
  pendingAttachments = [];
  renderAttachments();
}

// auto-grow the input as lines pile up; css max-height caps it, overflow scrolls without a scrollbar
input.addEventListener("input", () => {
  input.style.height = "3rem";
  input.style.height = input.scrollHeight + "px";
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});

// clicking anywhere outside the composer unfocuses it so the caret doesn't linger
document.addEventListener("click", (e) => {
  if (e.target !== input) input.blur();
});

// sidebar: pinned section on top, then the rest — name navigates, ⋮ opens pin/rename/delete
// the dot before ⋮ is pure broadcast state: green = turning, yellow = in a WAIT, off = idle
const agentMenu = document.getElementById("agent-menu");
const menuPinBtn = document.getElementById("menu-pin");
let menuAgent = null;
let pinnedAgents = new Set();
let lastAgentInfos = [];
const statusByAgent = {};

function renderAgentList(agentInfos) {
  pinnedAgents = new Set(agentInfos.filter(a => a.pinned).map(a => a.name));
  for (const [containerId, wantPinned] of [["pinned", true], ["agents", false]]) {
    const list = document.getElementById(containerId);
    list.innerHTML = "";
    for (const a of agentInfos.filter(x => x.pinned === wantPinned)) {
      const row = el("div", a.name === agent ? "agent-row active" : "agent-row");
      const link = el("a", null, a.name);
      link.href = `?agent=${a.name}`;
      const st = statusByAgent[a.name];
      const dot = el("span", "state-dot" + (st && st.waiting ? " waiting" : st && st.generating ? " generating" : ""));
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
      row.appendChild(dot);
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
  const name = prompt("agent name:");
  if (!name || !name.trim()) return;
  const withDocker = confirm(`also create a docker container named "${name.trim()}" assigned to it?`);
  sendCmd({ cmd: "create", name: name.trim(), with_docker: withDocker });
  location.search = `?agent=${name.trim()}`;
};

// model selector: pick a model or reasoning effort, server rebuilds the agent's model server live
document.querySelectorAll(".model-opt").forEach(btn => {
  btn.onclick = () => {
    if (!agent) return;
    sendCmd({ cmd: "set_model", name: agent, model_server_name: btn.dataset.server, model_name: btn.dataset.model });
  };
});

document.querySelectorAll(".effort-opt").forEach(btn => {
  btn.onclick = () => {
    if (!agent) return;
    sendCmd({ cmd: "set_reasoning_effort", name: agent, reasoning_effort: btn.dataset.effort });
  };
});

// context limit in k words, committed on enter
const ctxInput = document.getElementById("ctx-input");
ctxInput.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !agent) return;
  const k = parseInt(ctxInput.value, 10);
  if (!k || k <= 0) return;
  sendCmd({ cmd: "set_context_limit", name: agent, context_limit: k * 1000 });
  ctxInput.blur();
});

connect();
