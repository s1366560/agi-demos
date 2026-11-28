"""Billing command models. This module does not open the relational store."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _AccountView(_AccountRequest):
    full_history: bool = False


class _Plan(_AccountRequest):
    plan: Literal["free", "pro", "enterprise"]
