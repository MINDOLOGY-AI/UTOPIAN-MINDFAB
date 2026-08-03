# fab/DOC.md

the web layer of the monorepo: four apps under one fastapi server.
- **hub** (`fab/hub/`) — entry point: auth, index page, shared components, mounts the other apps.
- **TH0UGHTGR4PH** (`fab/TH0UGHTGR4PH/`) — knowledge graph: boards of doc/folder nodes with typed edges.
- **INT3RF4CE** (`fab/INT3RF4CE/`) — llm agents: each agent = a model + a context + a docker desktop + thoughtgraph access + chat channels + secrets.
- **INT3RPV1Z** (`mind/INT3RPV1Z/`) — FX-graph tensor visualizer for pytorch models. lives in mind/ but mounts under the hub like the rest; has its own `mind/INT3RPV1Z/doc.md`.

all user data lives in `fab/data/{app}/{user}/...` — never in the code dirs.

# reading order

1. `fab/hub/back/app.py` — how everything mounts together (one server, sub-apps).
2. `fab/hub/auth/` — sessions; every route/WS takes the user from a cookie.
3. `fab/TH0UGHTGR4PH/back/` — `storage.py` (disk layout) → `graph_actions.py` (the operations) → `api.py` (REST).
4. `fab/TH0UGHTGR4PH/front/` — `store.js` (client state + fetch) → `nodes.js` / `edges.js` (web components) → `board.js` (interaction) → `ctxpanel.js` (agent settings sidebar).
5. `fab/INT3RF4CE/back/` — `adapter.py` (**the internal data standard — read this first**) → `context.py` → `model.py` + `models/` → `agent.py` (the brain) → `server.py` (all WS commands) → `chat.py`, `secrets.py` → `container.py`, `prompt.py`.
6. `fab/INT3RF4CE/front/` — `app.js` (agent view), `chat.js` (chat view), `secrets.js`.
7. `fab/hub/components/` — shared web components: `BoardCanvas` (infinite pan/zoom board + svg edge layer, used by INT3RPV1Z), `MarkdownEditor`, `AuthBox`.
8. `mind/INT3RPV1Z/` — `back/inspector.py` (torch.export trace + tensor capture) → `back/layout.py` → `back/routing.py` → `back/server.py`; then `mind/INT3RPV1Z/doc.md`.
9. `fab/TH0UGHTGR4PH/tests/headless_test.py` — executable spec of most of the above.

# data types

## thoughtgraph (on disk, per user per board)
- `meta.json` — `{board, nodes: {id: node}, edges: {id: edge}}`. the whole graph minus doc text.
- node — `{id, title, kind: "doc"|"folder", node_type, state: "todo"|"doing"|"done"|null, ref, x, y, width, height, parent, expanded, color}`. titles are unique per board and path-safe. child x/y are relative to their folder; root nodes snap to GRID_SIZE.
- edge — `{id, source, target, edge_type}`. source/target are always docs (never folders); edge_type is one of `types.json`'s edge_types (default: support/reject/inference/training, each with a color).
- doc content — `tree/{folder titles...}/{title}.md`. the file path IS the node's place in the tree; rename/move rewrites the disk path (`storage.content_path`).
- `types.json` — `{doc_types: {name: {color}}, edge_types: {name: {color}}}`.
- `versions/{name}/` — full board snapshots (meta + tree), taken manually or before an upload-override.

## INT3RF4CE internal message standard (adapter.py — the one true shape)
a conversation is `messages: [{role: "system"|"user"|"assistant", content: [block]}]`. blocks:
- `{"type": "text", "text"}` — anywhere.
- `{"type": "tool_use", "id", "name", "arguments"}` — assistant only.
- `{"type": "tool_result", "tool_use_id", "name", "content"}` — user only, answers a tool_use.
- `{"type": "image", "source": {base64...}}` — user only (screenshots, attached images).

everything (context, agent loop, UI) speaks this standard. adapters (`KimiAdapter` etc.) convert it to/from each provider's native format — OpenAI-style tool_calls, reasoning params. adding a provider = one subclass + one adapter.

