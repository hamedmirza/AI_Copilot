from fastapi import Header, HTTPException, Request, WebSocket, WebSocketException, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.config_service import get_config_value


def _expected_api_token() -> str:
    db = SessionLocal()
    try:
        return str(get_config_value(db, "api_token", "dev-token"))
    finally:
        db.close()


def verify_api_token_value(token: str | None) -> None:
    expected = _expected_api_token()
    provided = token or "dev-token"
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid API token")


def verify_api_token(
    request: Request,
    x_api_token: str | None = Header(default=None, alias="X-Api-Token"),
) -> None:
    if request.url.path.endswith("/health") and request.method == "GET":
        return
    verify_api_token_value(x_api_token)


def verify_websocket_token(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing API token",
        )
    try:
        verify_api_token_value(token)
    except HTTPException as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc.detail),
        ) from exc
