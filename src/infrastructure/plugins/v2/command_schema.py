"""Draft 2020-12 checks for signed command documents."""

from typing import Any

import jsonschema
from jsonschema.exceptions import SchemaError, ValidationError

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


def validate_command_document(schema: dict[str, Any], value: object, code: str) -> None:
    if not isinstance(value, dict):
        raise OptionalBusinessError(code, "command value must be an object")
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except SchemaError as error:
        raise OptionalBusinessError("invalid_package", error.message) from error
    except ValidationError as error:
        raise OptionalBusinessError(code, error.message) from error
