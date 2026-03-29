from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from src.storage.database import Database

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a personal productivity assistant. "
    "You summarize a person's computer activity in clear, natural language. "
    "Focus on WHAT they were doing and WHY (the task/topic), not just which apps they opened. "
    "Be specific and insightful. Write 3-5 sentences max."
)

PROMPT_TEMPLATE = """\
Summarize what this person was doing on their computer from {start} to {end}.

TIME SPENT PER APP:
{app_usage}

PAGES / DOCUMENTS VISITED (most recent first):
{titles}

TEXT THEY TYPED:
{typed}
{idle_section}
Write a natural summary focused on their actual work and topics. Do not list apps mechanically.\
If there were notable idle periods, mention them naturally (e.g. "was away from 14:30 to 15:10")."""


# --- Idle / Session detection ---

IDLE_GAP_MINUTES = 5       # gaps >= 5 min = idle
SESSION_GAP_MINUTES = 15   # gaps >= 15 min = new session / away


def detect_idle_and_sessions(
    windows: list[dict],
    keystrokes: list[dict],
) -> dict:
    """
    Detect idle periods and active sessions from window + keystroke timestamps.

    Returns:
        {
          "sessions": [{"start": "HH:MM", "end": "HH:MM", "duration_min": int}, ...],
          "idle_periods": [{"start": "HH:MM", "end": "HH:MM", "duration_min": int}, ...],
          "total_active_min": int,
          "total_idle_min": int,
        }
    """
    timestamps: list[datetime] = []
    for w in windows:
        ts = w.get("timestamp", "")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except ValueError:
                pass
    for k in keystrokes:
        ts = k.get("timestamp", "")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except ValueError:
                pass

    if not timestamps:
        return {"sessions": [], "idle_periods": [], "total_active_min": 0, "total_idle_min": 0}

    timestamps.sort()

    sessions: list[dict] = []
    idle_periods: list[dict] = []
    session_start = timestamps[0]
    total_idle_min = 0

    for i in range(1, len(timestamps)):
        gap_min = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60

        if gap_min >= SESSION_GAP_MINUTES:
            # Close current session
            sessions.append({
                "start": session_start.strftime("%H:%M"),
                "end": timestamps[i - 1].strftime("%H:%M"),
                "duration_min": max(1, int((timestamps[i - 1] - session_start).total_seconds() / 60)),
            })
            idle_periods.append({
                "start": timestamps[i - 1].strftime("%H:%M"),
                "end": timestamps[i].strftime("%H:%M"),
                "duration_min": int(gap_min),
            })
            total_idle_min += int(gap_min)
            session_start = timestamps[i]
        elif gap_min >= IDLE_GAP_MINUTES:
            idle_periods.append({
                "start": timestamps[i - 1].strftime("%H:%M"),
                "end": timestamps[i].strftime("%H:%M"),
                "duration_min": int(gap_min),
            })
            total_idle_min += int(gap_min)

    # Close last session
    sessions.append({
        "start": session_start.strftime("%H:%M"),
        "end": timestamps[-1].strftime("%H:%M"),
        "duration_min": max(1, int((timestamps[-1] - session_start).total_seconds() / 60)),
    })

    total_active_min = sum(s["duration_min"] for s in sessions)

    return {
        "sessions": sessions,
        "idle_periods": idle_periods,
        "total_active_min": total_active_min,
        "total_idle_min": total_idle_min,
    }


def _format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _clean_app(name: str) -> str:
    name = re.sub(r'\.exe$', '', name, flags=re.IGNORECASE)
    aliases = {
        "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox",
        "code": "VS Code", "explorer": "File Explorer", "notepad": "Notepad",
        "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint",
        "slack": "Slack", "discord": "Discord", "spotify": "Spotify",
        "idea64": "IntelliJ", "pycharm64": "PyCharm",
    }
    return aliases.get(name.lower(), name)


