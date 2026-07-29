# reading order

foundations -> apps -> glue -> frontends -> tests. css excluded.

0. orientation
- fab/README.md, fab/DOC.md

1. hub (the shell everything mounts into)
- hub/back/app.py  (FastAPI root, shows how everything mounts)
- hub/auth/store.py -> hub/auth/routes.py  (users/sessions)
- hub/front/index.html  (the hub page)
- hub/components/AuthBox/AuthBox.js -> TechnoParadisalComponents.js  (shared UI kit)
- hub/components/MarkdownEditor/MarkdownEditor.js (+ markdown-it-katex.js skim)  (used by TH0UGHTGR4PH)
- rest of components (2dDraw, 3dDraw, LinePlot, Surface3D, VectorEditor): skim only, they belong to mind/'s pages

2. TH0UGHTGR4PH (simpler app, read first)
- back/config.py -> back/storage.py  (where the JSON lives)
- back/placement.py -> back/graph_actions.py  (the operations)
- back/api.py  (HTTP surface tying it together)
- front/index.html -> front/store.js  (client state)
- front/nodes.js -> front/edges.js -> front/board.js  (rendering & interaction)
- front/ctxpanel.js  (agent-settings sidebar, bridge to INT3RF4CE)

3. INT3RF4CE (the agent app)
- back/config.py
- back/adapter.py  (internal message standard + tool defs; read carefully, everything speaks this)
- back/models/kimi.py -> back/models/glm.py -> back/model.py  (providers + fallback hierarchy)
- back/context.py  (jsonl context + auto-summarize)
- back/prompt.py  (how system prompt + graph docs assemble)
- back/container.py  (docker lifecycle)
- back/agent.py  (main loop, access enforcement lives here)
- back/server.py  (WebSocket API tying it together)
- front/index.html -> front/app.js

4. verification
- TH0UGHTGR4PH/tests/headless_test.py  (doubles as executable documentation of the API)

core-only path: app.py, TH0UGHTGR4PH back (config -> storage -> graph_actions -> api), adapter.py, context.py, agent.py, server.py


# TH0UGHTGR4PH 


# data types  

folder and .md files mirror actual structure as stored.  

meta.json:
all placements, functions, connections, node types, color hexes. 
{

}







# function flows:  
