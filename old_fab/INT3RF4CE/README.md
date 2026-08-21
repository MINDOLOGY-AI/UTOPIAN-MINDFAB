# INT3RF4CE

wrapper for AI models to do long horizon actions and interact with the world. computer control, UI for human interaction and monitoring, potential robot control.  

multi agent collaboration  
this is a end game build. Primy will eventually use this.  
include safety monitoring.  

should remove all software limitations (allow it to keep running and trying) of the model so i can identify the algorithmic limitations for research directions.  

the doc is written in the step of the data processing:  

Prompts + Past Context --(model)-> output --(command parse) -> commands --(docker, augments)-->results

# prompt blocks  

we will have a global prompt explaining how to use INT3RF4CE that is unchangeble.  

each user can write their own prompt blocks. and for each agent they can custom select any prompt blocks in any order. they will be appeneded together and passed in as the system prompt for apis, and appeneded before all context each turn for local models.  

we have three additional prompts we hard code used later: summarization prompt, auto-turn prompt, chat mode prompt.   

summarization prompt tells the model to summarize it's context when it gets too long. auto-turn prompt is for when a model ends a turn without any enviroment returns so it keeps working, chat mode prompt is to tell the model it is now just chatting with the user single turn based no computer use no tool call.  

# context

sidenote: context is purely activations and weights in a human brain. but for llms they are stored as external tokens. as they cannot continually learn for now.

context is made up of, in turn order: user message, assistant message (content + tool_calls), tool messages (one per call). repeated.

context folder format:

```
original.jsonl
working.jsonl
kv_cache.pt
```

original.jsonl is the full log on disk, never deleted (only appends). only used for post checking on what the agent did and later safety purposes.
working.jsonl is what the model actually sees and what is actually displayed on the frontend. it is always in ram in context.messages.
kv_cache.pt is only for local models.


## auto summary
when context hits ~30k words, model summarizes everything. in-memory context becomes "SUMMARIZED CONTEXT: ..." + last 5 messages. summary is assistant role (model wrote it). summary appended to original.jsonl (original keeps full history).

## screenshot elision
LOOK screenshots are base64 `image_url` parts inside working.jsonl, so old ones pile up fast. `context.marshal()` keeps only the newest 3 screenshots (marked by a `"[screenshot]"` text part); older ones are swapped for a text placeholder on the way to the API. elision is API-only — disk keeps every byte. user-attached images (no marker) are never elided.


## message format

**the canonical format IS the OpenAI chat-completions format.** there is no internal translation layer anymore — context storage, the agent loop, the WS payloads, and the frontend all speak it directly:

```json
{"role": "system", "content": "..."}
{"role": "user", "content": "..."}                              // or content parts when images present
{"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}
{"role": "assistant", "content": "...", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "TYPE", "arguments": "{\"text\": \"ls\"}"}}]}
{"role": "tool", "tool_call_id": "call_1", "name": "TYPE", "content": "ok"}
```

rules:
- `tool_calls` only on assistant messages; `function.arguments` is a STRINGIFIED json object (json.loads at dispatch).
- every `tool_calls` entry must be answered by a `role: "tool"` message with the same id, immediately following the assistant message. cancelled turns leave dangling calls — `repair()`/`close_dangling_tool_calls()` inserts `[interrupted]` placeholder tool messages in position before any API call.
- tool messages only accept string content, so a LOOK screenshot splits: tool message `"[image result]"` + a following user message with a `"[screenshot]"` text part and the image part.
- reasoning folds into the assistant content string as `[reasoning]\n...\n[/reasoning]\n<reply>`.
- old block-format contexts (tool_use/tool_result/image blocks) are archived to `working.legacy.jsonl` on load and the context starts fresh.

`context.marshal()` returns canonical messages. it injects a WORK_MSG user message when the last message is an assistant message with no `tool_calls`, so the API has a user message to respond to. injection is API-only — not stored in context or shown in frontend.


## adapters

adapters live in `INT3RF4CE/back/adapter.py` and are THIN — since the canonical format is already OpenAI-compatible, messages pass through verbatim:

```python
class Adapter(ABC):
    def api_tools(self) -> list[dict]: ...
    def to_api_payload(self, model, system_prompt, messages, use_tools) -> dict: ...
    def parse_api_response(self, data) -> dict: ...
```

- `api_tools()` wraps the shared COMMANDS in `{"type": "function", "function": {...}}` schemas.
- `to_api_payload()` prepends the system prompt and adds tools + per-provider reasoning params (`reasoning_effort` for kimi-k3, `thinking` toggle for deepseek).
- `parse_api_response()` returns the canonical assistant message dict (folding reasoning_content in as `[reasoning]...[/reasoning]`).

a future Claude adapter would be the first one that actually translates message shapes.

## tool-call architecture

the rest of the app (context, agent, UI) speaks canonical OpenAI messages; each model provider has an **adapter** that handles only provider-specific wire details (tool schema wrapping, reasoning params, response parsing).

this lets us:
- read working.jsonl and see literally what the API sees.
- add new providers by writing a new adapter, without touching the agent.
- later train our own model directly on the canonical format.


