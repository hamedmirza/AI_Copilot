#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import ProjectModel  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


SEED_ROOT = REPO_ROOT / "runtime" / "verification" / "cr019_manual_check"
MANIFEST_PATH = SEED_ROOT / "manifest.json"


def main() -> int:
    if not MANIFEST_PATH.exists():
        print("No CR-019 seed manifest found.")
        return 0

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        project = db.query(ProjectModel).filter(ProjectModel.id == manifest["project_id"]).first()
        if project:
            db.delete(project)
            db.commit()
    finally:
        db.close()

    for key in ("review_workspace", "resume_workspace", "source_repo"):
        path = Path(manifest[key])
        if path.exists():
            shutil.rmtree(path)

    if SEED_ROOT.exists():
        shutil.rmtree(SEED_ROOT)

    print("CR-019 manual verification seed cleaned up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
