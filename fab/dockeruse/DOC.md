# dockeruse/DOC.md

spec for the port, distilled from old_fab/INT3RF4CE (~7.9k LOC). the old app was ONE thing: agent loop + container + channels + secrets + compute fused together. in new fab the loop is corechat's and dockeruse is JUST the computers: docker containers as first-class objects, a set of tools, and a watch page.

the old container code was hand-written, not vibecoded — it is precious. **COPY, don't rewrite**: `container.py`, the `docker_build/` dir (Dockerfile, tint2rc, openbox_rc.xml, .desktop files), and the noVNC proxy keep their comments and structure verbatim. the only sanctioned edits are the seam changes listed below.

- **REMOVED: the agent loop** (turn/work_loop/chat_mode/WAIT-in-loop/auto-continue) — corechat owns it.
- **REMOVED: model layer** (model.py, adapter.py, models/, kv cache) — corechat's modelserver owns it.
- **REMOVED: channels** (chat.py, chat page, file transfer, DM injection) — future wiresend module, not dockeruse.
- **REMOVED: secrets store + compute manager** (secrets.py, compute.py, their pages and tools) — secrets will live in thoughtgraph; compute comes back as its own module if ever.
- **multi-user is BACK via hub auth** (since this spec): per-user dirs under `~/.fab/users/{user}/`, per-user vnc port ownership. the old per-user param machinery stays dead — the user enters through the cookie, once.
- **REMOVED: graph tools + ctxpanel + settings files** — thoughtgraph owns G* and the access panel.
- **REMOVED: prompt blocks system** (prompt.py, the prompt popup) — corechat's prompt.py; prompt_docs injection is corechat-side plumbing.
- **REMOVED: original.jsonl, legacy block-format archiving** — corechat keeps working.jsonl only.
- **REMOVED: auto-feedback** (the old turn-level "keyboard without TERM → auto TERM, mouse without LOOK → auto LOOK" result-replacement machinery) — DELETED, not redesigned. every tool returns its own plain result; the model calls TERM/LOOK explicitly. typing into a browser must never drag terminal output into context.
- **REMOVED: screenshot elision** — see "screenshots: NO elision" below.
- **REMOVED: auto-provisioning** — agents never create or destroy computers, ever. see "the lifecycle".
- **REMOVED: STOP tool** — a corechat tool (see fab/TODO), not a dockeruse tool.
- **REMOVED: docker save button** — was a disabled placeholder, stays unimplemented.

everything below is what remains and must be preserved.

# concept

a docker container IS a computer: a full Linux desktop (Xvfb 1920x1080, openbox, tint2 sidebar, xterm, chromium) the model drives with xdotool, and the human watches through noVNC in the browser.

**containers are first-class objects, not agent appendages.** the human creates/destroys containers on the dockeruse page and assigns an agent to a container (one agent per container at a time — two minds on one mouse is chaos). the workspace belongs to the CONTAINER: reassigning a container hands the new agent the machine, its files, its term.log, everything. this is the old compute-manager claim pattern applied to local dockers.

the workspace is a host folder bind-mounted to /home/agent: files written by either side show up on both, term.log and screenshots live there, and it survives container stops, restarts and image rebuilds.

tools register into corechat's central COMMANDS — corechat must `import fab.dockeruse.back.tools` for registration to happen (the one plumbing line, same as thoughtgraph). handlers are `async fn(args, agent) -> str`; `agent.name` is the whole identity (no user). ZERO corechat changes — delayed and image results both ride the existing inbox (see "screenshots via deposit").

# the lifecycle (who may do what)

four verbs, two owners:

| verb      | docker          | human (watch page) | agent (tools) |
|-----------|-----------------|--------------------|---------------|
| create    | `docker run` (first boot) | ✓ | NEVER |
| destroy   | `docker rm`     | ✓                  | NEVER         |
| start     | `docker start` (resume)   | ✓ | ✓ DOCKER_START |
| pause     | `docker stop`   | ✓                  | ✓ DOCKER_STOP |

