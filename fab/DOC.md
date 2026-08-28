# doc

fab data types and function flow, short version

# corechat

core loop: input + context -> adapter -> model -> adapter -> parsed commands

parts: adapter (local/api), context, user, tools

## message format (universal, all models)

```json
{"role": "system",    "content": "str"}
{"role": "user",      "content": [{"type": "text", "text": "..."},
                                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}
{"role": "assistant", "content": "str?", "reasoning_content": "str?",
                      "tool_calls": [{"id": "str", "type": "function",
                                      "function": {"name": "str", "arguments": "<json string>"}}]}
{"role": "tool",      "tool_call_id": "str", "name": "str", "content": "str"}
```

- system: only first message
- user: always content blocks, even pure text. images = base64 data urls
- assistant: reasoning_content stored and sent back (kimi-style)
- tool_calls: id from provider, arguments = json string

## tools

the three shapes, three directions:

- **schema** — what WE send describing the tool ("MOUSE_CLICK exists, takes x and y"). registered in COMMANDS, sent with every model call
- **tool_call** — what the MODEL sends back requesting a run: {"id", "type": "function", "function": {"name", "arguments"}}. lives inside an assistant message's tool_calls field
- **tool message** — what WE answer with: {"role": "tool", "tool_call_id", "name", "content"}. the api matches call -> result by tool_call_id

- return immediately, in call order, pure text
- registered and parsed in a central file (back/commands.py), never touch the core loop

registry entry — COMMANDS[name] = {"schema": ..., "handler": ...}, handler is `async fn(args: dict, agent) -> str`.
schemas are registered wire-ready: ONE format, sent to the api as-is ([c["schema"] for c in COMMANDS.values()]). any provider translation is the modelserver's job.
handlers get the whole agent: agent.deposit(tool_name, result) drops a user message ("[tool result] NAME: ...") and wakes a turn (slow tools: placeholder now, deposit later — the model reacts on its own even in chat mode); agent.wake is awaitable (WAIT sleeps the turn on it)
example, a mouse click tool (args arrive as {"x": 120, "y": 340}):

```json
{"type": "function",
 "function": {"name": "MOUSE_CLICK", "description": "click the mouse at pixel (x, y)",
              "parameters": {"type": "object",
                             "properties": {"x": {"type": "integer", "description": "pixels from the left"},
                                            "y": {"type": "integer", "description": "pixels from the top"}},
                             "required": ["x", "y"]}}}
```

- dispatch(agent, tool_call) runs one call and returns the finished tool message: unknown name / bad json / handler exception all become "[ERROR] ..." results, the turn never dies on a bad call
- one turn = one model call: call -> dispatch any tool_calls -> append tool results -> done. the model sees tool output next turn (chat mode: when the user types again; agent mode will auto-continue)
- WAIT: the turn itself sleeps on wait_for(agent.wake.wait(), seconds) — timeout ends it, new input ends it early, a cancel kills it. broadcasts {"type": "status", "waiting": seconds} for the status line
- STOP: the model's own exit from agent mode — sets agent_mode false, the turn tail then never re-wakes. the only completion condition of agent mode; only the user can resume. broadcasts agents_changed so the run button face updates

## adapters

- one ModelServer subclass per provider (special params live there)
- agent guarantees well-formed universal context; adapter only translates, never patches
- local models: special tokens not json, later

## context

- append-only (KV/api cache), only compression rewrites
- `working.jsonl`: what the model sees, what compression rewrites, what the frontend shows
- compression: over the agent's context_limit (words, images = 1000) -> swap in SUMMARIZE prompt, call, rebuild as [system, summary, last 3]
- repair_context() runs at every turn start, before compress: dangling tool calls (killed mid-dispatch, interrupted WAIT) get REPAIR_NOTE placeholder results so the api doesn't reject them; in agent mode a bare assistant ending gets the WORK_MSG nudge

## user

- frontend posts blocks -> inbox; drained into context at start of next turn
- new input during a turn cancels it (task.cancel, the api call dies mid-flight) — the re-turn sees both messages
- every agent runs a permanent run() loop: sleeps on one wake event, one turn per wake. anything that wants a turn (inbox, agent-mode continuation, delayed tool results) sets it
- chat mode (toggle off): one reply then stop. agent mode (toggle on): tools + auto-continue, bare replies get WORK_MSG and it turns again
- toggle_run flips agent_mode: on -> armed, the next message you send starts the working loop (no api call on its own); off -> cancel the live turn and park it. the composer button shows ▶ off, ⏹ on; new agents default off

## api

one websocket at `/corechat/ws`, gated by the hub session cookie (checked at upgrade — ws skips the http middleware). everything is per-user: data lives under `~/.fab/users/{user}/`, broadcasts are scoped to the user's own tabs. client sends {cmd}, server pushes {type}.

client -> server:

```json
{"cmd": "list_agents"}
{"cmd": "create",       "name": "str"}
{"cmd": "rename",       "name": "str", "new_name": "str"}
{"cmd": "delete",       "name": "str"}
{"cmd": "pin",          "name": "str", "pinned": bool}
{"cmd": "set_model",    "name": "str", "model_server_name": "str", "model_name": "str"}
{"cmd": "set_reasoning_effort", "name": "str", "reasoning_effort": "str"}
{"cmd": "set_context_limit", "name": "str", "context_limit": int}
{"cmd": "toggle_run",   "name": "str"}
{"cmd": "get_messages", "name": "str"}
{"cmd": "chat",         "name": "str", "content": [<content blocks>]}
```

server -> client:

```json
{"type": "agents",   "agents": [{"name", "pinned", "model_server_name", "model_name", "reasoning_effort", "context_limit", "agent_mode"}, ...]}   on connect + after any agent mutation
{"type": "messages", "name": "str", "messages": [<full context>], "words": int}   after get_messages + after every turn
{"type": "status",   "name": "str", "generating": bool}         around every turn — the status line indicator
{"type": "status",   "name": "str", "waiting": int|false}       around a WAIT tool's sleep — status line shows "waiting Ns..."
{"type": "agents_changed"}                                      a tool mutated agent state (STOP parked itself) — client re-asks list_agents
{"type": "error",    "name": "str", "msg": "str"}            when a turn dies (api error, rate limit, ...)
```

- messages is always the FULL context, system first; frontend renders incrementally and wipes when it shrinks (compression)
- words: raw context word count (images = 1000), frontend formats the context meter from it
- chat to a nonexistent agent fails hard (assert); create only happens via the create cmd
- broadcast(msg, user, client) — user=X means all of X's open tabs, client=ws means just that socket (request/response)

## agents.json

`~/.fab/users/{user}/agents.json`, per-agent metadata keyed by name:

```json
{"agentname": {"created": 1700000000.0, "pinned": false,
               "model_server_name": "kimi", "model_name": "kimi-k3", "reasoning_effort": "high",
               "context_limit": 300000}}
```

- created: unix ts, sidebar sorts newest first
- pinned: pinned section on top of the sidebar
- model_server_name: which ModelServer subclass (kimi / deepseek); model_name: the api model id; reasoning_effort: low / high / max
- context_limit: context size in words that triggers compression (frontend sets it in k)
- changing model settings rebuilds the agent's model server live, context is untouched (model-agnostic json)
