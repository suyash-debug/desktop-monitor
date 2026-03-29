from __future__ import annotations

import yaml
from pathlib import Path
from pydantic import BaseModel


class ScreenshotConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 30
    ocr_engine: str = "pytesseract"
    vision_enabled: bool = False  # Qwen vision analysis — uses 6GB RAM, disabled by default


class WindowTrackerConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 3


class ClipboardConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 2


class KeystrokeConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 15


class CollectorsConfig(BaseModel):
    screenshot: ScreenshotConfig = ScreenshotConfig()
    window_tracker: WindowTrackerConfig = WindowTrackerConfig()
    clipboard: ClipboardConfig = ClipboardConfig()
    keystroke: KeystrokeConfig = KeystrokeConfig()


class StorageConfig(BaseModel):
    data_dir: str = "./data"
    retention_days: int = 30
    db_path: str = "./data/monitor.db"


class LLMConfig(BaseModel):
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    text_model: str = "llama3.2"
    vision_model: str = "llava"
    summary_interval_minutes: int = 60


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080


class PrivacyConfig(BaseModel):
    excluded_apps: list[str] = []
    excluded_window_titles: list[str] = []
    blur_sensitive: bool = True


class AppConfig(BaseModel):
    collectors: CollectorsConfig = CollectorsConfig()
    storage: StorageConfig = StorageConfig()
    llm: LLMConfig = LLMConfig()
    dashboard: DashboardConfig = DashboardConfig()
    privacy: PrivacyConfig = PrivacyConfig()


def load_config(config_path: str = "config.yaml") -> AppConfig:
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return AppConfig(**data)
    return AppConfig()
