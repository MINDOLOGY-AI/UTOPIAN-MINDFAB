# fab/DOC.md

the web layer of the monorepo: four apps under one fastapi server.
- **hub** (`fab/hub/`) — entry point: auth, index page, shared components, mounts the other apps.
- **TH0UGHTGR4PH** (`fab/TH0UGHTGR4PH/`) — knowledge graph: boards of doc/folder nodes with typed edges.
- **INT3RF4CE** (`fab/INT3RF4CE/`) — llm agents: each agent = a model + a context + a docker desktop + thoughtgraph access + chat channels + secrets + compute targets.
- **INT3RPV1Z** (`mind/INT3RPV1Z/`) — FX-graph tensor visualizer for pytorch models. lives in mind/ but mounts under the hub like the rest; has its own `mind/INT3RPV1Z/doc.md`.

all user data lives in `fab/data/{app}/{user}/...` — never in the code dirs.

# reading order

1. `fab/hub/back/app.py` — how everything mounts together (one server, sub-apps).
2. `fab/hub/auth/` — sessions; every route/WS takes the user from a cookie.
3. `fab/TH0UGHTGR4PH/back/` — `storage.py` (disk layout) → `graph_actions.py` (the operations) → `api.py` (REST).
4. `fab/TH0UGHTGR4PH/front/` — `store.js` (client state + fetch) → `nodes.js` / `edges.js` (web components) → `board.js` (interaction) → `ctxpanel.js` (agent settings sidebar).
5. `fab/INT3RF4CE/back/` — `adapter.py` (**the internal data standard — read this first**) → `context.py` → `model.py` + `models/` → `agent.py` (the brain) → `server.py` (all WS commands) → `chat.py`, `secrets.py`, `compute.py` → `container.py`, `prompt.py`.
6. `fab/INT3RF4CE/front/` — `app.js` (agent view), `chat.js` (chat view + channel file tree), `secrets.js`, `compute.js`.
7. `fab/hub/components/` — shared web components: `BoardCanvas` (infinite pan/zoom board + svg edge layer, used by INT3RPV1Z), `MarkdownEditor`, `AuthBox`.
8. `mind/INT3RPV1Z/` — `back/inspector.py` (torch.export trace + tensor capture) → `back/layout.py` → `back/routing.py` → `back/server.py`; then `mind/INT3RPV1Z/doc.md`.
9. `fab/TH0UGHTGR4PH/tests/headless_test.py` — executable spec of most of the above.

# data types

## thoughtgraph (on disk, per user per board)
- `meta.json` — `{board, nodes: {id: node}, edges: {id: edge}}`. the whole graph minus doc text.
- node — `{id, title, kind: "doc"|"folder", node_type, state: "todo"|"doing"|"done"|null, assignee, ref, x, y, width, height, parent, expanded, color}`. titles are unique per board and path-safe. child x/y are relative to their folder; root nodes snap to GRID_SIZE. `assignee` is the agent/user who claimed the task (set when state == "doing"). `kind: "folder"` has `node_type: "folder"`.
- edge — `{id, source, target, edge_type}`. source/target are always docs (never folders); edge_type is one of `types.json`'s edge_types (default: support/reject/causes/training, each with a color).
- doc content — `tree/{folder titles...}/{title}.md`. the file path IS the node's place in the tree; rename/move rewrites the disk path (`storage.content_path`). there is also a vestigial empty `content/` dir from an older layout (harmless, kept so nothing breaks).
- `types.json` — `{doc_types: {name: {color}}, edge_types: {name: {color}}, state_colors: {state: color}}`. state_colors maps todo/doing/done to hex colors.
- `versions/{name}/` — full board snapshots (meta + tree), taken manually or before an upload-override. the versions dir itself is excluded from board zip downloads to prevent recursive snapshots.

