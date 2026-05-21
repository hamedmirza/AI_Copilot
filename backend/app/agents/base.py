import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.providers.base import BaseProvider

SchemaT = TypeVar("SchemaT", bound=BaseModel)
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class BaseAgent:
    prompt_filename: str = ""

    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def load_system_prompt(self) -> str:
        path = PROMPTS_DIR / self.prompt_filename
        return path.read_text(encoding="utf-8").strip()

    def run(self, user_prompt: str, schema: type[SchemaT]) -> SchemaT | None:
        raw = self.provider.invoke_json(self.load_system_prompt(), user_prompt)
        payload = json.loads(raw)
        return schema.model_validate(payload)
