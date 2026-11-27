"""Permission vocabulary and contribution documents for optional business plugins."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .rich_pages import RichPage, parse_rich_pages

CONTRIBUTION_SCHEMA = "memstack.plugin.contributions/1"
UNIMPLEMENTED_EXECUTORS = frozenset({"channels", "llm_providers", "workflows", "mcp"})
SLOT_UI_SCHEMA = "memstack.slot-ui/1"
INVOKE_INPUT_OFFSET = 0
INVOKE_OUTPUT_OFFSET = 65536
MAX_INVOKE_OUTPUT_BYTES = 65536

PERMISSIONS = frozenset(
    {
        "tools.execute",
        "services.provide",
        "services.call",
        "graph.projection.compute",
        "agent.loop.drive",
        "model.chat.adapt",
        "model.chat.adapt.openai",
        "model.chat.adapt.deepseek",
        "skills.register",
        "subagents.register",
        "ui.slot",
        "ui.media.microphone",
        "storage.read",
        "storage.write",
    }
)


# Trusted application runtimes register individual named operations. Each operation
# requires an exact project approval, including capabilities added after host build.
_APPLICATION_CAPABILITY = re.compile(r"app(?:\.[a-z][a-z0-9_]{0,31}){2,6}")


def is_application_capability(name: str) -> bool:
    return _APPLICATION_CAPABILITY.fullmatch(name) is not None


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
    description: str = ""
    service_aliases: frozenset[str] = frozenset()


@dataclass(frozen=True, kw_only=True)
class SkillContribution:
    skill_id: str
    instructions: str
    permissions: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class SubAgentContribution:
    agent_id: str
    name: str
    description: str
    instructions: str
    tools: tuple[str, ...]
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
    scope: str = "shared"
    accepts_input: bool = False
    command_id: str
    host_operation: str | None = None
    tool: str
    payload: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
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
    subagents: tuple[SubAgentContribution, ...] = ()
    pages: tuple[RichPage, ...] = ()


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
    unknown_sections = payload.keys() - {
        "schema",
        "tools",
        "skills",
        "subagents",
        "commands",
        "ui",
        "storage",
        "pages",
    }
    if unknown_sections:
        raise ContractError(
            "contribution_unknown",
            f"unsupported contribution fields: {', '.join(sorted(unknown_sections))}",
        )
    tools = tuple(_tool(item) for item in _list(payload.get("tools", [])))
    skills = tuple(_skill(item) for item in _list(payload.get("skills", [])))
    subagents = tuple(_subagent(item) for item in _list(payload.get("subagents", [])))
    identifiers = {agent.agent_id for agent in subagents}
    package_tools = {tool.name for tool in tools}
    if len(identifiers) != len(subagents) or any(
        not set(agent.tools) <= package_tools for agent in subagents
    ):
        raise ContractError("subagent", "duplicate SubAgent id or undeclared package tool")
    commands = tuple(_command(item) for item in _list(payload.get("commands", [])))
    ui = tuple(_ui(item) for item in _list(payload.get("ui", [])))
    storage_payload = payload.get("storage")
    storage = None if storage_payload is None else _storage(storage_payload)
    exports: tuple[
        ToolContribution | SkillContribution | SubAgentContribution | UiContribution, ...
    ] = (*tools, *skills, *subagents, *ui)
    declared = {permission for item in exports for permission in item.permissions}
    if storage is not None:
        declared |= storage.permissions
    for command in commands:
        declared |= command.permissions
    named = {command.host_operation for command in commands if command.host_operation}
    unknown = sorted(declared - PERMISSIONS - named)
    if unknown:
        raise ContractError("permission_unknown", f"unknown permissions: {', '.join(unknown)}")
    try:
        pages = parse_rich_pages(payload.get("pages", []), {c.command_id for c in commands})
    except ValueError as error:
        raise ContractError("rich_page", str(error)) from error
    scopes = {command.command_id: command.scope for command in commands}
    if len(scopes) != len(commands):
        raise ContractError("command", "duplicate command id")
    if any(scopes[key] not in ("shared", page.scope) for page in pages for key in page.commands):
        raise ContractError("rich_page", "command unavailable in page installation scope")
    return ContributionDocument(
        pages=pages,
        tools=tools,
        skills=skills,
        subagents=subagents,
        commands=commands,
        ui=ui,
        storage=storage,
    )


def parse_slot_ui(payload: dict[str, Any]) -> SlotUiDocument:
    if not isinstance(payload, dict) or payload.get("schema") != SLOT_UI_SCHEMA:
        raise ContractError("slot_ui_schema", "unsupported slot ui schema")
    title = payload.get("title")
    if not isinstance(title, str) or not title or len(title.encode("utf-16-le")) > 240:
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
            or not re.fullmatch(r"[a-z0-9-]{1,64}", action_id)
            or not isinstance(label, str)
            or not label
            or len(label.encode("utf-16-le")) > 160
        ):
            raise ContractError("slot_ui_action", "slot ui action is invalid")
        if "input" in item:
            form = item["input"]
            if (
                not isinstance(form, dict)
                or not isinstance(form.get("label"), str)
                or not 0 < len(form["label"].encode("utf-16-le")) <= 160
                or not isinstance(form.get("initial"), dict)
                or len(
                    json.dumps(form["initial"], ensure_ascii=False, separators=(",", ":")).encode()
                )
                > 32768
            ):
                raise ContractError("slot_ui_action", "invalid action input")
        actions.append((action_id, label))
    return SlotUiDocument(title=title, actions=tuple(actions))


def parse_bound_slot_ui(
    payload: dict[str, Any],
    slot: str,
    commands: set[str],
    input_commands: frozenset[str] = frozenset(),
) -> SlotUiDocument:
    page = parse_slot_ui(payload)
    if slot == "settings_page" and any(action not in commands for action, _ in page.actions):
        raise ContractError("slot_ui_action", "settings page action has no signed command")
    if slot == "settings_page" and any(
        "input" in action and action["id"] not in input_commands
        for action in payload.get("actions", [])
    ):
        raise ContractError("slot_ui_action", "action input requires an input-enabled command")
    return page


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
    if not isinstance(name, str) or not name or abi not in {"invoke", "score", "mcp.stdio"}:
        raise ContractError("tool", "tool name or abi is invalid")
    input_schema = value.get("input_schema")
    output_schema = value.get("output_schema")
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise ContractError("tool_schema", "tool schemas must be objects")
    description = value.get("description", "")
    if not isinstance(description, str) or len(description) > 4096:
        raise ContractError("tool", "tool description must be a string of at most 4096 characters")
    raw_aliases = _list(value.get("service_aliases", []))
    aliases = frozenset(alias for alias in raw_aliases if isinstance(alias, str))
    if len(aliases) > 8 or len(aliases) != len(raw_aliases):
        raise ContractError("service_alias", "invalid tool service aliases")
    permissions = _permissions(value.get("permissions"))
    if bool(aliases) != ("services.call" in permissions):
        raise ContractError(
            "service_alias", "each consuming tool must authorize its service aliases"
        )
    return ToolContribution(
        name=name,
        abi=abi,
        input_schema=input_schema,
        output_schema=output_schema,
        description=description,
        permissions=permissions,
        service_aliases=aliases,
    )


def _command(value: object) -> CommandContribution:
    if not isinstance(value, dict):
        raise ContractError("command", "command contribution must be an object")
    command_id = value.get("id")
    operation = value.get("host_operation")
    permissions = _permissions(value.get("permissions"))
    if "host_operation" in value and (
        "tool" in value
        or not isinstance(operation, str)
        or not is_application_capability(operation)
        or permissions != frozenset({operation})
    ):
        raise ContractError("command", "a host command requires its exact capability grant")
    tool = value.get("tool", "" if operation else None)
    payload = value.get("payload")
    if (
        not isinstance(command_id, str)
        or not command_id
        or not isinstance(tool, str)
        or not (tool or operation)
    ):
        raise ContractError("command", "command id or tool is invalid")
    if not isinstance(payload, dict):
        raise ContractError("command", "command payload must be an object")
    input_schema = value.get("input_schema")
    output_schema = value.get("output_schema")
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise ContractError("command_schema", "command schemas must be objects")
    scope = value.get("scope", "shared")
    if scope not in ("project", "tenant", "shared"):
        raise ContractError("command", "unknown command installation scope")
    accepts_input = value.get("accepts_input", False)
    if not isinstance(accepts_input, bool):
        raise ContractError("command", "accepts_input must be boolean")
    return CommandContribution(
        scope=scope,
        accepts_input=accepts_input,
        command_id=command_id,
        host_operation=operation,
        tool=tool,
        payload=payload,
        input_schema=input_schema,
        output_schema=output_schema,
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


def _subagent(value: object) -> SubAgentContribution:
    fields = {"id", "name", "description", "instructions", "tools", "permissions"}
    if not isinstance(value, dict) or value.keys() - fields:
        raise ContractError("subagent", "unsupported SubAgent declaration")

    def required_text(key: str, limit: int) -> str:
        text = value.get(key)
        if not isinstance(text, str) or not text.strip() or len(text) > limit:
            raise ContractError("subagent", f"invalid SubAgent {key}")
        return text

    tools = _list(value.get("tools", []))
    names = tuple(name for name in tools if isinstance(name, str) and name and name != "*")
    if len(names) != len(tools) or len(names) != len(set(names)):
        raise ContractError("subagent", "SubAgent tools must name unique package tools")
    permissions = _permissions(value.get("permissions"))
    if permissions != frozenset({"subagents.register"}):
        raise ContractError("subagent", "SubAgent registration requires subagents.register")
    return SubAgentContribution(
        agent_id=required_text("id", 128),
        name=required_text("name", 128),
        description=required_text("description", 1024),
        instructions=required_text("instructions", 4000),
        tools=names,
        permissions=permissions,
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
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise ContractError("storage_schema", "storage schema_version must be a positive integer")
    return StorageContribution(
        schema_version=schema_version,
        permissions=_permissions(value.get("permissions")),
    )