## commands

there will be four tiers of computer commands. 
first two are computer control:
essentials (assuming a very capable agi like model, just screenshots, mouse control and keyboard control)
helpers (commands to make models more efficient, terminal output, file commands)
third is for custom programs the models can use:
augments:(planning, chatting with other models, and note taking etc).   
fourth is robotics. not implemented yet.  

commands are shared tool definitions (`COMMANDS` in adapter.py). the active adapter wraps them into the provider's native tool schema. the model returns `tool_calls` in its response; our program executes each one and replies with `role: "tool"` messages.

every entry in `tool_calls` must be matched by a tool message with the same id. action commands return `"ok"`. perception commands (LOOK, TERM, READ) return their actual output. commands are the following (the command name is the function name):

mouse commands:

- MOVE x y (move cursor to position)
- LCLICK (left click at current position)
- RCLICK (right click at current position)
- LDOWN (push down left mouse)
- LUP (release left mouse)
- RDOWN
- RUP
- SCROLLUP
- SCROLLDOWN

keyboard commands:

- TYPE text (type string. literal characters can be as long or short as model want)
- KEY special_key + char . ' ' space as seperator (i.e. Return i.e. ctrl shift s ). uses X11 keysym names: Return, BackSpace, Tab, Escape, Delete, Up, Down, Left, Right, Home, End, Page_Up, Page_Down, etc.

perception commands:

- LOOK (takes a screenshot of the screen puts it into model input stream)
- TERM (copies latest terminal output as raw text puts it into model input stream)

special commands:

- WAIT (pauses the model thinking, perhaps to wait for external events)

auto-feedback: agent automatically adds TERM once after all keyboard commands (TYPE/KEY) and LOOK once after all mouse commands in a response. model doesn't need to explicitly request perception - it's always provided after actions complete.

file commands

handled directly by the agent via file I/O on the mounted workspace — these bypass the terminal entirely. they're tools like the rest, but executed host-side instead of being forwarded to xdotool/the container.

- `READ {file, start?, end?}` — view file with line numbers (optional 1-indexed range)
- `WRITE {file, content}` — overwrite whole file
- `EDIT {file, old, new, which}` — replace `which` ("0", "1", ..., or "all") occurrence

not strictly needed — model could use nano/vim via TYPE, but that requires expensive screenshot loops for every edit. maybe true AGI with streaming video will just use an editor directly.


# model

`model.py` defines the base `Model` class and a provider registry. subclasses (kimi.py, deepseek.py, etc.) declare:

- `name` — provider short name, e.g. `"kimi"`
- `adapter` — an `Adapter` instance for provider wire details
- `models` — `{display_name: provider_model_id}` for the UI selector
- `make(model_id, get_key)` — factory that returns a configured model instance

subclasses implement `call(prompt, messages, kv_cache, use_tools) -> (assistant_message, kv_cache)`. the returned `assistant_message` is the **canonical OpenAI assistant message** (content string + tool_calls). wired up: `kimi.py` (moonshot, k3) and `deepseek.py` (subclasses Kimi, text-only v4-pro). `HierarchyModel` (ordered fallback, timeout/429/5xx → next in chain) exists in model.py but is deliberately unregistered — the selector shows just k3 and v4-pro.

api keys come ONLY from the user's secrets store (secrets page) — no env/.env fallbacks. a user without a stored key can't create agents, and their saved agents are skipped at boot (logged) until they add the key.

selecting a model in the UI picks the matching provider class, which automatically selects the matching adapter.

everything below model level includes weights, activations, learning functions.


# agent

orchestrates model, context, and container. iterates `tool_calls` from the model's assistant message.
each turn ends with model outputing EOS or reaching max_tokens:

1: model reads context (via adapter) and outputs an assistant message (content + tool_calls)
2: output added to context as one assistant message (memory + original.jsonl)
3: agent iterates `tool_calls`, json.loads each `function.arguments`, dispatches by name
4: each call produces a matching `role: "tool"` message (action -> "ok", perception -> actual output; screenshots -> "[image result]" + a following "[screenshot]" user message)
5: auto-feedback: after keyboard commands without TERM, the last "ok" is replaced with TERM; after mouse commands without LOOK, the last "ok" is replaced with LOOK
6: tool results added to context
7: check for summarization, if needed summarize (replace in-memory with summary + last 5)

RL/value model integration goes here - reward signals after actions, value estimates for planning, etc. programs in container write value to /home/agent/ (workspace), agent reads from host side.  


# data folder structure  

