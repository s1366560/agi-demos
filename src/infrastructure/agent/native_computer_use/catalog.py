"""Closed first-party effects and explicit MCP bindings for device catalogs."""

from __future__ import annotations

from typing import Any

from src.infrastructure.agent.native_computer_use.contracts import TOOL_NAMES
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, identifier

EXECUTE_TOOLS = frozenset({"cua_repl_js", "cua_repl_reset", "cua_repl_add_module_dir"})
BROWSER_TOOLS = frozenset(
    {"browser_read_operation", "browser_write_operation", "browser_cdp_operation"}
)
MCP_BINDING = "x-cua-mcp-binding"
STEP_ONLY = "x-cua-step-only"
READ_OPERATIONS = frozenset(
    {
        "browsers.list",
        "tabs.list",
        "tabs.selected",
        "tab.title",
        "tab.url",
        "tab.screenshot",
        "tab.getJsDialog",
        "capabilities.list",
        "playwright.domSnapshot",
        "playwright.elementInfo",
        "playwright.elementScreenshot",
        "playwright.waitForLoadState",
        "playwright.waitForURL",
        "playwright.waitForTimeout",
        "playwright.armNavigation",
        "playwright.waitNavigation",
        "playwright.cancelNavigation",
        "playwright.resolveElement",
        "download.path",
        "ax.get",
        "dom_cua.get_visible_dom",
        "dev.logs",
        "content.export",
        "content.exportGsuite",
        "content.exportYouTubeTranscript",
        "capability.pageAssets.bundle",
        "capability.management.getAuditTrail",
        "capability.management.tabs.get",
        "capability.management.tabs.query",
        "capability.management.windows.get",
        "capability.management.windows.getAll",
        "capability.management.tabGroups.get",
        "capability.management.tabGroups.query",
        "capability.management.bookmarks.get",
        "capability.management.bookmarks.getChildren",
        "capability.management.bookmarks.getTree",
        "capability.management.bookmarks.getSubTree",
        "capability.management.bookmarks.search",
        "capability.visibility.get",
        "capability.cdp.readEvents",
        "capability.pageAssets.list",
        "capability.webmcp.listTools",
        "user.getTabContext",
    }
)
WRITE_OPERATIONS = frozenset(
    {
        "capability.browserAuth.request",
        "capability.management.tabs.update",
        "capability.management.tabs.move",
        "capability.management.tabs.group",
        "capability.management.tabs.ungroup",
        "capability.management.tabs.remove",
        "capability.management.windows.create",
        "capability.management.windows.update",
        "capability.management.tabGroups.update",
        "capability.management.tabGroups.move",
        "capability.management.bookmarks.create",
        "capability.management.bookmarks.update",
        "capability.management.bookmarks.move",
        "capability.management.bookmarks.remove",
        "capability.management.bookmarks.removeTree",
        "capability.visibility.set",
        "capability.viewport.set",
        "capability.viewport.reset",
        "playwright.focusLocator",
        "tabs.new",
        "tab.claim",
        "tab.close",
        "tab.goto",
        "tab.back",
        "tab.forward",
        "tab.reload",
        "tab.markDeliverable",
        "tab.markHandoff",
        "tab.requestManualHandoff",
        "tab.requestUserTakeover",
        "ax.click",
        "ax.drag",
        "ax.paste",
        "ax.performSecondaryAction",
        "ax.pressKey",
        "ax.scroll",
        "ax.selectText",
        "ax.setValue",
        "ax.typeText",
        "ax.write",
        "cua.click",
        "cua.double_click",
        "cua.drag",
        "cua.keypress",
        "cua.move",
        "cua.scroll",
        "cua.type",
        "dom_cua.click",
        "dom_cua.double_click",
        "dom_cua.keypress",
        "dom_cua.scroll",
        "dom_cua.type",
        "dialog.accept",
        "dialog.dismiss",
        "nameSession",
    }
)
CDP_OPERATIONS = frozenset(
    {
        "playwright.evaluate",
        "capability.cdp.send",
        "filechooser.setFiles",
        "clipboard.read",
        "clipboard.readText",
        "clipboard.write",
        "clipboard.writeText",
        "capability.webmcp.callTool",
    }
)


def mcp_binding(schema: dict[str, Any]) -> dict[str, Any] | None:
    value = schema.get(MCP_BINDING)
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "server_id",
        "server_name",
        "revision",
        "catalog_digest",
    }:
        raise DeviceBridgeError("computer_use_invalid_mcp_binding")
    for name in ("server_id", "server_name", "catalog_digest"):
        identifier(value[name])
    if (
        not isinstance(value["revision"], int)
        or isinstance(value["revision"], bool)
        or value["revision"] < 1
    ):
        raise DeviceBridgeError("computer_use_invalid_mcp_binding")
    return value


def validate_tool_definition(name: object, schema: dict[str, Any]) -> None:
    identifier(name)
    binding = mcp_binding(schema)
    if name not in TOOL_NAMES | EXECUTE_TOOLS | BROWSER_TOOLS and binding is None:
        raise DeviceBridgeError("computer_use_invalid_catalog")
    if name in TOOL_NAMES | EXECUTE_TOOLS | BROWSER_TOOLS and binding is not None:
        raise DeviceBridgeError("computer_use_invalid_mcp_binding")
    if STEP_ONLY in schema and not isinstance(schema[STEP_ONLY], bool):
        raise DeviceBridgeError("computer_use_invalid_catalog")


def browser_effect(tool_name: str, arguments: dict[str, Any]) -> str:
    operation = arguments.get("operation")
    expected = None
    if operation in READ_OPERATIONS:
        expected = "browser_read_operation"
    elif operation in WRITE_OPERATIONS:
        expected = "browser_write_operation"
    elif operation in CDP_OPERATIONS:
        expected = "browser_cdp_operation"
    elif operation == "playwright.waitForEvent":
        args = arguments.get("args")
        event = args[0] if isinstance(args, list) and args else None
        if event in {"download", "filechooser"}:
            expected = "browser_write_operation"
    elif operation == "playwright.locator":
        args = arguments.get("args")
        method = args[1] if isinstance(args, list) and len(args) > 1 else None
        if method in {
            "count",
            "allTextContents",
            "getAttribute",
            "innerText",
            "textContent",
            "isVisible",
            "isEnabled",
            "waitFor",
        }:
            expected = "browser_read_operation"
        elif method in {
            "click",
            "dblclick",
            "fill",
            "type",
            "press",
            "pressSequentially",
            "selectOption",
            "check",
            "uncheck",
            "setChecked",
        }:
            expected = "browser_write_operation"
        elif method in {"evaluate", "evaluateAll"}:
            expected = "browser_cdp_operation"
    if expected != tool_name:
        raise DeviceBridgeError("computer_use_browser_effect_mismatch")
    return "read" if expected == "browser_read_operation" else "mutate"


def require_mcp_server(schema: dict[str, Any], allowed: tuple[str, ...]) -> None:
    binding = mcp_binding(schema)
    if binding is not None and not (
        "*" in allowed or binding["server_id"] in allowed or binding["server_name"] in allowed
    ):
        raise DeviceBridgeError("computer_use_mcp_server_denied")
