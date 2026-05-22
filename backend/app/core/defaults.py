from __future__ import annotations

DEFAULT_VALIDATION_PROFILES: dict[str, list[str]] = {
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
