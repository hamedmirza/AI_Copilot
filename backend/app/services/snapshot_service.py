from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.core.exceptions import NotFoundError, ValidationError

SNAPSHOTS_ROOT = Path(__file__).resolve().parents[3] / "runtime" / "snapshots"


def _snapshot_dir(run_id: str) -> Path:
    path = SNAPSHOTS_ROOT / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_promoted_files(run_id: str, source_repo: Path, paths: list[str]) -> dict:
    source = source_repo.resolve()
    if not source.exists():
        raise NotFoundError(f"Source repo not found: {source}")

    snapshot_dir = _snapshot_dir(run_id)
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for rel in paths:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            continue
        src_file = source / rel_path
        if not src_file.is_file():
            continue
        dest = snapshot_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest)
        copied.append(rel)

    metadata = {
        "paths": copied,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (snapshot_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return metadata


def restore_promoted_files(run_id: str, source_repo: Path, snapshot_meta: dict) -> int:
    source = source_repo.resolve()
    snapshot_dir = SNAPSHOTS_ROOT / run_id
    if not snapshot_dir.exists():
        raise ValidationError("No promotion snapshot found for this run")

    paths = snapshot_meta.get("paths") or []
    restored = 0
    for rel in paths:
        snap_file = snapshot_dir / rel
        if not snap_file.is_file():
            continue
        dest = source / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snap_file, dest)
        restored += 1

    shutil.rmtree(snapshot_dir, ignore_errors=True)
    return restored


def delete_snapshot(run_id: str) -> None:
    snapshot_dir = SNAPSHOTS_ROOT / run_id
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
