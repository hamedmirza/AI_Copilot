"""Execute visual checks via IDE browser control and persist visual_evidence artifacts."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ArtifactModel
from app.services.browser_control_service import browser_control
from app.services.run_engine.event_bus import event_bus
from app.services.workspace_dev_url import infer_dev_server_base

SCHEMA_VERSION = 2
_BACKEND_HEALTH = "http://127.0.0.1:8500/api/health"


def _curl_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return exc.code < 500, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def ensure_project_dev_server_ready(workspace: Path) -> tuple[bool, str]:
    """Verify the workspace frontend dev server responds."""
    base = infer_dev_server_base(workspace)
    ok, detail = _curl_ok(base)
    if ok:
        return True, f"Project dev server healthy at {base}"
    return False, f"Project dev server unavailable at {base}: {detail}. Start npm run dev in the workspace."


def ensure_copilot_backend_ready() -> tuple[bool, str]:
    ok, detail = _curl_ok(_BACKEND_HEALTH)
    return ok, detail


def _evidence_dir(workspace: Path, run_id: str) -> Path:
    dest = workspace / ".ai-copilot" / "runs" / run_id / "evidence"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _normalize_visual_url(url: str, workspace: Path) -> str:
    normalized = (url or infer_dev_server_base(workspace)).strip()
    if "127.0.0.1" in normalized:
        normalized = normalized.replace("127.0.0.1", "localhost")
    return normalized or infer_dev_server_base(workspace)


def _wait_for_browser_client(project_id: str) -> bool:
    loop = event_bus.loop
    if loop is None or loop.is_closed():
        return browser_control.has_client(project_id)
    future = asyncio.run_coroutine_threadsafe(browser_control.wait_for_client(project_id), loop)
    try:
        return bool(future.result(timeout=browser_control.BROWSER_WAIT_POLL_S + 10))
    except Exception:
        return browser_control.has_client(project_id)


def _browser_step(project_id: str, run_id: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
    return browser_control.execute_sync(project_id, action, args, run_id=run_id, timeout=45.0)


def _execute_browser_check(
    project_id: str,
    run_id: str,
    workspace: Path,
    check: dict,
    index: int,
    evidence_root: Path,
) -> dict:
    url = _normalize_visual_url(str(check.get("url") or ""), workspace)
    expected = str(check.get("expected") or "")
    description = str(check.get("description") or url)
    steps = list(check.get("steps") or [])
    step_log: list[dict] = []
    passed = True
    notes = ""

    nav = _browser_step(project_id, run_id, "navigate", {"url": url})
    step_log.append({"action": "navigate", "url": url, "ok": nav.get("ok"), "error": nav.get("error")})
    if not nav.get("ok"):
        return {
            "url": url,
            "description": description,
            "expected": expected,
            "passed": False,
            "notes": nav.get("error") or "navigate failed",
            "screenshot_path": None,
            "step_log": step_log,
        }

    wait = _browser_step(
        project_id,
        run_id,
        "wait_for",
        {"selector": "#root", "timeout_ms": 12000},
    )
    step_log.append({"action": "wait_for", "selector": "#root", "ok": wait.get("ok"), "error": wait.get("error")})
    if not wait.get("ok"):
        passed = False
        notes = wait.get("error") or "hydration wait failed"

    for step_idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "")
        args: dict[str, Any] = {}
        if step.get("selector"):
            args["selector"] = step.get("selector")
        if step.get("value") is not None:
            if action == "type":
                args["text"] = step.get("value")
            elif action == "wait":
                args["text"] = step.get("value")
            else:
                args["text"] = step.get("value")
        if step.get("timeout_ms"):
            args["timeout_ms"] = step.get("timeout_ms")
        if action == "assert_text" and step.get("value"):
            snap = _browser_step(project_id, run_id, "snapshot", {"selector": step.get("selector")})
            text = str((snap.get("result") or {}).get("visibleText") or "")
            ok = str(step.get("value")).lower() in text.lower()
            step_log.append({"action": action, "ok": ok, "value": step.get("value")})
            if not ok:
                passed = False
                notes = f"assert_text failed: {step.get('value')}"
            continue
        if action == "screenshot":
            action = "screenshot"
        elif action == "wait":
            action = "wait_for"
        elif action not in {"click", "type", "scroll_into_view", "screenshot", "wait_for"}:
            continue
        result = _browser_step(project_id, run_id, action, args)
        step_log.append({"action": action, "ok": result.get("ok"), "error": result.get("error"), "args": args})
        if not result.get("ok"):
            passed = False
            notes = result.get("error") or f"{action} failed"
            break

    snap = _browser_step(project_id, run_id, "snapshot", {})
    visible = str((snap.get("result") or {}).get("visibleText") or "")
    if expected.strip() and expected.lower() not in visible.lower():
        passed = False
        notes = notes or f"Expected text not found: {expected[:80]}"

    shot_path_rel: str | None = None
    shot = _browser_step(project_id, run_id, "screenshot", {})
    data_url = (shot.get("result") or {}).get("dataUrl") if shot.get("ok") else None
    if isinstance(data_url, str) and data_url.startswith("data:"):
        png_dest = evidence_root / f"check_{index}.png"
        try:
            browser_control.save_screenshot_data_url(data_url, png_dest)
            shot_path_rel = str(png_dest.relative_to(workspace)).replace("\\", "/")
        except (OSError, ValueError) as exc:
            passed = False
            notes = notes or f"screenshot save failed: {exc}"

    if not shot_path_rel and passed:
        passed = False
        notes = notes or "screenshot missing"

    return {
        "url": url,
        "description": description,
        "expected": expected,
        "passed": passed,
        "notes": notes or "ok",
        "screenshot_path": shot_path_rel,
        "step_log": step_log,
        "visible_text_preview": visible[:500],
    }


def execute_visual_checks(
    db: Session,
    run_id: str,
    workspace: Path,
    visual_checks: list[dict],
    *,
    project_id: str,
    require_pass: bool = True,
    emit=None,
) -> dict:
    del emit  # orchestration emits events
    project_ok, project_note = ensure_project_dev_server_ready(workspace)
    backend_ok, backend_note = ensure_copilot_backend_ready()
    evidence_root = _evidence_dir(workspace, run_id)
    results: list[dict] = []

    client_ready = _wait_for_browser_client(project_id)
    if not client_ready:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "passed": False,
            "browser_client_required": True,
            "server_preflight": {
                "project_dev": {"passed": project_ok, "notes": project_note},
                "copilot_backend": {"passed": backend_ok, "notes": backend_note},
            },
            "checks": [],
            "evidence_dir": str(evidence_root.relative_to(workspace)),
            "error": "Open AI Copilot IDE with this project loaded to complete visual verification.",
        }
        if require_pass or visual_checks:
            db.add(
                ArtifactModel(
                    run_id=run_id,
                    artifact_type="visual_evidence",
                    content_json=json.dumps(payload),
                )
            )
            db.commit()
        return payload

    all_passed = project_ok and backend_ok
    if not project_ok:
        all_passed = False

    for idx, check in enumerate(visual_checks):
        if not project_ok:
            results.append(
                {
                    "url": str(check.get("url") or ""),
                    "description": str(check.get("description") or ""),
                    "expected": str(check.get("expected") or ""),
                    "passed": False,
                    "notes": project_note,
                    "screenshot_path": None,
                    "step_log": [],
                }
            )
            continue
        row = _execute_browser_check(project_id, run_id, workspace, check, idx, evidence_root)
        if not row.get("passed"):
            all_passed = False
        results.append(row)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "passed": all_passed if visual_checks else True,
        "browser_client_required": False,
        "server_preflight": {
            "project_dev": {"passed": project_ok, "notes": project_note},
            "copilot_backend": {"passed": backend_ok, "notes": backend_note},
        },
        "checks": results,
        "evidence_dir": str(evidence_root.relative_to(workspace)),
    }
    if require_pass or results:
        db.add(
            ArtifactModel(
                run_id=run_id,
                artifact_type="visual_evidence",
                content_json=json.dumps(payload),
            )
        )
        db.commit()
    return payload


def load_visual_evidence(db: Session, run_id: str) -> dict | None:
    row = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "visual_evidence")
        .order_by(ArtifactModel.id.desc())
        .first()
    )
    if not row:
        return None
    try:
        data = json.loads(row.content_json)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def visual_evidence_passed(db: Session, run_id: str) -> bool:
    data = load_visual_evidence(db, run_id)
    if not data:
        return False
    if data.get("browser_client_required"):
        return False
    return bool(data.get("passed")) and all(
        c.get("passed") for c in (data.get("checks") or []) if isinstance(c, dict)
    )


def capture_visual_evidence(
    workspace: Path,
    run_id: str,
    visual_checks: list[dict],
    *,
    project_id: str,
) -> dict:
    """Run checks without DB persistence."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return execute_visual_checks(
            db,
            run_id,
            workspace,
            visual_checks,
            project_id=project_id,
            require_pass=False,
        )
    finally:
        db.close()


def save_visual_evidence_artifact(db: Session, run_id: str, payload: dict) -> None:
    db.add(
        ArtifactModel(
            run_id=run_id,
            artifact_type="visual_evidence",
            content_json=json.dumps(payload),
        )
    )
    db.commit()


def clear_visual_evidence_artifacts(db: Session, run_id: str) -> None:
    db.query(ArtifactModel).filter(
        ArtifactModel.run_id == run_id,
        ArtifactModel.artifact_type == "visual_evidence",
    ).delete()
    db.commit()
