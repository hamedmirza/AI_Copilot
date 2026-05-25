from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Heuristic limits based on LM Studio size_bytes + loaded footprint (no host RAM API).
MAX_SINGLE_MODEL_BYTES = 36 * 1024**3
HIGH_LOADED_BYTES = 32 * 1024**3
ELEVATED_LOADED_BYTES = 20 * 1024**3

MODE_PATTERN_GROUPS: dict[str, list[str]] = {
    "general": ["qwen3.6-27b", "qwen3", "instruct", "gpt-oss", "72b", "32b", "27b", "20b"],
    "agent": ["qwen3-coder", "coder-next", "coder", "qwen3.6", "32b", "27b"],
    "planner": ["qwen3", "72b", "instruct", "35b", "27b", "planner"],
    "debugger": ["qwen3-coder", "coder", "debugger", "32b", "27b"],
    "architect": ["qwen3", "72b", "instruct", "35b", "27b", "architect"],
}

SETTINGS_ROLE_KEYS: dict[str, str] = {
    "model_planner": "planner",
    "model_architect": "agent",
    "model_ui_designer": "agent",
    "model_coder": "agent",
    "model_reviewer": "general",
    "model_tester": "agent",
    "model_supervisor": "general",
    "model_chat": "general",
    "model_chat_agent": "agent",
    "model_chat_planner": "planner",
    "model_chat_debugger": "debugger",
    "model_chat_architect": "architect",
}


@dataclass
class LMStudioModelRecord:
    id: str
    state: str = "not-loaded"
    size_bytes: int = 0
    loaded_instances: list[str] = field(default_factory=list)
    tool_use: bool = False
    params_string: str = ""
    quantization: str = ""

    @property
    def is_loaded(self) -> bool:
        return self.state == "loaded" or bool(self.loaded_instances)

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024**3), 2) if self.size_bytes else 0.0


@dataclass
class LMStudioResourceSnapshot:
    loaded_count: int
    loaded_size_bytes: int
    catalog_count: int

    @property
    def loaded_size_gb(self) -> float:
        return round(self.loaded_size_bytes / (1024**3), 2)

    @property
    def pressure(self) -> str:
        if self.loaded_size_bytes >= HIGH_LOADED_BYTES or self.loaded_count >= 3:
            return "high"
        if self.loaded_size_bytes >= ELEVATED_LOADED_BYTES or self.loaded_count >= 2:
            return "elevated"
        return "ok"