## INT3RF4CE message standard (OpenAI chat completions IS the one true shape)
the canonical format is the OpenAI chat-completions message format, verbatim — in context storage, the agent loop, the WS payloads, and the frontend:
- `{"role": "system", "content": str}`
- `{"role": "user", "content": str}` — or a content-part list `[{"type": "text", "text"}, {"type": "image_url", "image_url": {"url": "data:...;base64,..."}}]` only when images are present (the APIs reject a bare dict content).
- `{"role": "assistant", "content": str (omit if none), "tool_calls": [{"id", "type": "function", "function": {"name", "arguments": "<json string>"}}]}` — arguments stay stringified JSON. `tool_calls[].id` comes from the API response directly. reasoning folds into the content string bracketed as `[reasoning]\n...\n[/reasoning]\n<reply>` so the frontend can split it back off.
- `{"role": "tool", "tool_call_id", "name", "content": str}` — must immediately follow the assistant tool_calls run.

screenshots (LOOK / auto-LOOK) split in two: a tool message with text content (`"[image result]"` when image-only), then a user message whose parts are a `"[screenshot]"` marker text part plus the image_url parts. the marker tells the model what the image is AND gives elision something to key on: `marshal()` keeps the newest 3 screenshot images and rewrites older ones to a text note (copy-on-write — storage keeps every screenshot; user-attached images have no marker and are never elided).

adapters are thin: they wrap the shared command definitions into tool schemas, add reasoning/thinking params, and parse responses into a canonical assistant message. messages themselves pass through nearly verbatim — a future Claude adapter would be the first one that actually translates. adding a provider = one Model subclass + one adapter.

legacy contexts (the old block format) are not migrated: on load, a `working.jsonl` containing old-style blocks is renamed to `working.legacy.jsonl` once and the context starts empty.

## model providers
- **Kimi** — Moonshot API (`api.moonshot.cn`). key: `moonshot`. models: kimi-k3. reasoning via `reasoning_effort`.
- **DeepSeek** — DeepSeek API (`api.deepseek.com`). key: `deepseek`. models: deepseek-v4-pro. v4 models are text-only (no image input). reasoning via `thinking` toggle.
- **hierarchy** — ordered fallback (`HIERARCHY` in model.py: kimi-k3 → deepseek-v4-pro): on timeout / 429 / 5xx the next provider answers. currently NOT registered (deliberately absent from the model selector); re-add `@register_provider` in model.py to re-enable.

## agent persistence (fab/data/INT3RF4CE/{user}/)
- `agents.json` — `{agent_name: {novnc_port, model, chat_mode}}`. live agent objects are rebuilt from this on boot.
- `context/{agent}/` — `working.jsonl` (the full message list, one json per line; summaries are inlined as assistant messages), `original.jsonl` (append-only archive), `kv_cache.pt` (kv only for local models; api models return None and never write it).
- `config/specific/{agent}/graph.json` — thoughtgraph access: `{prompt_docs, read, write, time, folders}`, entries `{board, id}`. prompt_docs are injected into the system prompt; read/write/time/folders are enforced by the G* tool dispatch. write implies read; time (to-do access) implies read but write does NOT imply time — flipping task states is its own grant. folders = total control over everything inside (read + write + time + children). graph.json settings can be saved/loaded as named presets via `config/settings_files/`.
- `config/specific/{agent}/secrets.json` — `{grants: [secret_name]}`.
- `workspace/{agent}/` — the only host dir bind-mounted into the agent's docker (as /home/agent). file tools (READ/WRITE/EDIT) are confined here via path resolution that rejects `..` escapes; absolute `/home/agent/...` paths are mapped in (the agent's own view of the workspace). all file ops run through `docker exec` — the container is the single writer, so ownership is uniform (root) and host-side permission mismatches can't happen. file tools require a running container (they're not advertised in chat mode anyway).
- `secrets.json` (user level) — `{name: {value, cat: "llm"|"account"|"git"|"gitrepo"}}`, chmod 600. llm names are hardset to provider `secret_name`s (moonshot, deepseek). git values are forced `{"account", "key"}` pairs (github identity + ssh private key); gitrepo values are plain urls (not secret, just co-located).
- `compute.json` — `[{"name", "ssh_command", "password"}]`, chmod 600. named ssh targets (rented gpu boxes etc).
- `compute_usage.json` — `{computer_name: agent_name}`, chmod 600. the claim map: who is using which machine. the human claims under their own username and can force-release anything.
- `chat/` — `channels.json` `{id: {id, name, members, dm, created}}`, `readers.json` (read cursors per agent), per-channel `messages.jsonl` + `files/` (a real tree — nested folders preserved). every agent gets a `dm-{agent}` channel with the user.

