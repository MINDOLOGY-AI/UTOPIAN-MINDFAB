import asyncio
import json
import logging

from fab.config import PRESERVE_LAST, udir
from fab.corechat.back.prompt import SYSTEM, SUMMARIZE, WORK_MSG, REPAIR_NOTE
from fab.corechat.back.modelserver import ModelServer
from fab.corechat.back.websocket import broadcast
from fab.corechat.back import commands


# if context over model max length, call the model to produce a summary based on the compression prompt
# replace entire context before the last three messages with the summary

class Agent():
    def __init__(self,
                 user:str,
                 name:str,
                 model_server:ModelServer,
                 context_limit:int=300_000,):
        self.user = user
        self.name = name
        self.working_context_path = udir(user)/"agents"/name
        # resume existing agent
        if self.working_context_path.exists():
            self.working_context: list[dict] = [json.loads(line) for line in open(self.working_context_path/"working.jsonl")]
        else:
            self.working_context = [{"role": "system", "content": SYSTEM}]
            self.working_context_path.mkdir(parents=True)
            self.save_working_context()

        self.inbox = []
        self.model_server = model_server
        self.context_limit = context_limit
        self.agent_mode = False
        # the one wake source: user inbox, agent-mode continuation, delayed tool results all set this
        self.wake = asyncio.Event()
        self.current_turn = None

    # dump the whole context to disk, always full rewrite so disk can never drift from memory
    def save_working_context(self):
        with open(self.working_context_path/"working.jsonl", "w") as f:
            for msg in self.working_context:
                f.write(json.dumps(msg) + "\n")

    # rough context size in words — an image is worth 1000 words
    def count_context_words(self) -> int:
        words = 0
        for msg in self.working_context:
            # an assistant message that only makes tool calls carries content: null
            content = msg.get("content")
            if not content:
                continue
            if isinstance(content, str):
                words += len(content.split())
            else:
                for block in content:
                    if block["type"] == "text":
                        words += len(block["text"].split())
                    elif block["type"] == "image_url":
                        words += 1000
        return words

    # a finished background tool drops its real result here; the model reads it as a user message next turn
    def deposit(self, tool_name: str, result: str):
        self.inbox.append({"role": "user", "content": [{"type": "text", "text": f"[tool result] {tool_name}: {result}"}]})
        self.wake.set()

    # the sole guarantor of a context the api will accept — run after EVERY mutation (inbox drain,
    # compression). tool calls and tool results must pair up in both directions or the api rejects
    # the whole request, and in agent mode a bare assistant ending gets the WORK_MSG nudge
    def repair_context(self):
        # a tool result whose call was never announced above it (compression cut the assistant
        # message it belonged to) — unpaired, so it goes
        announced = set()  # {str} — tool_call ids seen so far, in order
        kept = []          # [dict] — messages whose tool results all have a call above them
        for msg in self.working_context:
            if msg["role"] == "assistant":
                announced |= {tc["id"] for tc in msg.get("tool_calls") or []}
            elif msg["role"] == "tool" and msg["tool_call_id"] not in announced:
                continue
            kept.append(msg)
        # the mirror: an announced call with no result (killed mid-dispatch, interrupted WAIT)
        # gets a placeholder result
        answered = {m["tool_call_id"] for m in kept if m["role"] == "tool"}
        repaired = []
        for msg in kept:
            repaired.append(msg)
            if msg["role"] == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if tc["id"] not in answered:
                        repaired.append({"role": "tool", "tool_call_id": tc["id"],
                                         "name": tc["function"]["name"], "content": REPAIR_NOTE})
        self.working_context = repaired
        last = self.working_context[-1]
        if self.agent_mode and last["role"] == "assistant" and not last.get("tool_calls"):
            self.working_context.append({"role": "user", "content": [{"type": "text", "text": WORK_MSG}]})

    async def turn(self):
        # drain queued user messages into context at the start of each turn
        for msg in self.inbox:
            self.working_context.append(msg)
        self.inbox = []
        self.repair_context()
        self.save_working_context()
        try:
            await self.compress()
            # one turn = one model call; tool results wait in context for the next turn
            reply: dict = await self.model_server.call(self.working_context, [c["schema"] for c in commands.COMMANDS.values()])
            self.working_context.append(reply)
            for tc in reply.get("tool_calls") or []:
                self.working_context.append(await commands.dispatch(self, tc))
            self.save_working_context()
            broadcast({"type": "messages", "name": self.name, "messages": self.working_context,
                       "words": self.count_context_words()}, user=self.user)
        except Exception as e:
            # the frontend renders this where the reply would have been — a dead turn
            # (api error, rate limit, bad key) must never look like the agent said nothing
            logging.exception(f"turn failed for agent {self.name}")
            broadcast({"type": "error", "name": self.name, "msg": f"{type(e).__name__}: {e}"}, user=self.user)
            return
        if self.inbox or self.agent_mode:
            self.wake.set()

    # the only turn-starter: sleep until anything sets wake, run turns until idle
    # a cancelled turn (new input interrupted it) just loops back — context is only mutated at clean points
    async def run(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            self.current_turn = asyncio.create_task(self.turn())
            broadcast({"type": "status", "name": self.name, "generating": True}, user=self.user)
            try:
                await self.current_turn
            except asyncio.CancelledError:
                pass
            self.current_turn = None
            broadcast({"type": "status", "name": self.name, "generating": False}, user=self.user)

    async def compress(self):
        if self.count_context_words() > self.context_limit:
            # summarize over a COPY with the summarize prompt swapped in — the live context stays untouched
            # (a cancelled summarize call must never leave the real system prompt replaced)
            summary_context = [{"role": "system", "content": SUMMARIZE}] + self.working_context[1:]
            # no tools for the summarize call — it must answer in plain text
            summary: dict = await self.model_server.call(summary_context, [])
            # rebuild from scratch: real system, summary, last 3 real messages. the cut can orphan a
            # tool result from its call — repair_context pairs the seam back up before the api sees it
            self.working_context = [self.working_context[0], summary] + self.working_context[-PRESERVE_LAST:]
            self.repair_context()
            self.save_working_context()
