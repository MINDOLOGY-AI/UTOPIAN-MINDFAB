'''commands: the tool registry. schemas are registered wire-ready (full api envelope) so providers
get them as-is; any translation is the modelserver's job. explicit registrations at the bottom.'''

import asyncio
import json

from fab.corechat.back.websocket import broadcast

COMMANDS = {}  # name -> {"schema": wire-ready api schema, "handler": async fn(args: dict, agent) -> str}


def register(name: str, schema: dict, handler):
    COMMANDS[name] = {"schema": schema, "handler": handler}


# the wire-ready envelope every tool registers with — the one place its shape is written
def schema(name: str, description: str, properties: dict, required: list | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []}}}


# takes the agent and a raw tool_call, returns the finished tool message
# a bad call becomes an error tool result, never a crashed turn — the model reads it and retries
async def dispatch(agent, tc: dict) -> dict:
    name = tc["function"]["name"]
    cmd = COMMANDS.get(name)
    if not cmd:
        result = f"[ERROR] unknown command {name}"
    else:
        try:
            args = json.loads(tc["function"].get("arguments") or "{}")
        except json.JSONDecodeError as e:
            result = f"[ERROR] bad arguments json: {e}"
        else:
            try:
                result = await cmd["handler"](args, agent)
            except Exception as e:
                result = f"[ERROR] {type(e).__name__}: {e}"
    return {"role": "tool", "tool_call_id": tc["id"], "name": name, "content": result}


_TEXT = {"type": "string", "description": "any string"}


# TEST: echo tool to prove the registry works end to end
async def _test(args: dict, agent) -> str:
    return f"str received: {args['text']}"

register("TEST", schema("TEST", "echo test tool — returns the string it received",
    {"text": _TEXT}, ["text"]), _test)


# TEST_SLOW: same echo, but the real result deposits 3s later as a user message
async def _test_slow(args: dict, agent) -> str:
    async def work():
        await asyncio.sleep(3)
        agent.deposit("TEST_SLOW", f"str received: {args['text']}")
    asyncio.create_task(work())
    return "[TEST_SLOW running] the real result will arrive as a message"

register("TEST_SLOW", schema("TEST_SLOW",
    "slow echo test tool — returns a placeholder now, deposits the real echo as a message a few seconds later",
    {"text": _TEXT}, ["text"]), _test_slow)


# WAIT: the turn itself sleeps on the wake event — ends on timeout, early on new input, dead on cancel
async def _wait(args: dict, agent) -> str:
    seconds = args["seconds"]
    broadcast({"type": "status", "name": agent.name, "waiting": seconds}, user=agent.user)
    try:
        await asyncio.wait_for(agent.wake.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        result = f"waited {seconds}s"
    else:
        result = "wait interrupted — new input arrived"
    broadcast({"type": "status", "name": agent.name, "waiting": False}, user=agent.user)
    return result

register("WAIT", schema("WAIT", "wait for N seconds before continuing; ends early if new input arrives",
    {"seconds": {"type": "integer", "description": "seconds to wait"}}, ["seconds"]), _wait)


# STOP: the model's own exit from agent mode — parks itself, only the user can resume it
async def _stop(args: dict, agent) -> str:
    agent.agent_mode = False
    broadcast({"type": "agents_changed"}, user=agent.user)
    return "you stopped yourself. only the user can resume you, with the run button."

register("STOP", schema("STOP",
    "stop working and park yourself. ONLY call this when the task AND its verification are completely done — you cannot restart yourself, only the user can resume you",
    {}), _stop)


# plugin tools self-register on import (kept last: they import register from this module)
from fab.thoughtgraph.back import tools as _thoughtgraph_tools
from fab.dockeruse.back import tools as _dockeruse_tools
from fab.wiresend.back import tools as _wiresend_tools
