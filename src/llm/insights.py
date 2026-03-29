from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.llm.ollama_client import OllamaClient
from src.storage.database import Database

logger = logging.getLogger(__name__)

INSIGHTS_SYSTEM_PROMPT = """You are a productivity analyst. Given desktop activity metrics,
provide actionable insights about the user's work patterns. Be specific and constructive.
Focus on patterns like focus time, context switching, peak productivity hours, and app usage."""

TOPIC_SYSTEM_PROMPT = """You are a topic classifier for desktop activity. Given a list of window titles,
classify each into a high-level topic/category. Respond ONLY with a JSON array where each element is:
{"topic": "short topic name", "titles": ["title1", "title2"], "total_seconds": number}

Group similar activities together. Use short, clear topic names like:
"AI/ML Research", "Company Research", "Coding", "Email", "Social Media", "Documentation", "Web Browsing", etc.
Combine closely related titles into the same topic. Return at most 10 topics, sorted by total_seconds descending."""


class InsightsEngine:
    def __init__(self, db: Database, llm: OllamaClient):
        self.db = db
        self.llm = llm

    async def get_productivity_metrics(
        self, start: str | None = None, end: str | None = None
    ) -> dict:
        if not start:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start = today.isoformat()
        if not end:
            end = datetime.now().isoformat()

        app_usage = await self.db.get_app_usage(start, end)
        window_events = await self.db.get_window_events(start=start, end=end, limit=500)

        # Calculate metrics
        total_active_seconds = sum(u["total_seconds"] for u in app_usage)
        total_switches = sum(u["event_count"] for u in app_usage)

        # Detect focus sessions (>= 10 min on same app without switching)
        focus_sessions = self._detect_focus_sessions(window_events)

        # Hourly activity breakdown
        hourly_breakdown = self._hourly_breakdown(window_events)

        # Top apps
        top_apps = [
            {
                "app": u["process_name"],
                "minutes": round(u["total_seconds"] / 60, 1),
                "sessions": u["event_count"],
            }
            for u in app_usage[:10]
        ]

        return {
            "period": {"start": start, "end": end},
            "total_active_minutes": round(total_active_seconds / 60, 1),
            "total_context_switches": total_switches,
            "avg_focus_duration_minutes": (
                round(sum(f["duration_minutes"] for f in focus_sessions) / len(focus_sessions), 1)
                if focus_sessions else 0
            ),
            "focus_sessions": focus_sessions,
            "top_apps": top_apps,
            "hourly_breakdown": hourly_breakdown,
        }

    def _detect_focus_sessions(self, events: list[dict], min_duration_minutes: float = 10) -> list[dict]:
        sessions = []
        min_seconds = min_duration_minutes * 60

        for event in events:
            duration = event.get("duration_seconds", 0)
            if duration >= min_seconds:
                sessions.append({
                    "app": event["process_name"],
                    "title": event["window_title"][:80],
                    "start": event["timestamp"],
                    "duration_minutes": round(duration / 60, 1),
                })

        return sorted(sessions, key=lambda s: s["duration_minutes"], reverse=True)

    def _hourly_breakdown(self, events: list[dict]) -> dict[str, float]:
        hourly: dict[str, float] = {}
        for event in events:
            try:
                ts = datetime.fromisoformat(event["timestamp"])
                hour_key = ts.strftime("%H:00")
                hourly[hour_key] = hourly.get(hour_key, 0) + event.get("duration_seconds", 0)
            except (ValueError, KeyError):
                continue
        return {k: round(v / 60, 1) for k, v in sorted(hourly.items())}

    async def get_topic_breakdown(self, start: str | None = None, end: str | None = None) -> list[dict]:
        """Use the LLM to group window events into topics with time spent."""
        import json

        if not start:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start = today.isoformat()
        if not end:
            end = datetime.now().isoformat()

        window_events = await self.db.get_window_events(start=start, end=end, limit=500)
        if not window_events:
            return []

        # Build a summary of titles with durations for the LLM
        title_durations: dict[str, float] = {}
        for w in window_events:
            title = w["window_title"][:100]
            title_durations[title] = title_durations.get(title, 0) + w.get("duration_seconds", 0)

        # Format for the LLM — include duration so it can aggregate
        entries = "\n".join(
            f"- \"{title}\" ({dur:.0f}s)"
            for title, dur in sorted(title_durations.items(), key=lambda x: -x[1])[:50]
        )

        # Enrich with vision analysis samples
        screenshots = await self.db.get_screenshots(start=start, end=end, limit=20)
        vision_samples = "\n".join(
            f"- [{s['timestamp'][:16]}] {s['app_context'][:120]}"
            for s in screenshots if s.get("app_context")
        )
        vision_section = f"\n\nScreen content samples:\n{vision_samples}" if vision_samples else ""

        prompt = f"Classify these window titles into topics and sum their durations:\n\n{entries}{vision_section}"

        response = await self.llm.generate(prompt, system=TOPIC_SYSTEM_PROMPT)

        # Parse JSON response
        try:
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0]
            topics = json.loads(response)
            if isinstance(topics, list):
                return topics
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse topic breakdown from LLM, using fallback")

        # Fallback: group by process name
        app_usage = await self.db.get_app_usage(start, end)
        return [
            {
                "topic": u["process_name"].replace(".exe", ""),
                "titles": [],
                "total_seconds": u["total_seconds"],
            }
            for u in app_usage[:10]
        ]

    async def generate_insights(self, start: str | None = None, end: str | None = None) -> str:
        metrics = await self.get_productivity_metrics(start, end)

        # Pull vision analysis samples to give content-aware insights
        screenshots = await self.db.get_screenshots(start=start or metrics["period"]["start"], end=end or metrics["period"]["end"], limit=15)
        vision_samples = "\n".join(
            f"- [{s['timestamp'][:16]}] {s['app_context'][:120]}"
            for s in screenshots if s.get("app_context")
        )
        vision_section = f"\n\n## What was on screen (vision samples):\n{vision_samples}" if vision_samples else ""

        prompt = f"""Analyze the following desktop activity and provide productivity insights:

## Summary
- Total active time: {metrics['total_active_minutes']} minutes
- Context switches: {metrics['total_context_switches']}
- Average focus session: {metrics['avg_focus_duration_minutes']} minutes

## Top Applications:
{chr(10).join(f"- {a['app']}: {a['minutes']} min ({a['sessions']} sessions)" for a in metrics['top_apps'])}

## Focus Sessions (>{10} min uninterrupted):
{chr(10).join(f"- {s['app']}: {s['duration_minutes']} min on '{s['title']}'" for s in metrics['focus_sessions'][:10]) or "None detected"}

## Hourly Activity (minutes active):
{chr(10).join(f"- {h}: {m} min" for h, m in metrics['hourly_breakdown'].items())}{vision_section}

Provide 3-5 actionable productivity insights. Use the screen content to be specific about what the user was actually working on."""

        return await self.llm.generate(prompt, system=INSIGHTS_SYSTEM_PROMPT)
