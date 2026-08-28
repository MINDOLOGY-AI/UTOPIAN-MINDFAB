import asyncio
import json


from fastapi import WebSocket

# one websocket per open page, keyed by user — a user's tabs get their own events, never anyone else's
clients: dict[str, set[WebSocket]] = {}

# (json text, target user or None, target client or None) — one queue, one ordering, one place dead clients get reaped
_queue: asyncio.Queue = asyncio.Queue()

# agents drop messages here and move on; one broadcaster task sends them in order so a slow client can never stall an agent
# user=X -> all of X's tabs; client=ws -> just that socket (request/response)
def broadcast(msg: dict, user: str | None = None, client: WebSocket | None = None):
    _queue.put_nowait((json.dumps(msg), user, client))

# called once at server startup, when an event loop is guaranteed to exist
def start_broadcaster():
    asyncio.create_task(_broadcaster())

async def _broadcaster():
    while True:
        text, user, target = await _queue.get()
        for owner, sockets in list(clients.items()):
            if user is not None and owner != user:
                continue
            for client in list(sockets):
                if target is not None and client is not target:
                    continue
                try:
                    await client.send_text(text)
                except Exception:
                    sockets.discard(client) # dead connection
