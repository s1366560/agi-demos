#!/usr/bin/env python3
"""CLI tool for managing agent definitions and bindings via the MemStack REST API.

Usage:
    python scripts/agent_cli.py list
    python scripts/agent_cli.py get <agent_id>
    python scripts/agent_cli.py create --name NAME --system-prompt PROMPT [--model MODEL]
    python scripts/agent_cli.py update <agent_id> [--name NAME] [--system-prompt PROMPT] ...
    python scripts/agent_cli.py delete <agent_id>
    python scripts/agent_cli.py bindings list [--tenant-id ID]
    python scripts/agent_cli.py bindings create --tenant-id ID --agent-id ID [--channel-type TYPE]

Environment variables:
    MEMSTACK_API_URL  - API base URL (default: http://localhost:8000)
    MEMSTACK_API_KEY  - API key (required, format: ms_sk_...)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn

import httpx

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_url() -> str:
    return os.environ.get("MEMSTACK_API_URL", "http://localhost:8000").rstrip("/")


def _api_key() -> str:
    key = os.environ.get("MEMSTACK_API_KEY", "")
    if not key:
        _fatal("MEMSTACK_API_KEY environment variable is required")
    return key


def _fatal(message: str) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=_api_url(),
        headers={"Authorization": f"Bearer {_api_key()}"},
        timeout=30.0,
    )


def _handle_response(response: httpx.Response) -> Any:
    """Check HTTP response status and return parsed JSON, or exit on error."""
    if response.status_code == 401:
        _fatal("Authentication failed (401). Check your MEMSTACK_API_KEY.")
    if response.status_code == 403:
        _fatal("Access denied (403). You do not have permission for this resource.")
    if response.status_code == 404:
        _fatal("Resource not found (404).")
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = body.get("detail", "")
        except Exception:
            detail = response.text
        _fatal(f"API error ({response.status_code}): {detail}")

    if response.status_code == 204:
        return None
    return response.json()


# ---------------------------------------------------------------------------
# Table formatter
# ---------------------------------------------------------------------------

_DEFINITION_COLUMNS = ["id", "name", "display_name", "model", "enabled"]
_BINDING_COLUMNS = ["id", "agent_id", "channel_type", "channel_id", "enabled", "priority"]


def _print_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Print rows as a simple aligned table."""
    if not rows:
        print("(no results)")
        return

    # Compute column widths
    widths: dict[str, int] = {}
    for col in columns:
        widths[col] = len(col)
        for row in rows:
            val = str(row.get(col, ""))
            widths[col] = max(widths[col], len(val))

    # Header
    header = "  ".join(col.upper().ljust(widths[col]) for col in columns)
    print(header)
    print("  ".join("-" * widths[col] for col in columns))

    # Rows
    for row in rows:
        line = "  ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns)
        print(line)


def _output(data: Any, *, table: bool, columns: list[str] | None = None) -> None:
    """Print data as JSON or table depending on flags."""
    if not table:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    if isinstance(data, list):
        _print_table(data, columns or _DEFINITION_COLUMNS)
    elif isinstance(data, dict):
        _print_table([data], columns or _DEFINITION_COLUMNS)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

_BASE = "/api/v1/agent"


def cmd_list(args: argparse.Namespace) -> None:
    """List all agent definitions."""
    params: dict[str, Any] = {}
    if args.project_id:
        params["project_id"] = args.project_id
    if args.enabled_only:
        params["enabled_only"] = "true"

    with _client() as client:
        resp = client.get(f"{_BASE}/definitions", params=params)
    data = _handle_response(resp)
    _output(data, table=args.table, columns=_DEFINITION_COLUMNS)


def cmd_get(args: argparse.Namespace) -> None:
    """Get a single agent definition by ID."""
    with _client() as client:
        resp = client.get(f"{_BASE}/definitions/{args.agent_id}")
    data = _handle_response(resp)
    _output(data, table=args.table, columns=_DEFINITION_COLUMNS)


def cmd_create(args: argparse.Namespace) -> None:
    """Create a new agent definition."""
    payload: dict[str, Any] = {
        "name": args.name,
        "display_name": args.display_name or args.name,
        "system_prompt": args.system_prompt,
    }
    if args.model:
        payload["model"] = args.model
    if args.temperature is not None:
        payload["temperature"] = args.temperature
    if args.max_tokens is not None:
        payload["max_tokens"] = args.max_tokens

    with _client() as client:
        resp = client.post(f"{_BASE}/definitions", json=payload)
    data = _handle_response(resp)
    _output(data, table=args.table, columns=_DEFINITION_COLUMNS)


def cmd_update(args: argparse.Namespace) -> None:
    """Update an existing agent definition (PUT)."""
    payload: dict[str, Any] = {}
    if args.name is not None:
        payload["name"] = args.name
    if args.display_name is not None:
        payload["display_name"] = args.display_name
    if args.system_prompt is not None:
        payload["system_prompt"] = args.system_prompt
    if args.model is not None:
        payload["model"] = args.model
    if args.enabled is not None:
        # enabled toggle uses the dedicated PATCH endpoint
        with _client() as client:
            resp = client.patch(
                f"{_BASE}/definitions/{args.agent_id}/enabled",
                json={"enabled": args.enabled.lower() in ("true", "1", "yes")},
            )
        data = _handle_response(resp)
        # If there are other fields too, continue; otherwise output and return
        if not payload:
            _output(data, table=args.table, columns=_DEFINITION_COLUMNS)
            return

    if not payload and args.enabled is None:
        _fatal("No update fields provided. Use --name, --system-prompt, --model, or --enabled.")

    if payload:
        with _client() as client:
            resp = client.put(f"{_BASE}/definitions/{args.agent_id}", json=payload)
        data = _handle_response(resp)
        _output(data, table=args.table, columns=_DEFINITION_COLUMNS)


