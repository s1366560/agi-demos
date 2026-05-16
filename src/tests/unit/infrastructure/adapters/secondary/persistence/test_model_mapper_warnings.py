"""Regression tests for ORM mapper configuration."""

import warnings

import pytest
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import configure_mappers

from src.infrastructure.adapters.secondary.persistence import models as _models  # noqa: F401


@pytest.mark.unit
def test_orm_mappers_configure_without_sqlalchemy_warnings() -> None:
    """Relationship configuration should not emit SQLAlchemy mapper warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        configure_mappers()
