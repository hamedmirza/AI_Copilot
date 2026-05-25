from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.api import router
from app.core.logging import setup_logging
from app.core.settings import get_settings
from app.db.session import SessionLocal, run_migrations, seed_app_config
from app.services.config_service import ConfigService
from app.services.orchestration_service import resume_inflight_runs, run_engine
from app.services.run_engine.event_bus import event_bus


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    settings = get_settings()
    setup_logging(settings.log_level)
    run_migrations()
    db = SessionLocal()
    try:
        seed_app_config(db)
        ConfigService(db).reload_registry()
    finally:
        db.close()
    loop = asyncio.get_running_loop()
    event_bus.set_loop(loop)
    run_engine.set_loop(loop)
    db = SessionLocal()
    try:
        worker_count = int(ConfigService(db).get_all().get("worker_count", 1))
        run_engine.configure_workers(worker_count)
        auto_resume = bool(ConfigService(db).get_all().get("auto_resume_enabled", True))
        if auto_resume:
            resume_inflight_runs(db, limit=1)
    finally:
        db.close()
    yield
    event_bus.set_loop(None)
    run_engine.set_loop(None)


app = FastAPI(title="AI Copilot", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def block_path_traversal(request: Request, call_next):
    raw = request.scope.get("raw_path", b"").decode("utf-8", errors="ignore")
    if ".." in raw or "%2e%2e" in raw.lower():
        return JSONResponse(status_code=400, content={"detail": "Path traversal not allowed"})
    return await call_next(request)


@app.middleware("http")
async def verify_token(request: Request, call_next):
    if request.url.path.startswith("/api/ws/"):
        return await call_next(request)

    if request.url.path.startswith("/api/") and not request.url.path.endswith("/health"):
        token = request.headers.get("X-Api-Token")
        if not token and request.url.path == "/api/browser/preview":
            token = request.query_params.get("token")
        try:
            from app.api.deps import verify_api_token_value

            verify_api_token_value(token)
        except Exception as exc:
            from fastapi import HTTPException

            if isinstance(exc, HTTPException):
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


app.include_router(router, prefix="/api")
