"""Tenant automation command models. This module does not open the relational store."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Events(_Input):
    event_type: str | None = Field(None, max_length=256)
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class WebhookCreate(BaseModel):
    name: str
    url: str
    events: list[str]
    is_active: bool = True


class WebhookUpdate(BaseModel):
    name: str
    url: str
    events: list[str]
    is_active: bool


class _Create(_Input):
    data: WebhookCreate


class _Key(_Input):
    id: str = Field(min_length=1, max_length=128)


class _Update(_Key):
    data: WebhookUpdate
