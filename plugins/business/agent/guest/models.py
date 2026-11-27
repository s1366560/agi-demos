"""Input models shared by guest commands. No host imports."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeviceConversationCreate(_Input):
    title: str = Field(min_length=1, max_length=500)
    execution_target: Literal["cloud", "local"] = "cloud"
    workspace_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")


class ConversationRename(_Input):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9_:-]{1,128}$")
    title: str = Field(min_length=1, max_length=500)
