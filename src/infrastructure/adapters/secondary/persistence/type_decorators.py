"""
SQLAlchemy TypeDecorators for Pydantic model serialization.

These decorators enable automatic validation and serialization of
Pydantic models stored in JSON columns.
"""

from typing import Any, Generic, List, Optional, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import JSON
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

T = TypeVar("T", bound=BaseModel)


class PydanticType(TypeDecorator, Generic[T]):
    """
    SQLAlchemy TypeDecorator for storing Pydantic models as JSON.

    Usage:
        class MyModel(Base):
            config: Mapped[MyConfig] = mapped_column(PydanticType(MyConfig))
    """

    impl = JSON
    cache_ok = True

    def __init__(self, pydantic_type: Type[T], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pydantic_type = pydantic_type

    def process_bind_param(self, value: Optional[T], dialect: Dialect) -> Optional[dict]:
        """Convert Pydantic model to dict for storage."""
        if value is None:
            return None
        if isinstance(value, dict):
            # Validate dict through Pydantic model
            validated = self.pydantic_type.model_validate(value)
            return validated.model_dump(mode="json", by_alias=True)
        if isinstance(value, self.pydantic_type):
            return value.model_dump(mode="json", by_alias=True)
        raise ValueError(f"Expected {self.pydantic_type.__name__} or dict, got {type(value)}")

    def process_result_value(self, value: Optional[dict], dialect: Dialect) -> Optional[T]:
        """Convert stored dict back to Pydantic model."""
        if value is None:
            return None
        return self.pydantic_type.model_validate(value)


class PydanticListType(TypeDecorator, Generic[T]):
    """
    SQLAlchemy TypeDecorator for storing lists of Pydantic models as JSON.

    Usage:
        class MyModel(Base):
            items: Mapped[List[MyItem]] = mapped_column(PydanticListType(MyItem))
    """

    impl = JSON
    cache_ok = True

    def __init__(self, pydantic_type: Type[T], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pydantic_type = pydantic_type

    def process_bind_param(
        self, value: Optional[List[T]], dialect: Dialect
    ) -> Optional[List[dict]]:
        """Convert list of Pydantic models to list of dicts for storage."""
        if value is None:
            return None
        result = []
        for item in value:
            if isinstance(item, dict):
                validated = self.pydantic_type.model_validate(item)
                result.append(validated.model_dump(mode="json", by_alias=True))
            elif isinstance(item, self.pydantic_type):
                result.append(item.model_dump(mode="json", by_alias=True))
            else:
                raise ValueError(
                    f"Expected {self.pydantic_type.__name__} or dict, got {type(item)}"
                )
        return result

    def process_result_value(
        self, value: Optional[List[dict]], dialect: Dialect
    ) -> Optional[List[T]]:
        """Convert stored list of dicts back to list of Pydantic models."""
        if value is None:
            return None
        return [self.pydantic_type.model_validate(item) for item in value]


class ValidatedJSON(TypeDecorator):
    """
    SQLAlchemy TypeDecorator for JSON with optional Pydantic validation.

    This is a lighter-weight alternative that validates on write but
    returns plain dicts on read for better performance.

    Usage:
        class MyModel(Base):
            config: Mapped[dict] = mapped_column(ValidatedJSON(MyConfig))
    """

    impl = JSON
    cache_ok = True

    def __init__(self, pydantic_type: Optional[Type[BaseModel]] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pydantic_type = pydantic_type

    def process_bind_param(self, value: Any, dialect: Dialect) -> Optional[dict]:  # noqa: ANN401
        """Validate and convert value for storage."""
        if value is None:
            return None
        if self.pydantic_type is not None:
            if isinstance(value, dict):
                # Validate dict through Pydantic model
                validated = self.pydantic_type.model_validate(value)
                return validated.model_dump(mode="json", by_alias=True)
            if isinstance(value, self.pydantic_type):
                return value.model_dump(mode="json", by_alias=True)
        # Return as-is if no validation type or already a dict
        if isinstance(value, dict):
            return value
        raise ValueError(f"Expected dict, got {type(value)}")

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:  # noqa: ANN401
        """Return stored value as-is (dict)."""
        return value


# === Convenience Factories ===


def pydantic_column(pydantic_type: Type[T]) -> PydanticType[T]:
    """Create a PydanticType column for a Pydantic model."""
    return PydanticType(pydantic_type)


def pydantic_list_column(pydantic_type: Type[T]) -> PydanticListType[T]:
    """Create a PydanticListType column for a list of Pydantic models."""
    return PydanticListType(pydantic_type)


def validated_json_column(pydantic_type: Optional[Type[BaseModel]] = None) -> ValidatedJSON:
    """Create a ValidatedJSON column with optional validation."""
    return ValidatedJSON(pydantic_type)
