# intvrface

wrapper for AI models to interact with the world. computer control, UI for human interaction and monitoring, potential robot control

## ~/intvrface/ folder structure

```
~/intvrface/
├── agents.json              # [{"name": "agent_1", "novnc_port": 6080}, ...]
├── docker_build/
│   └── Dockerfile           # generated dockerfile for sandbox image
├── config/
│   ├── global/                  # shared across all agents
│   │   ├── identities.json      # [{"name", "git_user", "git_email", "ssh_key"}, ...] — git/github identities
│   │   ├── ssh_keys/            # actual private + .pub key files, referenced by identities.json
│   │   ├── secrets.json         # api keys (claude, etc) — gitignored
│   │   ├── global_prompt.md     # additional system prompt concatenated to hardcoded program prompt
│   │   └── defaults.json        # baseline config applied to every new agent
│   └── specific/
│       └── {agent_name}/        # per-agent overrides on top of global
│           ├── identity.json    # picks which global identity by name
│           ├── prompt.md        # overrides global default prompt
│           └── overrides.json   # any other per-agent settings
├── context/
│   └── {agent_name}/
│       ├── original.jsonl   # full conversation log (never deleted)
│       ├── working.jsonl    # current working memory (loaded on startup)
│       ├── kv_cache.pt      # cached key/values for local models
│       └── user_prompt.json # persistent task prompt (injected into system prompt every turn)
└── workspace/
    └── {agent_name}/        # mounted to /home/agent in container
        ├── term.log         # terminal output log
        ├── screenshots/
        │   └── screen.png   # latest screenshot
        └── ...              # agent's work files (code, projects, etc)
```

## configs

preset accounts, workflows, and custom prompts for agents.

### git

setup so far:
- github org: `MINDOLOGY-AI`
- bot account: `intvrfaceBot` (org member, write access)
- branch protection on `main`: bot blocked from direct push, must use feature branch + PR

per-identity setup:
- generate ssh keypair, register public half on the matching github account, store both in `config/global/ssh_keys/`
- on container start, host mounts the private key in + sets git user/email
- agent never sees the setup; `git push` just works as that identity

primy (see the primy repo) will use this. since the model can only modify weights and do IO it needs a bridge with the world.

we assume model is AGI level and use computers like a human. so no specialized MCPs or web navigators.

runs in docker + xvfb for sandboxing.

overall structure:

model -> (output) -> context -> agent -> (interpreted actions) -> enviroment
model <- (in-memory messages + kv cache) <- context <- agent <- (LOOK/TERM) <- enviroment

## commands (Claude tool-use)

there will be two tiers of commands. essentials (assuming a very capable agi like model, just screenshots, mouse control and keyboard control, cross agent chatting) and extras (commands to make models more efficient, terminal output, file commands, planning  and note taking etc). a model can always use both types.  

commands are exposed as Claude API tools. each command is a tool with a typed JSON schema, sent via the `tools=[...]` parameter. the model returns `tool_use` content blocks (validated by the API) instead of free-form text. agent dispatches each `tool_use` to the container.

every `tool_use` in an assistant message must be matched by a `tool_result` block (same `tool_use_id`) at the start of the next user message. action commands return `"ok"`. perception commands (LOOK, TERM, READ) return their actual output. commands are the following:

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

CUA models such as in the CUALDO repo will just view screen as streaming video and have their weights directly decoded as keystrokes and mouse moves if so we interpret those model numerical outputs with agent as the intvrface still into the computer.


## file commands

handled directly by the agent via file I/O on the mounted workspace — these bypass the terminal entirely. they're tools like the rest, but executed host-side instead of being forwarded to xdotool/the container.

- `READ {file, start?, end?}` — view file with line numbers (optional 1-indexed range)
- `WRITE {file, content}` — overwrite whole file
- `EDIT {file, old, new, which}` — replace `which` ("0", "1", ..., or "all") occurrence

not strictly needed — model could use nano/vim via TYPE, but that requires expensive screenshot loops for every edit. maybe true AGI with streaming video will just use an editor directly.

## model

model.py defines base Model class. subclasses (claude.py, llama.py, etc) implement `call(messages, kv_cache) -> (response_text, kv_cache)`. messages are in Claude API format - claude.py uses directly, other models convert as needed.

everything below model level includes weights, activations, learning functions.

## context (for token-limited models)

in a human brain, all memory is stored as activations (neuron depoloarization levels) and weights (neuron synaptic connection strength). however in a llm memory is stored as either past kv cache or tokens. maybe true AGI would also have memory be model level rather than context level. but for llm we manage context like this:

context:
- context.messages — in memory list, loaded from original.jsonl on init
- original.jsonl — full log on disk, never deleted (only appends)

when context hits ~30k words, model summarizes everything. in-memory context becomes "SUMMARIZED CONTEXT: ..." + last 5 messages. summary is assistant role (model wrote it). summary appended to original.jsonl (original keeps full history).

context folder format:

```
original.jsonl
working.jsonl
kv_cache.pt
user_prompt.json
```

`user_prompt.json` stores `{"user_prompt": "..."}` — a persistent task description set by the human via the frontend. injected into the system prompt every turn via `context.get_prompt()` so the model never loses track of the task, even after summarization.

