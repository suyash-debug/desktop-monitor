from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta

import uvicorn

from src.config import load_config
from src.storage.database import Database
from src.storage.file_store import FileStore
from src.collectors.screenshot import ScreenshotCollector
from src.collectors.window_tracker import WindowTracker
from src.collectors.clipboard import ClipboardCollector
from src.collectors.keystroke import KeystrokeCollector
from src.llm.summarizer import Summarizer
from src.llm.vision_worker import VisionWorker
from src.privacy import PrivacyFilter
from src.api.server import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("desktop-monitor")


async def run_summary_scheduler(summarizer: Summarizer, interval_minutes: int = 60):
    """Periodically generate hourly summaries."""
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await summarizer.generate_hourly_summary()
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")


async def run_cleanup_scheduler(file_store: FileStore, retention_days: int = 30):
    """Daily cleanup of old data."""
    while True:
        await asyncio.sleep(24 * 3600)  # Once per day
        try:
            file_store.cleanup_old_data(retention_days)
            logger.info("Old data cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")


async def async_main():
    config = load_config()

    # Initialize storage
    db = Database(config.storage.db_path)
    await db.connect()
    file_store = FileStore(config.storage.data_dir)

    logger.info("Storage initialized")

    # Privacy filter
    privacy_filter = PrivacyFilter(config.privacy)

    # Initialize collectors
    collectors = []

    if config.collectors.screenshot.enabled:
        vision_worker = VisionWorker(db, vision_enabled=config.collectors.screenshot.vision_enabled)
        await vision_worker.start()
        screenshot_collector = ScreenshotCollector(
            db=db,
            file_store=file_store,
            interval_seconds=config.collectors.screenshot.interval_seconds,
            ocr_engine=config.collectors.screenshot.ocr_engine,
            vision_worker=vision_worker,
        )
        collectors.append(screenshot_collector)

    if config.collectors.window_tracker.enabled:
        window_tracker = WindowTracker(
            db=db,
            interval_seconds=config.collectors.window_tracker.interval_seconds,
            privacy_filter=privacy_filter,
        )
        collectors.append(window_tracker)

    if config.collectors.clipboard.enabled:
        clipboard_collector = ClipboardCollector(
            db=db,
            interval_seconds=config.collectors.clipboard.interval_seconds,
        )
        collectors.append(clipboard_collector)

    if config.collectors.keystroke.enabled:
        keystroke_collector = KeystrokeCollector(
            db=db,
            interval_seconds=config.collectors.keystroke.interval_seconds,
        )
        collectors.append(keystroke_collector)

    # Start collectors
    for collector in collectors:
        await collector.start()

    logger.info(f"Started {len(collectors)} collectors")

    # Use Ollama (llama3.2) for summaries; Qwen only if vision_enabled
    from src.llm.ollama_client import OllamaClient
    ollama = OllamaClient(
        base_url=config.llm.base_url,
        text_model=config.llm.text_model,
    )
    summary_llm = (
        vision_worker if (config.collectors.screenshot.enabled and config.collectors.screenshot.vision_enabled)
        else ollama
    )
    logger.info(f"Summaries via: {'Qwen' if config.collectors.screenshot.vision_enabled else 'Ollama/' + config.llm.text_model}")

    # Background tasks
    summarizer = Summarizer(db, summary_llm)
    summary_task = asyncio.create_task(
        run_summary_scheduler(summarizer, config.llm.summary_interval_minutes)
    )
    cleanup_task = asyncio.create_task(
        run_cleanup_scheduler(file_store, config.storage.retention_days)
    )

    # Create and run web server
    app = create_app(config, db, file_store, vision_worker=vision_worker if config.collectors.screenshot.enabled else None, summary_llm=ollama)

    server_config = uvicorn.Config(
        app,
        host=config.dashboard.host,
        port=config.dashboard.port,
        log_level="info",
    )
    server = uvicorn.Server(server_config)

    logger.info(f"Dashboard available at http://{config.dashboard.host}:{config.dashboard.port}")

    try:
        await server.serve()
    finally:
        logger.info("Shutting down...")
        summary_task.cancel()
        cleanup_task.cancel()
        for collector in collectors:
            await collector.stop()
        if config.collectors.screenshot.enabled:
            await vision_worker.stop()
        await db.close()
        logger.info("Shutdown complete")


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
