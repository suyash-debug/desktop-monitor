from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import psutil

from src.collectors.base import BaseCollector
from src.storage.database import Database
from src.privacy import PrivacyFilter

logger = logging.getLogger(__name__)


def _get_active_window_info() -> dict | None:
    """Get the currently active window's title and process name (Windows)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        # Get window title
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title = buf.value

        # Get process ID
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # Get process name
        process_name = ""
        try:
            proc = psutil.Process(pid.value)
            process_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return {
            "title": title,
            "process_name": process_name,
            "pid": pid.value,
        }
    except Exception as e:
        logger.warning(f"Failed to get active window: {e}")
        return None


class WindowTracker(BaseCollector):
    name = "window_tracker"

    def __init__(self, db: Database, interval_seconds: int = 3, privacy_filter: PrivacyFilter | None = None):
        super().__init__(interval_seconds)
        self.db = db
        self.privacy_filter = privacy_filter
        self._last_window: dict | None = None
        self._last_change_time: datetime | None = None

    async def collect(self) -> None:
        info = await asyncio.to_thread(_get_active_window_info)
        if info is None:
            return

        # Privacy check
        if self.privacy_filter and self.privacy_filter.should_skip(
            process_name=info.get("process_name", ""),
            window_title=info.get("title", ""),
        ):
            return

        now = datetime.now()
        current_key = (info["title"], info["process_name"])

        # Detect window change
        if self._last_window is not None:
            last_key = (self._last_window["title"], self._last_window["process_name"])
            if current_key == last_key:
                return  # Same window, skip

            # Log the previous window's duration
            if self._last_change_time:
                duration = (now - self._last_change_time).total_seconds()
                await self.db.insert_window_event(
                    timestamp=self._last_change_time.isoformat(),
                    window_title=self._last_window["title"],
                    process_name=self._last_window["process_name"],
                    pid=self._last_window.get("pid", 0),
                    duration_seconds=duration,
                )
                logger.debug(
                    f"Window: {self._last_window['process_name']} "
                    f"'{self._last_window['title'][:50]}' ({duration:.1f}s)"
                )

        self._last_window = info
        self._last_change_time = now
