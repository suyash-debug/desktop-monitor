from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

router = APIRouter()


# --- Pydantic models ---

class SearchRequest(BaseModel):
    query: str


class SummaryRequest(BaseModel):
    period: str = "last_hour"  # last_hour, today, yesterday


# --- Dashboard Pages ---

@router.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request):
    templates = request.app.state.templates
    db = request.app.state.db

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    screenshots = await db.get_screenshots(start=today.isoformat(), limit=50)
    windows = await db.get_window_events(start=today.isoformat(), limit=100)
    summaries = await db.get_summaries(summary_type="hourly", limit=12)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "screenshots": screenshots,
        "window_events": windows,
        "summaries": summaries,
        "today": today.strftime("%Y-%m-%d"),
    })


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("search.html", {"request": request, "results": None})


@router.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request):
    templates = request.app.state.templates
    insights_engine = request.app.state.insights_engine

    metrics = await insights_engine.get_productivity_metrics()

    return templates.TemplateResponse("insights.html", {
        "request": request,
        "metrics": metrics,
    })


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, date: str = Query(default=None)):
    templates = request.app.state.templates
    db = request.app.state.db

    available_dates = await db.get_available_summary_dates(limit=60)
    selected_date = date or (available_dates[0] if available_dates else datetime.now().strftime("%Y-%m-%d"))

    summaries = await db.get_summaries_by_date(selected_date)
    daily = next((s for s in summaries if s["summary_type"] == "daily"), None)
    hourly = [s for s in summaries if s["summary_type"] == "hourly"]

    return templates.TemplateResponse("history.html", {
        "request": request,
        "selected_date": selected_date,
        "available_dates": available_dates,
        "daily_summary": daily,
        "hourly_summaries": hourly,
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    templates = request.app.state.templates
    config = request.app.state.config
    file_store = request.app.state.file_store
    llm = request.app.state.llm

    storage_stats = file_store.get_storage_stats()
    if hasattr(llm, 'is_available'):
        ollama_available = await llm.is_available()
        models = await llm.list_models() if ollama_available else []
    else:
        ollama_available = True
        models = ["Qwen2.5-VL-3B"]

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config,
        "storage_stats": storage_stats,
        "ollama_available": ollama_available,
        "models": models,
    })


# --- API Endpoints ---

@router.get("/api/timeline")
async def api_timeline(
    request: Request,
    date: str = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    db = request.app.state.db

    if date:
        start = f"{date}T00:00:00"
        end = f"{date}T23:59:59"
    else:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today.isoformat()
        end = datetime.now().isoformat()

    screenshots = await db.get_screenshots(start=start, end=end, limit=limit)
    windows = await db.get_window_events(start=start, end=end, limit=limit * 2)
    clips = await db.get_clipboard_events(start=start, end=end, limit=limit)

    return {
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "screenshots": screenshots,
        "window_events": windows,
        "clipboard_events": clips,
    }


@router.post("/api/search")
async def api_search(request: Request, body: SearchRequest):
    search_engine = request.app.state.search_engine
    results = await search_engine.search(body.query)
    return results


@router.get("/api/history")
async def api_history(
    request: Request,
    date: str = Query(default=None),
):
    """Return summaries + session/idle analysis for a given date."""
    db = request.app.state.db
    summarizer = request.app.state.summarizer

    selected_date = date or datetime.now().strftime("%Y-%m-%d")
    summaries = await db.get_summaries_by_date(selected_date)
    activity = await summarizer.get_day_activity(selected_date)

    return {
        "date": selected_date,
        "summaries": summaries,
        "sessions": activity["sessions"],
        "idle_periods": activity["idle_periods"],
        "total_active_min": activity["total_active_min"],
        "total_idle_min": activity["total_idle_min"],
    }


@router.get("/api/history/generate-daily")
async def api_generate_daily(
    request: Request,
    date: str = Query(...),
):
    """Generate (or regenerate) the daily summary for a specific date."""
    summarizer = request.app.state.summarizer
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return JSONResponse({"error": "Invalid date format, use YYYY-MM-DD"}, status_code=400)
    summary = await summarizer.generate_daily_summary(dt)
    return {"date": date, "summary": summary}


@router.get("/api/summary")
async def api_summary(
    request: Request,
    period: str = Query(default="last_hour"),
    refresh: bool = Query(default=False),
):
    summarizer = request.app.state.summarizer
    db = request.app.state.db

    # Return cached summary if recent enough (< 10 min old), unless refresh=true
    if not refresh:
        cached = await db.get_summaries(summary_type="recent", limit=1)
        if cached:
            from datetime import datetime
            generated_at = cached[0].get("generated_at", "")
            try:
                age = (datetime.now() - datetime.fromisoformat(generated_at)).total_seconds()
                if age < 600:  # 10 minutes
                    return {"period": period, "summary": cached[0]["summary_text"], "cached": True}
            except Exception:
                pass

    if period == "last_hour":
        summary = await summarizer.generate_recent_summary(minutes=60)
    elif period == "today":
        summary = await summarizer.generate_daily_summary(datetime.now())
    elif period == "yesterday":
        summary = await summarizer.generate_daily_summary(datetime.now() - timedelta(days=1))
    else:
        summary = await summarizer.generate_hourly_summary()

    return {"period": period, "summary": summary, "cached": False}


@router.get("/api/insights")
async def api_insights(
    request: Request,
    range: str = Query(default="today"),
):
    insights_engine = request.app.state.insights_engine

    now = datetime.now()
    if range == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif range == "week":
        start = (now - timedelta(weeks=1)).isoformat()
    elif range == "month":
        start = (now - timedelta(days=30)).isoformat()
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    metrics = await insights_engine.get_productivity_metrics(start=start)
    narrative = await insights_engine.generate_insights(start=start)

    return {"range": range, "metrics": metrics, "narrative": narrative}


@router.get("/api/topics")
async def api_topics(
    request: Request,
    range: str = Query(default="today"),
):
    insights_engine = request.app.state.insights_engine
    now = datetime.now()
    if range == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif range == "week":
        start = (now - timedelta(weeks=1)).isoformat()
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    topics = await insights_engine.get_topic_breakdown(start=start)
    return {"range": range, "topics": topics}


@router.get("/api/screenshot/{screenshot_id}")
async def api_screenshot(request: Request, screenshot_id: int):
    db = request.app.state.db
    cursor = await db.db.execute(
        "SELECT file_path FROM screenshots WHERE id = ?", (screenshot_id,)
    )
    row = await cursor.fetchone()
    if row and Path(row["file_path"]).exists():
        return FileResponse(row["file_path"], media_type="image/png")
    return JSONResponse({"error": "Screenshot not found"}, status_code=404)


@router.get("/api/status")
async def api_status(request: Request):
    llm = request.app.state.llm
    file_store = request.app.state.file_store

    # vision_worker (Qwen) doesn't have is_available/list_models — check gracefully
    if hasattr(llm, 'is_available'):
        ollama_available = await llm.is_available()
        models = await llm.list_models() if ollama_available else []
    else:
        ollama_available = True  # Qwen is always available if loaded
        models = ["Qwen2.5-VL-3B"]

    return {
        "ollama_available": ollama_available,
        "storage": file_store.get_storage_stats(),
        "models": models,
    }