## task management (thoughtgraph to-do system)
nodes with `state: "todo"|"doing"|"done"` form an agent's task queue. tasks are single-assignee:
- marking a node `doing` claims it under the agent's name (`assignee` set).
- only the assignee can then mark it `done` or release it back to `todo`.
- the agent's to-do list IS its `time` access entries + stateful nodes inside its total-control folders. dragging a node into/out of the ctx panel's time list assigns/unassigns it.
- the frontend's `get_agent_tasks` WS command returns every agent's task queue (doing first, then todo, then done; sorted by path) for the chat popup view.
- if a task is claimed by someone else, the agent is instructed to split the task rather than fight over it.

# function flow

## boot
`fab.hub.back.app` mounts auth + TH0UGHTGR4PH (REST) + INT3RPV1Z (WS + static) + INT3RF4CE (WS + static) + interp_journey static + components, and serves html/js/css/json with `Cache-Control: no-cache` (no `?v=` cache-busting anywhere). INT3RF4CE's `server.py` runs `load_agents()` at import: reads every user's agents.json, builds Agent objects (model instance, context loaded from disk, container handle — container NOT started), wires status callbacks, creates DM channels for each agent. the hub runs with `reload=True` — .py edits auto-restart it (wiping in-memory state: agent loops, loaded intvrpviz models); frontend edits just need a refresh.

## a user chat message (the main loop)
1. browser → WS `{"cmd": "chat", "name", "text", "attachments"}` → goes DIRECTLY into the agent's context (`inject_pending` first so queued channel messages stay chronological, then `context.add_message("user", blocks)`). nothing is written to any chat channel — the agent-view conversation is not chat traffic. attachments ride along base64-encoded (25MB cap): images become image blocks, text-ish files (`TEXT_EXTS`) are inlined as text (20k char cap), other binaries become a `[attached file: ...]` placeholder.
2. `agent.turn()`: builds system prompt (`prompt.build_system_prompt`: global prompt + prompt docs + chat-mode prompt), marshals context, calls `model.call`.
3. adapter converts messages → provider payload; response parsed back into internal blocks. `HierarchyModel` falls through the provider chain on transient errors.
4. assistant message appended to context; each tool_use dispatched by name (`agent._dispatch`), each producing a tool_result user message.
5. auto-feedback: keyboard commands without TERM → last result replaced with fresh TERM output; mouse without LOOK → fresh screenshot.
6. context persisted to working.jsonl; broadcast to the frontend. if `context.needs_summary()`, the model summarizes and context collapses to summary + last 5 messages. summary is stored as an assistant message inline in `working.jsonl` (no separate summary file).

model on/off vs single turn: `working` is the master switch (the model button) — off means the agent does nothing at all. `chat_mode` ("single turn" in the ui) is a pure MODE with no on/off semantics: on = the running model answers one turn per user message; off = the work loop runs turns back-to-back. agents start in single-turn mode with the model off. `DOCKER_START` (agent tool or user button) boots the container and flips single turn off → the server's status handler starts the work loop. STOP (agent tool) halts the agent permanently until the user starts it.

## pausing / cancelling a turn
when the user pauses or switches chat_mode, `cancel_and_settle` cancels the asyncio task and awaits its termination. then `close_dangling_tool_calls` walks the context for any assistant tool_use that never got a tool_result and fills them with `[interrupted]` placeholders — without this, every later API call would fail because provider APIs reject contexts with dangling tool calls.

