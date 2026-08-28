import asyncio
import json


from fastapi import WebSocket

# one websocket per open page, state changes are pushed to all of them
clients: set[WebSocket] = set()

# (json text, target client or None for everyone) — one queue, one ordering, one place dead clients get reaped
_queue: asyncio.Queue = asyncio.Queue()

# agents drop messages here and move on; one broadcaster task sends them in order so a slow client can never stall an agent
def broadcast(msg: dict, client: WebSocket | None = None):
    _queue.put_nowait((json.dumps(msg), client))

# called once at server startup, when an event loop is guaranteed to exist
def start_broadcaster():
    asyncio.create_task(_broadcaster())

async def _broadcaster():
    while True:
        text, target = await _queue.get()
        for client in list(clients):
            if target is not None and client is not target:
                continue
            try:
                await client.send_text(text)
            except Exception:
                clients.discard(client) # dead connection
