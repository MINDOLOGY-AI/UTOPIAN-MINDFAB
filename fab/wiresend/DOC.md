# wiresend/DOC.md

spec for the port, distilled from old_fab/INT3RF4CE's chat (chat.py + the chat page + server chat routes + the CHAT_* tools). old chat was fused into the old agent loop; in new fab wiresend is JUST the post office: channels, messages, and a per-channel file store. it knows nothing about agent loops and almost nothing about docker (see "workspace resolution").

the old store code was fine — **COPY, don't rewrite**: `chat.py` drops its `user` param and moves under `~/.fab/wiresend/`, keeping the path-safety guards and membership-as-ACL comments verbatim.

- **multi-user is BACK via hub auth** (since this spec): per-user dirs under `~/.fab/users/{user}/wiresend/`, cookie gates on the http routes and the ws upgrade. channels/agents never cross users.
- **REMOVED: inject_pending / turn-start injection** (unread messages + inlined file parts forced into context before each turn) — replaced by deposit pings, see below.
- **REMOVED: file bytes in context** — files are NEVER deposited or inlined into context. a file message is a text line; the agent pulls the file with WIRE_DOWNLOAD if it cares.
- **REMOVED: WS chat attachments** (the 25MB base64 path from the old agent view) — corechat's own page has paste-attachments for that; wiresend files are browser-upload only.
- **REMOVED: eager DM creation at agent creation** (old server hook) — DMs are lazy: `dm-{agent}` materializes the first time anyone touches it.
- **REMOVED: the tasks popup** on the chat page (read agent task queues off thoughtgraph) — thoughtgraph states died with the port.
- **REMOVED: CHAT_ tool names** — renamed WIRE_* to match the module.
- **NOT wiresend's job, ever**: compute renting (AutoDL), ssh keys, scp itself — that's a future compute module or the agent typing ssh in its own container. wiresend's job ends at "the file is in your workspace / the file is in the channel".

everything below is what remains and must be preserved.

# concept

a post office. channels hold messages and a file tree; membership is the whole ACL; the user and every agent are equal citizens. the headline use case: the user drops weights/datasets into `#ml-research` from the browser → member agents get pinged → an agent WIRE_DOWNLOADs the dataset into its docker's workspace (a host-side copy — same machine, instant) → scps it to its own rented GPU box from inside the container → trains there, never on the user's machine → WIRE_UPLOADs result graphs back to the channel for everyone to read.

tools register into corechat's central COMMANDS — corechat must `import fab.wiresend.back.tools` (the plumbing line, same as thoughtgraph and dockeruse). handlers are `async fn(args, agent) -> str`; `agent.name` is the whole identity.

# disk layout

everything under `FAB_DIR/users/{user}/wiresend/` (per user; the doc says `~/.fab/wiresend/` for short):

```
~/.fab/wiresend/
  channels.json               # {channel_id: {name, members, dm, created}}
  readers.json                # {agent_name: {channel_id: last_read_ts}} — unread counts only
  {channel_id}/messages.jsonl # append-only: {id, ts, sender, type: text|file, text?, file?}
  {channel_id}/files/...      # the file tree, original names, browsable
```

- channel ids: slugified name, `-2` on collision; DMs are deterministic `dm-{agent}` with members `["__user__", agent]`.
- **access model: membership is the whole ACL, plus one field.** `members` may read and talk; a `readonly: [agent_name, ...]` list on the channel marks members who can only WIRE_READ / WIRE_CHANNELS / WIRE_DOWNLOAD — WIRE_SEND and WIRE_UPLOAD bounce with a guidance error. this is for clean library channels (e.g. ML_files: agents download datasets, nobody posts). `__user__` is never readonly. the page toggles it per member row.
- **no librarian tools for agents**: no mkdir / rename / move / delete in the channel file tree — the human owns the library's structure (same principle as "agents never create docs" in thoughtgraph and "agents never create/destroy containers" in dockeruse). agents upload (paths imply their subdirs) and download, that's all.
- sender is `__user__` for the human, the agent's name otherwise.
- file messages carry `file: {name, size, path}` — path relative to the channel's files/ root.
- path safety (COPY the guards): `_safe_path` normalizes user paths (strip leading slashes, resolve `.`/`..`), `_validate_within` rejects escapes from the channel's files/ dir. MAX_FILE_BYTES = 100GB — datasets upload over HTTP.