## computer use (container.py)
the docker is a desktop: Xvfb :99 → x11vnc (localhost only) → websockify :6080 → server proxies it (login + per-user port ownership checked) → noVNC iframe. agent tools drive it: MOVE/CLICK/TYPE/KEY via xdotool, LOOK = screenshot, TERM = tail of term.log (xterm logs via `script -f`). READ/WRITE/EDIT go through `docker exec` too (single writer, uniform root ownership). EXEC is async under the hood: foreground calls cap at 30s, and past that the command is NOT killed — it's demoted to a background task (per-agent registry: id, `workspace/exec_logs/{id}.log`, status) and the agent is notified on completion via an injected context note (same pattern as chat injection). `background: true` starts one directly; TASKS lists them.

## compute manager (compute.py)
named ssh targets the user registers (page at `/INT3RF4CE/compute/`, linked from the AuthBox dropdown). all ops go over the main WS (`list_computes` / `add_compute` / `delete_compute` / `claim_compute` / `release_compute`). agents get the same thing as tools — `SEE_COMPUTERS` (redacted view: full ssh command + password only for free machines or its own claims), `USE_COMPUTER` (claim → full credentials in the tool result), `RELEASE_COMPUTER` — and these work in chat mode, no container needed; the agent ssh's out from wherever it runs. one holder per machine; the human claims under their own username and can force-release anything. `compute.py` fires a change hook after every mutation → the server broadcasts the fresh list to all of the user's sessions (so agent claims show up live on the page), and deleting an agent auto-releases its claims (`release_all`). no locking — the exact-same-instant double-claim race is accepted. the "compute rent" section on the page is a placeholder for a future auto-rent feature.

## graph tools (agent.py _graph_dispatch)
every G* command resolves its target against graph.json access: explicit read/write/time lists, or "inside a folder I totally control" (walk up parents). titles resolve to ids (ambiguous title → error). then it calls the same `graph_actions` functions the REST api uses — one implementation, two front doors. task state changes follow single-assignee rules: only the current assignee can move a node out of `doing`.

## thoughtgraph frontend
`store.js` mirrors meta.json client-side and does all REST calls. `board.js` owns interaction (pan/zoom/drag/expand), `nodes.js`/`edges.js` are the web components it renders. edits go browser → REST `api.py` → `graph_actions` (validation + autoplace via `placement.py`) → `storage` (meta.json + tree/ disk sync). versions are whole-board folder copies. the context panel (`ctxpanel.js`) manages thoughtgraph access (prompt docs/read/write/time/folders), secrets grants, compute assignment (assign a free machine to the agent / release it), and settings file save/load. dropping a folder into the to-do (time) list expands to every stateful node inside it.

## chat channels (chat.py)
append-only `messages.jsonl` per channel + read cursors. `pending_messages(user, agent)` = messages newer than the agent's cursor in channels it belongs to — that's what `inject_pending` delivers before turns. files live in a real per-channel tree under `files/` (nested folders, 100GB per-file cap, NO extension blocklist). the chat view has a lazy-loaded file-tree panel: upload files/folders (paths preserved), mkdir, rename, delete, drag-drop — all over REST (`files-list`, `mkdir`, `PUT`/`DELETE .../files/{path}`, download via `GET .../files/{path}`). agents transfer files with `CHAT_FILE_UPLOAD` (copies from their workspace into the channel tree, caption text required) and `CHAT_FILE_DOWNLOAD` (channel → workspace). deleting a dm channel is safe — it auto-recreates the next time anything (agent view fetch, chat_send, file upload) needs it.

## secrets (secrets.py)
two consumers, one store. backend: `server._make_model` passes each provider a `get_key` that resolves its `secret_name` from the store — the store is the SINGLE source of truth (no env/.env fallbacks) and values never enter agent context this way. agent: `READ_SECRETS` returns only the granted subset (grants drag-dropped in the ctx panel / secrets tab). values never go over the websocket — the UI is write-only. deleting a secret strips it from every agent's grant list automatically.
