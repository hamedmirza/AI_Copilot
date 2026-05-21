import json
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings

settings = get_settings()
_db_url = settings.db_url
ROOT_DIR = Path(__file__).resolve().parents[3]
if _db_url.startswith("sqlite:///./"):
    rel = _db_url.replace("sqlite:///./", "")
    db_file = ROOT_DIR / rel
    db_file.parent.mkdir(parents=True, exist_ok=True)
    _db_url = f"sqlite:///{db_file}"

engine = create_engine(
    _db_url,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


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


def seed_app_config(db: Session) -> None:
    from app.db.models import AppConfigModel

    if db.query(AppConfigModel).first():
        return

    bootstrap = get_settings()
    defaults = {
        "lmstudio_base_url": bootstrap.lmstudio_base_url,
        "lmstudio_api_key": bootstrap.lmstudio_api_key,
        "lmstudio_model": bootstrap.lmstudio_model or "",
        "ollama_base_url": "http://127.0.0.1:11434/v1",
        "ollama_enabled": False,
        "provider_timeout_seconds": 120,
        "auto_resume_enabled": True,
        "worker_count": 1,
        "max_review_retries": 3,
        "stop_on_first_failure": False,
        "model_planner": "qwen2.5-72b-instruct",
        "model_architect": "qwen2.5-coder-32b-instruct",
        "model_ui_designer": "qwen2.5-coder-32b-instruct",
        "model_coder": "qwen2.5-coder-32b-instruct",
        "model_reviewer": "qwen2.5-72b-instruct",
        "model_tester": "qwen2.5-coder-7b-instruct",
        "model_supervisor": "qwen2.5-72b-instruct",
        "editor_font_size": 14,
        "editor_tab_size": 2,
        "editor_auto_save": False,
        "editor_auto_save_delay_ms": 2000,
        "git_author_name": "AI Copilot",
        "git_author_email": "copilot@local.dev",
        "api_token": bootstrap.app_api_token,
        "onboarding_completed": False,
        "allowed_git_hosts_json": json.dumps(["github.com", "gitlab.com"]),
        "validation_profiles_json": json.dumps(
            {
                "python": ["ruff check .", "mypy .", "pytest -q"],
                "react": ["npm --prefix frontend run lint", "npm --prefix frontend run build"],
                "fullstack": [
                    "ruff check .",
                    "pytest -q",
                    "npm --prefix frontend run build",
                ],
                "node": ["npm run lint", "npm run build"],
                "custom": [],
            }
        ),
    }
    for key, value in defaults.items():
        db.add(AppConfigModel(key=key, value=str(value)))
    db.commit()
