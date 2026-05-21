import httpx

from app.core.enums import ProviderStatus
from app.core.exceptions import ProviderError
from app.providers.base import BaseProvider
from app.schemas.provider import ProviderHealthResponse


class OllamaProvider(BaseProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=float(timeout_seconds), write=30.0, pool=5.0),
        )

    def with_overrides(
        self,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> "OllamaProvider":
        if provider_name and provider_name != "ollama":
            raise ProviderError(f"Unsupported provider: {provider_name}")
        return OllamaProvider(
            self.base_url,
            model_name or self.model,
            timeout_seconds=int(self._client.timeout.read or 120),
        )

    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        model = (self.model or "").strip()
        if not model:
            raise ProviderError("Ollama model is not configured")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{user_prompt}\n\nReturn valid JSON only."},
            ],
        }
        response = self._client.post(url, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def healthcheck(self) -> ProviderHealthResponse:
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url)
            response.raise_for_status()
            data = response.json()
            models = [item.get("id") for item in data.get("data", []) if isinstance(item, dict)]
            status = ProviderStatus.HEALTHY if models else ProviderStatus.DEGRADED
            return ProviderHealthResponse(
                provider="ollama",
                status=status,
                detail="Ollama reachable.",
                model=self.model,
            )
        except httpx.HTTPError as exc:
            return ProviderHealthResponse(
                provider="ollama",
                status=ProviderStatus.UNREACHABLE,
                detail=f"Ollama unreachable: {exc}",
                model=self.model,
            )

    def list_models(self) -> list[str]:
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url)
            response.raise_for_status()
            data = response.json()
            return sorted(
                str(item.get("id")) for item in data.get("data", []) if isinstance(item, dict)
            )
        except httpx.HTTPError:
            return []
