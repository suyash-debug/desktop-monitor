from __future__ import annotations

import asyncio
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class VisionWorker:
    """Background worker that analyzes screenshots and generates text summaries using Qwen."""

    def __init__(self, db, vision_enabled: bool = False):
        self._db = db
        self._vision_enabled = vision_enabled
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")
        self._task: asyncio.Task | None = None
        self._last_hash: str | None = None
        self._client = None

    async def submit(self, screenshot_id: int, image_path: str) -> None:
        """Submit a screenshot for analysis. No-op if vision is disabled."""
        if not self._vision_enabled:
            return
        item = (screenshot_id, image_path)
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(item)

    async def generate(self, prompt: str, system: str = "") -> str:
        """Async text generation via Qwen — used by Summarizer. No-op if vision disabled."""
        if not self._vision_enabled:
            return ""
        loop = asyncio.get_event_loop()
        if self._client is None:
            await loop.run_in_executor(self._executor, self._ensure_client)
        return await loop.run_in_executor(
            self._executor, self._client.generate, prompt, system
        )

    def _ensure_client(self):
        if self._client is None:
            from src.llm.qwen_vision_client import QwenVisionClient
            self._client = QwenVisionClient()
            self._client._load()

    async def start(self) -> None:
        if not self._vision_enabled:
            logger.info("VisionWorker started (vision disabled — Qwen not loaded, using OCR only)")
            return
        self._task = asyncio.create_task(self._run(), name="vision-worker")
        logger.info("VisionWorker started (vision enabled — loading Qwen in background)")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._executor.shutdown(wait=False)

    async def _run(self) -> None:
        if not self._vision_enabled:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._ensure_client)

        while True:
            screenshot_id, image_path = await self._queue.get()
            try:
                image_hash = await loop.run_in_executor(
                    self._executor, _hash_file, image_path
                )
                if image_hash == self._last_hash:
                    logger.debug("Screen unchanged, skipping vision analysis")
                    continue
                self._last_hash = image_hash

                # Get active process name for prompt selection
                process_name = await self._get_active_process()
                logger.info(f"Analyzing screenshot {screenshot_id} [{process_name}]...")
                result = await loop.run_in_executor(
                    self._executor, self._client.analyze, image_path, None, process_name
                )
                await self._db.update_screenshot_vision(screenshot_id, result)
                logger.info(f"Vision done [{screenshot_id}]: {result[:80]}...")

            except Exception as e:
                logger.error(f"Vision analysis failed for {screenshot_id}: {e}")


    async def _get_active_process(self) -> str:
        try:
            cursor = await self._db.db.execute(
                "SELECT process_name FROM window_events ORDER BY id DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            return row[0] if row else ""
        except Exception:
            return ""


def _hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()