def _clean_title(title: str) -> str:
    title = re.sub(
        r'\s*[-–|]\s*(Google Chrome|Mozilla Firefox|Microsoft Edge|Visual Studio Code|Code|Notepad)$',
        '', title, flags=re.IGNORECASE
    )
    return title.strip()


class Summarizer:
    def __init__(self, db: Database, llm):
        self.db = db
        self.llm = llm

    async def _build_prompt(self, start: datetime, end: datetime) -> str | None:
        start_str = start.isoformat()
        end_str = end.isoformat()

        windows = await self.db.get_window_events(start=start_str, end=end_str, limit=500)
        keystrokes = await self.db.get_keystroke_events(start=start_str, end=end_str, limit=200)

        if not windows and not keystrokes:
            return None

        # App usage: time per app, sorted descending
        app_time: dict[str, float] = {}
        for w in windows:
            name = _clean_app(w.get("process_name", "unknown"))
            dur = w.get("duration_seconds", 0) or 0
            app_time[name] = app_time.get(name, 0) + dur

        app_lines = []
        for app, secs in sorted(app_time.items(), key=lambda x: x[1], reverse=True)[:6]:
            if secs < 10:
                continue
            mins = int(secs // 60)
            label = f"{mins}m" if mins > 0 else f"{int(secs)}s"
            app_lines.append(f"  {app}: {label}")
        app_usage = "\n".join(app_lines) or "  (no app data)"

        # Window titles: unique meaningful titles, preserve order
        seen: set[str] = set()
        title_lines = []
        for w in windows:
            t = _clean_title(w.get("window_title", ""))
            if not t or len(t) < 5 or t in seen:
                continue
            if t.lower().startswith("http"):
                continue
            seen.add(t)
            title_lines.append(f"  - {t[:90]}")
            if len(title_lines) >= 12:
                break
        titles = "\n".join(title_lines) or "  (none)"

        # Keystrokes: join into readable text
        chunks = [k.get("text", "").strip() for k in keystrokes if k.get("text", "").strip()]
        typed_raw = " ".join(chunks)
        typed_raw = re.sub(r'\s+', ' ', typed_raw).strip()
        typed = f'  "{typed_raw[:400]}"' if typed_raw else "  (nothing typed)"

        # Idle / session detection
        activity = detect_idle_and_sessions(windows, keystrokes)
        idle_lines = []
        for ip in activity["idle_periods"]:
            if ip["duration_min"] >= SESSION_GAP_MINUTES:
                idle_lines.append(f"  - Away/idle from {ip['start']} to {ip['end']} ({ip['duration_min']}m)")
            else:
                idle_lines.append(f"  - Short idle {ip['start']}–{ip['end']} ({ip['duration_min']}m)")
        idle_section = ""
        if idle_lines:
            idle_section = "\nIDLE / AWAY PERIODS:\n" + "\n".join(idle_lines) + "\n"

        return PROMPT_TEMPLATE.format(
            start=start.strftime("%H:%M"),
            end=end.strftime("%H:%M"),
            app_usage=app_usage,
            titles=titles,
            typed=typed,
            idle_section=idle_section,
        )

    async def _generate_summary(self, start: datetime, end: datetime, summary_type: str = "hourly") -> str:
        prompt = await self._build_prompt(start, end)

        if prompt is None:
            return "No activity recorded during this period."

        summary = await self.llm.generate(prompt, system=SYSTEM_PROMPT)

        if not summary or not summary.strip() or summary.startswith("[LLM Error"):
            summary = self._fallback(start, end, prompt)

        await self.db.insert_summary(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            summary_text=summary,
            summary_type=summary_type,
        )
        logger.info(f"Generated {summary_type} summary for {start.strftime('%H:%M')}–{end.strftime('%H:%M')}")
        return summary

    def _fallback(self, start: datetime, end: datetime, prompt: str) -> str:
        lines = [l.strip() for l in prompt.splitlines() if l.strip().startswith("-")]
        titles_str = "; ".join(l.lstrip("- ") for l in lines[:4]) if lines else ""
        return (
            f"Activity {start.strftime('%H:%M')}–{end.strftime('%H:%M')}. "
            + (f"Visited: {titles_str}." if titles_str else "No significant activity.")
        )

    async def generate_recent_summary(self, minutes: int = 60) -> str:
        end = datetime.now()
        start = end - timedelta(minutes=minutes)
        return await self._generate_summary(start, end, summary_type="recent")

    async def generate_hourly_summary(self, hour_start: datetime | None = None) -> str:
        if hour_start is None:
            hour_start = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        hour_end = hour_start + timedelta(hours=1)
        return await self._generate_summary(hour_start, hour_end, summary_type="hourly")

    async def generate_daily_summary(self, date: datetime | None = None) -> str:
        if date is None:
            date = datetime.now() - timedelta(days=1)
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        start_str = day_start.isoformat()
        end_str = day_end.isoformat()

        summaries = await self.db.get_summaries(summary_type="hourly", limit=24)
        day_summaries = [s for s in summaries if start_str <= s["period_start"] < end_str]
        app_usage = await self.db.get_app_usage(start_str, end_str)

        # Session / idle analysis for the whole day
        windows = await self.db.get_window_events(start=start_str, end=end_str, limit=2000)
        keystrokes = await self.db.get_keystroke_events(start=start_str, end=end_str, limit=500)
        activity = detect_idle_and_sessions(windows, keystrokes)

        hourly_text = "\n".join(
            f"  [{s['period_start'][11:16]}] {s['summary_text']}"
            for s in day_summaries
        ) or "  No hourly summaries yet."

        usage_text = "\n".join(
            f"  {_clean_app(u['process_name'])}: {int(u['total_seconds']//60)}m"
            for u in app_usage[:8] if u.get('total_seconds', 0) > 30
        ) or "  No usage data."

        session_text = "\n".join(
            f"  Session {i+1}: {s['start']}–{s['end']} ({_format_duration(s['duration_min'])})"
            for i, s in enumerate(activity["sessions"])
        ) or "  No session data."

        idle_text = "\n".join(
            f"  {ip['start']}–{ip['end']} ({ip['duration_min']}m)"
            for ip in activity["idle_periods"] if ip["duration_min"] >= SESSION_GAP_MINUTES
        ) or "  No significant idle periods."

        prompt = f"""\
Write a daily summary for {day_start.strftime('%A, %B %d %Y')}.

ACTIVE SESSIONS (computer was in use):
{session_text}
Total active: {_format_duration(activity['total_active_min'])}, Total idle/away: {_format_duration(activity['total_idle_min'])}

AWAY / IDLE PERIODS (>= {SESSION_GAP_MINUTES} min):
{idle_text}

HOURLY ACTIVITY:
{hourly_text}

TOTAL APP USAGE:
{usage_text}

Write 4-6 sentences covering the main themes, when the computer was in use vs idle, accomplishments, and patterns of the day."""

        summary = await self.llm.generate(prompt, system=SYSTEM_PROMPT)
        if not summary or not summary.strip() or summary.startswith("[LLM Error"):
            summary = f"Daily summary for {day_start.strftime('%Y-%m-%d')}:\n{hourly_text}"

        await self.db.insert_summary(
            period_start=start_str,
            period_end=end_str,
            summary_text=summary,
            summary_type="daily",
        )
        logger.info(f"Generated daily summary for {day_start.strftime('%Y-%m-%d')}")
        return summary

    async def get_day_activity(self, date_str: str) -> dict:
        """Return session/idle analysis for a given date without generating a summary."""
        day_start = f"{date_str}T00:00:00"
        day_end = f"{date_str}T23:59:59"
        windows = await self.db.get_window_events(start=day_start, end=day_end, limit=2000)
        keystrokes = await self.db.get_keystroke_events(start=day_start, end=day_end, limit=500)
        return detect_idle_and_sessions(windows, keystrokes)
