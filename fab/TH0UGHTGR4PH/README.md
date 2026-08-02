# TH0UGHTGR4PH

this is just the visual display and api control for a folder with .md files and a graph.json.  

the fab view: one 2D board where Objs (typed rectangles), Funcs (typed circles), and folders live, connected by plain white edges. INT3RF4CE agents are obj nodes — an agent connected into a func node is the doer of that function. models operate the board through graph-action commands (GCREATE/GREAD/GUPDATE/GDESTROY/GMOVE/GLINK/GUNLINK/GLIST).

# layout

- nodes have types (user-extendable, color-coded): obj types (axiom, definition, theory, evidence, hypothesis, algorithm, weights, dataset, benchmark, actuator, world_state, aesthetics, feature_doc, doc, prompt, agent) and func types (support, reject, inference, training, calculating, use).
- edges are just white lines with arrowheads. no types, no colors.
- objs have time states: todo / doing / done.
- agents are created and configured on the board (settings popup per agent node: model, prompts, computer). double-click an agent node to teleport into /INT3RF4CE/?agent=name for chatting.
- workflows = saved node groups (incl. agent settings) re-insertable into the same board.
- autoplacement only applies to model-created nodes; user placement is always kept.

# data

per-user JSON in `fab/data/F4B/{user}/`: types.json, templates.json, and one folder per board (meta.json + content/ + versions/).

# serving

mounted in `fab/hub/back/app.py` at `/F4B/`. auth via hub session cookie.

# tests

`venv/bin/python -m fab.F4B.tests.headless_test` — agent-POV graph actions + REST/auth isolation. boots a throwaway server on port 2999, cleans up after itself.
