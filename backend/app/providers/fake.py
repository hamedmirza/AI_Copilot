import json
from typing import Callable

from app.core.enums import ProviderStatus
from app.providers.base import BaseProvider
from app.schemas.provider import ProviderHealthResponse


class FakeProvider(BaseProvider):
    """Deterministic provider for tests — returns preconfigured JSON payloads."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        default_response: str | None = None,
        model: str = "fake-model",
    ) -> None:
        self.responses = responses or {}
        self.default_response = default_response or "{}"
        self.model = model
        self.call_log: list[tuple[str, str]] = []
        self._review_attempt = 0

    def set_response_for_keyword(self, keyword: str, payload: dict) -> None:
        self.responses[keyword.lower()] = json.dumps(payload)

    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        self.call_log.append((system_prompt[:80], user_prompt[:200]))
        lower = user_prompt.lower()
        for key, response in self.responses.items():
            if key in lower or key in system_prompt.lower():
                return response
        if "reviewer" in system_prompt.lower():
            self._review_attempt += 1
            approved = self._review_attempt >= 3
            return json.dumps(
                {
                    "approved": approved,
                    "summary": "Review complete",
                    "issues": [] if approved else [{"severity": "warn", "file_path": "a.py", "message": "fix"}],
                    "suggestions": [],
                }
            )
        if "planner" in system_prompt.lower():
            return json.dumps(
                {
                    "summary": "Plan for task",
                    "steps": [
                        {
                            "step_id": "1",
                            "title": "Implement",
                            "description": "Do the work",
                            "acceptance_criteria": ["Tests pass"],
                        }
                    ],
                    "risks": [],
                }
            )
        if "architect" in system_prompt.lower():
            return json.dumps(
                {
                    "overview": "Architecture",
                    "modules": ["core"],
                    "file_changes": [
                        {"path": "main.py", "action": "modify", "rationale": "Add feature"}
                    ],
                    "dependencies": [],
                }
            )
        if "ui designer" in system_prompt.lower() or "ui_designer" in system_prompt.lower():
            if "frontend" not in lower:
                raise ValueError("skip_ui")
            return json.dumps(
                {
                    "layout_description": "Simple layout",
                    "components": [{"name": "App", "component_type": "page", "props": {}}],
                    "styling_notes": "Use tailwind",
                    "accessibility_notes": ["aria labels"],
                }
            )
        if "coder" in system_prompt.lower():
            return json.dumps(
                {
                    "summary": "Applied changes",
                    "file_changes": [
                        {
                            "path": "main.py",
                            "line_changes": [{"start_line": 1, "end_line": 1, "new_content": "# updated\n"}],
                        }
                    ],
                    "requires_operator_approval": False,
                }
            )
        if "tester" in system_prompt.lower():
            return json.dumps(
                {
                    "passed": True,
                    "summary": "Validation plan",
                    "commands": [{"command": "python3 -m compileall .", "description": "Syntax check"}],
                    "notes": [],
                }
            )
        if "supervisor" in system_prompt.lower() or "playbook" in system_prompt.lower():
            return json.dumps(
                {
                    "approved": True,
                    "summary": "Playbook approved",
                    "safety_concerns": [],
                    "required_changes": [],
                }
            )
        return self.default_response

    def healthcheck(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(
            provider="fake",
            status=ProviderStatus.HEALTHY,
            detail="Fake provider always healthy",
            model=self.model,
        )

    def list_models(self) -> list[str]:
        return ["fake-model"]
