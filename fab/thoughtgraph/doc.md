# thoughtgraph/doc.md

spec for the rewrite, distilled from old_fab/TH0UGHTGR4PH (~6.3k LOC). everything the old one did, minus the two amputations:

- **REMOVED: versions** (whole-board snapshots, versions panel, `/versions` routes, save-version-on-upload-override).
- **REMOVED: time states** (node.state todo/doing/done, assignee claiming, state_colors, state picker, todo.js view, `time` access in graph.json, list_tasks/flip_task_state).

everything below is what remains and must be preserved.

# concept

a 2D board of typed doc rectangles and folders connected by typed, colored edges. the graph IS a folder tree of .md files: the file path is the node's place in the tree, so boards stay plain-folder compatible (edit/upload/download as normal files). shared external memory of the user and all agents. agents operate it through graph actions; the user through the board UI; both hit the same operation layer.

# disk layout

everything lives under `FAB_DIR/users/{user}/thoughtgraph/` (per user — hub auth gates every route; the doc says `~/.fab/thoughtgraph/` for short):

```
~/.fab/thoughtgraph/
  types.json                # type registry (doc_types + edge_types)
  access.json               # per-agent graph access (see "agent access settings")
  {board}/
    meta.json               # the whole graph minus doc text
    tree/{folder titles...}/{title}.md   # doc content; folders are plain directories
```

- the title IS the path component: titles unique per board and filesystem-safe. rename/move rewrites the disk path.
- `content/` dir in old layout was vestigial — do not recreate.
- board ids become folder paths: reject `".", "..", "/", "\\", "\x00"`.
- plain-folder first: the tree is real .md files — edit content in neovim freely (content is read from disk on demand, changes show up immediately). symlink `~/.fab/thoughtgraph` anywhere convenient.

## reconcile scan

structural disk edits (new/moved/deleted files) desync meta.json, so on board load, reconcile:

- orphan .md file (on disk, no node) → adopt: create a doc node (type "doc") with the file's title, parented to the folder chain it sits in, autoplaced via placement.next_position. missing folder dirs in the chain get folder nodes the same way.
- node whose file vanished → drop the node; edges touching it die with it.
- that's ALL. a hand-rename looks like delete+create: the new node gets a fresh id and loses its edges/position — acceptable, re-link by hand or in the UI.
- runs on load (server boot / board open), not on every op — ops keep meta and disk in sync themselves.

# data structures (reusable, complete)

## meta.json

```json
{"board": "main",            // injected on download/upload; not required on disk
 "nodes": {id: node},
 "edges": {id: edge}}
```

## node

```json
{"id": "a1b2c3d4",           // secrets.token_hex(4), unique per board
 "title": "jumprelu SAE",    // unique per board, path-safe (see validate_title)
 "kind": "doc",              // "doc" | "folder"
 "node_type": "algorithm",   // a key of types.json doc_types; folders always "folder"
 "ref": null,                // optional external reference, shown as a badge on collapsed docs
 "x": 400, "y": 200,         // root nodes: absolute, snapped to GRID_SIZE; children: relative to parent folder, plain ints
 "width": 560, "height": 360,// expanded size; only meaningful while expanded
 "parent": null,             // folder node id or null
 "expanded": false,
 "color": null}              // optional per-node override; else type color
```

## edge

```json
{"id": "f0e1d2c3",
 "source": "a1b2c3d4",       // always a doc, never a folder
 "target": "b2c3d4e5",       // always a doc, never a folder
 "edge_type": "support"}     // a key of types.json edge_types
```

## types.json (per user, seeded on first use)

```json
{"doc_types":  {name: {"color": "#hex"}},
 "edge_types": {name: {"color": "#hex"}}}
```

defaults can be recolored but never permanently deleted (backend merges defaults under disk on load); user-added types are kept as-is.

default doc_types (color families: purple = knowledge, blue = science loop, red = directives, orange = world/self):

```python
_PURPLE, _BLUE, _ORANGE, _RED = "#B8A0FF", "#6BC4FF", "#FF8C00", "#FF0055"
{"axiom": _PURPLE, "definition": _PURPLE, "theory": _PURPLE, "doc": _PURPLE,
 "hypothesis": _BLUE, "experiment": _BLUE, "evidence": _BLUE,
 "task": _RED, "guideline": _RED,
 "actuator": _ORANGE, "world_state": _ORANGE, "aesthetics": _ORANGE, "personal": _ORANGE}
```

