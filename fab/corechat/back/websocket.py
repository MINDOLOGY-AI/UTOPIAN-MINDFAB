import asyncio
import json

from fastapi import WebSocket

# one websocket per open page, state changes are pushed to all of them
clients: set[WebSocket] = set()

# agents drop messages here and move on; one broadcaster task sends them in order so a slow client can never stall an agent
_queue: asyncio.Queue = asyncio.Queue()

def broadcast(msg: dict):
    _queue.put_nowait(json.dumps(msg))

# called once at server startup, when an event loop is guaranteed to exist
def start_broadcaster():
    asyncio.create_task(_broadcaster())

async def _broadcaster():
    while True:
        text = await _queue.get()
        for client in list(clients):
            try:
                await client.send_text(text)
            except Exception:
                clients.discard(client) # dead connection
