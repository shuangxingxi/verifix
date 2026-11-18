from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConfigChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: dict[str, object] = Field(min_length=1)
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    exemption: str = ""