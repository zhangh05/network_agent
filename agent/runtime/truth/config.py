# agent/runtime/truth/config.py
"""ConfigTruth — snapshot of model and runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConfigSnapshot:
    model_provider: str = ""
    model_name: str = ""
    runtime_mode: str = "standard"
    max_steps: int = 0
    workspace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ConfigTruth:
    """Extract config truth from ctx."""

    def snapshot(self, ctx) -> ConfigSnapshot:
        model_config = getattr(ctx, "model_config", None) or {}
        return ConfigSnapshot(
            model_provider=model_config.get("provider_type", ""),
            model_name=model_config.get("model", ""),
            runtime_mode="standard",
            max_steps=model_config.get("max_steps", 0),
            workspace_id=getattr(ctx, "workspace_id", ""),
        )