@dataclass
class LMStudioCatalog:
    models: list[LMStudioModelRecord]

    def by_id(self) -> dict[str, LMStudioModelRecord]:
        return {item.id: item for item in self.models}

    def ids(self) -> list[str]:
        return [item.id for item in self.models]

    def resources(self) -> LMStudioResourceSnapshot:
        loaded = [item for item in self.models if item.is_loaded]
        return LMStudioResourceSnapshot(
            loaded_count=len(loaded),
            loaded_size_bytes=sum(item.size_bytes for item in loaded),
            catalog_count=len(self.models),
        )

    def loaded_instance_ids(self, *, except_model: str | None = None) -> list[str]:
        instances: list[str] = []
        for item in self.models:
            if except_model and item.id == except_model:
                continue
            instances.extend(item.loaded_instances)
        return instances

    def pick_best(self, mode: str, *, require_tool_use: bool = True) -> str | None:
        if not self.models:
            return None
        patterns = MODE_PATTERN_GROUPS.get(mode, MODE_PATTERN_GROUPS["general"])
        scored: list[tuple[float, str]] = []
        for item in self.models:
            if require_tool_use and not item.tool_use:
                continue
            score = _score_record(item, patterns)
            if score is None:
                continue
            scored.append((score, item.id))
        if not scored:
            for item in self.models:
                score = _score_record(item, patterns, ignore_tool_use=True)
                if score is not None:
                    scored.append((score, item.id))
        if not scored:
            return self.models[0].id
        scored.sort(reverse=True)
        return scored[0][1]

    def resolve_runnable(
        self,
        requested: str,
        mode: str,
        *,
        require_tool_use: bool = True,
    ) -> tuple[str, list[str]]:
        """Return model id to use and instance ids that should be unloaded first."""
        target = (requested or "").strip()
        catalog = self.by_id()
        if not target or target.lower() == "auto":
            best = self.pick_best(mode, require_tool_use=require_tool_use)
            return (best or "", [])

        record = catalog.get(target)
        if record is None:
            best = self.pick_best(mode, require_tool_use=require_tool_use)
            return (best or target, [])

        if record.is_loaded:
            return target, []

        resources = self.resources()
        if record.size_bytes >= MAX_SINGLE_MODEL_BYTES:
            fallback = self.pick_best(mode, require_tool_use=require_tool_use)
            if fallback and fallback != target:
                fallback_record = catalog.get(fallback)
                fallback_unload = (
                    self.loaded_instance_ids()
                    if fallback_record and not fallback_record.is_loaded
                    else self.loaded_instance_ids(except_model=fallback)
                )
                return fallback, fallback_unload

        unload: list[str] = []
        if resources.loaded_count > 0 and (
            resources.loaded_size_bytes + record.size_bytes > HIGH_LOADED_BYTES
            or record.size_bytes >= ELEVATED_LOADED_BYTES
        ):
            unload = self.loaded_instance_ids(except_model=target)

        return target, unload

    def recommendations(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for settings_key, mode in SETTINGS_ROLE_KEYS.items():
            best = self.pick_best(mode)
            if best:
                out[settings_key] = best
        return out


def _score_record(
    item: LMStudioModelRecord,
    patterns: list[str],
    *,
    ignore_tool_use: bool = False,
) -> float | None:
    lowered = item.id.lower()
    pattern_score = 0.0
    for index, pattern in enumerate(patterns):
        if pattern.lower() in lowered:
            pattern_score = max(pattern_score, 80.0 - index * 8.0)
    if pattern_score == 0.0 and not item.is_loaded:
        pattern_score = 5.0
    elif pattern_score == 0.0:
        pattern_score = 10.0

    score = pattern_score
    if item.is_loaded:
        score += 200.0
    if item.tool_use or ignore_tool_use:
        score += 15.0
    elif not ignore_tool_use:
        return None
    score -= item.size_bytes / (1024**3) * 2.0
    return score


def merge_catalog_payload(v0_models: list[dict[str, Any]], v1_models: list[dict[str, Any]]) -> LMStudioCatalog:
    v1_by_key = {str(item.get("key") or ""): item for item in v1_models if item.get("key")}
    records: list[LMStudioModelRecord] = []
    seen: set[str] = set()

    for item in v0_models:
        model_id = str(item.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        v1_raw = v1_by_key.get(model_id)
        v1 = v1_raw if isinstance(v1_raw, dict) else {}
        caps_value = v1.get("capabilities")
        caps = caps_value if isinstance(caps_value, dict) else {}
        quant_value = v1.get("quantization")
        quant = quant_value if isinstance(quant_value, dict) else item.get("quantization")
        loaded_instances = [
            str(inst.get("id") or "")
            for inst in (v1.get("loaded_instances") or [])
            if isinstance(inst, dict) and inst.get("id")
        ]
        records.append(
            LMStudioModelRecord(
                id=model_id,
                state=str(item.get("state") or ("loaded" if loaded_instances else "not-loaded")),
                size_bytes=int(v1.get("size_bytes") or 0),
                loaded_instances=loaded_instances,
                tool_use=bool(caps.get("trained_for_tool_use") or "tool_use" in (item.get("capabilities") or [])),
                params_string=str(v1.get("params_string") or ""),
                quantization=str(quant.get("name") if isinstance(quant, dict) else quant or ""),
            )
        )

    for key, v1 in v1_by_key.items():
        if key in seen:
            continue
        seen.add(key)
        caps_value = v1.get("capabilities")
        caps = caps_value if isinstance(caps_value, dict) else {}
        quant_value = v1.get("quantization")
        quant = quant_value if isinstance(quant_value, dict) else {}
        loaded_instances = [
            str(inst.get("id") or "")
            for inst in (v1.get("loaded_instances") or [])
            if isinstance(inst, dict) and inst.get("id")
        ]
        records.append(
            LMStudioModelRecord(
                id=key,
                state="loaded" if loaded_instances else "not-loaded",
                size_bytes=int(v1.get("size_bytes") or 0),
                loaded_instances=loaded_instances,
                tool_use=bool(caps.get("trained_for_tool_use")),
                params_string=str(v1.get("params_string") or ""),
                quantization=str(quant.get("name") if isinstance(quant, dict) else ""),
            )
        )

    records.sort(key=lambda item: item.id.lower())
    return LMStudioCatalog(models=records)
