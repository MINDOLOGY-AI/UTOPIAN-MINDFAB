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

- return immediately, in call order, pure text
- delayed result -> placeholder now, inject user message with real result later (same for image results)
- registered and parsed in a central file, never touch the core loop

## adapters

- one ModelServer subclass per provider (special params live there)
- agent guarantees well-formed universal context; adapter only translates, never patches
- local models: special tokens not json, later

## context

- append-only (KV/api cache), only compression rewrites
- `working.jsonl`: what the model sees, what compression rewrites, what the frontend shows
- compression: over MAX_WORDS -> swap in SUMMARIZE prompt, call, rebuild as [system, summary, last 3]
- agent mode: bare assistant ending (no tool calls) -> inject WORK_MSG user message
- killed mid tool call -> inject REPAIR_NOTE tool result so the api doesn't reject dangling calls

## user

- frontend posts blocks -> inbox; drained into context at start of next turn
- chat mode: one reply then stop. agent mode: tools + auto-continue
- start/stop: stop a message immediately

## api

one websocket at `/corechat/ws`. client sends {cmd}, server pushes {type}. server broadcasts everything to every open page; each page filters by agent name.

client -> server:

```json
{"cmd": "list_agents"}
{"cmd": "create",       "name": "str"}
{"cmd": "rename",       "name": "str", "new_name": "str"}
{"cmd": "delete",       "name": "str"}
{"cmd": "get_messages", "name": "str"}
{"cmd": "chat",         "name": "str", "content": [<content blocks>]}
```

server -> client:

```json
{"type": "agents",   "agents": ["name", ...]}                on connect + after create/rename/delete
{"type": "messages", "name": "str", "messages": [<full context>]}   after get_messages + after every turn
{"type": "error",    "name": "str", "msg": "str"}            when a turn dies (api error, rate limit, ...)
```

- messages is always the FULL context, system first; frontend renders incrementally and wipes when it shrinks (compression)
- chat to a nonexistent agent fails hard (assert); create only happens via the create cmd
