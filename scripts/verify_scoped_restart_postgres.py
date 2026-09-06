"""Verify scoped and ROOT startup races on an owned PostgreSQL migration slice."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = (
    "dc206dd13ac3",
    "e91f4c7b2d60",
    "a4d8e2c7b901",
    "f43f5cd2fb21",
    "b58c04d49a92",
    "c69d15e50ba3",
    "d72e6b8f0a41",
)
TESTS = (
    "src/tests/integration/test_scoped_restart_recovery_postgres.py",
    "src/tests/integration/test_scoped_publication_coordinator_postgres.py",
    "src/tests/integration/test_platform_plugin_scoped_ledger_postgres.py",
    "src/tests/integration/test_scoped_profile_fence_postgres.py",
    "src/tests/integration/test_root_startup_postgres.py",
)


async def migrate(url: str) -> None:
    engine = create_async_engine(url)
    try:
        for attempt in range(80):
            try:
                async with engine.connect():
                    break
            except (OSError, ConnectionError):
                if attempt == 79:
                    raise
                await asyncio.sleep(0.25)
        async with engine.begin() as connection:

            def apply(sync_connection: Connection) -> None:
                with Operations.context(MigrationContext.configure(sync_connection)):
                    for revision in REVISIONS:
                        path = next((ROOT / "alembic/versions").glob(f"{revision}_*.py"))
                        spec = importlib.util.spec_from_file_location(revision, path)
                        if spec is None or spec.loader is None:
                            raise RuntimeError("Migration module is unavailable")
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        module.upgrade()

            await connection.run_sync(apply)
        print("Isolated ledger migration slice applied through d72e6b8f0a41", flush=True)
    finally:
        await engine.dispose()


def main() -> int:
    container_name = f"cordis-scoped-restore-{uuid4().hex[:12]}"
    password = secrets.token_urlsafe(32)
    container_env = dict(os.environ, POSTGRES_PASSWORD=password)
    created = False
    try:
        _ = subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container_name,
                "--publish",
                "127.0.0.1::5432",
                "--env",
                "POSTGRES_PASSWORD",
                "--env",
                "POSTGRES_DB=cordis_acceptance",
                "pgvector/pgvector:pg16",
            ],
            env=container_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        created = True
        port = (
            subprocess.check_output(["docker", "port", container_name, "5432/tcp"], text=True)
            .strip()
            .rsplit(":", 1)[1]
        )
        url = f"postgresql+asyncpg://postgres:{password}@127.0.0.1:{port}/cordis_acceptance"
        asyncio.run(migrate(url))
        test_env = dict(os.environ, PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL=url)
        return subprocess.run(
            [sys.executable, "-m", "pytest", *TESTS, "-q"],
            cwd=ROOT,
            env=test_env,
            check=False,
        ).returncode
    finally:
        if created:
            result = subprocess.run(
                ["docker", "rm", "--force", container_name],
                stdout=subprocess.DEVNULL,
                check=False,
            )
            print(f"Owned PostgreSQL container cleanup exit {result.returncode}", flush=True)
            if result.returncode:
                raise RuntimeError("Owned PostgreSQL container cleanup failed")


if __name__ == "__main__":
    raise SystemExit(main())