## agent persistence (fab/data/INT3RF4CE/{user}/)
- `agents.json` — `{agent_name: {novnc_port, model, chat_mode}}`. live agent objects are rebuilt from this on boot.
- `context/{agent}/` — `working.jsonl` (the full message list, one json per line) + summary + kv cache (kv only for local models; api models return None).
- `config/specific/{agent}/graph.json` — thoughtgraph access: `{prompt_docs, read, write, folders}`, entries `{board, id}`. prompt_docs are injected into the system prompt; read/write/folders are enforced by the G* tool dispatch (write implies read; folders = total control over everything inside).
- `config/specific/{agent}/secrets.json` — `{grants: [secret_name]}`.
- `workspace/{agent}/` — the only host dir bind-mounted into the agent's docker (as /home/agent). file tools (READ/WRITE/EDIT) are confined here.
- `secrets.json` (user level) — `{name: {value, cat: "llm"|"computerent"|"compute"|"account"|"git"|"gitrepo"}}`, chmod 600. llm names are hardset to provider `secret_name`s (moonshot, deepseek, openrouter); computerent names are hardset to RENT_PROVIDERS (autodl). git values are forced `{"account", "key"}` pairs (github identity + ssh private key); gitrepo values are plain urls (not secret, just co-located).
- `chat/` — `channels.json` `{id: {id, name, members, dm}}`, `readers.json` (read cursors per agent), per-channel `messages.jsonl` + `files/`. every agent gets a `dm-{agent}` channel with the user.

# function flow

## boot
`fab.hub.back.app` mounts auth + TH0UGHTGR4PH (REST) + INT3RPV1Z (WS + static) + INT3RF4CE (WS + static) + interp_journey static + components. INT3RF4CE's `server.py` runs `load_agents()` at import: reads every user's agents.json, builds Agent objects (model instance, context loaded from disk, container handle — container NOT started), wires status callbacks. the hub runs with `reload=True` — .py edits auto-restart it (wiping in-memory state: agent loops, loaded intvrpviz models); frontend edits just need a hard refresh.

## a user chat message (the main loop)
1. browser → WS `{"cmd": "chat", "name", "text"}` → text goes DIRECTLY into the agent's context as plain user text (agent-view conversation is not chat traffic). only file uploads route through the chat system: each becomes a DM channel message, delivered by `inject_pending` before the next turn (image blocks for images, inline text for text files).
2. `agent.turn()`: builds system prompt (`prompt.build_system_prompt`: global prompt + prompt docs + chat-mode prompt), marshals context, calls `model.call`.
3. adapter converts messages → provider payload; response parsed back into internal blocks.
4. assistant message appended to context; each tool_use dispatched by name (`agent._dispatch`), each producing a tool_result user message.
5. auto-feedback: keyboard commands without TERM → last result replaced with fresh TERM output; mouse without LOOK → fresh screenshot.
6. context persisted to working.jsonl; broadcast to the frontend. if `context.needs_summary()`, the model summarizes and context collapses to summary + last 5 messages.

model on/off vs single turn: `working` is the master switch (the model button) — off means the agent does nothing at all. `chat_mode` ("single turn" in the ui) is a pure MODE with no on/off semantics: on = the running model answers one turn per user message; off = the work loop runs turns back-to-back. agents start in single-turn mode with the model off. `DOCKER_START` (agent tool or user button) boots the container and flips single turn off → the server's status handler starts the work loop. STOP (agent tool) halts the agent permanently until the user starts it.

## computer use (container.py)
the docker is a desktop: Xvfb :99 → x11vnc (localhost only) → websockify :6080 → server proxies it (login + per-user port ownership checked) → noVNC iframe. agent tools drive it: MOVE/CLICK/TYPE/KEY via xdotool, LOOK = screenshot, TERM = tail of term.log (xterm logs via `script -f`). READ/WRITE/EDIT bypass the desktop entirely and hit the host-side workspace bind directly.

## graph tools (agent.py _graph_dispatch)
every G* command resolves its target against graph.json access: explicit read/write lists, or "inside a folder I totally control" (walk up parents). titles resolve to ids (ambiguous title → error). then it calls the same `graph_actions` functions the REST api uses — one implementation, two front doors.

## thoughtgraph frontend
`store.js` mirrors meta.json client-side and does all REST calls. `board.js` owns interaction (pan/zoom/drag/expand), `nodes.js`/`edges.js` are the web components it renders. edits go browser → REST `api.py` → `graph_actions` (validation + autoplace via `placement.py`) → `storage` (meta.json + tree/ disk sync). versions are whole-board folder copies.

## chat channels (chat.py)
append-only `messages.jsonl` per channel + read cursors. `pending_messages(user, agent)` = messages newer than the agent's cursor in channels it belongs to — that's what `inject_pending` delivers before turns. files go to `files/` with extension allowlisting; agents attach via CHAT_SEND from their own workspace only. deleting a dm channel is safe — it auto-recreates the next time anything (agent view fetch, chat_send, file upload) needs it.

## secrets (secrets.py)
two consumers, one store. backend: `server._make_model` passes each provider a `get_key` that resolves its `secret_name` from the store (env var fallback) — values never enter agent context this way. agent: `READ_SECRETS` returns only the granted subset (grants drag-dropped in the ctx panel / secrets tab). values never go over the websocket — the UI is write-only.
