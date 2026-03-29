from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        text_model: str = "llama3.2",
        vision_model: str = "llava",
        timeout: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.text_model = text_model
        self.vision_model = vision_model
        self.timeout = timeout

    async def generate(self, prompt: str, model: str | None = None, system: str = "") -> str:
        model = model or self.text_model
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {},
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")
            except httpx.HTTPError as e:
                logger.error(f"Ollama API error: {e}")
                return f"[LLM Error: {e}]"

    async def chat(
        self, messages: list[dict], model: str | None = None
    ) -> str:
        model = model or self.text_model
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "")
            except httpx.HTTPError as e:
                logger.error(f"Ollama chat error: {e}")
                return f"[LLM Error: {e}]"

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []
