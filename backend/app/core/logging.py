import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
worker_id_var: ContextVar[str | None] = ContextVar("worker_id", default=None)

ROOT_DIR = Path(__file__).resolve().parents[3]
LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "app.jsonl"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "request_id": request_id_var.get(),
            "run_id": run_id_var.get(),
            "worker_id": worker_id_var.get(),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["extra"] = {"exc_info": self.formatException(record.exc_info)}
        elif hasattr(record, "extra_data"):
            payload["extra"] = record.extra_data  # type: ignore[attr-defined]
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(JsonFormatter())
    root.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)


def new_request_id() -> str:
    return str(uuid.uuid4())[:8]


def read_log_lines(limit: int = 200) -> list[dict[str, Any]]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    result: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result
