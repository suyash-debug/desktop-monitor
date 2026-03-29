from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Base class for all activity collectors."""

    def __init__(self, interval_seconds: int = 5):
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def collect(self) -> None:
        """Perform a single collection cycle."""
        ...

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"[{self.name}] collector started (interval={self.interval_seconds}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"[{self.name}] collector stopped")

    async def _run_loop(self):
        while self._running:
            try:
                await self.collect()
            except Exception as e:
                logger.error(f"[{self.name}] collection error: {e}")
            await asyncio.sleep(self.interval_seconds)
