# all theoretical data format converting happens here.  
# whether it's context_format -> model_format, model_format -> context_format, or model creation and model call
from abc import ABC, abstractmethod

import httpx

from fab.config import API_TIMEOUT


class ModelServer(ABC):
    def __init__(self,
                 model_server_name:str,
                 model_name:str,
                 max_tokens:int):
        self.model_server_name = model_server_name
        self.model_name = model_name
        self.max_tokens = max_tokens

    @abstractmethod
    async def call(self, context:list, tools:list) -> dict:
        pass


class APIModelServer(ModelServer):
    def __init__(self,model_server_name:str,
                 model_name:str,
                 max_tokens:int,
                 base_url:str):
        super().__init__(model_server_name,model_name,max_tokens)
        self.base_url = base_url

class KimiModelServer(APIModelServer):
    def __init__(self,model_name:str="kimi-k3",
                 max_tokens:int=8192,
                 reasoning_effort:str="high",
                 api_key:str="",
                 base_url:str="https://api.moonshot.cn/v1"):
        super().__init__("kimi",model_name,max_tokens,base_url)
        self.reasoning_effort = reasoning_effort
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=API_TIMEOUT)

    # adapter only translates: context in, assistant message out — the agent owns the context
    async def call(self, context:list, tools:list) -> dict:
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model_name,
                  "messages": context,
                  "max_tokens": self.max_tokens,
                  "reasoning_effort": self.reasoning_effort,
                  "tools": tools})
        response.raise_for_status()
        return response.json()["choices"][0]["message"]

class DeepSeekModelServer(APIModelServer):
    def __init__(self,model_name:str="deepseek-v4-flash-vision-exp",
                 max_tokens:int=8192,
                 reasoning_effort:str="high",
                 api_key:str="",
                 base_url:str="https://api.deepseek.com"):
        super().__init__("deepseek",model_name,max_tokens,base_url)
        self.reasoning_effort = reasoning_effort
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=API_TIMEOUT)

    # same shape as kimi plus the thinking toggle, per deepseek's docs
    async def call(self, context:list, tools:list) -> dict:
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model_name,
                  "messages": context,
                  "max_tokens": self.max_tokens,
                  "reasoning_effort": self.reasoning_effort,
                  "thinking": {"type": "enabled"},
                  "tools": tools})
        response.raise_for_status()
        return response.json()["choices"][0]["message"]
