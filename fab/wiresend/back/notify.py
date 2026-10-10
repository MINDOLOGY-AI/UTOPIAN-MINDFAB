'''notify: the two ways a new message reaches the world, per user.

- broadcast(msg, user=X) — X's open wiresend pages (the live-append in the chat view)
- pings — a one-line deposit to every member agent of THAT user currently loaded in
  corechat, except the sender. the ping is a badge, never the payload: the agent calls
  WIRE_READ if it cares. unloaded agents catch up via unread counts.

lazy-imports its corechat target inside the function so import order can never
bite (corechat's commands.py imports wiresend.tools at the bottom of its module).'''

from fab.websocket import Broadcaster
from fab.wiresend.back import chat

_bus = Broadcaster()

clients = _bus.clients            # user -> that user's open wiresend sockets
broadcast = _bus.send
start_broadcaster = _bus.start


# a fresh message in a channel: the user's pages get the full message, loaded member
# agents get a one-line ping in their inbox (which also wakes their next turn)
def message_posted(user: str, channel_id: str, msg: dict):
    broadcast({"type": "chat_message", "channel": channel_id, "message": msg}, user=user)
    ch = chat.channel_of(user, channel_id)
    if not ch:
        return
    # lazy import: corechat's live agent registry, read-only — nested per user
    from fab.corechat.back.api import agents
    for member in ch["members"]:
        if member in (chat.USER_SENDER, msg["sender"]):
            continue
        agent = agents.get(user, {}).get(member)
        if agent is None:
            continue  # not loaded — unread counts cover the backlog
        text = f"[wiresend] new message in #{ch['name']} from {msg['sender']}"
        if msg["type"] == "file" and msg.get("file"):
            text += f" (file: {msg['file']['name']})"
        agent.inbox.append({"role": "user", "content": [{"type": "text", "text": text}]})
        agent.wake.set()
