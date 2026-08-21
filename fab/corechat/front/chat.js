const agent = new URLSearchParams(location.search).get("agent") || "corechat";
const msgs = document.getElementById("msgs");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// expanded block for real conversation text (you / assistant)
function addTextBlock(cssClass, label, text) {
  const div = el("div", `msg ${cssClass}`);
  div.appendChild(el("div", "role", label));
  div.appendChild(el("div", "content", text));
  msgs.appendChild(div);
}

// thin block for extras (reasoning, tool calls, tool results) — collapsed by default, click label to expand
function addThinBlock(cssClass, label, text) {
  const div = el("div", `msg thin ${cssClass}`);
  const roleDiv = el("div", "role", label);
  const contentDiv = el("div", "content collapsed", text);
  roleDiv.onclick = () => contentDiv.classList.toggle("collapsed");
  div.appendChild(roleDiv);
  div.appendChild(contentDiv);
  msgs.appendChild(div);
}

function render(m) {
  if (m.role === "user") {
    addTextBlock("user", "you", typeof m.content === "string" ? m.content : JSON.stringify(m.content));
  } else if (m.role === "assistant") {
    if (m.reasoning_content) addThinBlock("reasoning", "reasoning", m.reasoning_content);
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

async function load() {
  const r = await fetch(`api/history?agent=${agent}`);
  for (const m of (await r.json()).messages) render(m);
  scrollDown();
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendBtn.disabled = true;
  render({ role: "user", content: text });
  scrollDown();
  const r = await fetch("api/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent, text }),
  });
  for (const m of (await r.json()).messages.slice(1)) render(m); // skip the user msg we already drew
  sendBtn.disabled = false;
  scrollDown();
}

sendBtn.addEventListener("click", send);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});

load();
