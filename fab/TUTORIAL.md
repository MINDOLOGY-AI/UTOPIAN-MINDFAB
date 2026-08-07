# fab/TUTORIAL.md

read this top to bottom and you understand the whole web layer without opening the code.
order follows the data: boot → auth → thoughtgraph (back then front) → int3rface (model stack, context, agent, container, server, services, frontend) → shared components → tests.

sibling docs: `fab/DOC.md` is the architecture map (reading order, data layouts), `fab/INT3RF4CE/README.md` is the design doc. this one is the full explanation.

# 1. what fab is

one FastAPI process (`fab/hub/back/app.py`) serving four apps plus shared static components:

- **hub** (`fab/hub/`) — entry point: the landing page, auth, shared components. mounts the rest.
- **TH0UGHTGR4PH** (`fab/TH0UGHTGR4PH/`) — knowledge graph: boards of doc/folder nodes, typed edges, markdown content, versions.
- **INT3RF4CE** (`fab/INT3RF4CE/`) — llm agents: each agent = a model + a context + a docker desktop + thoughtgraph access + chat channels + secrets + compute targets.
- **INT3RPV1Z** (`mind/INT3RPV1Z/`) — FX-graph tensor visualizer. lives in mind/ (it's ml research code) but mounts like the rest; has its own doc.md.

rules that hold everywhere:

- **all user data lives in `fab/data/{app}/{user}/...`** — never in code dirs. `fab/data/` is gitignored.
- **the server runs from repo root** (`python3 -m fab.hub.back.app`). every path constant is `Path.cwd()`-relative. run it from anywhere else and everything breaks.
- **frontend is plain html/css/js** with web components. no build step, no frameworks.
- **no `?v=` cache-busting params** — the hub serves html/js/css/json with `Cache-Control: no-cache`.

# 2. boot

`fab/hub/back/app.py`:

- `LineLimitedFileHandler` (app.py:12) — a logging FileHandler that keeps only the last 2000 lines of `fab/logs/app.log`, trimming on every emit.
- two middlewares run on every request:
  - `limit_body_size` (app.py:86) — 413 if content-length > 1MB, EXCEPT any POST whose path contains `/chat/` (INT3RF4CE file uploads are allowed to be huge — datasets). note it trusts the header; chunked bodies without content-length bypass it.
  - `revalidate_statics` (app.py:101) — adds `Cache-Control: no-cache` to html/js/css/json responses. this is why you never add `?v=` params.
- `GET /` → `hub_index` (app.py:116) reads `fab/hub/front/index.html` from disk PER REQUEST and injects `data-mode="display"` into `<body>` (display mode hides admin-only link sections via css — cosmetic, not security).
- routers: `/auth/*` (auth), `/api/function_approximator/*` (interp_journey).
- mounts, order matters (app.py:126-131): `/TH0UGHTGR4PH`, `/INT3RPV1Z`, `/INT3RF4CE` sub-apps; `/interp_journey/...` static; `/components` → `fab/hub/components`; and LAST the catch-all `/` → `fab/hub/front` static. if `/` mounted first it would swallow everything.
- `uvicorn.run(..., host=0.0.0.0, port=2121, reload=True)`. **reload=True means every .py save restarts the server**, wiping in-memory state: rate-limit counters, open websockets, and every INT3RF4CE agent loop.

INT3RF4CE boot (server.py import time):

- `load_agents()` (server.py:353) runs at import. it globs `fab/data/INT3RF4CE/*/agents.json`, and for each entry rebuilds a live `Agent`: model instance via `_make_model`, context loaded from disk, container handle (NOT started), status callbacks wired, DM channel ensured.
- **an agent whose provider key is missing from the user's secrets store is skipped with a logged error — it does not crash boot.** this is what lets a second user exist without holding your api keys.
- agents boot stopped: `working=False`, container off, chat_mode restored from disk.

# 3. auth

`fab/hub/auth/` — two files, plain JSON storage under `fab/data/auth/`.

**store.py**:
- `_load`/`_save` (28/34) — JSON file ↔ dict; saves are atomic (tmp file + rename).
- `_hash_password` (42) — scrypt N=2¹⁴ r=8 p=1, hex digest. per-user salt.
- `create_user(username, password)` (46) — usernames 1-32 chars, alnum/`_`/`-` only (this allowlist is load-bearing: AuthBox renders the username into innerHTML unescaped, and agent/docker names derive from it). stores `{salt, hash, created}`.
- `verify_user` (65) — constant-time `secrets.compare_digest`.
- sessions: `create_session(username)` (78) returns a raw `secrets.token_hex(32)` token; only its **sha256 hash** is stored (`{hash: {user, expires: now+30d}}`) — a leaked sessions.json leaks nothing usable. `user_for_token` (87) resolves a token AND lazily prunes all expired sessions (so it's a read with a write side effect). `delete_session` (107) for logout.
- constants: cookie name `mindology_session`, TTL 30 days.

**routes.py** (prefix `/auth`):
- in-memory rate limiting: `_rate_limited(key)` (19) — ≥10 attempts per 300s window per key → 429. prunes the whole attempts dict on every call. **in-memory = reloads reset it**; fine at this scale.
- `POST /register` (40) — rate-limits on both `(username, ip)` and `("__register__", ip)`, counting EVERY attempt (successes too — unlimited account creation is a resource hole). creates user + session, sets cookie.
- `POST /login` (65) — rate-limited per (username, ip), records only FAILURES (so legit users don't lock themselves out by logging in). errors are deliberately ambiguous 401 "wrong username or password".
- `POST /logout` (81) — deletes session + cookie. always 200.
- `GET /me` (88) — 401 or `{"user": name}`.
- the cookie: `HttpOnly, SameSite=Lax, Path=/`, `Secure` iff https (checked via `x-forwarded-proto`, trusted blindly — fine behind your own proxy).

**frontend side**: `<auth-box>` (components/AuthBox) is on every page; it calls these endpoints and broadcasts `auth-changed {user}` on `document`. apps gate themselves on that event + the cookie. every backend route/WS takes the user from the cookie via `user_for_token`.

# 4. TH0UGHTGR4PH backend

`fab/TH0UGHTGR4PH/back/` — 5 files. no websockets here; plain REST.

## disk layout

```
fab/data/TH0UGHTGR4PH/{user}/
├── types.json                  # {doc_types: {name:{color}}, edge_types: {...}, state_colors: {...}} — PER USER, shared across boards
└── {board}/
    ├── meta.json               # {"nodes": {id: node}, "edges": {id: edge}} — the whole graph minus doc text
    ├── tree/{folder titles...}/{title}.md   # doc content. the path IS the node's place in the tree
    ├── content/                # vestigial empty dir from an older layout. ignore it
    └── versions/version_N/     # full board snapshots (meta + tree), never nested
```

**node**: `{id (8 hex), title, kind: "doc"|"folder", node_type, state: "todo"|"doing"|"done"|null, assignee, ref, x, y, width, height, parent, expanded, color}`. titles are unique PER BOARD (across all folders) and are literal filesystem path components — that's why `validate_title` rejects `/ \` leading `.` control chars and >120 chars. root x/y are absolute and snapped to GRID_SIZE=200; child x/y are **relative to their parent folder**, plain ints, unsnapped. two different coordinate spaces — never mix them.

**edge**: `{id, source, target, edge_type}`. endpoints are always docs, never folders (containment IS parenting; an edge to a folder would be ambiguous).

## storage.py — disk I/O

- path helpers (`_user_dir`, `_board_dir`, `_meta_file`, `_versions_dir`, `_types_file`).
- `_write_json` (41) — atomic tmp+rename, mkdirs first. single-writer assumed: **no locking**, last save wins.
- `new_id` (55) — `secrets.token_hex(4)`, collision-retried.
- `init_user_storage(user)` (65) — first-use seeding: default types.json + a `main` board. called by the auth dependency on every request.
- `load_meta`/`save_meta` (112/116) — the graph dict.
- `require_unique_title` (144) — board-wide uniqueness, ValueError on dupe.
- `content_path` (150) — resolves a node to its file by WALKING THE PARENT CHAIN and joining titles. docs get `.md`, folders are directories. this function is why meta must still contain a node when its content is deleted/moved.
- `read_content`/`write_content` (165/172); `delete_content` (189) — rmtree for folders, unlink for docs, then prunes empty ancestor dirs upward (never past `tree/`).
- `move_content(old_meta, meta, node_id)` (199) — computes the old path from a PRE-MUTATION copy of meta, the new path from current meta, `shutil.move`s. this is why `update_node`/`move_node` deep-copy meta before mutating.
- `load_types` (213) — **backfills defaults over disk on every read** (`{**defaults, **disk}`): default types are recolorable but immortal — you can't delete one, it re-emerges. customs are preserved.
- versions: `list_versions`, `save_version` (names itself `version_N`, max+1), `delete_version`, `restore_version` (278) — restore WIPES live content first, no safety net. (contrast: zip upload-override auto-snapshots first.) `_copy_data_tree` excludes `versions/` so snapshots can't nest recursively.

## placement.py — autoplace

`next_position(meta, near=None, parent=None)` — called only by `create_node` when x/y aren't given:
- `near` a sibling → one column right of it, first free row at/below its row.
- empty space → (0,0). inside a folder → stack down column 0. root → new column right of the rightmost node (left-to-right DAG growth).
- never moves existing nodes — "user placement is sacred".

## graph_actions.py — the operations (also the agent's tool backend)

these are called directly by INT3RF4CE's agent (no HTTP) AND by api.py. one implementation, two front doors. all raise ValueError on bad input.

- `resolve_node(meta, ref)` (36) — id passthrough, else unique-title match; ambiguous title → error.
- `create_node(...)` (53) — validates board/kind/title/type/state/uniqueness; parent must be a folder; autoplaces; root coords snap to grid. writes meta.
- `read_node` (101) — node + markdown content + connected nodes with direction.
- **`_apply_state(node, new_state, actor)` (129) — the single-assignee task rules.** every state change needs an actor. entering `doing` sets `assignee=actor`; if a node is `doing` under someone else, EVERY change is rejected (steal, complete, release, re-claim — all blocked); leaving `doing` clears assignee. REST passes `actor=user` (the human's username), agents pass their name.
- `update_node(...)` (146) — title/node_type/state/expanded/content. `state=...` (Ellipsis) is the "not passed" sentinel vs explicit null = clear. content capped at 100k chars. renames move the file via move_content.
- `destroy_node` (176) — recursive subtree delete. **content files first (paths resolve through meta), nodes second** — reversing this breaks path resolution. edges touching deleted nodes go too.
- `move_node` (201) — x/y and/or parent. new parent must be a folder and NOT inside the node's own subtree (walks the parent chain).
- `link` (238) — no self-links, no folder endpoints, no duplicate (source,target) pairs, edge_type validated. `retype_edge`/`unlink`.
- `node_path(meta, nid)` (280) — title path like `mind/mech interp/train SAE`.
- `gmap(user, board, ref=None, visible=None)` (291) — the agent's PRIMARY picture of the graph: dry listing, `path (type) [state]` per node (`[doing: name]` when claimed, folders get trailing `/`), then every edge `src -(type)-> tgt`. `ref` scopes to a subtree, `visible` to an access set.
- `ascii_map(user, board, ref)` (344) — box-art spatial layout with coordinates. NICHE tool — for fixing layout before GMOVE. frontend never uses either of these text formats.

## api.py — REST

- `current_user(request)` (25) — the auth dependency on every data route: cookie → `user_for_token` → 401 or username (+ lazy storage seeding). **auth is all-or-nothing per user** — you own your whole tree; agent-level ACL lives in INT3RF4CE, not here.
- every ValueError from storage/graph_actions becomes a 400 via the exception handler (35). `validate_board_id` (40) rejects path-poison board names — and raises HTTPException, which bypasses that handler.
- boards: `GET/POST /boards`, `PUT/DELETE /boards/{id}` (rename/delete; delete rmtrees incl. versions).
- `GET /boards/{id}/download` (172) — in-memory zip: meta.json (with a `"board"` field injected) + everything under `tree/`. versions excluded.
- `POST /boards/upload` (195) — **raw zip body, no multipart**, 50MB cap. tolerates one wrapping directory. name resolution: `meta["board"]` → legacy `board.json` → `?name=` → "board". `_validate_meta` (137) checks structure, title validity/uniqueness, types against the user's registry, parent existence, edge endpoints non-folder. existing board + no `?override=1` → 409; with override → **save_version snapshots the live board first**, then replaces. zip-slip guarded per entry.
- `GET /boards/{id}/graph` — raw meta (what the frontend polls).
- nodes: `POST .../nodes` (create), `PUT .../nodes/{id}` (274) — the frontend's single update route, internally split: x/y/parent → `move_node`; title/node_type/state → `update_node(actor=user)`; expanded/width/height/color patched directly. **meta is reloaded between the two ga calls** because each loads/saves independently — skip the reload and the first change is clobbered. `DELETE .../nodes/{id}` — recursive destroy.
- `GET/PUT .../nodes/{id}/content` — markdown, 100k cap on write.
- edges: `POST/PUT/DELETE .../edges[/{id}]`.
- types: `GET/PUT /types` — PUT validates names/colors and saves verbatim (defaults re-emerge on next load via backfill).
- versions: `GET/POST .../versions`, `DELETE .../versions/{name}`, `POST .../versions/{name}/restore`.

# 5. TH0UGHTGR4PH frontend

`fab/TH0UGHTGR4PH/front/` — store.js (state), nodes.js + edges.js (web components), board.js (interaction), ctxpanel.js (agent settings sidebar), style.css. index.html is a thin shell: auth gate, `<fab-board>`, the ctx-panel skeleton, CDN markdown-it/katex.

## store.js — FabStore (the client mirror + geometry brain)

state: `nodes{}`, `edges{}`, `types`, `camera{x,y,zoom}`, selection sets, `activeFolderId`, `edgeMode`, and two render-time-only offset maps: `tempOffsets` (push-aside) and `folderContentOffsets` (child packing). **offsets are recomputed every render and never persisted.**

- `api(method, path, body)` (29) — every REST call; throws with the server's `detail` on non-OK.
- `loadGraph` (41) — GET graph, replaces nodes/edges, resets expanded docs to default size (expansion sizes are render-time-only), emits "change".
- node/edge/type CRUD wrappers (`createNode`, `updateNode`, `deleteNode` (73) — purges the returned recursive `deleted` list plus dangling edges), content get/put.
- `typeColor`/`edgeColor` — node's own color override → type registry color → fallback.

geometry (this is the part that bites):
- `renderPos(node)` (167) — world position = own coords + parent's renderPos + parent's folderContentOffset + own tempOffset. **never read raw x/y to know where something is.**
- `nodeRect`/`collapsedRect`/`gridRect` — gridRect is the grid-aligned bbox used for overlap math; for an expanded folder it's the recursive bbox of children.
- `computeFolderContentOffsets` (261) — per expanded folder: shift children so the top-left-most child sits at the folder's stored position. a node being dragged keeps pre-drag coords so the folder doesn't chase it.
- `folderTitleLadder` (290) — expanded folders sharing a corner stack their floating titles: deepest right above the frame, each outer 20px higher.
- `resolveCollisions` (313) — the "grid-stretch" rule, recomputed fresh each render: for each expanded node (deepest first), compute its exact-pixel overflow past its home cell; every visible same-parent sibling at/past that edge shifts right/down by that amount (corners get both). exact pixels so grip-resize glides; drop/resize-end snaps back to whole grid cells so alignment returns.
- `wouldOverlap(id, x, y, parent)` (402) — a probe that temporarily relocates, recomputes offsets, tests, restores. used by drop and arrow-key moves. don't call it mid-render.
- `freePositionNear` / `freeChildPosition` — first free grid cell scans.

## nodes.js — the node components

`FabNode` base: attribute/property changes trigger `render()`; mousedown/dblclick dispatch bubbling custom events (`node-mousedown`, `node-dblclick`) that board.js listens to. textareas/buttons are ignored so editing doesn't start drags.

`DocNode`: title, state dot (todo=near-white, doing=green pulse, done=sky), assignee label under the dot while doing, type label, `ref` badge when collapsed. expanded → a `<markdown-editor>` plus a bottom-right `.resize-grip` (dispatches `node-resize-start`; grip size is render-time-only, snapped to whole cells on release). dispatches `doc-expand` so the board lazy-loads content.

`FolderNode`: title only, floating above the frame when expanded (ladder position injected by the board). **`_onFrame` (167): an expanded folder is grabbable only on its frame** (20px top band, 14px other edges) or title — the interior is "empty ground" and falls through to the viewport (pan/deselect). this is what stops accidental collapses while you work inside a folder. collapsed folders drag like normal nodes.

## edges.js — orthogonal routing

`computeRoutes(store)` (12) — pure: visible rects in, `{edgeId: [points]}` out. classify each edge (vertical pair if x-spans overlap, else horizontal), spread multiple edges' ports evenly along a node's border (sorted so closer destinations get earlier ports), then route: straight lines for border cases, 4-point jogs/Z-shapes otherwise, with 12px-staggered turn lanes so parallel edges don't overlap.

`FabEdge` — not a custom element, just wraps 3 SVG nodes per edge: an invisible fat hit-strip polyline (for clicking), the visible polyline, the arrowhead polygon. mousedown → `board.selectEdge`.

## board.js — FabBoard, the interaction state machine

lifecycle: `connectedCallback` (19) builds DOM, restores the board id from localStorage, inits the store, wires events, starts a 60s `pollGraph` (52) — refetches the graph and replaces state only if the signature differs and NO drag/edge-mode is in progress. **this polling is how agent-made graph edits appear in the UI.** `?agent=<name>` in the URL opens the CtxPanel.

render pipeline (261), order load-bearing: `applyCamera` (CSS transform on #world) → `computeFolderContentOffsets` → `resolveCollisions` → `syncNodes` (creates/removes `<doc-node>`/`<folder-node>` elements, injects store + rect + ladder index) → `syncEdges` (`computeRoutes` + FabEdge per visible edge).

selection model — two decoupled concepts:
- **selection** (mousedown): shift = additive. primary selection = LAST-inserted Set element (insertion order is load-bearing).
- **folder activation** (mouseup without drag): `activeFolderId` = the current drop target. keeping these separate is what lets you drag node A into folder B while B stays active. only empty-ground clicks clear the active folder.

drag/drop (`onMouseUp`, 767) — the drop state machine, in order: pan/resize finish (resize snaps to whole cells) → click without movement → select/activate → snap to grid → **ctx-panel drop** (if over a `.ctx-drop` zone: restore original position, add the node to that access list) → folder detection via `elementsFromPoint` under the dragged node → drop into the ACTIVE folder (first free child cell, auto-expands it) → **escape**: if dragged >80px (ESCAPE_MARGIN) outside the parent's pre-drag bounds, move one level up to the grandparent, coords converted spaces → `wouldOverlap` probe, reject-and-restore on collision → PUT.

edge mode (537): toggle, first click sets source, second click on a different node opens the type popup, same node exits, Escape cancels.

keyboard (927): ctrl/cmd+F search (works even inside inputs — searches node TITLES only, folders included, Enter transports you there: expand ancestors + select + center camera). Delete → recursive delete. arrows move the primary selection one grid cell, rejected on overlap.

sidebar/popups: board select + create/rename/delete boards, doc/edge type registries with color pickers (defaults immortal server-side), versions panel (save/delete/restore — restore is destructive, confirm first), zip download/upload (409 → confirm → `?override=1`, server snapshots first).

zoom (887): wheel deltas accumulate (threshold 60 per step, 150ms silence resets) so touchpads don't fly through all 13 levels; zoom anchors at the cursor.

## ctxpanel.js — the agent settings sidebar

opened via `?agent=<name>`; talks to INT3RF4CE's `/ws` (cookie-authed). the SKELETON lives in index.html (visible markup, `.open` slides it in); ctxpanel.js's `_wire()` fills the agent name + done link and wires events; the lists are data-driven and JS-rendered (chips with × remove, ↑ reorder for prompt_docs — order matters, it becomes prompt order).

WS protocol: on open it sends `get_graph_settings`, `list_settings_files`, `list_secrets`, `get_secret_grants`; renders on the matching replies; `error` → the error line; reconnects every 2s unless closed.

semantics of the five lists (stored in `config/specific/{agent}/graph.json`): `prompt_docs` (injected into the system prompt), `read`, `write`, `time` (to-do: may flip task states — write does NOT imply time), `folders` (total control over everything inside). dropping a board node onto a list adds it (folders list rejects non-folders). saving settings runs `reconcile_task_assignment` server-side: nodes dragged INTO the time list get claimed by the agent; nodes dragged OUT get released back to todo.

secrets: two lists (granted / pool), chips dragged between them via HTML5 DnD (`text/secret` dataTransfer with stopPropagation — a separate drag system from board-node mouse drags). values never cross the wire; only names.

settings files: name + save, select + load — named snapshots of graph.json in `config/settings_files/`.

# 6. INT3RF4CE — the model stack

`fab/INT3RF4CE/back/`. the rule that shapes everything here: **the canonical message format IS the OpenAI chat-completions format.** there is no internal translation layer. context storage, the agent loop, the websocket payloads, and the frontend all speak it directly — what you read in `working.jsonl` is what the API sees.

## the canonical format

```json
{"role": "system", "content": "..."}
{"role": "user", "content": "..."}        // or a parts list when images are present:
{"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}
{"role": "assistant", "content": "...", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "TYPE", "arguments": "{\"text\": \"ls\"}"}}]}
{"role": "tool", "tool_call_id": "call_1", "name": "TYPE", "content": "ok"}
```

the rules that make it work:

- `tool_calls` only on assistant messages; `function.arguments` is a STRINGIFIED json object — the agent `json.loads` it at dispatch time.
- every `tool_calls` entry must be answered by a `role: "tool"` message with the same id, positioned immediately after the assistant message's tool run. a cancelled turn leaves dangling calls, and every provider rejects contexts containing them — that's what repair is for (section 7).
- tool messages only accept string content. so a screenshot splits in two: the tool message says `"[image result]"`, and a following user message carries a `"[screenshot]"` text marker plus the actual `image_url` part. the marker does double duty: it tells the model what the image is, and it's what screenshot elision keys on (user-attached images have no marker and are never elided).
- reasoning folds into the assistant content as `[reasoning]\n...\n[/reasoning]\n<reply>` — the closing marker exists so the frontend can split thinking from reply.
- messages on disk also carry a `ts` (timestamp) — stripped from the wire view by marshal's `_API_KEYS` whitelist (`role, content, tool_calls, tool_call_id, name`). anything the model must see must use one of those five keys.

## adapter.py — COMMANDS + thin adapters

`COMMANDS` (adapter.py:30-208) is the single source of truth for tools — ~41 definitions `{name, description, parameters(JSON-schema)}`, grouped: mouse (MOVE/LCLICK/RCLICK/DCLICK/LDOWN/LUP/RDOWN/RUP/SCROLLUP/SCROLLDOWN), keyboard (TYPE, KEY), perception (LOOK, TERM, TERM_LAST_COMMAND), shell (EXEC), special (WAIT, STOP), file (READ/WRITE/EDIT), graph (CHECK_ACCESS, GMAP, ASCII_MAP, GREAD, GUPDATE, GEDIT, GCREATE, GMOVE, GLINK), docker (DOCKER_START/STOP), chat (CHAT_SEND/CHAT_READ/CHECK_CHANNELS/CHAT_FILE_DOWNLOAD/CHAT_FILE_UPLOAD), secrets (READ_SECRETS), compute (SEE_COMPUTERS/USE_COMPUTER/RELEASE_COMPUTER). names must match the agent's dispatch table.

`Adapter` ABC: `api_tools(allowed)`, `to_api_payload(model, system_prompt, messages, use_tools, allowed_tools)`, `parse_api_response(data)`, `reasoning_params(model)`.

`OpenAICompatAdapter` — shared by Kimi and DeepSeek; because the canonical format is already the wire format, `to_api_payload` just prepends the system message, passes messages VERBATIM, adds `max_tokens` + reasoning params + tools (each command wrapped as `{"type": "function", "function": cmd}`, filtered by `allowed`). `parse_api_response` returns the canonical assistant dict directly, folding `reasoning_content` into the `[reasoning]...[/reasoning]` prefix and passing `tool_calls` through untouched. a future Claude adapter would be the first one that actually translates message shapes.

reasoning params are model-name-matched: `"k3" in model` → `{"reasoning_effort": "max"}`; else moonshot's `{"reasoning": {...}}`. `DeepSeekAdapter` overrides with its own `{"thinking": {"type": "enabled"}}` (moonshot params would be rejected).

## model.py — registry + hierarchy

`Model` ABC: class attrs `name`, `adapter`, `models` (display name → provider id), `secret_name` (the key's name in the user's secrets store), `SUPPORTED_ATTACHMENT_TYPES`. abstract `call(prompt, messages, kv_cache, use_tools, allowed_tools) -> (assistant_message, kv)` and `summarize(messages, kv_cache) -> (text, kv)`. `make(model_id, get_key)` is the factory; `get_key` resolves a secret_name to an api key (server passes `secretsmod.resolve`).

providers self-register via `@register_provider` at import (server.py imports them for the side effect). `get_model_class(model_id)` linear-scans the registry.

`HierarchyModel` (provider name "hierarchy", **currently unregistered** — the selector shows only k3 and v4-pro; re-add `@register_provider` to re-enable): `HIERARCHY = ["kimi-k3", "deepseek-v4-pro"]` — ordered fallback. `_try_chain` falls through ONLY on `asyncio.TimeoutError`, HTTP 429, or HTTP ≥500; other 4xx re-raise immediately (a malformed request should surface, not be retried downstream). `active_model` records who answered last. gotcha: the chain advertises the UNION of attachment types, but if a screenshot-carrying turn falls through to text-only DeepSeek, the request 4xxs and surfaces — the fallback is blind to content.

## models/kimi.py, models/deepseek.py

`Kimi`: `secret_name="moonshot"`, the kimi-k3 model, accepts png/jpeg/gif/webp. `__init__` **raises RuntimeError if the key is missing** — fail fast at agent creation (server catches this: skips at boot, error message at create). `call`/`summarize` POST via httpx with a double 180s timeout (the outer `asyncio.wait_for` is the one that raises the TimeoutError HierarchyModel catches). `_check_response` logs status + first 200 chars of the reply only — deliberately never the payload (chat content shouldn't leak into logs).

`DeepSeek(Kimi)`: swaps `base_url`, `secret_name="deepseek"`, the v4-pro model, and `SUPPORTED_ATTACHMENT_TYPES = set()` — text-only, no screenshots.

api keys come ONLY from the user's secrets store. there is no env var or .env fallback anywhere — a random registered user can't burn your keys because their agents can't be created without THEIR key.

# 7. INT3RF4CE — context.py (the memory)

per-agent storage at `fab/data/INT3RF4CE/{user}/context/{agent}/`:
- `original.jsonl` — append-only full archive (every message, forever; for post-hoc review).
- `working.jsonl` — current working memory; loaded at init, appended per message, fully rewritten by repair/summary.
- `working.legacy.jsonl` — created once if an old block-format context is detected at load (archived, context starts fresh).
- `kv_cache.pt` — kv cache for local models; always None for API models today.

constants: `MAX_WORDS=30000` (summary trigger), `PRESERVE_LAST=5`, `KEEP_RECENT_SCREENSHOTS=3`.

the class:

- `__init__(user, name)` — mkdirs, touches the jsonl files, loads working.jsonl, archives legacy formats. **constructing a Context mutates disk.**
- `add_message(role, content, **extra)` — appends `ts` and writes the line to BOTH original and working jsonl. `add_user_text`, `add_assistant_message(msg)` (passes tool_calls through), and `add_tool_result(tid, name, content)` — string content → plain tool message; parts-with-images → `"[image result]"` tool message + the `"[screenshot]"` user message.
- `marshal()` — **the API view, and it's not pure.** steps: (1) `repair()`; (2) strip each message to the canonical keys; (3) flush `pending_attachments` (one-turn-only upload parts from chat injection — consumed, never persisted) into one trailing user message; (4) if the last message is a bare-text assistant, append an ephemeral `{"role":"user","content":"[SYSTEM]\n"+WORK_MSG}` so the API has a user turn to respond to (this is the auto-turn mechanism — pure-text turns are allowed to keep going); (5) `_elide_old_screenshots`. only repair and the attachment flush touch state; everything else is wire-only. don't expect to find WORK_MSG or elided placeholders in the jsonl.
- `repair(note)` — the load-bearing invariant: walks messages, and for every assistant `tool_calls` run, inserts placeholder tool messages for unanswered ids **immediately after the run, in tool_calls order** — never appended at the end (position is what providers validate). persists only if it changed something.
- `close_dangling_tool_calls(note)` — repair with an "[interrupted]" note; called by the server on pause and on chat-mode switch. without it every later API call fails silently.
- `_elide_old_screenshots(out)` — finds image parts in `"[screenshot]"`-marked user messages; all but the newest 3 become an elided-note text part. **copy-on-write**: marshal's message dicts share structure with `self.messages`, so anything it modifies is rebuilt first — disk keeps every byte, and raising the limit tomorrow loses nothing.
- `needs_summary()` — word count over everything (image parts count 1000 words each, tool_call argument strings count); ≥ MAX_WORDS triggers.
- `apply_summary(summary)` — working memory becomes the summary (an assistant message, "SUMMARIZED CONTEXT: ...") + the last 5 messages — with two correctness details: the cut point walks backward over leading `role: "tool"` messages so a tool run is never split from its assistant message, and if the tail then starts with an assistant message a synthetic `[continue]` user message keeps the alternation. the summary is also archived to original.jsonl; the caller drops the kv cache.
- `load_kv` — `torch.load(weights_only=True)`: the weights_only flag is a deliberate pickle-RCE guard (a planted kv_cache.pt would otherwise execute code on load). `save_kv(None)` deletes the file.

# 8. INT3RF4CE — prompt.py and the agent loop

## prompt.py — what the agent believes

`build_system_prompt(user, agent_name, chat_mode)` = `global_prompt.md` + prompt-docs block + (chat mode ? `chat_mode_prompt.md`), joined and **re-read from disk every call** — your prompt edits take effect next turn.

- the default global prompt (prompt.py:39-108) is the agent's whole world model: what INT3RF4CE is; the workspace rules (`/home/agent` is the only persistent dir; term.log and screenshots/ are managed); the 1920×1080 screen and tint2 sidebar; the preinstalled `/opt/agent-venv`; the full command reference (kept in sync with COMMANDS by hand); the graph access + to-do queue workflow (GMAP first; todos with edges between them are a chain — do them in edge order; no edges = unrelated, any order; single-assignee rules); chat discipline (CHAT_SEND only for reports/blockers, don't flood); compute workflow (SEE → claim → release).
- `_prompt_docs_block` (157) injects the agent's `prompt_docs` nodes from thoughtgraph (title + content, 2000 chars/doc, 8000 total cap). read/write/time lists are NOT injected — the agent queries them with CHECK_ACCESS.
- seeded-but-unwired: `auto_turn_prompt.md` (the live auto-turn text is the hardcoded `WORK_MSG`) and `summarization_prompt.md` (summarize uses the `CONTEXT_SUMMARIZATION_PROMPT` constant). editing those two files currently does nothing.

## agent.py — one turn

`Agent.__init__` builds the Context and Container, loads kv, sets up the `_tool_handlers` table (19 container/file tools), `stopped=False`, `on_status`/`on_stop` hooks.

tool gating is two-layered: `CHAT_MODE_TOOLS` (docker + graph + self + chat + secrets + compute — NO computer tools) is passed as `allowed_tools` so the model physically can't see computer tools in chat mode, AND `turn()` rejects non-allowed calls server-side with an "[unavailable in chat mode]" tool message.

`turn(user_input=None)` (104):

1. optional user text into context.
2. `model.call(prompt, context.marshal(), kv, allowed_tools=...)` → canonical assistant message. status notifications fire (`api_call started/ended`, `model_used` for hierarchy).
3. `add_assistant_message` (persisted), `save_kv`.
4. no tool_calls → done.
5. per tool_call: name uppercased; chat-mode gate; DOCKER_* → `_docker_control` (async); else `_dispatch`; exceptions become `[ERROR executing NAME]` tool messages (with traceback) so a bad tool call never kills the loop; each call gets `add_tool_result`. WAIT sleeps inline.
6. **auto-feedback**: a turn with keyboard commands but no TERM → the LAST tool result is replaced with fresh TERM_LAST_COMMAND output; mouse commands but no LOOK → replaced with a fresh screenshot. replaces, not appends — if that last result carried real content it's overwritten (by design; EXEC output counts as perception and doesn't trigger this).
7. `needs_summary()` → `model.summarize` → `apply_summary` → kv dropped.

`_dispatch(name, args)` (203) routes: names starting with "G"/"ASCII_"/CHECK_ACCESS → `_graph_dispatch`; STOP → sets `stopped=True` + fires `on_stop` (one-way — only the user's start button un-stops it; the container is NOT destroyed); CHAT_* → `_chat_dispatch`; READ_SECRETS → the granted-secrets dump; compute names → `_compute_dispatch`; else the `_tool_handlers` table. returns `(content, is_perception)`.

`_docker_control` (238): DOCKER_START (blocked when `stopped`) boots the container in a thread, flips chat_mode OFF, notifies — and it's the server's status handler that reacts to "chat_mode off" by spawning the work loop. DOCKER_STOP destroys the container and returns to chat mode.

`_graph_dispatch` (278) — the thoughtgraph ACL layer. resolves the agent's `graph.json`; access = explicit read/write/time entries OR inside a total-control folder (`in_scope` walks parents); write⇒read, time⇒read, **write⇏time**. ids OR unique titles resolve (ambiguous → error). every command delegates to `graph_actions` with `actor=self.name`; ValueErrors become `[G* ERROR] ...` tool results. GEDIT does search/replace on node content with the same semantics as the EDIT file tool (0-indexed occurrence or "all").

`_chat_dispatch` (540): CHAT_SEND (text only), CHAT_READ (marks read + formats recent log), CHECK_CHANNELS (membership + unread counts), CHAT_FILE_DOWNLOAD (channel tree → workspace, dirs recursive), CHAT_FILE_UPLOAD (workspace → channel tree, caption text REQUIRED, single files also append a `file` message to the channel).

`_compute_dispatch` (629): SEE_COMPUTERS (redacted view), USE_COMPUTER (claim → full ssh command + password in the result), RELEASE_COMPUTER.

file tools: `_workspace_path` (669) is THE confinement — resolve and require `is_relative_to(workspace)`; without it the LLM (or a prompt injection) could read/write any host file. READ (line-numbered, 1-indexed range), WRITE (overwrite), EDIT (occurrence or "all").

`_h_*` handlers (720-792): thin Container calls returning `("ok", False)`; the perception ones: LOOK → screenshot image parts; TERM → last 5000 chars of term.log; TERM_LAST_COMMAND → only bytes since the last keyboard command (a byte offset `_term_offset` tracks it, advanced by type/key); EXEC → runs the command in the container via docker exec, appends `$ cmd + output` to term.log (so you see it in the VNC terminal later), returns the tail.

# 9. INT3RF4CE — container.py (the computer)

the docker container is a full desktop the agent drives. the chain: Xvfb :99 (virtual display, 1920x1080) → x11vnc (serves that display on localhost:5900) → websockify (websocket↔tcp bridge on :6080, serves the noVNC web client) → the server proxies it to the browser iframe (auth + per-user port ownership checked).

lifecycle:

- `build()` / `_needs_rebuild()` — the image `int3rf4ce_sandbox` builds from `docker_build/Dockerfile` (tracked in git); a `last_build` copy of the Dockerfile detects changes → rebuild nukes all containers of the old image first. no CMD in the Dockerfile — the runtime command is passed at `docker run`.
- `STARTUP_CMD` (43-71), line by line: **clear stale X locks** (`rm -f /tmp/.X99-lock /tmp/.X11-unix/X99` — without this Xvfb sees its own leftover lock from a previous run, concludes a server already owns :99, and exits → black noVNC forever; this one line is what makes resume-instead-of-recreate possible) → Xvfb → wait for the display → disable screen blanking → paint the root window dark grey (never pure black) → x11vnc (`-forever -shared -nopw -listen localhost`: multiple viewers allowed, no password, only websockify in the same container can reach it) → websockify on 6080 → openbox (window manager) → tint2 (the sidebar with terminal/chromium launchers) → xterm at fixed small geometry logging via `script -f /home/agent/term.log` → `sleep infinity` (PID 1).
- `start()` (146) — rebuild if needed; then: container exists → `docker start` (RESUMES it — the writable layer survives stop, so pip installs into /opt/agent-venv persist across restarts; only destroy/rebuild wipes them) → else `docker run -d` with: `--gpus all` if the host has nvidia-container-toolkit, `-p 127.0.0.1:{novnc_port}:6080` (localhost-only binding — otherwise anyone scanning the host gets unauthenticated keyboard/mouse), `-v {workspace}:/home/agent` (the bind mount — the ONLY host dir the container sees). then polls until the display reports 1920 and an XTerm window exists, focuses it. **blocking — every caller wraps it in `asyncio.to_thread`.** note: port/gpu config is baked at `docker run` time; a resumed container keeps its original mapping.
- `stop()` — docker stop, layer preserved, resume later. `destroy()` — stop + rm; workspace and context are the server's, untouched.
- `run(cmd)` — docker exec bash. `read_file`/`write_file` (via tee stdin — no shell escaping).
- `screenshot()` — xwd → convert to png at `/home/agent/screenshots/screen.png` (overwritten each time — old screenshots live only as base64 in working.jsonl), with a red crosshair drawn at the cursor so the model can see the mouse. returns the host-side path (the workspace is shared).
- input: `click/double_click/mousedown/mouseup/scroll/type_text/key/move` — xdotool wrappers. `type_text`/`key` call `_mark_term()` first so TERM_LAST_COMMAND reads only output produced after your last keystroke.

# 10. INT3RF4CE — server.py (the wiring)

~1300 lines: every REST route + the `/ws` command loop + agent lifecycle + the vnc proxies.

## module level

- `users` (92) — the in-memory registry: `{username: {agent_name: {agent, novnc_port, model, container_on, working, work_loop?, chat_task?}}}`. everything else derives from disk; this is the live state.
- file constants: `IMAGE_EXTS`, `TEXT_EXTS`, `MAX_ATTACH_CHARS=20000` (text files inline up to this), `MAX_WS_ATTACH_BYTES=25MB` (base64 attachments over the ws — huge files go through channel upload, not the ws).
- `inject_pending(user, name, info)` (117) — pulls the agent's unread channel messages (`pending_messages`), writes them into context as one user text message (`[chat #chan from who] ...`), inlines their file attachments as one-turn `pending_attachments`, marks them read. called before every work-loop turn and every agent-view chat send — this is how chat reaches agents, lazily, never polled.
- `agents_file`/`save_agents` — `agents.json` = `{name: {novnc_port, model, chat_mode}}`.
- `next_port()` — lowest free port ≥6080 across ALL users (ports are global).
- `_make_model(user, model_name)` (302) — registry lookup + `make` with `get_key=secretsmod.resolve`. key resolution happens once, at construction.
- `_attach_status_handler` (314) — the `on_status` reactions: "chat_mode off" + working → spawn the work loop; "chat_mode on" → cancel it; container phase → `container_on`. everything broadcast. `on_stop`: sets `working=False` WITHOUT cancelling the loop — STOP arrives mid-turn, so the loop exits cleanly after the turn's writes instead of being decapitated mid-write.
- `work_loop` (431) — seeds "start working" on an empty context; then loops: inject_pending → `agent.turn()` → broadcast full context. CancelledError exits; timeouts/exceptions sleep 5s and retry.
- `cancel_and_settle(info, key)` (453) — cancel the task AND await its termination before touching context — the dying task's final writes would race yours.
- `reconcile_task_assignment` (464) — when graph settings change: nodes newly in the agent's `time` list that are `doing` under someone else get their claim transferred to this agent; nodes removed from the list that were `doing` under this agent go back to `todo` with assignee cleared. runs as the owner, deliberately bypassing the single-assignee guard, BEFORE the new settings are written.
- `agent_task_list` (493) — the chat-popup data: every agent's stateful nodes (time list + total-control folders), sorted doing/todo/done then path.
- compute hook: `computemod.set_on_change(...)` → any compute mutation (UI or agent tool) broadcasts the fresh list to all of the user's sessions — agent claims show up live on your compute page.
- `broadcast(user, msg)` — to that user's websockets only.

## REST routes

- `POST /chat/{cid}/files` (148) — raw bytes + `?name=relative/path` → stored in the channel tree + a `file` message appended + broadcast. these POSTs are exempt from the hub's 1MB body cap (that's the substring exemption in the middleware).
- the file tree: `GET .../files-list?path=` (one level), `POST .../mkdir`, `PUT/DELETE .../files/{path:path}` (rename/delete), `GET .../files/{path:path}` (download — note: this one checks login but NOT membership, unlike its siblings; harmless in the single-owner model, worth knowing).
- `GET /chat/`, `/secrets/`, `/compute/` — the pages.
- `GET /vnc/{port}/{path:path}` (1232) + `WS /vnc/{port}/websockify` (1260) — the authenticated streaming proxy + websocket byte-pipe to the container's websockify. both verify the port belongs to one of the REQUESTING USER'S agents (`_owned_vnc_port`) — you can't watch or drive another user's desktop.
- `_rmtree_even_root_owned` (1219) — workspace files written by the container are root-owned; on PermissionError a throwaway root container does the delete.

## WS /ws command handlers

connection: Origin-vs-Host check (cross-site websocket hijacking guard, close 1008), cookie auth (`auth_required` + close otherwise), then immediately sends the `agents` list.

- lifecycle: `list` → agents. `create` (573) — validates name (allowlist regex — it becomes a folder path and docker name), model id, and key presence (**a missing secrets key comes back as an error message, not a crash**); builds the Agent, ensures the DM channel, saves, broadcasts. `start` (694) — clears `stopped`, sets working, spawns the loop unless chat_mode. `pause` (727) — cancel_and_settle the loop + `close_dangling_tool_calls` + broadcast (the settle-before-close ordering is what prevents both races and dangling-call API rejections). `kill`/`docker_stop` — cancel without settling + destroy container. `delete` (771) — cancel, destroy container, rmtree workspace (root-aware) + context, strip from all channels, `release_all` its compute claims, save + broadcast. `rename` — stop/destroy, rename workspace+context dirs, recreate the Agent, new DM. `chat_mode` (867) — flip; enabling settles the loop + closes dangling calls; disabling spawns the loop if working.
- `chat` (892) — the agent-view send: inject_pending FIRST (so queued channel messages stay chronological), then builds the user message from text + base64 attachments (images → image_url parts validated against the model's supported types; TEXT_EXTS → inlined content capped at 20k chars; other binaries → a size placeholder; 25MB per attachment). goes DIRECTLY into context — never touches any channel. chat_mode + working → spawns a single-turn task; the reply stays in the context stream (only an explicit CHAT_SEND reaches the DM channel).
- `get_context`, `list_models` (flat map + attachment capabilities), `set_model`.
- channels: `list_channels`, `create_channel`, `set_members`, `rename_channel`, `delete_channel`, `get_messages` (auto-recreates the DM for existing agents — deleting a DM doesn't stick while the agent exists), `chat_send` (appends as `__user__`, broadcasts `chat_message`).
- graph settings: `get_graph_settings`, `set_graph_settings` (999 — validates every entry's board/id, folders must be folders, reconciles task assignment, then writes exactly the 5 keys), `get_agent_tasks`, `list_settings_files`, `save_settings_file`, `load_settings_file`.
- secrets: `list_secrets` (items only — values never cross the wire), `set_secret` (cat "llm" names restricted to registered provider secret_names — currently moonshot/deepseek), `delete_secret` (also strips the key from every agent's grant list), `get_secret_grants`, `set_secret_grants`.
- compute: `list_computes`, `add_compute`, `delete_compute`, `claim_compute` (held under the USER's own name — that's how the human force-releases anything), `release_compute`. broadcasts flow through the compute.py change hook.

# 11. INT3RF4CE — the services

## chat.py — channels

per-channel append-only `messages.jsonl` + a real file tree under `files/`. `channels.json` = `{cid: {id, name, members, dm, created}}`; `readers.json` = per-agent read cursors.

- channels: `create_channel` (slugified id, suffixes -2, -3 on collision), `ensure_dm` (deterministic `dm-{agent}`, members `[__user__, agent]`), `set_members`, `delete_channel` (rmtrees the dir), `remove_agent_everywhere` (strips membership, never deletes channels), `rename_channel`, `is_member`, `resolve_channel` (id or unique name, membership-enforced — the agent can only address channels it belongs to).
- messages: `append_message(user, cid, sender, type, text, file)` — `{id, ts, sender, type: "text"|"file", ...}`; `read_messages(limit, since_ts)`.
- files: `store_file` (176) — 100GB per-file cap (datasets), path made safe, parents created; `_safe_path` + `_validate_within` reject escapes; `list_file_tree` (one level, `[{name, path, size, is_dir}]`); `mkdir_channel`, `rename_file`, `delete_file` (recursive).
- readers: `mark_read`, `pending_messages(user, agent)` — unread messages from others across all member channels (the inject_pending source), limit 100.

## secrets.py — the single source of truth

`secrets.json` = `{name: {value, cat}}`, chmod 600, categories `llm | account | git | gitrepo`. llm names are hardset to provider secret_names (moonshot, deepseek). git values are forced `{"account", "key"}` pairs and the key must contain "PRIVATE KEY". gitrepo values are plain urls (not secret, just co-located).

two consumers, one store: the backend (`resolve` feeds `_make_model` — values never enter agent context this way) and the agent (`READ_SECRETS` returns only the granted subset via `granted`). `items()` is the UI view — values stripped; only gitrepo urls and git account names leave the host. `delete_secret` strips the key from every agent's grant list automatically. grants live at `config/specific/{agent}/secrets.json` = `{"grants": [name]}`.

## compute.py — claimable ssh targets

`compute.json` = `[{name, ssh_command, password}]`, `compute_usage.json` = `{computer: holder}` — both chmod 600. one holder per machine.

- `add_computer`/`delete_computer` (delete auto-releases claims), `usage_map`, `claim` (errors if taken), `release` (only the holder or the account owner — the user claims under their own username, which is also how they force-release), `release_all` (frees everything an agent held — wired into agent delete), `computers_for_agent` (redacted view: full credentials only for free or own-claimed machines).
- `set_on_change(fn)` — the change hook; server registers a broadcast so every mutation (UI or agent tool) pushes the fresh list to all your sessions.
- no locking: the exact-same-instant double-claim race is an accepted trade.
- the "compute rent" section on the page is placeholder UI for a future auto-rent feature — no handler, by design.

# 12. INT3RF4CE — frontend pages

four pages sharing `style.css`, all with a top-left hub button and the AuthBox.

**agent view** (`index.html` + `app.js`): left = agent list (status dots, ⋮ menu with rename/delete/settings), mid = the noVNC iframe (`/INT3RF4CE/vnc/{port}/vnc.html?autoconnect&resize=scale` — scaled to fit, not 1:1; auto-retries every 3s while the container is down), right = the message stream + model dropdown + input.

the stream is a MERGE: DM channel messages + context extras, interleaved by `ts`, deduped by substring (a quirk: an assistant text that's a substring of a DM message vanishes). rendering: markdown via the hub's `makeMarkdownRenderer`; `[reasoning]...[/reasoning]` splits into a collapsible block; tool messages and tool_calls render as thin collapsible environment blocks; `"[screenshot]"` markers and `[chat #...]` injection lines are hidden. CHAT_SEND to non-DM channels shows as `#channel` text.

sends are direct: Enter → `cmd:"chat"` with text + base64 attachments (drag/paste, 25MB cap, validated against the selected model's supported types). buttons: docker toggle (container only), model toggle (start/pause = the `working` master switch), single-turn toggle (chat_mode), model select, settings → `/TH0UGHTGR4PH/?agent=...`.

**chat view** (`chat.html` + `chat.js`): channels list (DMs first, status dot = agent working), message stream (markdown bodies, file chips download from the channel tree), a `tasks` popup (every agent's doing/todo/done with assignees), and the file-tree panel: lazy-loaded per-channel tree (expand fetches that folder's children, collapse purges that subtree's cache; state cleared on channel switch), per-row rename/delete, toolbar with upload / upload-folder (webkitRelativePath preserved) / + folder, drag-drop onto the panel. message uploads use XHR with a progress bar; Enter uploads pending files then sends.

**secrets page** (`secrets.js`): four category sections; values are write-only (saved, never read back); git entries take the account+key pair; per-row delete. errors pin red in the header.

**compute page** (`compute.js`): rows of name + ssh command + password (plaintext — you own them) + status (unused / in use by X / you), a claim/release toggle per row (disabled when held by someone else), delete with confirm. live updates arrive via the broadcast hook.

# 13. hub components

`fab/hub/components/`, served at `/components/`. plain web components, no shadow DOM.

- **TechnoParadisalTheme.css** — global theme: color vars (lavender/sky/mint/neon-pink/green/red/grays on #000), Space Grotesk (Google Fonts import), a global `*{margin:0;padding:0}` reset and 21px base font. every page loads it — and inherits the reset.
- **TechnoParadisalComponents.js/.css** — the cyberMechanical set: `<cyber-link>` (sol-button link with side cut), `<cyber-button>` (press-down face), `<cyber-ul>` (category header with LED), `<cyber-home>`/`<cyber-back>` (nav). shared `escapeHtml`/`safeHref` helpers (safeHref allows only `/`, `./`, `http(s)://`).
- **AuthBox** — `<auth-box>`: top-right login/register/logout, talks to `/auth/*`, broadcasts `auth-changed`. renders the username unescaped — safe only because usernames are allowlisted server-side.
- **MarkdownEditor** — `<markdown-editor>`: textarea↔rendered-preview toggle with `[[wikilinks]]` (resolveLink hook maps titles to node ids; broken links render as spans). debounced `content-change` events; `wikilink-click` events. used by thoughtgraph doc nodes. `markdown-render.js` is the shared `makeMarkdownRenderer()` factory (markdown-it + katex, `html:false` — the XSS guard for model output). depends on CDN globals — script order matters: markdown-it → katex → markdown-it-katex → markdown-render.
- **BoardCanvas** — `<board-canvas>`: infinite pan/zoom board + SVG edge layer. the host app appends its own node divs and feeds fully-computed edge point lists. used by INT3RPV1Z (thoughtgraph has its own board).
- the function_approximator widgets (interp_journey): **FreeDrawCanvas** (drawable 2D canvas, exports a downsampled RGBA grid), **DrawCanvas3D** + **math3d.js** (3D perspective canvas with arcball rotate, quaternion camera; ES module — load with type="module"), **LinePlot**, **VectorEditor** (draggable 2D vectors), **Surface3D** (isometric surface plot).

# 14. tests

- `venv/bin/python -m fab.TH0UGHTGR4PH.tests.headless_test` — the executable spec, from repo root. part 1 drives graph_actions/context/agent dispatch in-process (access enforcement, task assignee rules, repair/elision, chat, secrets, compute). part 2 boots the hub on port 2999 with throwaway users (seeded with a fake moonshot key — secrets are the only key source now) and exercises every REST route + WS command end to end.
- `node fab/TH0UGHTGR4PH/tests/geometry.test.js` + `node fab/TH0UGHTGR4PH/tests/edges.test.js` — the store.js collision/expansion math and the edge router (both files are node-loadable via `module.exports` guards for exactly this).
- `venv/bin/python mind/INT3RPV1Z/tests/ws_test.py` — the visualizer's suite.

# 15. the one-paragraph version

a request comes in with a `mindology_session` cookie; auth resolves it to a user; everything after is per-user json files under `fab/data/`. thoughtgraph is REST: meta.json mirrored in the browser, edits flow through graph_actions to disk, the 60s poll picks up agent edits. int3rface is WS: the server owns Agent objects whose contexts are canonical OpenAI message lists on disk; a turn is marshal (repair + strip + inject + elide) → provider call through a thin adapter → persist → dispatch tools (container, files, graph, chat, secrets, compute) → auto-feedback → maybe summarize; the work loop repeats it until paused. chat channels and compute claims are shared state between you and the agents; secrets are the single source of truth for keys; the docker desktop is the agent's hands, proxied to your browser over an authenticated vnc pipe.
