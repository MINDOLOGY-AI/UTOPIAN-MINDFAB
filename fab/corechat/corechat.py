from __future__ import annotations
import json
import os
from pathlib import Path
from abc import ABC, abstractmethod


import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fab.config import FAB_DIR, MAX_WORDS, PRESERVE_LAST, API_TIMEOUT
from fab.corechat.back.prompt import SYSTEM, SUMMARIZE, REPAIR_NOTE, WORK_MSG


# if context over model max length, call the model to produce a summary based on the compression prompt
# replace entire context before the last three messages with the summary

class Agent():
    def __init__(self,
                 name:str,
                 model_server:ModelServer,
                ):

        self.name = name
        self.working_context_path = FAB_DIR/"agents"/name
        # resume existing agent
        if self.working_context_path.exists():
            self.working_context = [json.loads(line) for line in open(self.working_context_path/"working.jsonl")]
        else:
            self.working_context = [{"role": "system", "content": SYSTEM}]

        self.model_server = model_server
        self.KeepTurning = False

    #TODO: not implemented
    def turn(self):
        if self.KeepTurning:
            self.turn()

    def compress(self):
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

        if words > self.model_server.max_tokens:
            messages = self.working_context
            system = messages[0] 
            # swap in the summarize prompt for this one call
            messages[0] = {"role": "system", "content": SUMMARIZE}
            self.model_server.call(self.working_context) 
            # response lands at messages[-1]
            summary = messages[-1]
            self.working_context_path.mkdir(parents=True, exist_ok=True)
            # rebuild from scratch: real system, summary, last 3 real messages
            self.working_context = [system, summary] + messages[-PRESERVE_LAST-1:-1]
            with open(self.working_context_path/"working.jsonl", "w") as f:
                for msg in self.working_context:
                    f.write(json.dumps(msg) + "\n")




class ModelServer(ABC):
    def __init__(self,
                 model_name:str,
                 max_tokens:int):
        self.model_name = model_name
        self.max_tokens = max_tokens

    @abstractmethod
    def call(self, context:list):
        pass


class APIModelServer(ModelServer):
    def __init__(self,model_name:str,
                 max_tokens:int,
                 base_url:str):
        super().__init__(model_name,max_tokens)
        self.base_url = base_url

class KimiModelServer(APIModelServer):
    def __init__(self,model_name:str,
                 max_tokens:int,
                 base_url:str,
                 reasoning_effort:str):
        super().__init__(model_name,max_tokens,base_url)
        self.reasoning_effort = reasoning_effort







