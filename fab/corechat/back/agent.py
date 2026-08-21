'''agent: the core loop. add input -> compress if needed -> model -> execute tools -> repeat until the model stops calling tools.'''

from fab.config import MAX_WORDS
from fab.corechat.back import commands, context, prompt
from fab.corechat.back.models import kimi


async def turn(agent: str, user_text: str | None = None) -> list:
    '''run one turn to completion; returns the messages added during it.'''
    ctx = context.load(agent)
    start = len(ctx["messages"])
    if user_text:
        context.add(ctx, "user", user_text)
    while True:
        if context.word_count(ctx["messages"]) >= MAX_WORDS:
            context.compress(ctx, await kimi.summarize(context.marshal(ctx)))
        reply = await kimi.call(prompt.SYSTEM, context.marshal(ctx), tools=commands.schemas())
        context.add(ctx, "assistant", reply.get("content"),
                    **{k: v for k, v in reply.items() if k not in ("role", "content")})
        calls = reply.get("tool_calls") or []
        if not calls:
            break
        for tc in calls:
            result = await commands.dispatch(tc["function"]["name"], tc["function"].get("arguments", ""))
            context.add(ctx, "tool", result, tool_call_id=tc["id"], name=tc["function"]["name"])
    return ctx["messages"][start:]
