from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path


class FileStore:
    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.screenshots_dir = self.data_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def get_screenshot_path(self, timestamp: datetime | None = None) -> Path:
        ts = timestamp or datetime.now()
        date_dir = self.screenshots_dir / ts.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        filename = ts.strftime("%H-%M-%S") + ".png"
        return date_dir / filename

    def cleanup_old_data(self, retention_days: int = 30):
        cutoff = datetime.now() - timedelta(days=retention_days)
        for date_dir in self.screenshots_dir.iterdir():
            if not date_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                if dir_date < cutoff:
                    shutil.rmtree(date_dir)
            except ValueError:
                continue

    def get_storage_stats(self) -> dict:
        total_size = 0
        file_count = 0
        for root, _, files in os.walk(self.screenshots_dir):
            for f in files:
                fp = Path(root) / f
                total_size += fp.stat().st_size
                file_count += 1
        return {
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "file_count": file_count,
            "data_dir": str(self.data_dir),
        }