def cmd_delete(args: argparse.Namespace) -> None:
    """Delete an agent definition."""
    with _client() as client:
        resp = client.delete(f"{_BASE}/definitions/{args.agent_id}")
    data = _handle_response(resp)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_bindings_list(args: argparse.Namespace) -> None:
    """List agent bindings."""
    params: dict[str, Any] = {}
    if args.agent_id:
        params["agent_id"] = args.agent_id
    if args.enabled_only:
        params["enabled_only"] = "true"

    with _client() as client:
        resp = client.get(f"{_BASE}/bindings", params=params)
    data = _handle_response(resp)
    _output(data, table=args.table, columns=_BINDING_COLUMNS)


def cmd_bindings_create(args: argparse.Namespace) -> None:
    """Create a new agent binding."""
    payload: dict[str, Any] = {
        "agent_id": args.agent_id,
    }
    if args.channel_type:
        payload["channel_type"] = args.channel_type
    if args.channel_id:
        payload["channel_id"] = args.channel_id
    if args.priority is not None:
        payload["priority"] = args.priority

    with _client() as client:
        resp = client.post(f"{_BASE}/bindings", json=payload)
    data = _handle_response(resp)
    _output(data, table=args.table, columns=_BINDING_COLUMNS)


def cmd_bindings_delete(args: argparse.Namespace) -> None:
    """Delete an agent binding."""
    with _client() as client:
        resp = client.delete(f"{_BASE}/bindings/{args.binding_id}")
    data = _handle_response(resp)
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-cli",
        description="MemStack Agent Management CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agent-cli {VERSION}",
    )
    parser.add_argument(
        "--table",
        action="store_true",
        default=False,
        help="Output as a formatted table instead of JSON",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -- list --
    p_list = subparsers.add_parser("list", help="List all agent definitions")
    p_list.add_argument("--project-id", default=None, help="Filter by project ID")
    p_list.add_argument("--enabled-only", action="store_true", help="Only show enabled agents")
    p_list.set_defaults(func=cmd_list)

    # -- get --
    p_get = subparsers.add_parser("get", help="Get agent definition details")
    p_get.add_argument("agent_id", help="Agent definition ID")
    p_get.set_defaults(func=cmd_get)

    # -- create --
    p_create = subparsers.add_parser("create", help="Create a new agent definition")
    p_create.add_argument("--name", required=True, help="Agent name (unique identifier)")
    p_create.add_argument("--display-name", default=None, help="Display name (defaults to name)")
    p_create.add_argument("--system-prompt", required=True, help="System prompt text")
    p_create.add_argument("--model", default=None, help="LLM model override")
    p_create.add_argument("--temperature", type=float, default=None, help="Sampling temperature")
    p_create.add_argument("--max-tokens", type=int, default=None, help="Max output tokens")
    p_create.set_defaults(func=cmd_create)

    # -- update --
    p_update = subparsers.add_parser("update", help="Update an existing agent definition")
    p_update.add_argument("agent_id", help="Agent definition ID")
    p_update.add_argument("--name", default=None, help="New agent name")
    p_update.add_argument("--display-name", default=None, help="New display name")
    p_update.add_argument("--system-prompt", default=None, help="New system prompt")
    p_update.add_argument("--model", default=None, help="New LLM model")
    p_update.add_argument(
        "--enabled",
        default=None,
        help="Enable or disable the agent (true/false)",
    )
    p_update.set_defaults(func=cmd_update)

    # -- delete --
    p_delete = subparsers.add_parser("delete", help="Delete an agent definition")
    p_delete.add_argument("agent_id", help="Agent definition ID")
    p_delete.set_defaults(func=cmd_delete)

    # -- bindings --
    p_bindings = subparsers.add_parser("bindings", help="Manage agent bindings")
    bindings_sub = p_bindings.add_subparsers(dest="bindings_command", help="Binding commands")

    # bindings list
    p_blist = bindings_sub.add_parser("list", help="List agent bindings")
    p_blist.add_argument("--agent-id", default=None, help="Filter by agent ID")
    p_blist.add_argument("--enabled-only", action="store_true", help="Only show enabled bindings")
    p_blist.set_defaults(func=cmd_bindings_list)

    # bindings create
    p_bcreate = bindings_sub.add_parser("create", help="Create an agent binding")
    p_bcreate.add_argument("--agent-id", required=True, help="Agent definition ID to bind")
    p_bcreate.add_argument("--channel-type", default=None, help="Channel type (e.g. feishu, web)")
    p_bcreate.add_argument("--channel-id", default=None, help="Channel ID")
    p_bcreate.add_argument("--priority", type=int, default=None, help="Binding priority")
    p_bcreate.set_defaults(func=cmd_bindings_create)

    # bindings delete
    p_bdelete = bindings_sub.add_parser("delete", help="Delete an agent binding")
    p_bdelete.add_argument("binding_id", help="Binding ID to delete")
    p_bdelete.set_defaults(func=cmd_bindings_delete)

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "bindings" and getattr(args, "bindings_command", None) is None:
        parser.parse_args(["bindings", "--help"])
        sys.exit(1)

    try:
        args.func(args)
    except httpx.ConnectError:
        _fatal(f"Cannot connect to {_api_url()}. Is the server running?")
    except httpx.TimeoutException:
        _fatal(f"Request to {_api_url()} timed out.")
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
