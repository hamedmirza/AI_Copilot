import json

from app.core.enums import ProviderStatus
from app.providers.base import BaseProvider, ChatCompletionResult, ChatStreamChunk, ChatToolCall
from app.schemas.provider import ProviderHealthResponse


class FakeProvider(BaseProvider):
    """Deterministic provider for tests — returns preconfigured JSON payloads."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        default_response: str | None = None,
        model: str = "fake-model",
        invoke_sequence: list[str] | None = None,
        review_approve_attempt: int = 3,
    ) -> None:
        self.responses = responses or {}
        self.default_response = default_response or "{}"
        self.model = model
        self.call_log: list[tuple[str, str]] = []
        self._review_attempt = 0
        self._review_approve_attempt = max(1, int(review_approve_attempt))
        self._invoke_sequence = list(invoke_sequence or [])

    def set_response_for_keyword(self, keyword: str, payload: dict) -> None:
        self.responses[keyword.lower()] = json.dumps(payload)

    @staticmethod
    def _schema_name_from_user_prompt(user_prompt: str) -> str:
        marker = '"schema_name": "'
        idx = user_prompt.find(marker)
        if idx < 0:
            return ""
        start = idx + len(marker)
        end = user_prompt.find('"', start)
        return user_prompt[start:end] if end > start else ""

    def _default_payload_for_schema(self, schema_name: str, user_prompt: str) -> str | None:
        lower = user_prompt.lower()
        if schema_name == "PlannerOutput":
            payload: dict = {
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
            if "debug" in lower or "diagnose" in lower or "investigate" in lower:
                payload["hypothesis"] = "Root cause is in the failing module import path"
                payload["repro_steps"] = ["Run pytest on the affected test module"]
            return json.dumps(payload)
        if schema_name == "ArchitectOutput":
            report_paths = (
                {
                    "overview": "Analysis architecture",
                    "modules": ["reports"],
                    "file_changes": [
                        {
                            "path": ".ai-copilot/reports/analysis.md",
                            "action": "create",
                            "rationale": "Capture findings",
                        }
                    ],
                    "dependencies": [],
                }
                if "analysis" in lower or "audit" in lower or "report" in lower
                else {
                    "overview": "Architecture",
                    "modules": ["core"],
                    "file_changes": [
                        {"path": "main.py", "action": "modify", "rationale": "Add feature"}
                    ],
                    "dependencies": [],
                }
            )
            if "frontend" in lower and "app.tsx" in lower:
                report_paths = {
                    "overview": "Frontend scaffold",
                    "modules": ["frontend"],
                    "file_changes": [
                        {"path": "frontend/package.json", "action": "create", "rationale": "Scaffold"},
                        {"path": "frontend/src/App.tsx", "action": "create", "rationale": "App shell"},
                    ],
                    "dependencies": [],
                }
            return json.dumps(report_paths)
        if schema_name == "UIDesignerOutput":
            from app.services.run_truth_service import description_implies_frontend_ui

            if not description_implies_frontend_ui(lower):
                raise ValueError("skip_ui")
            return json.dumps(
                {
                    "layout_description": "Simple layout",
                    "components": [{"name": "App", "component_type": "page", "props": {}}],
                    "styling_notes": "Use tailwind",
                    "accessibility_notes": ["aria labels"],
                }
            )
        if schema_name == "CoderOutput":
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
        if schema_name == "ReviewerOutput":
            self._review_attempt += 1
            approved = self._review_attempt >= self._review_approve_attempt
            return json.dumps(
                {
                    "approved": approved,
                    "summary": "Review complete",
                    "issues": [] if approved else [{"severity": "warn", "file_path": "a.py", "message": "fix"}],
                    "suggestions": [],
                }
            )
        if schema_name == "TesterOutput":
            return json.dumps(
                {
                    "passed": True,
                    "summary": "Validation plan",
                    "dry_run_steps": [{"command": "python3 -m compileall .", "description": "Dry-run syntax check"}],
                    "visual_checks": [],
                    "visual_checks_skip_reason": None,
                    "commands": [{"command": "python3 -m compileall .", "description": "Syntax check"}],
                    "notes": [],
                }
            )
        if schema_name == "SupervisorOutput":
            return json.dumps(
                {
                    "approved": True,
                    "summary": "Deployment matches plan",
                    "plan_gaps": [],
                    "doc_updates": [],
                }
            )
        if schema_name == "AppDesignOutput":
            return json.dumps(
                {
                    "app_summary": "Greenfield app design",
                    "entities": [{"name": "Item", "fields": ["id", "title"], "relationships": []}],
                    "api_endpoints": [
                        {"path": "/items", "method": "GET", "description": "List items", "auth_required": False}
                    ],
                    "stack": {
                        "language": "python",
                        "framework": "fastapi",
                        "database": "sqlite",
                        "auth_method": "token",
                        "ui_framework": "react",
                    },
                    "file_structure": ["backend/app/api/main.py", "frontend/src/App.tsx"],
                    "open_questions": [],
                    "assumptions": ["SQLite for persistence"],
                    "clarification_needed": False,
                    "question": "",
                }
            )
        if schema_name == "DocumentationOutput":
            return json.dumps(
                {
                    "changelog_entry": "Implemented task",
                    "readme_updated": False,
                    "readme_changes": [],
                    "change_request_resolution": "STATUS: IMPLEMENTED",
                    "architecture_delta": "Updated application behavior per task.",
                }
            )
        if schema_name == "PlaybookSupervisorOutput":
            destructive_without_rollback = "destructive" in lower and "without rollback" in lower
            return json.dumps(
                {
                    "approved": not destructive_without_rollback,
                    "summary": "Playbook rejected: missing rollback"
                    if destructive_without_rollback
                    else "Playbook approved",
                    "safety_concerns": ["Missing rollback steps"] if destructive_without_rollback else [],
                    "required_changes": ["Add rollback procedure"] if destructive_without_rollback else [],
                }
            )
        if schema_name == "AppDesignOutput":
            return json.dumps(
                {
                    "app_summary": "Greenfield application design",
                    "entities": [{"name": "Item", "fields": ["id", "title"], "relationships": []}],
                    "api_endpoints": [
                        {"path": "/api/items", "method": "GET", "description": "List items", "auth_required": False}
                    ],
                    "stack": {
                        "language": "python",
                        "framework": "fastapi",
                        "database": "sqlite",
                        "auth_method": "token",
                        "ui_framework": "react",
                    },
                    "file_structure": ["backend/app/api/main.py", "frontend/src/App.tsx"],
                    "open_questions": [],
                    "assumptions": ["SQLite for persistence"],
                }
            )
        if schema_name == "DocumentationOutput":
            return json.dumps(
                {
                    "summary": "Documentation updated",
                    "changelog_entry": "Implemented task changes",
                    "change_request_status": "implemented",
                    "readme_updated": False,
                    "architecture_notes": "Updated module map",
                }
            )
        return None

    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        self.call_log.append((system_prompt, user_prompt))
        if self._invoke_sequence:
            return self._invoke_sequence.pop(0)
        lower = user_prompt.lower()
        for key, response in self.responses.items():
            if key in lower:
                return response
        schema_name = self._schema_name_from_user_prompt(user_prompt)
        if schema_name:
            payload = self._default_payload_for_schema(schema_name, user_prompt)
            if payload is not None:
                return payload
        return self.default_response

    def invoke_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
        tool_choice: dict | str | None = None,
    ) -> ChatCompletionResult:
        system_prompt, user_prompt = self._build_react_prompt(messages, tools or [])
        parsed = self._parse_chat_json(self.invoke_json(system_prompt, user_prompt))
        return ChatCompletionResult(
            content=str(parsed.get("content") or ""),
            tool_calls=[
                ChatToolCall(
                    id=str(call.get("id") or "fake-tool"),
                    name=str(call.get("name") or ""),
                    arguments=call.get("arguments") or {},
                )
                for call in parsed.get("tool_calls", [])
                if call.get("name")
            ],
            finish_reason=str(parsed.get("finish_reason") or "stop"),
            raw={"text": parsed.get("content", "")},
        )

    def invoke_chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        tool_choice: dict | str | None = None,
    ):
        result = self.invoke_chat(
            messages, tools=tools, stream=False, max_tokens=max_tokens, tool_choice=tool_choice
        )
        if result.content:
            yield ChatStreamChunk(delta=result.content, finish_reason=result.finish_reason)
        if result.tool_calls:
            yield ChatStreamChunk(tool_calls=result.tool_calls, finish_reason=result.finish_reason)
        yield ChatStreamChunk(done=True, finish_reason=result.finish_reason or "stop")

    def healthcheck(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(
            provider="fake",
            status=ProviderStatus.HEALTHY,
            detail="Fake provider always healthy",
            model=self.model,
        )

    def list_models(self) -> list[str]:
        return ["fake-model"]
