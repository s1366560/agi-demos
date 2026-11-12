"""Permission vocabulary and contribution documents for optional business plugins."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

CONTRIBUTION_SCHEMA = "memstack.plugin.contributions/1"
UNIMPLEMENTED_EXECUTORS = frozenset({"channels", "llm_providers", "workflows", "mcp"})
SLOT_UI_SCHEMA = "memstack.slot-ui/1"
INVOKE_INPUT_OFFSET = 0
INVOKE_OUTPUT_OFFSET = 65536
MAX_INVOKE_OUTPUT_BYTES = 65536

PERMISSIONS = frozenset(
    {
        "tools.execute",
        "skills.register",
        "ui.slot",
        "storage.read",
        "storage.write",
    }
)


class ContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class ToolContribution:
    name: str
    abi: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class SkillContribution:
    skill_id: str
    instructions: str
    permissions: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class UiContribution:
    slot: str
    path: str
    digest: str
    targets: frozenset[str]
    permissions: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class CommandContribution:
    command_id: str
    tool: str
    payload: dict[str, Any]
    permissions: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class StorageContribution:
    schema_version: int
    permissions: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class ContributionDocument:
    tools: tuple[ToolContribution, ...]
    skills: tuple[SkillContribution, ...]
    commands: tuple[CommandContribution, ...]
    ui: tuple[UiContribution, ...]
    storage: StorageContribution | None


@dataclass(frozen=True, kw_only=True)
class SlotUiDocument:
    title: str
    actions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, kw_only=True)
class ScanEvidence:
    """A scan result. Absence is unknown and is not a passing report."""

    status: str
    report_digest: str | None = None


def parse_contribution(payload: dict[str, Any]) -> ContributionDocument:
    if payload.get("schema") != CONTRIBUTION_SCHEMA:
        raise ContractError("contribution_schema", "unsupported contribution schema")
    missing = sorted(set(payload) & UNIMPLEMENTED_EXECUTORS)
    if missing:
        raise ContractError(
            "executor_unavailable",
            f"profile rejected unimplemented executors: {', '.join(missing)}",
        )
    tools = tuple(_tool(item) for item in _list(payload.get("tools", [])))
    skills = tuple(_skill(item) for item in _list(payload.get("skills", [])))
    commands = tuple(_command(item) for item in _list(payload.get("commands", [])))
    ui = tuple(_ui(item) for item in _list(payload.get("ui", [])))
    storage_payload = payload.get("storage")
    storage = None if storage_payload is None else _storage(storage_payload)
    declared = {permission for item in (*tools, *skills, *ui) for permission in item.permissions}
    if storage is not None:
        declared |= storage.permissions
    unknown = sorted(declared - PERMISSIONS)
    if unknown:
        raise ContractError("permission_unknown", f"unknown permissions: {', '.join(unknown)}")
    return ContributionDocument(
        tools=tools, skills=skills, commands=commands, ui=ui, storage=storage
    )


def parse_slot_ui(payload: dict[str, Any]) -> SlotUiDocument:
    if payload.get("schema") != SLOT_UI_SCHEMA:
        raise ContractError("slot_ui_schema", "unsupported slot ui schema")
    title = payload.get("title")
    if not isinstance(title, str) or not title or len(title) > 120:
        raise ContractError("slot_ui_title", "slot ui title is invalid")
    actions_raw = payload.get("actions", [])
    if not isinstance(actions_raw, list) or len(actions_raw) > 16:
        raise ContractError("slot_ui_actions", "slot ui actions are invalid")
    actions: list[tuple[str, str]] = []
    for item in actions_raw:
        if not isinstance(item, dict):
            raise ContractError("slot_ui_action", "slot ui action must be an object")
        action_id = item.get("id")
        label = item.get("label")
        if (
            not isinstance(action_id, str)
            or not action_id.isascii()
            or not action_id.replace("-", "").isalnum()
            or not isinstance(label, str)
            or not label
            or len(label) > 80
        ):
            raise ContractError("slot_ui_action", "slot ui action is invalid")
        actions.append((action_id, label))
    return SlotUiDocument(title=title, actions=tuple(actions))


def sha256_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def canonical_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ContractError("contribution_list", "contribution list is invalid")
    return value


def _permissions(value: object) -> frozenset[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ContractError("permissions", "permissions must be a non-empty string list")
    return frozenset(value)


def _tool(value: object) -> ToolContribution:
    if not isinstance(value, dict):
        raise ContractError("tool", "tool contribution must be an object")
    name = value.get("name")
    abi = value.get("abi")
    if not isinstance(name, str) or not name or abi not in {"invoke", "score"}:
        raise ContractError("tool", "tool name or abi is invalid")
    input_schema = value.get("input_schema")
    output_schema = value.get("output_schema")
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise ContractError("tool_schema", "tool schemas must be objects")
    return ToolContribution(
        name=name,
        abi=abi,
        input_schema=input_schema,
        output_schema=output_schema,
        permissions=_permissions(value.get("permissions")),
    )


def _command(value: object) -> CommandContribution:
    if not isinstance(value, dict):
        raise ContractError("command", "command contribution must be an object")
    command_id = value.get("id")
    tool = value.get("tool")
    payload = value.get("payload")
    if not isinstance(command_id, str) or not command_id or not isinstance(tool, str) or not tool:
        raise ContractError("command", "command id or tool is invalid")
    if not isinstance(payload, dict):
        raise ContractError("command", "command payload must be an object")
    return CommandContribution(
        command_id=command_id,
        tool=tool,
        payload=payload,
        permissions=_permissions(value.get("permissions")),
    )


def _skill(value: object) -> SkillContribution:
    if not isinstance(value, dict):
        raise ContractError("skill", "skill contribution must be an object")
    skill_id = value.get("id")
    instructions = value.get("instructions")
    if not isinstance(skill_id, str) or not skill_id:
        raise ContractError("skill", "skill id is invalid")
    if not isinstance(instructions, str) or not instructions or len(instructions) > 4000:
        raise ContractError("skill", "skill instructions are invalid")
    return SkillContribution(
        skill_id=skill_id,
        instructions=instructions,
        permissions=_permissions(value.get("permissions")),
    )


def _ui(value: object) -> UiContribution:
    if not isinstance(value, dict):
        raise ContractError("ui", "ui contribution must be an object")
    slot = value.get("slot")
    path = value.get("path")
    digest = value.get("digest")
    targets = value.get("targets")
    if slot not in {"tool_result_renderer", "settings_page", "conversation"}:
        raise ContractError("ui_slot", "ui slot is not supported")
    if not isinstance(path, str) or not path or ".." in path.split("/"):
        raise ContractError("ui_path", "ui path is invalid")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ContractError("ui_digest", "ui digest is invalid")
    if not isinstance(targets, list) or not set(targets) <= {"web", "desktop-renderer"}:
        raise ContractError("ui_target", "ui target plane is invalid")
    return UiContribution(
        slot=slot,
        path=path,
        digest=digest,
        targets=frozenset(targets),
        permissions=_permissions(value.get("permissions")),
    )


def _storage(value: object) -> StorageContribution:
    if not isinstance(value, dict):
        raise ContractError("storage", "storage contribution must be an object")
    schema_version = value.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
        raise ContractError("storage_schema", "storage schema_version must be a positive integer")
    return StorageContribution(
        schema_version=schema_version,
        permissions=_permissions(value.get("permissions")),
    )
