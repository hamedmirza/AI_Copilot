import json
import logging
from pathlib import Path
from typing import Any, TypeVar, get_args, get_origin

from pydantic import BaseModel

from app.agents.payload_normalize import loads_agent_json, normalize_agent_payload
from app.agents.skill_loader import (
    load_integrity_charter,
    load_pipeline_framework,
    load_role_skill,
    skill_key_from_prompt_filename,
)
from app.providers.base import BaseProvider

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SOFT_PROMPT_SKILL_LIMIT_BYTES = 8 * 1024


class BaseAgent:
    prompt_filename: str = ""
    skill_filename: str = ""

    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def _role_skill_key(self) -> str:
        if self.skill_filename:
            key = self.skill_filename.strip()
            return key.removesuffix(".md") if key.endswith(".md") else key
        return skill_key_from_prompt_filename(self.prompt_filename)

    def load_system_prompt(self) -> str:
        path = PROMPTS_DIR / self.prompt_filename
        prompt = path.read_text(encoding="utf-8").strip()
        parts = [prompt]
        skill_key = self._role_skill_key()
        skill = load_role_skill(skill_key) if skill_key else ""
        if skill:
            parts.append(skill)
        framework = load_pipeline_framework()
        if framework:
            parts.append(framework)
        integrity = load_integrity_charter()
        if integrity:
            parts.append(integrity)
        combined = "\n\n".join(parts)
        size = len(combined.encode("utf-8"))
        if size > _SOFT_PROMPT_SKILL_LIMIT_BYTES:
            logger.warning(
                "Agent %s system prompt+skill is %s bytes (soft limit %s)",
                type(self).__name__,
                size,
                _SOFT_PROMPT_SKILL_LIMIT_BYTES,
            )
        return combined

    def _example_for_annotation(self, annotation: Any) -> Any:
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is None:
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                return self._schema_example(annotation)
            if annotation is str:
                return "string"
            if annotation is bool:
                return False
            if annotation is int:
                return 1
            if annotation is float:
                return 1.0
            return "value"
        if origin in (list, tuple):
            inner = args[0] if args else str
            return [self._example_for_annotation(inner)]
        if origin is dict:
            return {"key": "value"}
        if str(origin).endswith("Union"):
            non_none = [arg for arg in args if arg is not type(None)]
            return self._example_for_annotation(non_none[0] if non_none else str)
        return "value"

    def _schema_example(self, schema: type[BaseModel]) -> dict[str, Any]:
        example: dict[str, Any] = {}
        for name, field in schema.model_fields.items():
            example[name] = self._example_for_annotation(field.annotation)
        return example

    def _schema_instruction(self, schema: type[SchemaT]) -> str:
        contract = {
            "schema_name": schema.__name__,
            "required_top_level_fields": list(schema.model_fields.keys()),
            "example_payload": self._schema_example(schema),
            "json_schema": schema.model_json_schema(),
        }
        return json.dumps(contract, indent=2)

    def _provider_output_rules(self) -> str:
        provider_name = type(self.provider).__name__.lower()
        common = (
            "Output rules:\n"
            "1. Return exactly one JSON object.\n"
            "2. Do not wrap the JSON in markdown fences.\n"
            "3. Do not add commentary before or after the JSON.\n"
            "4. Use the exact field names from the schema contract.\n"
            "5. Do not rename fields to aliases such as task, goal, id, name, status, patches, or blueprint.\n"
        )
        if "lmstudio" in provider_name:
            return (
                f"{common}"
                "6. LM Studio requirement: keep the response compact and schema-first.\n"
                "7. Do not emit status wrappers or partial reports outside the JSON object.\n"
                "8. If evidence is incomplete, say that in allowed string fields while still returning the exact schema.\n"
            )
        return common

    def run(self, user_prompt: str, schema: type[SchemaT]) -> SchemaT | None:
        system_prompt = self.load_system_prompt()
        system_with_rules = (
            f"{system_prompt}\n\n"
            f"{self._provider_output_rules()}\n"
            "You must satisfy the exact schema contract in the user message."
        )
        user_with_schema = (
            f"{user_prompt}\n\n"
            "Return JSON matching this schema exactly:\n"
            f"{self._schema_instruction(schema)}"
        )
        raw = self.provider.invoke_json(system_with_rules, user_with_schema)
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        payload = loads_agent_json(text)
        if isinstance(payload, dict):
            payload = normalize_agent_payload(schema.__name__, payload)
        return schema.model_validate(payload)