# tools (back/tools.py)

five tools, schemas adapted from old adapter.py CHAT_* (wording mostly kept):

- **WIRE_CHANNELS** {} — every channel the agent is a member of: name, id, member count, unread count (from readers.json). the orient tool.
- **WIRE_SEND** {channel, text} — send a text message to a member channel. final reports, questions, blocked notices — not progress spam.
- **WIRE_READ** {channel, limit?} — recent messages (marks them read); file messages render as `file: name (size)` lines.
- **WIRE_UPLOAD** {channel, source, text} — copy a file OR folder from the agent's workspace into the channel's files/ store (relative path structure preserved; caption REQUIRED — say what you're uploading and why). broadcasts the file message.
- **WIRE_DOWNLOAD** {channel, file, dest?} — copy a file or folder from the channel's store into the agent's workspace (recursive for folders).

both file tools are plain host-side copies between two local paths — the docker is always on the same machine as the wiresend server (for now). if remote dockers ever happen, switch to curl against the REST routes.

## workspace resolution (the ONLY inter-module touch)

the agent's workspace belongs to its dockeruse container, and wiresend does NOT import dockeruse. instead it reads `users/{user}/dockeruse/containers.json` at FILE level (read-only, per user) — the same precedent as thoughtgraph reading corechat's agents.json. find the entry whose "agent" is this agent's name; workspace = `users/{user}/dockeruse/workspace/{container}`.

- no assignment → "no docker assigned to you — files move through your computer's workspace; the user assigns one on the dockeruse page". text tools work fine without one.
- the workspace path-confinement guard is ten lines (`resolve()` + `is_relative_to`) — copy them, don't import them. `/home/agent` and `/home/agent/...` prefixes are accepted and rewritten, same as dockeruse's own file tools.

## notifications: deposit the ping, never the payload

on EVERY new message (user or agent), wiresend deposits a one-line ping to every member agent that is currently loaded in corechat's registry, except the sender: `[wiresend] new message in #{name} from {sender}`. that's a badge — the agent calls WIRE_READ if it cares. context stays lean; the channel store is the source of truth.

- loaded agents = the `agents` dict in corechat's api (read-only lookup; deposit is the sanctioned channel). unloaded agents miss nothing that matters: readers.json keeps unread counts honest and WIRE_CHANNELS shows them the backlog on their next turn.
- agent-to-agent pings included — a wake is one cheap turn (read the ping, decide). runaway reply loops are a prompt-level discipline problem, not an architecture problem.

# the chat page (front/ + REST + WS)

dockeruse got a watch page; wiresend gets the old chat page, ported: channels left (DMs with ✉, groups with #, member management, rename/delete, + channel), messages middle (markdown for text, download chips for files), lazy file browser right (upload files/folders with paths preserved, mkdir, rename, delete, drag-drop). no auth overlay, no tasks popup.

transports, per house rule (WS for events, HTTP for bytes):

- **WS /ws** — the old cmd set minus user, plus readonly: `list_channels, create_channel, set_members, set_readonly, rename_channel, delete_channel, get_messages, chat_send`; server pushes `{type: "channels"}`, `{type: "messages"}`, `{type: "chat_message"}` (the live-append). every mutation broadcasts to every open page.
- **REST** — file bytes only: `POST /chat/{cid}/files?name=path` (raw body upload), `GET /chat/{cid}/files-list?path=`, `POST /chat/{cid}/mkdir`, `PUT/DELETE/GET /chat/{cid}/files/{path}` (rename / delete / download via plain navigation).
- mounted at /wiresend by hub. imports /hub/front (TechnoParadisal.css), plain html/css/js, no framework.

# what NOT to port (the short list, again, because vibecoding loves resurrection)

no turn-start injection, no file bytes in context, no WS attachments, no eager DM hook, no tasks popup, no CHAT_ names, no compute/secrets/ssh tooling, no dockeruse imports. if a behavior isn't in this doc, it died with old_fab. (the "no user param" line aged out — hub auth landed; the user threads in from the cookie, once.)
