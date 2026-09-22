"""FastAPI server — create_app() mounts all routes and serves the UI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.logging_ import setup_logging, get_logger
from app.settings import get_settings


def create_app() -> FastAPI:
    s = get_settings()
    setup_logging(s.log_level)
    _log = get_logger("api.server")

    app = FastAPI(title="Marketing Insight Agent v2", docs_url="/api/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    web_dir = Path(__file__).resolve().parent.parent / "web"
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.get("/health", response_class=JSONResponse)
    async def health():
        return {"status": "ok"}

    @app.get("/readyz", response_class=JSONResponse)
    async def readyz():
        from app.data.db import check_connection
        from app.data.catalog import warmup
        db_ok = check_connection()
        dq_ok = True
        catalog_ok = True
        if db_ok:
            try:
                warmup()
            except Exception:
                catalog_ok = False
        status = "ok" if (db_ok and dq_ok and catalog_ok) else "degraded"
        code = 200 if status == "ok" else 503
        return JSONResponse(
            {"status": status, "db": "ok" if db_ok else "fail",
             "dq": "ok" if dq_ok else "fail", "catalog": "ok" if catalog_ok else "fail"},
            status_code=code,
        )

    from fastapi.responses import RedirectResponse

    @app.get("/", response_class=RedirectResponse)
    async def root_redirect():
        return RedirectResponse(url="/dashboard", status_code=302)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request):
        return templates.TemplateResponse(request, "dashboard_page.html", {})

    @app.get("/chat", response_class=HTMLResponse)
    async def chat_page(request: Request):
        return templates.TemplateResponse(request, "chat_page.html", {})

    @app.get("/chat/{conversation_id}", response_class=HTMLResponse)
    async def chat_conversation(request: Request, conversation_id: str):
        return templates.TemplateResponse(request, "chat_page.html", {"conversation_id": conversation_id})

    from app.api.dashboard import router as dashboard_router
    from app.api.chat import router as chat_router
    from app.api.admin import router as admin_router
    from app.api.invocations import router as invocations_router
    from app.api.conversations import router as conversations_router

    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(chat_router, prefix="/api", tags=["chat"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
    app.include_router(invocations_router, tags=["invocations"])
    app.include_router(conversations_router, prefix="/api", tags=["conversations"])

    @app.get("/api/trace/{trace_id}")
    async def get_trace(trace_id: str):
        from app.telemetry.trace import get_trace as _get
        result = _get(trace_id)
        if result is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return result

    @app.get("/{path:path}", response_class=HTMLResponse)
    async def spa_fallback(path: str, request: Request):
        """Catch-all for SPA routes — serve index.html for non-API paths."""
        return templates.TemplateResponse(request, "index.html", {"version": "1.0.0"})

    _log.info("FastAPI app created — profile=%s", s.profile)
    return app
