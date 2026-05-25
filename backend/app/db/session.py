import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

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
    resolved_url = _resolve_db_url(db_url)
    engine_kwargs = {
        "echo": False,
        "connect_args": {"check_same_thread": False, "timeout": 30},
    }
    if resolved_url == "sqlite:///:memory:":
        engine_kwargs["poolclass"] = StaticPool
    elif resolved_url.startswith("sqlite:///"):
        engine_kwargs["poolclass"] = NullPool
    built = create_engine(
        resolved_url,
        **engine_kwargs,
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


def _safe_execute_ddl(conn, statement: str) -> None:
    try:
        conn.execute(text(statement))
    except OperationalError as exc:
        if "duplicate column name" in str(exc).lower():
            return
        raise


def run_migrations() -> None:
    """Lightweight additive migrations without Alembic."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Example additive column migration
    if "projects" in existing and not _column_exists("projects", "protected_files_json"):
        with engine.begin() as conn:
            _safe_execute_ddl(conn, "ALTER TABLE projects ADD COLUMN protected_files_json TEXT DEFAULT '[]'")

    if _table_exists("chat_sessions"):
        with engine.begin() as conn:
            if not _column_exists("chat_sessions", "title"):
                _safe_execute_ddl(conn, "ALTER TABLE chat_sessions ADD COLUMN title VARCHAR(255) DEFAULT 'New Chat'")
            if not _column_exists("chat_sessions", "mode"):
                _safe_execute_ddl(conn, "ALTER TABLE chat_sessions ADD COLUMN mode VARCHAR(64) DEFAULT 'general'")
            if not _column_exists("chat_sessions", "model_override"):
                _safe_execute_ddl(conn, "ALTER TABLE chat_sessions ADD COLUMN model_override VARCHAR(255)")
            if not _column_exists("chat_sessions", "nothink"):
                _safe_execute_ddl(conn, "ALTER TABLE chat_sessions ADD COLUMN nothink BOOLEAN")

    if _table_exists("chat_messages"):
        with engine.begin() as conn:
            if not _column_exists("chat_messages", "tool_calls_json"):
                _safe_execute_ddl(conn, "ALTER TABLE chat_messages ADD COLUMN tool_calls_json TEXT DEFAULT '[]'")
            if not _column_exists("chat_messages", "tool_call_id"):
                _safe_execute_ddl(conn, "ALTER TABLE chat_messages ADD COLUMN tool_call_id VARCHAR(255)")
            if not _column_exists("chat_messages", "metadata_json"):
                _safe_execute_ddl(conn, "ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT DEFAULT '{}'")

    if _table_exists("runs"):
        with engine.begin() as conn:
            if not _column_exists("runs", "task_kind"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN task_kind VARCHAR(32)")
            if not _column_exists("runs", "operator_feedback"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN operator_feedback TEXT")
            if not _column_exists("runs", "promote_snapshot_json"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN promote_snapshot_json TEXT")
            if not _column_exists("runs", "failure_class"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN failure_class VARCHAR(64)")
            if not _column_exists("runs", "failure_subclass"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN failure_subclass VARCHAR(128)")
            if not _column_exists("runs", "failure_signature"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN failure_signature VARCHAR(255)")
            if not _column_exists("runs", "recovery_status"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN recovery_status VARCHAR(32)")
            if not _column_exists("runs", "superseded_by_run_id"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN superseded_by_run_id VARCHAR(36)")
            if not _column_exists("runs", "terminal_success"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN terminal_success BOOLEAN")
            if not _column_exists("runs", "terminal_status"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN terminal_status VARCHAR(64)")
            if not _column_exists("runs", "retry_count"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN retry_count INTEGER DEFAULT 0")
            if not _column_exists("runs", "schema_failure_count"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN schema_failure_count INTEGER DEFAULT 0")
            if not _column_exists("runs", "reviewer_failure_count"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN reviewer_failure_count INTEGER DEFAULT 0")
            if not _column_exists("runs", "tester_failure_count"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN tester_failure_count INTEGER DEFAULT 0")
            if not _column_exists("runs", "operator_feedback_present"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN operator_feedback_present BOOLEAN DEFAULT 0")
            if not _column_exists("runs", "approval_reached"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN approval_reached BOOLEAN DEFAULT 0")
            if not _column_exists("runs", "promote_rolled_back"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN promote_rolled_back BOOLEAN DEFAULT 0")
            if not _column_exists("runs", "primary_failure_class"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN primary_failure_class VARCHAR(64)")
            if not _column_exists("runs", "chat_session_id"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN chat_session_id VARCHAR(36)")
            if not _column_exists("runs", "deliverable_kind"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN deliverable_kind VARCHAR(32)")
            if not _column_exists("runs", "expected_targets_json"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN expected_targets_json TEXT DEFAULT '[]'")
            if not _column_exists("runs", "expected_validation_family"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN expected_validation_family VARCHAR(32)")
            if not _column_exists("runs", "readiness_json"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN readiness_json TEXT DEFAULT '{}'")
            if not _column_exists("runs", "mismatch_classes_json"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN mismatch_classes_json TEXT DEFAULT '[]'")
            if not _column_exists("runs", "approval_override"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN approval_override BOOLEAN DEFAULT 0")
            if not _column_exists("runs", "clarification_question"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN clarification_question TEXT")
            if not _column_exists("runs", "clarification_stage"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN clarification_stage VARCHAR(64)")
            if not _column_exists("runs", "clarification_context_json"):
                _safe_execute_ddl(conn, "ALTER TABLE runs ADD COLUMN clarification_context_json TEXT DEFAULT '{}'")

    if not _table_exists("run_thread_entries"):
        Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables["run_thread_entries"]])

    if _table_exists("tasks"):
        with engine.begin() as conn:
            if not _column_exists("tasks", "task_kind"):
                _safe_execute_ddl(conn, "ALTER TABLE tasks ADD COLUMN task_kind VARCHAR(32)")

    if _table_exists("mcp_servers"):
        with engine.begin() as conn:
            if not _column_exists("mcp_servers", "enabled"):
                _safe_execute_ddl(conn, "ALTER TABLE mcp_servers ADD COLUMN enabled BOOLEAN DEFAULT 1")
            if not _column_exists("mcp_servers", "last_status"):
                _safe_execute_ddl(conn, "ALTER TABLE mcp_servers ADD COLUMN last_status VARCHAR(64) DEFAULT 'unknown'")
            if not _column_exists("mcp_servers", "last_error"):
                _safe_execute_ddl(conn, "ALTER TABLE mcp_servers ADD COLUMN last_error TEXT")
            if not _column_exists("mcp_servers", "tool_count"):
                _safe_execute_ddl(conn, "ALTER TABLE mcp_servers ADD COLUMN tool_count INTEGER DEFAULT 0")


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
        "stop_on_first_failure": True,
        "model_planner": "qwen3.6-27b",
        "model_architect": "qwen3.6-27b",
        "model_ui_designer": "qwen3.6-27b",
        "model_coder": "qwen3.6-27b",
        "model_reviewer": "qwen3.6-27b",
        "model_tester": "qwen3.6-27b",
        "model_supervisor": "qwen3.6-27b",
        "model_chat": "qwen3.6-27b",
        "model_chat_agent": "qwen3.6-27b",
        "model_chat_planner": "qwen3.6-27b",
        "model_chat_debugger": "qwen3.6-27b",
        "model_chat_architect": "qwen3.6-27b",
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
        "learning_auto_trial_enabled": True,
        "learning_auto_promote_enabled": True,
        "learning_min_trial_runs": 3,
        "learning_min_success_rate_delta_pct": 10.0,
        "learning_max_harmful_rate_pct": 34.0,
        "learning_min_confidence": 0.65,
        "learning_unknown_failure_autopromote_enabled": False,
    }
    for key, value in defaults.items():
        db.add(AppConfigModel(key=key, value=str(value)))
    db.commit()
