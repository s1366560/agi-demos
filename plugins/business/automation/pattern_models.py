"""Workflow pattern command models. This module does not open the relational store."""

from pydantic import BaseModel, ConfigDict, Field


class ListPatterns(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=100)


class DeletePattern(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    pattern_id: str = Field(min_length=1, max_length=128)
