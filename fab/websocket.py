'''the one websocket broadcaster. corechat and wiresend each own an instance: separate
client registries (different pages, different sockets), same machinery.

pages drop messages in and move on; one task per bus sends them in order, so a slow
client can never stall an agent, and dead sockets get reaped in exactly one place.'''

import asyncio
import json

from fastapi import WebSocket


class Broadcaster:
    def __init__(self):
        # user -> that user's open sockets. a user's tabs get their own events, never anyone else's
        self.clients: dict[str, set[WebSocket]] = {}
        # [(json text, target user or None, target client or None)] — one queue, one ordering
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None  # the loop _task belongs to

    # user=X -> all of X's tabs; client=ws -> just that socket (request/response)
    def send(self, msg: dict, user: str | None = None, client: WebSocket | None = None):
        self._queue.put_nowait((json.dumps(msg), user, client))

    # idempotent PER EVENT LOOP: called from the app lifespan and from every ws connect, so it
    # must not start a second sender on the same loop
    def start(self):
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # an asyncio.Queue binds to the loop that first awaits it and refuses every other
            # one, so a new loop (a fresh TestClient, two suites in one process) needs a fresh
            # queue and a fresh sender — the ones from the closed loop are dead weight
            self._loop, self._queue, self._task = loop, asyncio.Queue(), None
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run())

    async def _run(self):
        while True:
            text, user, target = await self._queue.get()
            for owner, sockets in list(self.clients.items()):
                if user is not None and owner != user:
                    continue
                for client in list(sockets):
                    if target is not None and client is not target:
                        continue
                    try:
                        await client.send_text(text)
                    except Exception:
                        sockets.discard(client)  # dead connection
