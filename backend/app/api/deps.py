from fastapi import Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.config_service import get_config_value


def verify_api_token(
    request: Request,
    x_api_token: str | None = Header(default=None, alias="X-Api-Token"),
) -> None:
    if request.url.path.endswith("/health") and request.method == "GET":
        return
    db = SessionLocal()
    try:
        expected = get_config_value(db, "api_token", "dev-token")
    finally:
        db.close()
    token = x_api_token or "dev-token"
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid API token")
