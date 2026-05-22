from __future__ import annotations

import json
from typing import Any

from app.providers.registry import ProviderRegistry
from app.services.lmstudio_catalog import SETTINGS_ROLE_KEYS

ROLE_KEYS = tuple(SETTINGS_ROLE_KEYS.keys())


def _parse_snapshot(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).strip() for k, v in data.items() if str(v).strip()}


def _snapshot_key(provider: str) -> str:
    return f"{provider}_role_models_json"


def _snapshot_current_roles(config: dict[str, Any]) -> dict[str, str]:
    return {key: str(config.get(key, "")).strip() for key in ROLE_KEYS if str(config.get(key, "")).strip()}


def _recommendations_for_provider(config: dict[str, Any], provider: str) -> dict[str, str]:
    temp = {**config, "ollama_enabled": provider == "ollama"}
    registry = ProviderRegistry.get()
    registry.reload(temp)
    if provider == "ollama":
        return registry._list_ollama_models_detailed().recommendations or {}
    catalog = registry.get_lmstudio_catalog(refresh=True)
    return catalog.recommendations() if catalog is not None else {}


def build_provider_switch_updates(
    config: dict[str, Any],
    *,
    from_provider: str,
    to_provider: str,
) -> dict[str, Any]:
    """Save role models for the leaving provider; restore or recommend for the entering one."""
    if from_provider == to_provider:
        return {}

    updates: dict[str, Any] = {}
    updates[_snapshot_key(from_provider)] = _snapshot_current_roles(config)

    saved = _parse_snapshot(config.get(_snapshot_key(to_provider)))
    role_values = saved if saved else _recommendations_for_provider(
        {**config, **updates, "ollama_enabled": to_provider == "ollama"},
        to_provider,
    )

    for key in ROLE_KEYS:
        value = str(role_values.get(key, "")).strip()
        if value:
            updates[key] = value

    updates["ollama_enabled"] = to_provider == "ollama"
    return updates


def sync_active_provider_role_models(config: dict[str, Any], provider: str) -> dict[str, str]:
    """Re-apply saved or recommended role models for the given provider (no provider flip)."""
    saved = _parse_snapshot(config.get(_snapshot_key(provider)))
    role_values = saved if saved else _recommendations_for_provider(
        {**config, "ollama_enabled": provider == "ollama"},
        provider,
    )
    updates: dict[str, str] = {}
    for key in ROLE_KEYS:
        value = str(role_values.get(key, "")).strip()
        if value:
            updates[key] = value
    return updates
