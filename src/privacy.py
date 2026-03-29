from __future__ import annotations

import fnmatch
import logging

from src.config import PrivacyConfig

logger = logging.getLogger(__name__)


class PrivacyFilter:
    def __init__(self, config: PrivacyConfig):
        self.excluded_apps = [a.lower() for a in config.excluded_apps]
        self.excluded_titles = [t.lower() for t in config.excluded_window_titles]
        self.blur_sensitive = config.blur_sensitive

    def should_skip(self, process_name: str = "", window_title: str = "") -> bool:
        proc_lower = process_name.lower()
        title_lower = window_title.lower()

        # Check excluded apps
        for app in self.excluded_apps:
            if app in proc_lower:
                logger.debug(f"Privacy: skipping excluded app '{process_name}'")
                return True

        # Check excluded window titles (supports glob patterns)
        for pattern in self.excluded_titles:
            if fnmatch.fnmatch(title_lower, pattern):
                logger.debug(f"Privacy: skipping excluded title '{window_title[:50]}'")
                return True

        return False
