from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pyperclip

from src.collectors.base import BaseCollector
from src.storage.database import Database

logger = logging.getLogger(__name__)


class ClipboardCollector(BaseCollector):
    name = "clipboard"

    def __init__(self, db: Database, interval_seconds: int = 2):
        super().__init__(interval_seconds)
        self.db = db
        self._last_content: str = ""

    async def collect(self) -> None:
        try:
            content = await asyncio.to_thread(pyperclip.paste)
        except Exception:
            return

        if not content or content == self._last_content:
            return

        self._last_content = content
        now = datetime.now()

        # Truncate very long clipboard content
        stored_content = content[:5000] if len(content) > 5000 else content

        await self.db.insert_clipboard_event(
            timestamp=now.isoformat(),
            content_text=stored_content,
            content_type="text",
        )
        logger.debug(f"Clipboard: {len(content)} chars captured")
