from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import AppConfig
from src.storage.database import Database
from src.storage.file_store import FileStore
from src.llm.ollama_client import OllamaClient
from src.llm.summarizer import Summarizer
from src.llm.search import SearchEngine
from src.llm.insights import InsightsEngine

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"


def create_app(config: AppConfig, db: Database, file_store: FileStore, vision_worker=None, summary_llm=None) -> FastAPI:
    app = FastAPI(title="Desktop Activity Monitor", version="0.1.0")

    # Use summary_llm (always a real working LLM) for all text generation.
    # Fall back to Ollama if not provided. vision_worker is only for screenshot analysis.
    if summary_llm is not None:
        llm = summary_llm
    elif vision_worker is not None:
        llm = vision_worker
    else:
        llm = OllamaClient(
            base_url=config.llm.base_url,
            text_model=config.llm.text_model,
            vision_model=config.llm.vision_model,
        )

    summarizer = Summarizer(db, llm)
    search_engine = SearchEngine(db, llm)
    insights_engine = InsightsEngine(db, llm)

    # Store references on app state
    app.state.db = db
    app.state.file_store = file_store
    app.state.llm = llm
    app.state.summarizer = summarizer
    app.state.search_engine = search_engine
    app.state.insights_engine = insights_engine
    app.state.config = config

    # Templates
    templates = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))
    app.state.templates = templates

    # Static files
    static_dir = DASHBOARD_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Import and include routes
    from src.api.routes import router
    app.include_router(router)

    return app
