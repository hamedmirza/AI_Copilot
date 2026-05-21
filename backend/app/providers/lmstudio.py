import logging
import time
from typing import Any

import httpx

from app.core.enums import ProviderStatus
from app.core.exceptions import ProviderError
from app.providers.base import BaseProvider
from app.schemas.provider import ProviderHealthResponse

logger = logging.getLogger(__name__)


class LMStudioProvider(BaseProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=float(timeout_seconds), write=30.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def with_overrides(
        self,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> "LMStudioProvider":
        if provider_name and provider_name != "lmstudio":
            raise ProviderError(f"Unsupported provider: {provider_name}")
        return LMStudioProvider(
            self.base_url,
            self.api_key,
            model_name or self.model,
            timeout_seconds=int(self._client.timeout.read or 120),
        )

    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        model = (self.model or "").strip()
        if not model:
            raise ProviderError("LM Studio model is not configured")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"{user_prompt}\n\nReturn valid JSON only. No markdown fences.",
                },
            ],
        }
        try:
            response = self._client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return (content or "").strip()
        except httpx.HTTPError as exc:
            raise ProviderError(f"LM Studio request failed: {exc}") from exc

    def healthcheck(self) -> ProviderHealthResponse:
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            models = [item.get("id") for item in data.get("data", []) if isinstance(item, dict)]
            configured = (self.model or "").strip()
            if configured and configured in models:
                status = ProviderStatus.HEALTHY
                detail = "LM Studio reachable and configured model is listed."
            elif models:
                status = ProviderStatus.DEGRADED
                detail = "LM Studio reachable, configured model not listed."
            else:
                status = ProviderStatus.DEGRADED
                detail = "LM Studio reachable but no models returned."
            return ProviderHealthResponse(
                provider="lmstudio",
                status=status,
                detail=detail,
                model=self.model,
            )
        except httpx.HTTPError as exc:
            return ProviderHealthResponse(
                provider="lmstudio",
                status=ProviderStatus.UNREACHABLE,
                detail=f"LM Studio unreachable: {exc}",
                model=self.model,
            )

    def list_models(self) -> list[str]:
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            return sorted(
                str(item.get("id")) for item in data.get("data", []) if isinstance(item, dict)
            )
        except httpx.HTTPError:
            return []