```
/data/INT3RF4CE/usr_name
├── agents.json              # {agent_name: {"novnc_port": 6080, "model": "kimi-k3", "chat_mode": true}}
├── secrets.json             # {name: {"value", "cat"}} chmod 600 — THE single source of truth for api keys
├── compute.json             # [{"name", "ssh_command", "password"}] — claimable ssh targets
├── compute_usage.json       # {computer_name: agent_name} — who holds what
├── chat/                    # channels.json, readers.json, per-channel messages.jsonl + files/ tree
├── config/
│   ├── prompts/                  # system prompt
│   │   ├── global_prompt.md      # explain how to use INT3RF4CE. not editable but de-selectable.  
│   │   └── usr_prompt_1.md       # use defined task instructions / preferences.
│   ├── settings_files/           # named graph.json presets
│   └── specific/
│       └── {agent_name}/        # per-agent overrides on top of global
│           ├── graph.json       # thoughtgraph access {prompt_docs, read, write, time, folders}
│           └── secrets.json     # {"grants": [secret_name]}
├── context/
│   └── {agent_name}/
│       ├── original.jsonl   # full conversation log (never deleted)
│       ├── working.jsonl    # current working memory (loaded on startup)
│       └── kv_cache.pt      # cached key/values for local models
└── workspace/
    └── {agent_name}/        # mounted to /home/agent in container
        ├── term.log         # terminal output log
        ├── screenshots/
        │   └── screen.png   # latest screenshot
        └── ...              # agent's work files (code, projects, etc)
```

# tech stack

frontend: html/css/js. markdown-it. 
backend: python + fastapi
database: jsonl
sandboxing: docker


# UI description  

## theme
use the technoParadisal CSS in hub first before any additional css files.

## pages
agent view (noVNC + chat log), chat view (channels + per-channel file tree), secrets, compute. top-left button on every page goes back to the hub.

## layout (agent view):

left division: agent name input + create button, then the agent scrollbar. each row shows name, status, and a &#8942; menu button (rename/delete/settings).  
mid division: the noVNC screen (scaled to fit, not 1:1).  
right division: the chat log + model dropdown + text box. shift+enter for newline, enter sends — messages go DIRECTLY into the agent's context (not through chat channels); attachments ride base64 in the same WS message (25MB cap, text files inlined at 20k chars).


## docker save.  
saves the docker image so next time a agent gets created it uses the new image. DISABLED FOR NOW just a button dont implement.  

## prompt popup:

clicking the prompt button opens a popup with an exit button. the popup has three areas:  
- library (left): global prompt plus user-defined prompts. click a prompt to add it to the selected list and open the editor. user prompts have a small × delete button.  
- selected (middle): prompts currently used by this agent, in order. drag to reorder. click a user prompt to remove it. global prompt is always first and cannot be removed.  
- editor (right): textarea to edit the clicked user prompt.  

system prompts (auto_turn, chat_mode, summarization) are used automatically by the backend and are not shown or selectable.  

## chatmode:  

when i press chatmode, stop the command parser. add the chat mode prompt after global prompt, stop auto prompting after each agent turn. 

## model select popup:  
kimi k3 / deepseek v4 pro. (hierarchy fallback chain exists but is unregistered.)


# future things to add:  

configs for ssh keys / account names?  
more customization (multi docker images, context save load, workspace save load, custom summarization prompt) 

augments: todo, chat.  

workflows:    
workflows are like todo app templates   
1: fresh context to test the app like a user, to completion, report problems  
2: write report of everything it did

maybe need a software dev workflow, and a scientific method workflow lol

## docker slinging

need gpu compute nodes. slingn this docker on their. 



## file upload/download (channels)

chat channels have a real per-channel file tree (`files/` with nested folders, 100GB per-file cap, NO extension blocklist). a channel is `{id, name, members}`; membership is the whole ACL. every agent gets a DM channel with you (`dm-{agent}`) on creation. the chat view has a lazy-loaded file-tree panel: upload files/folders (paths preserved), mkdir, rename, delete, drag-drop — all over REST (`files-list`, `mkdir`, `PUT`/`DELETE .../files/{path}`, download via `GET .../files/{path}`).

**me -> model**: two paths. chat view uploads go into the channel store as file messages, delivered on the agent's NEXT turn via the injection cursor (images become image parts for that one turn, text-like files inline capped at 20k chars — bytes never persist in context). agent-view attachments skip channels entirely: base64 in the WS chat message straight into context (25MB cap).

**model -> me**: the LLM calls `CHAT_FILE_UPLOAD channel source=path text="..."` (path confined to its own workspace, caption required) — the server copies the bytes into the channel tree and broadcasts the message. `CHAT_FILE_DOWNLOAD channel file=path [dest]` pulls channel files into its workspace. `CHAT_READ channel [limit]` reads back history. group channels: create with `create_channel` (WS) naming member agents — agent-to-agent messages flow through the same injection.

**safety model**: channels are the only agent<->user file path, every send is an explicit visible tool call or UI action, files are inert bytes in a per-channel store, membership gates agent-to-agent, uploads are auth'd, downloads path-confined. docker file transfer is out of scope — use github/ssh for that.

## compute manager

named ssh targets the user registers on the compute page (`compute.json` + `compute_usage.json`, both chmod 600). agents claim them with `USE_COMPUTER` (full ssh command + password in the tool result), list with `SEE_COMPUTERS` (redacted for machines held by others), free with `RELEASE_COMPUTER`. one holder per machine; the human claims under their own username and can force-release anything. every mutation broadcasts the fresh list to all of the user's sessions; deleting an agent auto-releases its claims. no locking — the exact-same-instant double-claim race is accepted. the "compute rent" section on the page is a placeholder for a future auto-rent feature.