storage IS the Claude API format — only two roles, `user` and `assistant`. content is a list of blocks (text / tool_use / tool_result / image). frontend distinguishes rows by block type, not by role.

- **user** — human chat messages (text) AND container feedback (tool_result blocks for each tool_use the model emitted last turn)
- **assistant** — model thinking (text) + commands (tool_use blocks) interleaved in any order

jsonl format:

```json
{"role": "user", "content": [{"type": "text", "text": "complete this task"}]}
{"role": "assistant", "content": [
  {"type": "text", "text": "ok i'll cd to Desktop."},
  {"type": "tool_use", "id": "toolu_01ABC", "name": "TYPE", "input": {"text": "cd ~/Desktop"}},
  {"type": "tool_use", "id": "toolu_01DEF", "name": "KEY",  "input": {"keys": ["Return"]}}
]}
{"role": "user", "content": [
  {"type": "tool_result", "tool_use_id": "toolu_01ABC", "content": "ok"},
  {"type": "tool_result", "tool_use_id": "toolu_01DEF", "content": "[TERM]\n~/Desktop"}
]}
```

images are base64 inline (PNG only). a LOOK tool_result has `content` as a list with an image block.

`context.marshal()` is now nearly identity — messages are already API-shaped. it only injects WORK_MSG (as a user text block) when the last message is assistant with no `tool_use` blocks (pure-text turn) so the API has a user message to respond to. injection is API-only — not stored in context or shown in frontend.

streaming context gets trimmed when summary limit is reached. original context only adds, never deletes.

## prompt  

prompts are always in the model call api each message before the context  

there are two prompt situations.  

in summarization, just use the hard coded summarization_prompt  

in normal we use the hardcoded system prompt with specific configs appened to it.  




## memory

NOT IMPLEMENTED YET

this is long term memory whereas context is working memory. in a human brain or AGI this would be weight change through online learning. in a current frozen weight LLM this could simply be file edits of a memory documents maybe in a folder strucutre it can read and write from.  
perhaps this could be useful in thoughtgraph the app? or just more useful for talking to users in general. where the idea is the model learns about the user through each conversation and project and gets a compprehensive view of the user. and for thoughtgraph it's more explicit like the user can visually see the thoughts being gathered and how they relate to each other. so maybe the memory would be in a relational database that can be nicely displayed.  

## agent

orchestrates model, context, and container. iterates `tool_use` blocks from the model's content list.
each turn ends with model outputing EOS or reaching max_tokens:

1: model reads context and outputs (text + tool_use blocks)
2: output added to context as one assistant message (memory + original.jsonl)
3: agent iterates tool_use blocks, dispatches each to container
4: each tool_use produces a matching tool_result (action -> "ok", perception -> actual output)
5: auto-feedback: if any input action ran AND the last tool wasn't perception, the last "ok" tool_result is replaced with TERM (if xterm focused) or LOOK (otherwise)
6: tool_results added to context as one user message
7: check for summarization, if needed summarize (replace in-memory with summary + last 5)

RL/value model integration goes here - reward signals after actions, value estimates for planning, etc. programs in container write value to /home/agent/ (workspace), agent reads from host side.  

## data storage

all agent data stored in `~/intvrface/` (see folder structure at top)

## frontend  

we can create, start, stop, and delete agents. each come with a docker.  

we view each agent in the following layout (cycle between them with arrow keys):  
screen viewing and control with noVNC    
original context on the right side (scrollable)  
type box on the bottom (type to model)  
start/stop button on button right.

## configs  

we want to preset some accounts and workflows and also add custom prompts  

git:  






## tech stack

frontend: html/css/js
backend: python + fastapi
database: jsonl
sandboxing: docker

## Test Prompts

### Interactive Brain Map

```
build me an interactive website that visualizes the human brain.

step 1: research first. open chromium and search for information about brain regions, their functions, neurotransmitter systems, neuron types, and signal speeds. look at multiple sources. take your time reading — don't rush this. save your research notes to /home/agent/notes.md as you go.

step 2: plan the site. based on your research, write a brief plan in /home/agent/plan.md — what regions you'll include, what data each region shows, and how the interaction will work.

step 3: build it. create an interactive single-page website at /home/agent/brain/index.html using HTML/CSS/JS (no frameworks). it should have:
- a visual map/diagram of the brain with clickable regions (prefrontal cortex, hippocampus, amygdala, cerebellum, brainstem, visual cortex, motor cortex, etc.)
- when you click a region, show a detail panel with: main functions, primary neurotransmitters, dominant neuron types, signal propagation speed, and a fun fact
- make it visually striking — dark background, glowing regions, smooth animations
- all data should come from your actual research, not guesses

step 4: test it visually. serve the site with `python3 -m http.server 8080 -d /home/agent/brain &` and open it in chromium at localhost:8080. click through every region. check that the layout looks good, text is readable, animations work, and all regions are clickable.

step 5: polish. based on what you see, fix any visual issues — colors that clash, text that overflows, regions that are hard to click, animations that feel off. make at least 3 specific improvements based on your visual inspection. test again after each change.
```

