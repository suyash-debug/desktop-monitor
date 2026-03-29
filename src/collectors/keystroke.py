from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime

from pynput import keyboard

from src.collectors.base import BaseCollector
from src.storage.database import Database

logger = logging.getLogger(__name__)

# Keys to record as readable text vs special keys
SPECIAL_KEY_MAP = {
    keyboard.Key.space: " ",
    keyboard.Key.enter: "\n",
    keyboard.Key.tab: "\t",
}

# Keys to ignore entirely (modifiers, function keys, etc.)
IGNORE_KEYS = {
    keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
    keyboard.Key.caps_lock, keyboard.Key.num_lock, keyboard.Key.scroll_lock,
    keyboard.Key.print_screen, keyboard.Key.pause, keyboard.Key.insert,
    keyboard.Key.menu,
}


class KeystrokeCollector(BaseCollector):
    """Collects keystrokes in buffered chunks and stores them periodically.

    PRIVACY NOTE: Keystrokes are buffered and stored as text chunks (not individual keys).
    No passwords are intentionally captured — use the privacy filter to exclude
    sensitive apps like password managers, banking sites, etc.
    """

    name = "keystroke"

    def __init__(self, db: Database, interval_seconds: int = 15):
        super().__init__(interval_seconds)
        self.db = db
        self._buffer: list[str] = []
        self._buffer_lock = threading.Lock()
        self._listener: keyboard.Listener | None = None

    def _on_key_press(self, key):
        try:
            # Regular character keys
            if hasattr(key, "char") and key.char is not None:
                with self._buffer_lock:
                    self._buffer.append(key.char)
            # Special keys we want to capture
            elif key in SPECIAL_KEY_MAP:
                with self._buffer_lock:
                    self._buffer.append(SPECIAL_KEY_MAP[key])
            elif key == keyboard.Key.backspace:
                with self._buffer_lock:
                    if self._buffer:
                        self._buffer.pop()
                    else:
                        self._buffer.append("[BS]")
            # Skip ignored keys silently
            elif key in IGNORE_KEYS:
                pass
            # Record other special keys as tags
            else:
                name = key.name if hasattr(key, "name") else str(key)
                with self._buffer_lock:
                    self._buffer.append(f"[{name}]")
        except Exception:
            pass

    async def start(self):
        # Start the pynput listener in a background thread
        self._listener = keyboard.Listener(on_press=self._on_key_press)
        self._listener.daemon = True
        self._listener.start()
        # Start the periodic flush loop
        await super().start()

    async def stop(self):
        if self._listener:
            self._listener.stop()
        # Flush remaining buffer
        await self._flush_buffer()
        await super().stop()

    async def collect(self) -> None:
        """Flush the keystroke buffer to the database."""
        await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        with self._buffer_lock:
            if not self._buffer:
                return
            text = "".join(self._buffer)
            self._buffer.clear()

        # Skip if it's just whitespace
        if not text.strip():
            return

        now = datetime.now()
        await self.db.insert_keystroke_event(
            timestamp=now.isoformat(),
            text=text,
        )
        logger.debug(f"Keystrokes flushed: {len(text)} chars")