default edge_types: `{"support": "#00FF41", "reject": "#FF0055", "causes": "#6BC4FF", "training": "#FF8C00"}`

## constants

```python
GRID_SIZE = 200          # root snap + layout cell
MARGIN = 20              # inset of a node inside its grid cell
COLLAPSED = 160          # collapsed node size (GRID - 2*MARGIN)
EXPANDED_W, EXPANDED_H = 560, 360
MIN_EXPANDED_W, MIN_EXPANDED_H = 360, 160
ESCAPE_MARGIN = 80       # drag this far past an active parent's bounds to escape it
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.02, 5, 0.1   # additive step
MAX_TITLE_CHARS = 120
MAX_CONTENT_CHARS = 100_000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
```

## agent access settings (`~/.fab/thoughtgraph/access.json`)

thoughtgraph owns its own access file — NOT part of corechat's agents.json. the G* tools live here and enforce it, so the store lives here. keyed by agent name, per user (agent.user picks the world). the agent list is that user's `users/{user}/agents.json`, read at FILE level (read-only); every read of it also garbage-collects access.json — entries whose agent no longer exists get deleted. no preconfiguring agents that don't exist.

```json
{"agentname": {
  "read":        [{"board": "main", "id": "nid"}],
  "write":       [{"board": "main", "id": "nid"}]}}  // write implies read
```

DOC-LEVEL grants only — no folder total control, no time, no secrets. every entry points at a doc node. entries are CROSS-BOARD by construction: `{board, id}` carries its board, so one agent's grants can span every board.

(`time` list removed with the state system.) an agent with no entry gets nothing.

enforcement: every G* call resolves its target against the caller's entry. GMAP shows read+write docs; GREAD needs read; GEDIT/GMETA/GDESTROY need write.

**agents can NEVER create docs — structure is the human's alone.** GWRITE is deleted. an agent with write on an empty doc bootstraps it through GEDIT: `old: ""` on an empty doc sets the content to `new`; after that, single-occurrence replace as usual. one content-mutation tool, one rule, one stated special case.

**edges: GLINK/GDLINK need write on ONE endpoint and at least read on the other.** write+read ✓, write+write ✓, read+read ✗, write+no-access ✗ — you can only touch the graph you can see, and you must own one side of it. GMAP shows edges only when both endpoints are visible, so "no access" and "can't see it" are the same thing.

**presets** (`~/.fab/thoughtgraph/presets.json`): `{preset_name: <an access entry>}`. save = copy the agent's current entry under a name; load = replace the agent's entry with the preset. for stamping a standard access pattern onto new agents.

# title validation (storage.validate_title)

strip; non-empty; ≤120 chars; no leading `.`; no `/` or `\`; no control chars (<32). uniqueness per board enforced on create/rename/upload.

# backend operations (actions.py — one implementation, two front doors: REST for the UI, G* tools for agents)

every op takes (user, board, ...) — per user, the user threads in from the cookie (REST) or agent.user (G* tools). no error handling: bad input raises and the caller (dispatch / fastapi) turns it into an error result. `resolve_node(ref)` accepts an id or a title (titles are unique). ops that rename/reparent sync the on-disk tree via old-meta vs new-meta path comparison, then remove emptied ancestor dirs.

- **create_node**(title, kind, node_type, parent?, ref?, near?, x?, y?) — autoplaces via storage.next_position when x/y absent; root coords snap to grid, child coords round to ints. every doc gets its (empty) .md file at creation — reconcile drops fileless docs.
- **read_node**(ref) — `{node, content, connected: [{edge_id, direction: "in"|"out", id, title, kind, node_type}]}` (directly connected docs only).
- **edit_node**(ref, old, new) — GEDIT: old must occur exactly once in the content; 0 or 2+ occurrences raise. special case: `old == ""` on an empty doc sets the content to `new` (the bootstrap — agents can fill docs but never create them).
- **set_meta**(ref, title?, node_type?, x?, y?, parent?, expanded?, color?, width?, height?) — GMETA: everything about a node that isn't content; parent uses a `...` sentinel (null = move to root); x/y snap by final parent.
- **destroy_node**(ref) — deletes the whole subtree: files first (paths resolve through meta), then nodes, then any edge touching a deleted node.
- **link**(source, target, edge_type) — no self-links, no folders; an existing (source,target) pair gets retyped.
- **unlink**(source, target) / **unlink_edge**(edge_id) — pair form for the G* tools, id form for REST.
- **gmap**(ref?, visible?) — the model's primary picture: text listing, one node per line `path (type)` sorted by path (folders get a trailing `/`), then edges `path (type) -(edge_type)-> path (type)`. ref scopes to a folder's subtree (edges shown when either endpoint inside); visible scopes to an access set (edges need BOTH endpoints visible).
- **node_path**(nid) — `folder/title/title` joined path.

## autoplacement (storage.next_position, model-created + adopted nodes only — user placement is sacred)

per-parent occupied grid cells; `near` → one column right of that node, first free lane from its row; folder children stack down the folder's first column; root nodes go right of the rightmost root column, first free lane.

# REST api (as built in back/api.py, minus old /versions)

per user (session cookie via hub auth). no validation — bad input raises, fastapi returns 500.

```
GET    /boards                                -> {boards: [id]}
POST   /boards              {board_id}
PUT    /boards/{board}      {board_id}        # rename (dir rename)
DELETE /boards/{board}
GET    /boards/{board}/download               # zip: meta.json (with "board" injected) + tree/**
POST   /boards/upload       raw zip body      # name from meta.json's "board" (or ?name=);
                                              # 409 if board exists, ?override=1 to replace (just overwrites)
