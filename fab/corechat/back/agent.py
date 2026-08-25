import asyncio
import json
import logging

from fab.config import FAB_DIR, MAX_WORDS, PRESERVE_LAST
from fab.corechat.back.prompt import SYSTEM, SUMMARIZE
from fab.corechat.back.modelserver import KimiModelServer
from fab.corechat.back.websocket import broadcast


# if context over model max length, call the model to produce a summary based on the compression prompt
# replace entire context before the last three messages with the summary

class Agent():
    def __init__(self,
                 name:str,
                 model_server:KimiModelServer,):
        self.name = name
        self.working_context_path = FAB_DIR/"agents"/name
        # resume existing agent
        if self.working_context_path.exists():
            self.working_context = [json.loads(line) for line in open(self.working_context_path/"working.jsonl")]
        else:
            self.working_context = [{"role": "system", "content": SYSTEM}]
            self.working_context_path.mkdir(parents=True)
            self.save_working_context()

        self.inbox = []
        self.model_server = model_server
        self.KeepTurning = False
        self.in_a_turn = False

    # dump the whole context to disk, always full rewrite so disk can never drift from memory
    def save_working_context(self):
        with open(self.working_context_path/"working.jsonl", "w") as f:
            for msg in self.working_context:
                f.write(json.dumps(msg) + "\n")

    async def turn(self):
        # drain queued user messages into context at the start of each turn
        for msg in self.inbox:
            self.working_context.append(msg)
        self.inbox = []
        self.save_working_context()
        try:
            await self.compress()
            reply: dict = await self.model_server.call(self.working_context)
            self.working_context.append(reply)
            self.save_working_context()
            broadcast({"type": "messages", "name": self.name, "messages": self.working_context})
        except Exception:
            logging.exception(f"turn failed for agent {self.name}")
        # messages that piled up during the turn get ONE follow-up turn, otherwise go idle
        if self.inbox:
            asyncio.create_task(self.turn())

        # TODO: agent mode; continue working prompt; tool calls; tool repairs
        else:
            self.in_a_turn = False

    async def compress(self):
        words = 0
        for msg in self.working_context:
            content = msg["content"]
            if isinstance(content, str):
                words += len(content.split())
            # an image is worth 1000 words
            else:
                for block in content:
                    if block["type"] == "text":
                        words += len(block["text"].split())
                    elif block["type"] == "image_url":
                        words += 1000

        if words > MAX_WORDS:
            messages = self.working_context
            system = messages[0] 
            # swap in the summarize prompt for this one call
            messages[0] = {"role": "system", "content": SUMMARIZE}
            summary: dict = await self.model_server.call(self.working_context) 
            # rebuild from scratch: real system, summary, last 3 real messages
            self.working_context = [system, summary] + messages[-PRESERVE_LAST:]
            self.save_working_context()