- **create** (human only): the page's add button creates the containers.json entry + port allocation AND does the first boot, so the docker container exists from that moment on. container.py's `start()` is create-or-resume in one function — the first human start is what runs `docker run`.
- **destroy** (human only): `docker rm`. workspace untouched unless the human explicitly confirms workspace deletion too.
- **start** (both): resume an EXISTING container. the agent's DOCKER_START is a strict resume: it checks `docker ps -a` and only ever runs `docker start` — if the human never created the container it answers "your computer doesn't exist yet — ask the user to create it". it NEVER creates and NEVER triggers an image rebuild (`_needs_rebuild` is the human-start path's business; a stale image makes the agent's start answer "ask the user to start it once").
- **pause** (both): `docker stop` — state preserved, writable layer keeps pip installs, resume takes seconds. does NOT destroy, does NOT touch the workspace. (the old DOCKER_STOP destroyed — that was a bug-flavored decision, fixed here.)
- no mode flags, no work-loop coupling, no notifications — corechat's agent_mode is the human's switch and stays orthogonal.

# disk layout

everything under `FAB_DIR/users/{user}/dockeruse/` (per user — hub auth gates every route; the doc says `~/.fab/dockeruse/` for short):

```
~/.fab/dockeruse/                 # read as: users/{user}/dockeruse/
  containers.json               # {container_name: {"novnc_port": 6080, "agent": name|null}}
                                # dockeruse owns this — NOT corechat's agents.json
                                # (same precedent as thoughtgraph's access.json)
  workspace/{container}/
    term.log                    # xterm output via script -f (written inside the container)
    screenshots/screen.png      # latest LOOK
    exec_logs/{id}.log          # background EXEC output
    ...                         # the agent's actual work files
```

- container names are validated against `^[a-zA-Z0-9_-]{1,64}$` (a name becomes a docker name and a folder path — copy the old NAME_RE cybersec comment).
- ports are host-wide: they allocate from 6080 upward across ALL users' containers.json (no cross-user collision), then stick to the container.
- workspaces are created on container start, never by the tools.
- agent names come from the user's `users/{user}/agents.json`, read at FILE level (read-only, same as thoughtgraph's /agents route — including garbage-collecting assignments to dead agents).

# the container (back/container.py — COPY)

copied from old_fab/INT3RF4CE/back/container.py with exactly these seam edits and no others:

- `Container(name)` — drop `user`; the name is the container's own (not an agent's); workspace is `FAB_DIR/dockeruse/workspace/{name}`.
- `DATA_DIR`/`PROJECT_ROOT` imports become `fab.config.FAB_DIR` + `Path.cwd()`.
- novnc_port comes in as a constructor arg from containers.json, as before.

everything else stays, including all comments:

