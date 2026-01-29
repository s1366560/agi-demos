"""Persistence layer initialization."""

# Import session models to ensure they're registered with SQLAlchemy
from src.infrastructure.persistence.session_models import SessionModel, SessionMessageModel

__all__ = [
    "SessionModel",
    "SessionMessageModel",
]
