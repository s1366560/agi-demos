#!/usr/bin/env python3
"""Dry-run by default; exact inactive legacy cleanup with mandatory restorable backup."""

import argparse
import asyncio
import json
from pathlib import Path

from src.application.services.marketplace_legacy_cleanup_v2 import MarketplaceLegacyCleanupV2
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-digest")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--retire-applied", action="store_true")
    args = parser.parse_args()
    if args.restore and args.apply_digest:
        parser.error("restore and apply are mutually exclusive")
    if args.apply_digest and args.backup is None:
        parser.error("--apply-digest requires --backup")
    settings = get_settings()
    async with async_session_factory() as db:
        service = MarketplaceLegacyCleanupV2(
            db, database_url=settings.postgres_url, environment=settings.environment
        )
        if args.restore:
            result = await service.restore(args.restore)
        elif args.apply_digest and args.retire_applied:
            from src.application.services.marketplace_legacy_retirement_v2 import (
                maintenance_scoped_runtime,
                retire_legacy_applied_scopes,
            )
            from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import (
                AGENT_TURN_REQUIRED_SERVICES_V2,
            )

            runtime, host = await maintenance_scoped_runtime(db)

            from src.domain.model.plugins.generated_v2 import ScopeV2
            from src.infrastructure.plugins.v2.runtime_host import PlatformPluginPublicationV2

            async def publish(scope: ScopeV2) -> PlatformPluginPublicationV2:
                return (
                    await runtime.publish_current(
                        scope, required_services=AGENT_TURN_REQUIRED_SERVICES_V2
                    )
                ).publication

            try:
                result = await retire_legacy_applied_scopes(
                    service,
                    expected_digest=args.apply_digest,
                    backup_path=args.backup,
                    publish=publish,
                )
            finally:
                await runtime.close()
                await host.close()
        elif args.apply_digest:
            result = await service.apply(args.apply_digest, args.backup)
        else:
            plan = await service.plan()
            result = {key: value for key, value in plan.items() if key != "tables"}
            result["candidates"] = {
                table: [
                    {key: row[key] for key in ("id", "plugin_id", "version") if key in row}
                    for row in rows
                ]
                for table, rows in plan["tables"].items()
            }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
