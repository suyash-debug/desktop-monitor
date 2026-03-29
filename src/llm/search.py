from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from src.llm.ollama_client import OllamaClient
from src.storage.database import Database

logger = logging.getLogger(__name__)

SEARCH_SYSTEM_PROMPT = """You are a search assistant for a desktop activity monitor.
The user will ask natural language questions about their past computer activity.
Your job is to extract search parameters from their question.

Respond with a JSON object containing:
- "keywords": list of search keywords to look for in OCR text and window titles
- "time_filter": one of "last_hour", "last_3_hours", "today", "yesterday", "last_week", or null
- "app_filter": specific app name to filter by, or null

Example: "What was I working on in VS Code yesterday?"
{"keywords": ["VS Code"], "time_filter": "yesterday", "app_filter": "Code.exe"}

Respond ONLY with the JSON, no other text."""

ANSWER_SYSTEM_PROMPT = """You are a helpful assistant that answers questions about a user's desktop activity.
Based on the search results provided, give a clear, concise answer to the user's question.
Reference specific timestamps and applications when relevant.
If the data doesn't contain enough information to answer, say so clearly."""


class SearchEngine:
    def __init__(self, db: Database, llm: OllamaClient):
        self.db = db
        self.llm = llm

    async def search(self, query: str) -> dict:
        # Step 1: Parse the query with LLM
        params = await self._parse_query(query)

        # Step 2: Execute database search
        results = await self._execute_search(params)

        # Step 3: Generate answer with LLM
        answer = await self._generate_answer(query, results)

        return {
            "query": query,
            "parsed_params": params,
            "results": results,
            "answer": answer,
        }

    async def _parse_query(self, query: str) -> dict:
        response = await self.llm.generate(
            f"User question: {query}", system=SEARCH_SYSTEM_PROMPT
        )

        try:
            # Try to extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(response)
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Failed to parse search params, falling back to keyword search")
            return {"keywords": query.split(), "time_filter": None, "app_filter": None}

    async def _execute_search(self, params: dict) -> dict:
        # Calculate time range
        start, end = self._resolve_time_filter(params.get("time_filter"))

        all_results = {"screenshots": [], "window_events": [], "clipboard_events": []}

        # Search by keywords
        keywords = params.get("keywords", [])
        for keyword in keywords:
            results = await self.db.search_all(keyword, limit=20)
            for key in all_results:
                all_results[key].extend(results.get(key, []))

        # Apply time filter
        if start:
            for key in all_results:
                all_results[key] = [
                    r for r in all_results[key]
                    if r.get("timestamp", "") >= start
                ]
        if end:
            for key in all_results:
                all_results[key] = [
                    r for r in all_results[key]
                    if r.get("timestamp", "") <= end
                ]

        # Apply app filter
        app_filter = params.get("app_filter")
        if app_filter:
            all_results["window_events"] = [
                w for w in all_results["window_events"]
                if app_filter.lower() in w.get("process_name", "").lower()
            ]

        # Deduplicate by id
        for key in all_results:
            seen = set()
            unique = []
            for item in all_results[key]:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    unique.append(item)
            all_results[key] = unique

        return all_results

    def _resolve_time_filter(self, time_filter: str | None) -> tuple[str | None, str | None]:
        if not time_filter:
            return None, None

        now = datetime.now()
        if time_filter == "last_hour":
            start = now - timedelta(hours=1)
        elif time_filter == "last_3_hours":
            start = now - timedelta(hours=3)
        elif time_filter == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_filter == "yesterday":
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start.isoformat(), end.isoformat()
        elif time_filter == "last_week":
            start = now - timedelta(weeks=1)
        else:
            return None, None

        return start.isoformat(), now.isoformat()

    async def _generate_answer(self, query: str, results: dict) -> str:
        # Format results for the LLM
        context_parts = []

        windows = results.get("window_events", [])[:20]
        if windows:
            context_parts.append("## Window Activity:")
            for w in windows:
                context_parts.append(
                    f"- [{w['timestamp'][:19]}] {w['process_name']}: "
                    f"{w['window_title'][:80]} ({w.get('duration_seconds', 0):.0f}s)"
                )

        screenshots = results.get("screenshots", [])[:10]
        if screenshots:
            context_parts.append("\n## Screen Content (Vision Analysis):")
            for s in screenshots:
                text = s.get("app_context") or s.get("ocr_text", "")
                if text:
                    context_parts.append(f"- [{s['timestamp'][:19]}] {text[:200]}")

        clips = results.get("clipboard_events", [])[:10]
        if clips:
            context_parts.append("\n## Clipboard:")
            for c in clips:
                context_parts.append(f"- [{c['timestamp'][:19]}] {c['content_text'][:150]}")

        if not context_parts:
            return "No matching activity found for your query."

        context = "\n".join(context_parts)
        prompt = f"""User question: {query}

Relevant activity data:
{context}

Please answer the user's question based on this activity data."""

        return await self.llm.generate(prompt, system=ANSWER_SYSTEM_PROMPT)
