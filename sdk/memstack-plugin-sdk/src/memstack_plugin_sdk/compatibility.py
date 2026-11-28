"""Signature-covered, half-open ABI ranges for independent business packages."""

import json
import re

import rfc8785

HOST_ABI = (2, 0, 0)
LEGACY_V2_ABI = (2, 0, 0)
DESCRIPTOR = "compatibility.json"
SCHEMA = "memstack.host-compatibility/1"
DEFAULT_RANGE = {"min_inclusive": "2.0.0", "max_exclusive": "3.0.0"}


def _version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,9})(?:\.(?:0|[1-9][0-9]{0,9})){2}", value
    ):
        raise ValueError("invalid host ABI version")
    major, minor, patch = map(int, value.split("."))
    if max(major, minor, patch) > 0xFFFFFFFF:
        raise ValueError("invalid host ABI version")
    return major, minor, patch


def _range(value: object) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if not isinstance(value, dict) or set(value) != {"min_inclusive", "max_exclusive"}:
        raise ValueError("host ABI range requires min_inclusive and max_exclusive")
    lower, upper = _version(value["min_inclusive"]), _version(value["max_exclusive"])
    if lower >= upper:
        raise ValueError("host ABI range must be nonempty")
    return lower, upper


def build_compatibility(value: object) -> bytes:
    lower, upper = _range(value)
    return rfc8785.dumps(
        {
            "schema": SCHEMA,
            "min_inclusive": ".".join(map(str, lower)),
            "max_exclusive": ".".join(map(str, upper)),
        }
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate host ABI descriptor field")
    return fields


def require_compatible(descriptor: bytes | None, host_abi: tuple[int, int, int] = HOST_ABI) -> None:
    if descriptor is None:
        if host_abi != LEGACY_V2_ABI:
            raise ValueError("package requires the legacy host ABI 2.0.0")
        return
    if len(descriptor) > 1024:
        raise ValueError("host ABI descriptor exceeds 1024 bytes")
    try:
        value = json.loads(descriptor.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as e:
        raise ValueError("invalid host ABI descriptor") from e
    if not isinstance(value, dict) or value.pop("schema", None) != SCHEMA:
        raise ValueError("unknown host ABI descriptor schema")
    lower, upper = _range(value)
    if not lower <= host_abi < upper:
        raise ValueError(
            f"incompatible host ABI, requires [{value['min_inclusive']}, {value['max_exclusive']})"
        )
