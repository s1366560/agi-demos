"""
SQLAlchemy TypeDecorators for Pydantic model serialization.

These decorators enable automatic validation and serialization of
Pydantic models stored in JSON columns.
"""

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import JSON
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

T = TypeVar("T", bound=BaseModel)


class PydanticType[T: BaseModel](TypeDecorator):
    """
    SQLAlchemy TypeDecorator for storing Pydantic models as JSON.

    Usage:
        class MyModel(Base):
            config: Mapped[MyConfig] = mapped_column(PydanticType(MyConfig))
    """

    impl = JSON
    cache_ok = True

    def __init__(self, pydantic_type: type[T], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pydantic_type = pydantic_type

    def process_bind_param(self, value: T | None, dialect: Dialect) -> dict | None:
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

    def process_result_value(self, value: dict | None, dialect: Dialect) -> T | None:
        """Convert stored dict back to Pydantic model."""
        if value is None:
            return None
        return self.pydantic_type.model_validate(value)


class PydanticListType[T: BaseModel](TypeDecorator):
    """
    SQLAlchemy TypeDecorator for storing lists of Pydantic models as JSON.

    Usage:
        class MyModel(Base):
            items: Mapped[List[MyItem]] = mapped_column(PydanticListType(MyItem))
    """

    impl = JSON
    cache_ok = True

    def __init__(self, pydantic_type: type[T], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pydantic_type = pydantic_type

    def process_bind_param(self, value: list[T] | None, dialect: Dialect) -> list[dict] | None:
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

    def process_result_value(self, value: list[dict] | None, dialect: Dialect) -> list[T] | None:
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

    def __init__(
        self, pydantic_type: type[BaseModel] | None = None, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.pydantic_type = pydantic_type

    def process_bind_param(self, value: Any, dialect: Dialect) -> dict | None:
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

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        """Return stored value as-is (dict)."""
        return value


# === Convenience Factories ===


def pydantic_column[T: BaseModel](pydantic_type: type[T]) -> PydanticType[T]:
    """Create a PydanticType column for a Pydantic model."""
    return PydanticType(pydantic_type)


def pydantic_list_column[T: BaseModel](pydantic_type: type[T]) -> PydanticListType[T]:
    """Create a PydanticListType column for a list of Pydantic models."""
    return PydanticListType(pydantic_type)


def validated_json_column(pydantic_type: type[BaseModel] | None = None) -> ValidatedJSON:
    """Create a ValidatedJSON column with optional validation."""
    return ValidatedJSON(pydantic_type)
