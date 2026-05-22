import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.defaults import DEFAULT_VALIDATION_PROFILES
from app.core.settings import get_settings

ROOT_DIR = Path(__file__).resolve().parents[3]
SessionLocal = sessionmaker(autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        cursor.execute("PRAGMA journal_mode=DELETE")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _resolve_db_url(db_url: str) -> str:
    resolved = db_url
    if resolved.startswith("sqlite:///./"):
        rel = resolved.replace("sqlite:///./", "")
        db_file = ROOT_DIR / rel
        db_file.parent.mkdir(parents=True, exist_ok=True)
        resolved = f"sqlite:///{db_file}"
    return resolved


def _build_engine(db_url: str):
    built = create_engine(
        _resolve_db_url(db_url),
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )
    event.listen(built, "connect", _set_sqlite_pragma)
    return built


engine = _build_engine(get_settings().db_url)
SessionLocal.configure(bind=engine)


def reconfigure_engine(db_url: str | None = None) -> None:
    global engine

    next_url = db_url or get_settings().db_url
    previous_engine = engine
    previous_engine.dispose()
    engine = _build_engine(next_url)
    SessionLocal.configure(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _column_exists(table: str, column: str) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def _table_exists(table: str) -> bool:
    inspector = inspect(engine)
    return table in set(inspector.get_table_names())


def run_migrations() -> None:
    """Lightweight additive migrations without Alembic."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Example additive column migration
    if "projects" in existing and not _column_exists("projects", "protected_files_json"):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN protected_files_json TEXT DEFAULT '[]'"))

    if _table_exists("chat_sessions"):
        with engine.begin() as conn:
            if not _column_exists("chat_sessions", "title"):
                conn.execute(
                    text("ALTER TABLE chat_sessions ADD COLUMN title VARCHAR(255) DEFAULT 'New Chat'")
                )
            if not _column_exists("chat_sessions", "mode"):
                conn.execute(
                    text("ALTER TABLE chat_sessions ADD COLUMN mode VARCHAR(64) DEFAULT 'general'")
                )
            if not _column_exists("chat_sessions", "model_override"):
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN model_override VARCHAR(255)"))
            if not _column_exists("chat_sessions", "nothink"):
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN nothink BOOLEAN"))

    if _table_exists("chat_messages"):
        with engine.begin() as conn:
            if not _column_exists("chat_messages", "tool_calls_json"):
                conn.execute(
                    text("ALTER TABLE chat_messages ADD COLUMN tool_calls_json TEXT DEFAULT '[]'")
                )
            if not _column_exists("chat_messages", "tool_call_id"):
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN tool_call_id VARCHAR(255)"))
            if not _column_exists("chat_messages", "metadata_json"):
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT DEFAULT '{}'"))

    if _table_exists("runs"):
        with engine.begin() as conn:
            if not _column_exists("runs", "operator_feedback"):
                conn.execute(text("ALTER TABLE runs ADD COLUMN operator_feedback TEXT"))
            if not _column_exists("runs", "promote_snapshot_json"):
                conn.execute(text("ALTER TABLE runs ADD COLUMN promote_snapshot_json TEXT"))

    if _table_exists("mcp_servers"):
        with engine.begin() as conn:
            if not _column_exists("mcp_servers", "enabled"):
                conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN enabled BOOLEAN DEFAULT 1"))
            if not _column_exists("mcp_servers", "last_status"):
                conn.execute(
                    text("ALTER TABLE mcp_servers ADD COLUMN last_status VARCHAR(64) DEFAULT 'unknown'")
                )
            if not _column_exists("mcp_servers", "last_error"):
                conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN last_error TEXT"))
            if not _column_exists("mcp_servers", "tool_count"):
                conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN tool_count INTEGER DEFAULT 0"))


def seed_app_config(db: Session) -> None:
    from app.db.models import AppConfigModel

    if db.query(AppConfigModel).first():
        return

    bootstrap = get_settings()
    defaults = {
        "lmstudio_base_url": bootstrap.lmstudio_base_url,
        "lmstudio_api_key": bootstrap.lmstudio_api_key,
        "lmstudio_model": bootstrap.lmstudio_model or "",
        "ollama_base_url": "http://172.10.1.2:11434/v1",
        "ollama_model": "qwen3.6:latest",
        "ollama_enabled": False,
        "provider_timeout_seconds": 300,
        "auto_resume_enabled": True,
        "worker_count": 1,
        "max_review_retries": 3,
        "chat_history_limit": 50,
        "chat_max_context_tokens": 32768,
        "chat_max_output_tokens": 4096,
        "stop_on_first_failure": False,
        "model_planner": "qwen2.5-72b-instruct",
        "model_architect": "qwen2.5-coder-32b-instruct",
        "model_ui_designer": "qwen2.5-coder-32b-instruct",
        "model_coder": "qwen2.5-coder-32b-instruct",
        "model_reviewer": "qwen2.5-72b-instruct",
        "model_tester": "qwen2.5-coder-7b-instruct",
        "model_supervisor": "qwen2.5-72b-instruct",
        "model_chat": "qwen2.5-72b-instruct",
        "model_chat_agent": "qwen2.5-coder-32b-instruct",
        "model_chat_planner": "qwen2.5-72b-instruct",
        "model_chat_debugger": "qwen2.5-coder-32b-instruct",
        "model_chat_architect": "qwen2.5-72b-instruct",
        "chat_modes_json": "[]",
        "editor_font_size": 14,
        "editor_tab_size": 2,
        "editor_auto_save": False,
        "editor_auto_save_delay_ms": 2000,
        "git_author_name": "AI Copilot",
        "git_author_email": "copilot@local.dev",
        "api_token": bootstrap.app_api_token,
        "onboarding_completed": False,
        "allowed_git_hosts_json": json.dumps(["github.com", "gitlab.com"]),
        "validation_profiles_json": json.dumps(DEFAULT_VALIDATION_PROFILES),
    }
    for key, value in defaults.items():
        db.add(AppConfigModel(key=key, value=str(value)))
    db.commit()
