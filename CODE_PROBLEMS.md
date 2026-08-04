# Code Problems — FAB Codebase

## Fixed

### 1. `agent.py:107-108` — Duplicate line
```python
allowed = self.CHAT_MODE_TOOLS if self.chat_mode else None
allowed = self.CHAT_MODE_TOOLS if self.chat_mode else None
```
Duplicate copy-paste line. Fixed by removing the duplicate.

### 2. `server.py:776` — No DM channel after agent rename
`chatmod.ensure_dm(user, new_name)` was never called after rename. The agent had no DM channel with the user after being renamed. Also the old name wasn't cleaned from channel member lists. Fixed by adding `remove_agent_everywhere` + `ensure_dm` in the rename handler.

### 4. `app.py:89-90` — Content-Length header crashes on junk
```python
if content_length and int(content_length) > MAX_BODY_BYTES:
```
Non-numeric Content-Length (e.g. `"abc"`) crashes with ValueError (500). Fixed by wrapping in try/except and returning 400.

---

## Open

### 5. `storage.py:272-284` — `restore_version` destroys current board without snapshotting
Restoring a version wipes current state. Inconsistent with upload (which snapshots first). Frontend popup needed: "restoring destroys current unsaved changes." Also consider auto-snapshotting before restore.

### 6. `storage.py:258` — `save_version` crashes on non-standard version dirs
```python
nums = [int(n.split("_")[1]) for n in list_versions(user, board_id)]
```
If a manually-created directory like `version_corrupted` exists in `versions/`, `int("corrupted")` crashes.

### 7. `graph_actions.py:301-314` — `gmap` scope computation is O(n^2)
Finding children iterates ALL nodes per node. Not a problem for typical small graphs but O(n^2) on large boards.

### 8. `routes.py:20-26` — `_rate_limited` iterates ALL entries on every auth request
```python
for k in list(_attempts):
    _attempts[k] = [t for t in _attempts[k] if now - t < ATTEMPT_WINDOW]
```
Recreates every list even for untouched keys. The dict grows unbounded (never dropped, only pruned lazily). Could be done per-key on access instead.

### 9. `server.py:625-636` — `docker_start` command doesn't update agent.chat_mode
User's docker_start starts the container but the agent stays in chat_mode=True, so its tools remain `CHAT_MODE_TOOLS`. User says this is intentional (want docker without agent interfering) but worth confirming.

### 10. `server.py:634` — `docker_start` blocks a thread in `container.start()`
`asyncio.to_thread(agent.container.start)` can block for minutes (Docker build, waiting for xvfb/xterm). Multiple concurrent users could exhaust the default thread pool. Consider a semaphore or dedicated executor.

### 11. `storage.py:150-162` — `content_path` loops forever on cyclic parent data
Unlike `in_scope` in agent.py (which has a `seen` set), `content_path` has no cycle detection. If corrupted/legacy data has parent cycles, it infinite-loops.

### 12. `agent.py:590-596` — `_workspace_path` TOCTOU race
Path resolved/validated, then accessed later. Symlink swap between check and use could escape workspace. Low risk since only the agent controls its own workspace files.

### 13. `chat.py:178-188` — `store_file` reads full 500MB into memory
`data: bytes` receives the entire file. `MAX_FILE_BYTES = 500MB` means a single file near the limit allocates 500MB of RAM.

### 14. `adapter.py:295` — `json.loads` on model tool-call arguments can crash
Malformed JSON from the model crashes with unhandled `JSONDecodeError`.

### 15. `container.py:178-193` — `start()` infinite loops with no timeout
If xvfb or xterm never start, the `while True` loops hang the thread permanently. No timeout.

### 16. `storage.py:150-162` — `content_path` unbounded depth
No guard against deeply nested folders creating path names exceeding OS limits.

### 17. `server.py:307` — `load_agents` sets `working=False` for all agents on restart
Agents that were in work mode before restart won't resume. While `container_on` is restored via `is_container_running`, the work loop doesn't restart.

### 18. Import-inside-function violations (AGENTS.md style rule)
- `app.py:113`: `from fastapi.responses import HTMLResponse` inside `hub_index`
- `server.py:101`: `from fab.INT3RF4CE.back.context import Context` inside `_block_for_file`
- `agent.py:528`: `from fab.INT3RF4CE.back import chat as chatmod` inside `_chat_dispatch`

### 19. `storage.py:88-92` — `list_boards` returns ALL directories
Any non-board directory inside the user dir shows up as a board. No validation that it contains `meta.json`.

### 20. `graph_actions.py:226-231` — Move-to-own-subtree guard exists but no load-time validation
Parent cycle detection is enforced on write but nothing validates existing data on load.

### 21. `container.py:133-141` — `_cleanup_all_containers` nukes all agents
When rebuilding, the filter `ancestor={self.image}` matches ALL containers using the shared image. User says this is fine (everything uses same docker).

### 22. `restore_version` — no confirmation popup in frontend
Version restore destroys current unsaved board state without warning. Need a popup: "restoring destroys current unsaved changes."

### 23. CHAT_SEND agent tool reads arbitrary workspace file fully into memory (agent.py:538)
`p.read_bytes()` loads the entire file. With files up to 500MB, this can spike memory.
