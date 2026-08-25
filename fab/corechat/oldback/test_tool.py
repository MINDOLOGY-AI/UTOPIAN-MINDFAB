'''TEST: echo tool to prove the registry works end to end.'''

from fab.corechat.oldback.commands import register

SCHEMA = {
    "name": "TEST",
    "description": "echo test tool — returns the string it received",
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "any string"}},
        "required": ["text"],
    },
}


async def handler(args: dict) -> str:
    return f"str received: {args['text']}"


register("TEST", SCHEMA, handler)