- **STARTUP_CMD**: rm stale X locks (resume breaks without it) → Xvfb :99 → wait-for-display loop → xset/xsetroot → x11vnc (`-forever -shared -nopw -listen localhost`, :5900) → websockify --web novnc :6080 → openbox → tint2 → xterm at fixed `-geometry 100x30+56+8` logging via `script -f /home/agent/term.log` → sleep infinity.
- **image lifecycle**: `_needs_rebuild` (image missing / no last_build / Dockerfile changed) → nuke stale containers, rmi, rebuild; `build_docker.sh` retries forever in tmux. `start()` RESUMES the preserved container when it exists (writable layer keeps pip installs), recreates only when there's nothing to resume.
- **run args**: `-d`, `-p 127.0.0.1:{port}:6080` (localhost-only — the app proxies it; copy the cybersec comment), `-v {workspace}:/home/agent`, `--gpus all` only when nvidia-container-cli exists on the host.
- **readiness waits**: poll `xdotool getdisplaygeometry` for "1920", then search XTerm and `windowfocus --sync` it.
- **control surface**: `run` (bash -c, stdout+stderr), `read_file` (cat, no shell), `write_file`/`append_file` (tee via stdin, no escaping), `screenshot()` (xwd -root -silent | convert → png into workspace, then a red crosshair drawn at the xdotool mouse position so the model can see its cursor), xdotool `move/click/double_click/mousedown/mouseup/scroll(4=up 5=down, active window)/type/key`, `_mark_term` byte offset so TERM_LAST_COMMAND returns only new output.
- `stop()` preserves state; `destroy()` stops + removes but never touches the workspace. **destroy is a human-only action (the watch page's delete). the tools never destroy.**

# the image (docker_build/ — COPY the whole dir)

debian bookworm-slim + xvfb, x11-apps, xdotool, imagemagick, xterm, x11vnc, novnc, websockify, chromium, openbox, tint2 + the everyday tools (git, tmux, curl, rg, vim, htop, sqlite3, sshpass, ...) + python3 and the baked `/opt/agent-venv` (fastapi, uvicorn, httpx, websockets, matplotlib, pandas, ipython, pytest, huggingface_hub, einops, tqdm, torch) on PATH. `DISPLAY=:99`. chromium gets a `--no-sandbox` wrapper at /usr/local/bin/chromium. tint2 sidebar with terminal + chromium launcher icons (icons drawn with ImageMagick at build), openbox rc (Chromium fullscreen, XTerm borderless). every comment in the Dockerfile survives.

# tools (back/tools.py — the one new file of any size)

registered wire-ready into corechat's COMMANDS, schemas copied from old adapter.py COMMANDS (the descriptions are good — keep the wording, minus the auto-feedback claims). handlers get the agent and resolve their container through containers.json: the container whose "agent" is this agent's name. no assignment → computer tools answer "no docker assigned to you — the user assigns one on the dockeruse page".

final tool surface (23 tools):

- **mouse**: MOVE {x,y}, LCLICK, RCLICK, DCLICK, LDOWN, LUP, RDOWN, RUP, SCROLLUP, SCROLLDOWN — all return plain `"ok"`.
- **keyboard**: TYPE {text}, KEY {keys: [X11 keysyms]} — plain `"ok"` (they still `_mark_term` first so TERM_LAST_COMMAND works).
- **perception**: LOOK (screenshot, see below), TERM (last 5000 chars of term.log), TERM_LAST_COMMAND (term.log since the last TYPE/KEY offset mark). fully explicit — the model calls these when it wants eyes.
- **shell**: EXEC {command, background?} — foreground caps at 30s (EXEC_TIMEOUT): over the limit the command is NOT killed, it's demoted to a background task (id + exec_logs/{id}.log) and the agent finds out via `agent.deposit` when it finishes; `background: true` starts that way directly. output is mirrored into term.log so the human sees it in the VNC terminal. **TASKS** lists background tasks.
- **files**: READ {file, start?, end?} (line numbers, 1-indexed range), WRITE {file, content}, EDIT {file, old, new, which} ('0','1',... 0-indexed occurrence or 'all')
- **computer**: DOCKER_STATUS, DOCKER_START (strict resume, see the lifecycle), DOCKER_STOP (pause)
- **special**: WAIT already lives in corechat's commands.py — do not re-register.

## computer tools

- **DOCKER_STATUS** {} — the agent's situation in one line: its assigned container's name + state (`running` / `paused`), or "no docker assigned to you". the orient-before-acting tool.
- **DOCKER_START** {} — resume the assigned container (`docker start`). errors when there is no assignment, when the container was never created ("ask the user to create it"), or when the image went stale ("ask the user to start it once"). never creates, never rebuilds.
- **DOCKER_STOP** {} — pause the assigned container (`docker stop`). after it, every other computer tool answers "your computer is paused — DOCKER_START resumes it".

## file tool rules (preserve)

- `_workspace_path`: all file args resolve inside the assigned container's workspace; `/home/agent` and `/home/agent/...` prefixes are accepted and rewritten; anything escaping the workspace raises (copy the cybersec comment — prompt injection must not reach ../../.env).
- ALL file ops go through `docker exec` as root (the container is the single writer, ownership stays uniform) and therefore require a running container.

## EXEC bookkeeping (preserve)

per-container `_bg_tasks` registry {id: {command, log, status, exit, task}}, spawn via `asyncio.create_subprocess_exec("docker", "exec", ...)`, output streamed to the workspace log, finish announced by `agent.deposit(f"EXEC BG {id} finished...", ...)` — deposit is exactly what it was built for.

## screenshots via deposit (no corechat changes)

tool messages carry strings only — the APIs only SEE an image as an image_url content part on a user message (base64 in a tool string would arrive as ~250k tokens of unreadable text). so LOOK splits its return the way the old context.add_tool_result did, but over the existing inbox:

1. the handler returns `"[image result]"` — dispatch appends the tool message in order, as usual.
2. the handler appends the screenshot itself to `agent.inbox`: `{"role": "user", "content": [{"type": "text", "text": "[screenshot]"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}`.
3. corechat's turn() already re-wakes when the inbox is non-empty, so the model reacts to the screenshot on the very next call even in chat mode — same latency as a normal tool result.

## screenshots: NO elision (explicit decision)

old context.py elided old screenshots at marshal time (newest 3 survive). DELETED, not ported: rewriting earlier messages invalidates the provider's prefix/KV cache — every turn would reprocess the whole context. all screenshots stay in context as-is; the ONLY size relief is corechat's normal compression. consequence: LOOK is a deliberate, expensive act — another reason there is no auto-LOOK.

# the watch page (front/ + the vnc proxy)

dockeruse's own page, mounted at /dockeruse by hub (`app.mount("/dockeruse", dockeruse_app)`). imports /hub/front (TechnoParadisal.css), plain html/css/js, no framework. layout mirrors the thoughtgraph board + access panel pattern:

- **left: container list.** create (name input + add — this does the first boot) and delete (destroy container, workspace untouched — deleting the workspace is a separate explicit confirm) containers here. each row: name, running dot, assigned agent tag. click = select.
- **middle: the noVNC screen** of the selected container, scaled to fit; placeholder text when paused or unselected.
- **bottom bar: start / pause** for the selected container (both just reflect `docker ps` state).
- **right sidebar: assignment** (thoughtgraph-access-panel style slide-in). a dropdown of your agents (from `users/{user}/agents.json`, file level) + assign/unassign for the selected container. assigning a container already held by another agent requires unassigning there first — one agent per computer.
- that's the whole page. no chat (corechat's page), no graph settings (thoughtgraph's panel), no secrets/compute.

REST (plain JSON, no auth, no websocket — the page polls GET /containers on its own tick):

```
GET    /containers                     -> [{name, novnc_port, agent, running}]
POST   /containers                   {name}                # create entry (port allocated) + first boot
DELETE /containers/{name}                                    # destroy container; ?workspace=1 also deletes it
POST   /containers/{name}/start
POST   /containers/{name}/stop
POST   /containers/{name}/assign     {agent}               # agent must be free of other containers
POST   /containers/{name}/unassign
GET    /agents                                             # corechat agents.json names (+ assignment GC)
```

## vnc proxy (server-side routes — near-verbatim copy from old server.py)

- `GET /vnc/{port}/{path:path}` — stream noVNC static assets from the localhost-only container port (httpx streaming, as before).
- `WS /vnc/{port}/websockify` — the byte bridge: accept with subprotocol 'binary' only if offered, connect upstream with subprotocols=["binary"], pipe both ways, FIRST_COMPLETED then cancel the survivor.
- ownership check: the session cookie resolves the user, and the port must appear in THEIR containers.json (keeps the cybersec point — otherwise the proxy reaches arbitrary localhost services, or another user's desktop).
- iframe url: `/dockeruse/vnc/{port}/vnc.html?autoconnect=true&resize=scale&path=dockeruse/vnc/{port}/websockify`.
- the frontend retry babysitter from old app.js ports too: noVNC never retries on its own — reload the iframe when its status element reports error, or when it hangs in connecting >12s.

# what NOT to port (the short list, again, because vibecoding loves resurrection)

no user param, no auth, no channels, no secrets, no compute, no graph tools, no chat_mode, no work loop, no model registry, no prompt blocks, no original.jsonl, no kv cache, no legacy archiving, no versions, no STOP, no auto-provisioning, no create/destroy-from-tools, no settings_files, no task popups, no hierarchy fallback, no auto-feedback, no screenshot elision. if a behavior isn't in this doc, it died with old_fab.
