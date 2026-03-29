from __future__ import annotations

import aiosqlite
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    file_path TEXT NOT NULL,
    ocr_text TEXT DEFAULT '',
    app_context TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS window_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    window_title TEXT NOT NULL,
    process_name TEXT DEFAULT '',
    pid INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clipboard_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',
    content_text TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    summary_type TEXT DEFAULT 'hourly',
    generated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    dominant_app TEXT DEFAULT '',
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS keystroke_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    text TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_screenshots_timestamp ON screenshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_window_events_timestamp ON window_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_clipboard_events_timestamp ON clipboard_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_keystroke_events_timestamp ON keystroke_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_summaries_period ON summaries(period_start, period_end);
"""


class Database:
    def __init__(self, db_path: str = "./data/monitor.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    # --- Screenshots ---

    async def insert_screenshot(
        self, timestamp: str, file_path: str, ocr_text: str = "", app_context: str = ""
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO screenshots (timestamp, file_path, ocr_text, app_context) VALUES (?, ?, ?, ?)",
            (timestamp, file_path, ocr_text, app_context),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore

    async def get_screenshots(
        self, start: str | None = None, end: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM screenshots"
        params: list = []
        conditions = []
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_screenshot_vision(self, screenshot_id: int, vision_text: str) -> None:
        await self.db.execute(
            "UPDATE screenshots SET app_context = ? WHERE id = ?",
            (vision_text, screenshot_id),
        )
        await self.db.commit()

    async def search_screenshots(self, text: str, limit: int = 20) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM screenshots WHERE ocr_text LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{text}%", limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Window Events ---

    async def insert_window_event(
        self,
        timestamp: str,
        window_title: str,
        process_name: str = "",
        pid: int = 0,
        duration_seconds: float = 0,
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO window_events (timestamp, window_title, process_name, pid, duration_seconds) VALUES (?, ?, ?, ?, ?)",
            (timestamp, window_title, process_name, pid, duration_seconds),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore

    async def get_window_events(
        self, start: str | None = None, end: str | None = None, limit: int = 100
    ) -> list[dict]:
        query = "SELECT * FROM window_events"
        params: list = []
        conditions = []
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_app_usage(self, start: str, end: str) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT process_name, SUM(duration_seconds) as total_seconds, COUNT(*) as event_count
               FROM window_events
               WHERE timestamp >= ? AND timestamp <= ?
               GROUP BY process_name
               ORDER BY total_seconds DESC""",
            (start, end),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Clipboard Events ---

    async def insert_clipboard_event(
        self, timestamp: str, content_text: str, content_type: str = "text"
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO clipboard_events (timestamp, content_type, content_text) VALUES (?, ?, ?)",
            (timestamp, content_type, content_text),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore

    async def get_clipboard_events(
        self, start: str | None = None, end: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM clipboard_events"
        params: list = []
        conditions = []
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Keystroke Events ---

    async def insert_keystroke_event(self, timestamp: str, text: str) -> int:
        cursor = await self.db.execute(
            "INSERT INTO keystroke_events (timestamp, text) VALUES (?, ?)",
            (timestamp, text),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore

    async def get_keystroke_events(
        self, start: str | None = None, end: str | None = None, limit: int = 100
    ) -> list[dict]:
        query = "SELECT * FROM keystroke_events"
        params: list = []
        conditions = []
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Summaries ---

    async def insert_summary(
        self, period_start: str, period_end: str, summary_text: str, summary_type: str = "hourly"
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO summaries (period_start, period_end, summary_text, summary_type) VALUES (?, ?, ?, ?)",
            (period_start, period_end, summary_text, summary_type),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore

    async def get_summaries(
        self, summary_type: str | None = None, limit: int = 24
    ) -> list[dict]:
        query = "SELECT * FROM summaries"
        params: list = []
        if summary_type:
            query += " WHERE summary_type = ?"
            params.append(summary_type)
        query += " ORDER BY period_start DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_summaries_by_date(self, date_str: str) -> list[dict]:
        """Get all summaries for a specific date (YYYY-MM-DD), ordered by time."""
        start = f"{date_str}T00:00:00"
        end = f"{date_str}T23:59:59"
        cursor = await self.db.execute(
            "SELECT * FROM summaries WHERE period_start >= ? AND period_start <= ? ORDER BY period_start ASC",
            (start, end),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_available_summary_dates(self, limit: int = 60) -> list[str]:
        """Get distinct dates that have window activity, newest first."""
        cursor = await self.db.execute(
            "SELECT DISTINCT substr(timestamp, 1, 10) as date FROM window_events ORDER BY date DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [row["date"] for row in rows]

    # --- Full text search across all tables ---

    async def search_all(self, query_text: str, limit: int = 30) -> dict:
        like = f"%{query_text}%"
        screenshots = await self.db.execute(
            "SELECT * FROM screenshots WHERE ocr_text LIKE ? OR app_context LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (like, like, limit),
        )
        windows = await self.db.execute(
            "SELECT * FROM window_events WHERE window_title LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (like, limit),
        )
        clips = await self.db.execute(
            "SELECT * FROM clipboard_events WHERE content_text LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (like, limit),
        )
        keys = await self.db.execute(
            "SELECT * FROM keystroke_events WHERE text LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (like, limit),
        )
        return {
            "screenshots": [dict(r) for r in await screenshots.fetchall()],
            "window_events": [dict(r) for r in await windows.fetchall()],
            "clipboard_events": [dict(r) for r in await clips.fetchall()],
            "keystroke_events": [dict(r) for r in await keys.fetchall()],
        }
