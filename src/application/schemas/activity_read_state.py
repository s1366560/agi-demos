"""Server-authoritative Activity read receipt contracts."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _ReadStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _normalize_utc_datetimes(cls, value: object) -> object:
        if not isinstance(value, datetime):
            return value
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ActivityReadEntry(_ReadStateModel):
    entry_id: str = Field(min_length=1, max_length=255)
    entry_revision: int = Field(ge=0)
    read_at: datetime


class UpdateActivityReadStateRequest(_ReadStateModel):
    expected_authority_revision: int | None = Field(default=None, ge=0)
    entries: list[ActivityReadEntry] = Field(max_length=500)


class ActivityReadStateResponse(_ReadStateModel):
    project_id: str
    entries: list[ActivityReadEntry]
    authority_revision: int = Field(ge=0)


__all__ = [
    "ActivityReadEntry",
    "ActivityReadStateResponse",
    "UpdateActivityReadStateRequest",
]
