import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar

T = TypeVar("T")


@dataclass(kw_only=True)
class Entity(ABC):
    """
    Base class for Domain Entities.
    Entities have a unique identity that persists throughout their lifecycle.
    Equality is based on identity, not attributes.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique UUID string for entity identification."""
        return str(uuid.uuid4())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass(frozen=True)
class ValueObject(ABC):
    """
    Base class for Value Objects.
    Value Objects are immutable and defined by their attributes.
    Equality is based on all attributes.
    """


@dataclass(frozen=True)
class DomainEvent(ABC):
    """
    Base class for Domain Events.
    Events represent something that happened in the past.
    They are immutable and contain all necessary data.
    """

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class DomainException(Exception):
    """Base exception for all domain errors.

    Optional i18n attributes — when set, the exception handler will surface a
    locale-aware ``user_message`` rendered via ``gettext`` instead of the raw
    debugging string passed to ``__str__``. The internal ``args[0]`` text stays
    in English so logs remain locale-agnostic.

    Subclasses may either pass ``user_message=...`` to mark the exception
    message itself as a translatable English source string, or pass
    ``user_message=..., user_message_params={...}`` for placeholder formatting.
    """

    def __init__(
        self,
        message: str = "",
        *,
        user_message: str | None = None,
        user_message_params: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.user_message = user_message
        self.user_message_params = user_message_params or {}

    def localized_message(self) -> str | None:
        """Translate ``user_message`` using the active request locale.

        Returns ``None`` when no translatable user-facing message was attached;
        callers should then fall back to ``str(exc)``.
        """
        if not self.user_message:
            return None
        # Imported lazily to avoid pulling i18n into pure-domain test surfaces.
        from src.infrastructure.i18n import gettext as _

        translated = _(self.user_message)
        if self.user_message_params:
            try:
                return translated.format(**self.user_message_params)
            except (KeyError, IndexError):
                return translated
        return translated
