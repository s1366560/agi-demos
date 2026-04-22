"""Top-level `memstack` CLI entry point."""

from __future__ import annotations

from typing import Any

import click

from . import __version__
from .commands.artifacts_cmd import artifacts_group
from .commands.auth_cmd import login, logout
from .commands.chat_cmd import chat
from .commands.info_cmd import conversations, projects, whoami


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--api-key",
    "api_key",
    help="Override API key (else MEMSTACK_API_KEY env or ~/.memstack/credentials).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.version_option(version=__version__, prog_name="memstack")
@click.pass_context
def cli(ctx: click.Context, api_key: str | None, as_json: bool) -> None:
    """MemStack command-line interface."""
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["json"] = as_json


cli.add_command(login)
cli.add_command(logout)
cli.add_command(whoami)
cli.add_command(projects)
cli.add_command(conversations)
cli.add_command(chat)
cli.add_command(artifacts_group)


def main(argv: list[str] | None = None) -> Any:
    return cli.main(args=argv, standalone_mode=True)


if __name__ == "__main__":
    main()
