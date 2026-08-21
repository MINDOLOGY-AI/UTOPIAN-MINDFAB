'''adapter: canonical messages <-> openai-compatible wire format.
the wire format IS the canonical format — this only wraps tool schemas.'''

MAX_TOKENS = 8192


def build_payload(model: str, system: str | None, messages: list, tools: list | None = None) -> dict:
    payload = {"model": model, "messages": [], "max_tokens": MAX_TOKENS}
    if system:
        payload["messages"].append({"role": "system", "content": system})
    payload["messages"].extend(messages)
    if tools:
        payload["tools"] = [{"type": "function", "function": s} for s in tools]
    return payload


def parse_response(data: dict) -> dict:
    # keep the provider's shape verbatim: reasoning_content is its own field, never folded into content
    msg = data["choices"][0]["message"]
    out = {"role": "assistant"}
    if msg.get("reasoning_content"):
        out["reasoning_content"] = msg["reasoning_content"]
    if msg.get("content"):
        out["content"] = msg["content"]
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]  # arguments stay stringified json — canonical shape
    return out
