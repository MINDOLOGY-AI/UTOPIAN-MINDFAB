# AGENTS.md — for all agents, biological or digital

# do not code

- DO NOT CODE or change files unless i tell you to. a question about code is never a request to change code. if my prompt ends with a question, i'm asking something — answer it.
- "check if my code is correct" = answer, don't write tests. "discuss" = discuss.
- NEVER delete my comments or docstrings when editing.
- never edit a .md file unless i explicitly ask.
- NEVER start or stop big scripts (training, downloads, builds). ask before running anything heavy. temp test scripts are fine.
- never make your own venv or install anything — use the root venv, tell me if something's missing.
- never host servers or run one on my port. only start a server to test code, then close it (isolated docker like INT3RF4CE excepted).
- when discussing ideas: concise, ~1000 word limit.

# code quality

- code is sacred: quality > dev speed, zero tech debt, as simple as possible.
- within ~10% of theoretical optimal speed. no major performance mistakes (e.g. converting native data formats to python objects).
- DRY: import from this monorepo instead of rewriting (ML code imports SYN4P5E algorithms/utils/probes; physicsim imports symbolcore).
- break code into separate files and functions.
- the only complexity in this codebase should be the models themselves. frontend and backend stay as simple as possible.

# tech stack

- ML and backend: python, pytorch, fastapi, sqlite, textual.
- frontend: pure html/css/js, no frameworks. situational: c++, verilog.

# python

- everything runs from root as modules: use `Path.cwd()` for paths, import from root.
- comments: `#` for short, `'''` only for long header comments.
- config files over CLI options.
- comment tensor shapes always.
- no defensive try/except imports. just import.

# frontend

- always import /hub/front/ (TechnoParadisal.css). absolute imports starting with /.
- reusable + complicated UI → web components in the components folder. never react.
- website = a visual interface to the programs in this repo (viz, software, readings). convey the real research, nothing else:
  - don't put it in the website if you don't have to
  - if you have to, prefer a component (graph, table) over text
  - if you need text, use text — no decorative headers, footers, lights, or symbols
