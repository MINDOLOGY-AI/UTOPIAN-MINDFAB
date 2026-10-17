# UTOPIAN-MINDFAB

the harness and website of MINDOLOGY AI, live at [mindologyai.com](https://mindologyai.com).

by utopians, *for* utopians. our focus is understanding the mind, and fabbing (producing) the mind (primy, silicon agi) that will help steer the world towards utopia. mind is also what the Culture series calls its ASIs.

all code, weights, docs here should be sacred: correct, compressed, understood. vibecoding without understanding is not allowed — a good test is whether you could rewrite it from scratch yourself. the worst code is the unwritten one.

the ML research (synapse, datasteps, evoke, interpviz, primy, SlabConeSAEs) lives in the separate mindology repo.

# structure

```
fab/              ai harness — computer use, graph memory, chat. see fab/README.md, fab/DOC.md
  corechat/       agent loop, model adapters (kimi, deepseek), context compression
  dockeruse/      agent sandboxes: docker + xvfb + noVNC desktop, bash/read/write/edit tools
  thoughtgraph/   graph memory as a plain folder of markdown, canvas editor
  wiresend/       chat channels + file sharing between users and agents
  workflow/       (empty)
hub/              the website: fastapi app that mounts every fab module, auth, landing page
  back/           app.py (entry), auth.py (users, sessions, rate limits)
  front/          html/css/js, TechnoParadisal.css, web components
  test/           pytest per module + e2e
writing/          essays (gitignored, WIP)
```

all runtime data lives in `~/.fab/`: `auth/`, `logs/`, and `users/{user}/{module}/`.

# run

```bash
# .env at repo root: MOONSHOT_API_KEY, DEEPSEEK_API_KEY, OPENROUTER_API_KEY
python -m venv venv && venv/bin/pip install -r requirements.txt
bash fab/dockeruse/build_docker.sh     # builds the fab_sandbox image, ~10 GB, run in tmux
venv/bin/python -m hub.back.app        # http://localhost:2121
venv/bin/pytest hub/test
```

# deploy

AWS ap-northeast-1, m7i.xlarge, Ubuntu 26.04, repo at `~/UTOPIAN-MINDFAB`.

- `fab.service` (systemd) runs uvicorn on `127.0.0.1:2121`, restarts on crash and boot
- caddy (`/etc/caddy/Caddyfile`) serves mindologyai.com with auto HTTPS, redirects www

update: `ssh -A ubuntu@<ip>`, then `cd ~/UTOPIAN-MINDFAB && git pull && sudo systemctl restart fab`.
