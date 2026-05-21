from abc import ABC, abstractmethod

from app.schemas.provider import ProviderHealthResponse


class BaseProvider(ABC):
    @abstractmethod
    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def healthcheck(self) -> ProviderHealthResponse:
        raise NotImplementedError

    def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return self.invoke_json(system_prompt, user_prompt)

    def list_models(self) -> list[str]:
        return []

    @property
    def name(self) -> str:
        return self.__class__.__name__
