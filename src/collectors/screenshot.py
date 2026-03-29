from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import mss
from PIL import Image

from src.collectors.base import BaseCollector
from src.storage.database import Database
from src.storage.file_store import FileStore

logger = logging.getLogger(__name__)


class ScreenshotCollector(BaseCollector):
    name = "screenshot"

    def __init__(
        self,
        db: Database,
        file_store: FileStore,
        interval_seconds: int = 30,
        ocr_engine: str = "pytesseract",
        vision_worker=None,
    ):
        super().__init__(interval_seconds)
        self.db = db
        self.file_store = file_store
        self.ocr_engine = ocr_engine
        self.vision_worker = vision_worker

    async def collect(self) -> None:
        now = datetime.now()
        screenshot_path = self.file_store.get_screenshot_path(now)

        # Capture screenshot in a thread (mss is synchronous)
        await asyncio.to_thread(self._capture_screenshot, str(screenshot_path))

        # Run OCR in a thread
        ocr_text = await asyncio.to_thread(self._extract_text, str(screenshot_path))

        # Store in database
        timestamp = now.isoformat()
        screenshot_id = await self.db.insert_screenshot(
            timestamp=timestamp,
            file_path=str(screenshot_path),
            ocr_text=ocr_text,
        )
        logger.debug(f"Screenshot saved: {screenshot_path} ({len(ocr_text)} chars OCR)")

        # Submit to vision worker (non-blocking)
        if self.vision_worker is not None:
            await self.vision_worker.submit(screenshot_id, str(screenshot_path))

    def _capture_screenshot(self, path: str) -> None:
        with mss.mss() as sct:
            # Capture the primary monitor
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img.save(path, "PNG", optimize=True)

    def _extract_text(self, image_path: str) -> str:
        try:
            if self.ocr_engine == "pytesseract":
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                text = pytesseract.image_to_string(Image.open(image_path))
                return text.strip()
            elif self.ocr_engine == "easyocr":
                import easyocr
                reader = easyocr.Reader(["en"], gpu=False)
                results = reader.readtext(image_path)
                return " ".join([r[1] for r in results]).strip()
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
        return ""