GET    /boards/{board}/graph                  -> meta.json (load reconciles the tree)
POST   /boards/{board}/nodes    {title, kind, node_type?, parent?, ref?, near?, x?, y?}
PUT    /boards/{board}/nodes/{id}  {title?, node_type?, x?, y?, parent?, expanded?, width?, height?, color?}
                                   # all through actions.set_meta
DELETE /boards/{board}/nodes/{id}             # subtree destroy
GET    /boards/{board}/nodes/{id}/content     -> {content}
PUT    /boards/{board}/nodes/{id}/content  {content}   # 100k cap
POST   /boards/{board}/edges    {source, target, edge_type}
PUT    /boards/{board}/edges/{id}  {edge_type}
DELETE /boards/{board}/edges/{id}
GET    /types                                 -> types.json (defaults merged)
PUT    /types               full types dict
GET    /access                                -> access.json
PUT    /access              full access dict
GET    /agents              agent names from corechat's agents.json (+ access.json garbage collection)
GET    /presets                               -> {presets: {name: entry}}
POST   /presets/save      {name, agent}       # snapshot the agent's access entry
POST   /presets/load      {name, agent}       # replace the agent's entry from the preset
```

upload: meta.json + tree/** extracted as-is (zip-slip paths skipped — the one security check worth keeping); reconcile on the next load fixes anything the upload got wrong. no wrapping-dir tolerance, no board.json backcompat.

# coordinate system (the subtle part — preserve exactly)

- root nodes: absolute world coords, always grid-snapped. children: coords relative to their folder → dragging a folder moves its whole subtree for free.
- a folder's rect is always anchored at its stored position. `folderContentOffsets` packs each expanded folder's children so the top-left-most child sits at the folder's origin — moving children never re-anchors the folder. a mid-drag child keeps its pre-drag spot in this computation so the folder doesn't chase it.
- `tempOffsets` / `resolveCollisions`: an expanded node claims room past its home cell; every sibling at/past its right edge shifts right by the exact pixel overflow, same for bottom; corner siblings get both. exact pixels (no rounding) so grip-resizes glide; recomputed fresh every render so collapsing restores the grid exactly. deepest-first so inner shifts settle before outer folders read bounds.
- `folderBounds`: expanded folder frame = exact union of children's grid rects, no padding (children are grid-aligned, title floats above) → frame edges land on grid lines. empty folder = its one home cell.
- `folderTitleLadder`: expanded folder titles float above the frame line; folders sharing the exact same top-left pixel stack their titles — deepest at step 0, each outer level 20px higher.
- visibility: a node is hidden if any ancestor folder is collapsed. edges render only when both endpoints are visible.

# frontend

plain html/css/js, no frameworks. hub components: TechnoParadisal css, `<markdown-editor>` (markdown-it + katex, `[[wikilink]]` support, debounced content-change, click-anywhere opens the textarea), AuthBox. board is a `<fab-board>` web component; nodes are `<doc-node>`/`<folder-node>`; edges are SVG polylines. store.js mirrors meta.json client-side (EventTarget, one "change" event → full render) and owns all geometry above.

## layout

- toolbar (top): hub link, brand, add doc / add folder / add edge, delete + meta (appear only with a selection), then right side: search, zoom −/+, doc text size input (scales only markdown inside doc nodes, 8–32px, persisted in localStorage), board download ↓ / upload ↑ (zip).
- sidebar (left): board select + new/rename/delete; "file view" (collapsible): indented tree projection of the graph (folders get `/`), click = expand ancestors + select + center camera; doc types + edge types editors (collapsible): color swatch per type (change saves), × delete, name+color+ add row.
- viewport: infinite pannable/zoomable world, dot grid, svg edge layer under the node layer.
- popups: create (title + type chips), meta (rename + retype chips; folders: title only), edge type picker, search panel.

## interactions

- pan: drag empty ground (the interior of an expanded folder IS empty ground — folders grabbable only by frame + floating title: top MARGIN strip + 14px bands). plain wheel scroll pans (dx+dy) — an expanded doc's editor keeps the scroll ONLY if it can still scroll that way (textarea in edit mode, preview div otherwise); at its scroll end the board pans. zoom works over editors too.
- zoom: ctrl/pinch or alt+wheel, anchored at cursor; deltas accumulate to |60| per step, reset after 150ms silence. zoom survives board switches.
- click node = select (shift = additive toggle). click folder = also makes it the ACTIVE folder (creation and drops target it). click empty = clear selection + deactivate. Escape = same + close popups + exit edge mode.
- double-click doc = expand/collapse (expand auto-expands ancestors; expand state persisted). expanded doc = live markdown editor + bottom-right resize grip (raw pixels mid-drag, snaps to whole grid cells on release, min sizes enforced, size persists on node.width/height but collapsing forgets it... old note: no reset on re-expand, custom size survives collapse→expand). double-click folder = expand/collapse; collapsing a folder collapses all expanded descendants. double-click inside the editor or on the grip never collapses.
- drag node: raw movement mid-drag; on release snap to grid, then: dropped onto the active folder → becomes a child at its first free spot (auto-expands the folder); dragged >ESCAPE_MARGIN past its active parent's bounds → escapes one level up (coords recomputed to keep the visual drop position); dropped on top of a sibling → rejected, returns to pre-drag spot. drop detection scans the full element stack under the cursor (edges/siblings on top of a folder don't swallow the drop).
- selection only on mousedown; folder ACTIVATION on click (mouseup without drag) — that's what makes folder-into-folder drags possible.
- arrow keys: move primary selection one grid cell (overlap rejected). Delete/Backspace: delete selection (edge or nodes). ctrl/cmd+F: search.
- edge mode: "add edge" toggles; click source doc, click target doc → type picker popup → create. clicking empty ground or the same node exits.
- select an edge (fat invisible hit strip) → the meta button appears; meta popup for an edge is just the edge-type chips (no title, no save), click retypes instantly. delete key removes it.
- create doc: popup with title + type chips (default = first type); position = free spot near viewport center, or first free child spot inside the active folder; overlap-resolved; creating inside a collapsed folder expands it.
- `[[wikilinks]]` in doc content resolve by title → click = expand ancestors + select + center camera.
- meta popup: rename + retype the primary selection; for an edge: retype only.
- search: title substring, top 50 sorted, arrow keys + enter navigate, jump = expand ancestors + select + center.
- polling: every 5s, refetch the graph meta (server reconciles the disk tree on each call, so neovim/agent/other-tab edits all land here) + refetch the content of every expanded doc; skipped during drag/edge mode; meta replaced only if the signature differs, editor content swapped only if changed — an editor with its textarea open (mid-typing) is skipped so the poll can't roll back unsaved keystrokes.
- last board persisted in localStorage; falls back to "main" (seeded on first use).
- download: plain navigation to the zip route. upload: file picker → raw zip POST → 409 confirm overwrite → replaces and switches to it.

## doc save lifecycle (mdeditor.js — why no wipe is possible)

a doc node's editor has two faces: preview (rendered markdown, textarea hidden — the poll MAY refresh it) and edit mode (textarea visible — the poll SKIPS it). saves go browser → PUT → disk; disk is the single source of truth, last write wins.

- typing: every keystroke updates `_content` in memory, marks the editor dirty, and resets a 400ms debounce timer. nothing hits disk per keystroke.
- save path 1: 400ms after the last keystroke, the timer flushes — whole-doc PUT.
- save path 2: blur (click out) flushes INSTANTLY, then returns to preview mode. without this, a poll landing between blur and the pending debounce would briefly roll the doc back to the last save.
- `flush()` is guarded by the dirty flag: whichever path fires first saves, the other no-ops. no double PUTs.
- after any stop, disk and editor agree within 400ms, so the 5s poll always compares equal and does nothing. the only remaining overwrite is the accepted one: agent edits the doc while you're in it — if you keep typing, your next save wins (last-write-wins both directions).

## edge rendering (edges.js — ported from interpviz routing, preserve the look)

orthogonal routing, left-to-right flow. edges exit/enter through ports spread evenly along the border facing the other node (right/left for horizontal pairs, bottom/top for x-overlapping vertical pairs), sorted so closer counterparts get extreme ports. same row/column: straight line for border (extreme-port) edges, small jog near the target for inner ones. otherwise a Z route with one vertical turn, turn lanes staggered by 12px per incoming edge so parallels don't merge. arrowhead polygon at the target port. edges colored by type; selected edges highlight (pink). hit strip is a fat invisible polyline under the visible one.

## node rendering

doc: colored by type (`--nc`), title, type label bottom-right, ref badge when collapsed, collapsed = 160px square in its grid cell. folder: near-white, collapsed = dashed square, expanded = frame + floating title. ctx-panel drag highlight etc. via css classes. selected/active states are attributes.

# agent integration

the G* tools (back/tools.py) register into corechat's central COMMANDS via the import at the bottom of commands.py. handlers are `async fn(args, agent) -> str`; access enforcement reads `access.json` keyed by `agent.name`; violations raise → dispatch turns them into `[ERROR]` tool results.

final tool surface (7 tools — ascii map and GWRITE deleted, GRENAME/GMOVE/GUPDATE folded into GMETA, retype into GLINK, GLIST into GMAP):

- **GMAP** {board, ref?} — the graph as a text listing, filtered to the agent's visible set
- **GREAD** {board, ref} — one node: meta, full content, connections
- **GEDIT** {board, ref, old, new} — single-occurrence search/replace; `old: ""` on an empty doc writes `new` as the full content (the bootstrap)
- **GMETA** {board, ref, title?, node_type?, x?, y?, parent?, expanded?, color?} — meta write
- **GDESTROY** {board, ref} — delete subtree (separate from GMETA so destructive ops stay salient)
- **GLINK** {board, source, target, edge_type} — create or retype an edge
- **GDLINK** {board, source, target} — remove an edge

access rules: see "agent access settings" — doc-level grants only, no doc creation, edges need write on one endpoint + read on the other.

## the access panel (frontend)

right slide-in sidebar on the board page, toolbar button `access`. everything stays in thoughtgraph — it reads the current user's `users/{user}/agents.json` at FILE level (read-only, no import) to list which agents exist.

- top: agent picker — dropdown of agents.json names, pure (GET /agents; reading it also garbage-collects stale access.json entries). no preconfiguration.
- two grant lists: `read`, `write`. click a list's empty area to ARM it (green border) → clicking board docs grants them to it; click the list again to disarm. chips show title + board tag + ×. folders are rejected with a hint — doc-level grants only.
- CROSS-BOARD: chips from every board show together (the board tag says where); switch boards mid-session and keep dragging — the entry is `{board, id}`, it's just a path. chips for other boards resolve their titles by fetching that board's graph once.
- presets: name input + save (POST /presets/save: copy the agent's entry into presets.json), select + load (POST /presets/load: replace the agent's entry from a preset).
- saves on every change via PUT /access. no websocket, no secrets/compute/todo sections — deleted.

# what NOT to port

- versions/ dir, version routes/panel, snapshot-before-upload (upload override just overwrites now).
- node.state, node.assignee, STATES, state_colors, state picker, state dots, assignee labels, todo.js, list_tasks/flip_task_state, `time` access + folder-expands-to-tasks drop behavior.
- `content/` vestigial dir, `board.json` back-compat in upload, legacy block-format context migration.
- ascii_map (deleted by decision — GMAP + GREAD carry the information), upload meta validation.
- folder total control, the folders grant list, secrets/compute/todo sections of the old ctxpanel (the new access panel is docs only, three lists + presets).

(hub auth landed since this spec: everything above is per user under `~/.fab/users/{user}/`.)
