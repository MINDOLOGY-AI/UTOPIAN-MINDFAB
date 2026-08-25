'''commands: the tool registry. one entry per tool — name, openai function schema, handler.
schemas() feeds the api payload, dispatch() runs a tool_call. tools self-register from their own modules.'''

import json

COMMANDS = {}  # name -> {"schema": dict, "handler": async fn(args) -> str}


def register(name: str, schema: dict, handler):
    COMMANDS[name] = {"schema": schema, "handler": handler}


def schemas() -> list:
    return [c["schema"] for c in COMMANDS.values()]


async def dispatch(name: str, arguments: str) -> str:
    # a bad call becomes an error tool result, never a crashed loop
    cmd = COMMANDS.get(name)
    if not cmd:
        return f"[ERROR] unknown command {name}"
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        return f"[ERROR] bad arguments json: {e}"
    try:
        return await cmd["handler"](args)
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


# tool modules register themselves on import
from fab.corechat.oldback import test_tool  # noqa: E402,F401
