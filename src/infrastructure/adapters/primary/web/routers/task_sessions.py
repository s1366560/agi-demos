"""Request schemas for the Avernet-owned cloud task-session saga."""

from __future__ import annotations

import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.infrastructure.adapters.primary.web.routers.workspace_agent_policy import (
    PermissionMode,
    ReasoningEffort,
    RouteTarget,
)


class ExistingWorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["existing"]
    workspace_id: str


class CreateWorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["create"]
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    use_case: Literal["general", "programming", "conversation", "research", "operations"]
    collaboration_mode: Literal[
        "single_agent", "multi_agent_shared", "multi_agent_isolated", "autonomous"
    ]
    sandbox_code_root: str | None = None


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    capability_mode: Literal["work", "code"]


class ComposerContextItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["attachment", "agent", "skill", "plugin", "command", "thread"]
    resource_id: str = Field(min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=255)
    metadata: dict[str, str | int | float | bool | None] | None = None

    @field_validator("resource_id", "label")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("context item text cannot be empty")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(
        cls,
        value: dict[str, str | int | float | bool | None] | None,
    ) -> dict[str, str | int | float | bool | None] | None:
        if value is not None:
            encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
            if len(encoded) > 4 * 1024:
                raise ValueError("context item metadata is too large")
        return value


class InitialMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=100_000)
    context_items: list[ComposerContextItemInput] = Field(
        default_factory=list[ComposerContextItemInput],
        max_length=32,
    )

    @model_validator(mode="after")
    def validate_unique_context_items(self) -> Self:
        identities = {(item.kind, item.resource_id) for item in self.context_items}
        if len(identities) != len(self.context_items):
            raise ValueError("context_items cannot contain duplicate resources")
        return self


class WorkspacePolicySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    route: RouteTarget
    reasoning_effort: ReasoningEffort
    permission_mode: PermissionMode


class CreateTaskSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    workspace: ExistingWorkspaceInput | CreateWorkspaceInput = Field(discriminator="kind")
    conversation: ConversationInput
    initial_message: InitialMessageInput
    workspace_policy: WorkspacePolicySelection | None = None
