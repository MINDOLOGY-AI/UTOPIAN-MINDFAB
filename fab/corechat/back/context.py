'''context: the conversation state and every step that transforms it.

context format in fab/README.md

working.jsonl
'''

import json

from fab.config import FAB_DIR, MAX_WORDS, PRESERVE_LAST
from fab.corechat.back.prompt import REPAIR_NOTE, WORK_MSG

DATA_DIR = FAB_DIR / "corechat"


def load(agent: str) -> dict:
    folder = DATA_DIR / agent
    folder.mkdir(parents=True, exist_ok=True)
    working = folder / "working.jsonl"
    working.touch(exist_ok=True)
    messages = [json.loads(l) for l in working.read_text().splitlines() if l.strip()]
    return {"agent": agent, "folder": folder, "messages": messages}


def add(ctx: dict, role: str, content=None, **extra) -> dict:
    msg = {"role": role, **extra}
    if content is not None:
        msg["content"] = content
    ctx["messages"].append(msg)
    line = json.dumps(msg) + "\n"
    with open(ctx["folder"] / "working.jsonl", "a") as f:
        f.write(line)
    return msg


def _persist(ctx: dict):
    (ctx["folder"] / "working.jsonl").write_text("".join(json.dumps(m) + "\n" for m in ctx["messages"]))


def repair(ctx: dict):
    # fill placeholder results for tool_calls left unanswered by a killed turn — providers reject dangling calls
    msgs = ctx["messages"]
    repaired = False
    i = 0
    while i < len(msgs):
        tcs = msgs[i].get("tool_calls") if msgs[i].get("role") == "assistant" else None
        if not tcs:
            i += 1
            continue
        have = set()
        j = i + 1
        while j < len(msgs) and msgs[j].get("role") == "tool":
            have.add(msgs[j].get("tool_call_id"))
            j += 1
        missing = [tc for tc in tcs if tc.get("id") not in have]
        for k, tc in enumerate(missing):
            msgs.insert(j + k, {"role": "tool", "tool_call_id": tc["id"],
                                "name": tc.get("function", {}).get("name", "unknown"),
                                "content": REPAIR_NOTE})
        repaired |= bool(missing)
        i = j + len(missing)
    if repaired:
        _persist(ctx)


def marshal(ctx: dict) -> list:
    '''api-ready messages: WORK_MSG injected when the model must respond to its own bare
    assistant message. stored messages are already in wire shape — nothing else to strip.'''
    repair(ctx)
    out = list(ctx["messages"])  # copy the list so the WORK_MSG append doesn't touch ctx
    if out and out[-1].get("role") == "assistant" and not out[-1].get("tool_calls"):
        out.append({"role": "user", "content": f"[SYSTEM]\n{WORK_MSG}"})
    return out


def word_count(messages: list) -> int:
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c.split())
        elif isinstance(c, list):
            n += sum(len(p.get("text", "").split()) if p.get("type") == "text" else 1000 for p in c)
        n += len(m.get("reasoning_content", "").split())
        for tc in m.get("tool_calls") or []:
            n += len(tc.get("function", {}).get("arguments", "").split())
    return n


def compress(ctx: dict, summary: str):
    # replace everything before the last PRESERVE_LAST messages with the summary
    msgs = ctx["messages"]
    if len(msgs) <= PRESERVE_LAST:
        return
    start = len(msgs) - PRESERVE_LAST
    # never let the preserved tail open on a bare tool message — walk back to its assistant
    while start > 0 and msgs[start].get("role") == "tool":
        start -= 1
    summary_msg = {"role": "assistant", "content": f"SUMMARIZED CONTEXT: {summary}"}
    rebuilt = [summary_msg]
    if msgs[start].get("role") == "assistant":
        rebuilt.append({"role": "user", "content": "[continue]"})
    ctx["messages"] = rebuilt + msgs[start:]
    _persist(ctx)
