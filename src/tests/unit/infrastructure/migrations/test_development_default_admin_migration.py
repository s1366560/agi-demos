"""Isolated executable checks for the proposed data migration; no network or app startup."""

from __future__ import annotations

import ast
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations

from alembic import command

HERE = Path(__file__).resolve().parents[5]
MIGRATION = HERE / "alembic/versions/d10a27f4c901_promote_selected_development_default_admin.py"
TARGET = "10000000-0000-4000-8000-000000000001"
OTHER = "10000000-0000-4000-8000-000000000002"
OPTIONS = {
    "user_id": TARGET,
    "email": "admin@memstack.ai",
    "environment": "development",
    "database_host": "localhost",
}
spec = importlib.util.spec_from_file_location("selected_admin_migration", MIGRATION)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def users_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("is_superuser", sa.Boolean()),
        sa.Column("unchanged_marker", sa.String()),
    )


class PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.network_guard = patch("socket.socket", side_effect=AssertionError("Network forbidden"))
        self.network_guard.start()
        self.engine = sa.create_engine("sqlite:///:memory:")
        self.metadata = sa.MetaData()
        self.users = users_table(self.metadata)
        self.metadata.create_all(self.engine)
        self.connection = self.engine.connect()
        self.connection.execute(
            self.users.insert(),
            [
                {
                    "id": TARGET,
                    "email": "admin@memstack.ai",
                    "is_active": True,
                    "is_superuser": False,
                    "unchanged_marker": "target-fixture",
                },
                {
                    "id": OTHER,
                    "email": "other@example.invalid",
                    "is_active": True,
                    "is_superuser": False,
                    "unchanged_marker": "other-fixture",
                },
            ],
        )

    def tearDown(self) -> None:
        self.connection.close()
        self.engine.dispose()
        self.network_guard.stop()

    def invoke(self, **changes: object) -> None:
        options = {**OPTIONS, **changes}
        context = MigrationContext.configure(
            self.connection, opts={"development_admin_promotion": options}
        )
        with Operations.context(context):
            migration.upgrade()

    def rows(self) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in self.connection.execute(
                sa.select(self.users).order_by(self.users.c.id)
            ).mappings()
        ]

    def test_promotes_only_exact_selected_account_and_preserves_other_columns(
        self,
    ) -> None:
        before = self.rows()
        self.invoke()
        expected = [dict(row) for row in before]
        expected[0]["is_superuser"] = True
        self.assertEqual(self.rows(), expected)

    def test_repeat_is_idempotent_and_does_not_update_an_existing_superuser(
        self,
    ) -> None:
        self.invoke()
        statements = []
        sa.event.listen(
            self.connection,
            "before_cursor_execute",
            lambda c, cu, st, p, co, many: statements.append(st),
        )
        before = self.rows()
        self.invoke()
        self.assertEqual(before, self.rows())
        self.assertFalse(any(statement.startswith("UPDATE") for statement in statements))

    def test_no_selection_does_not_query_or_change_users(self) -> None:
        context = MigrationContext.configure(self.connection)
        with (
            Operations.context(context),
            patch.object(self.connection, "execute", side_effect=AssertionError("SQL forbidden")),
        ):
            migration.upgrade()

    def test_empty_selection_is_noop_in_production(self) -> None:
        before = self.rows()
        self.invoke(
            user_id=None,
            email=None,
            environment="production",
            database_host="db.invalid",
        )
        self.assertEqual(self.rows(), before)

    def test_invalid_options_fail_before_sql(self) -> None:
        invalid = [
            {"user_id": None},
            {"email": None},
            {"user_id": ""},
            {"user_id": "bad"},
            {"user_id": TARGET.replace("-", "")},
            {"user_id": 1},
            {"email": "other@example.invalid"},
            {"email": "Admin@memstack.ai"},
            {"email": "admin@memstack.ai "},
            {"environment": "production"},
            {"environment": "staging"},
            {"environment": "Development"},
            {"database_host": "db.internal"},
            {"database_host": None},
            {"database_host": "localhost.invalid"},
        ]
        for changes in invalid:
            with (
                self.subTest(changes=changes),
                patch.object(
                    self.connection,
                    "execute",
                    side_effect=AssertionError("SQL forbidden"),
                ),
                self.assertRaises(RuntimeError),
            ):
                self.invoke(**changes)

    def test_loopback_hosts_are_supported(self) -> None:
        for host in ("localhost", "127.0.0.1", "::1"):
            with self.subTest(host=host):
                self.invoke(database_host=host)

    def test_noncanonical_uppercase_uuid_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "canonical UUID"):
            self.invoke(user_id="ABCDEFAB-0000-4000-8000-000000000001")

    def test_missing_target_is_rejected_without_creation(self) -> None:
        self.connection.execute(self.users.delete().where(self.users.c.id == TARGET))
        before = self.rows()
        with self.assertRaisesRegex(RuntimeError, "uniquely matched"):
            self.invoke()
        self.assertEqual(before, self.rows())

    def test_wrong_id_is_rejected(self) -> None:
        before = self.rows()
        with self.assertRaisesRegex(RuntimeError, "uniquely matched"):
            self.invoke(user_id=OTHER)
        self.assertEqual(before, self.rows())

    def test_duplicate_email_is_rejected(self) -> None:
        self.connection.execute(
            self.users.update().where(self.users.c.id == OTHER).values(email="admin@memstack.ai")
        )
        before = self.rows()
        with self.assertRaisesRegex(RuntimeError, "uniquely matched"):
            self.invoke()
        self.assertEqual(before, self.rows())

    def test_inactive_target_is_not_activated_or_promoted(self) -> None:
        self.connection.execute(
            self.users.update().where(self.users.c.id == TARGET).values(is_active=False)
        )
        before = self.rows()
        with self.assertRaisesRegex(RuntimeError, "already be active"):
            self.invoke()
        self.assertEqual(before, self.rows())

    def test_invalid_privilege_flag_is_rejected(self) -> None:
        self.connection.execute(
            self.users.update().where(self.users.c.id == TARGET).values(is_superuser=None)
        )
        with self.assertRaisesRegex(RuntimeError, "privilege flag is invalid"):
            self.invoke()

    def test_changed_target_is_rejected_at_conditional_update(self) -> None:
        self.connection.exec_driver_sql("""CREATE TRIGGER prevent_promotion BEFORE UPDATE ON users
            WHEN NEW.is_superuser = 1 BEGIN SELECT RAISE(IGNORE); END""")
        before = self.rows()
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            self.invoke()
        self.assertEqual(before, self.rows())

    def test_offline_promotion_is_rejected(self) -> None:
        context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={
                "as_sql": True,
                "output_buffer": io.StringIO(),
                "development_admin_promotion": OPTIONS,
            },
        )
        with (
            Operations.context(context),
            self.assertRaisesRegex(RuntimeError, "online identity"),
        ):
            migration.upgrade()

    def test_downgrade_never_blindly_revokes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "forward-only"):
            migration.downgrade()


class EnvironmentOptionsTests(unittest.TestCase):
    def test_real_environment_helper_passes_only_allowlisted_nonsecret_options(
        self,
    ) -> None:
        source = ast.parse((HERE / "alembic/env.py").read_text())
        helper = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "default_admin_promotion_options"
        )
        context = SimpleNamespace(
            get_x_argument=lambda **kwargs: {
                "development_admin_user_id": TARGET,
                "development_admin_email": "admin@memstack.ai",
                "unrelated": "excluded",
            }
        )
        scope = {
            "context": context,
            "settings": SimpleNamespace(
                environment="development",
                postgres_url="postgresql+asyncpg://localhost/fixture",
            ),
            "make_url": sa.engine.make_url,
        }
        # Execute only the parsed local helper; importing env.py would start migrations.
        exec(  # noqa: S102
            compile(ast.Module(body=[helper], type_ignores=[]), "env_helper", "exec"),
            scope,
        )
        self.assertEqual(scope["default_admin_promotion_options"](), OPTIONS)


class RevisionExecutionTests(unittest.TestCase):
    def test_unselected_upgrade_consumes_revision_and_later_selection_does_not_rerun(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="memstack-admin-revision-unit-") as directory:
            root = Path(directory)
            (root / "versions").mkdir()
            (root / "versions/base.py").write_text(
                "revision='c86fa94f00dd'\ndown_revision=None\ndef upgrade(): pass\ndef downgrade(): pass\n"
            )
            (root / "versions/selected_admin.py").write_text(MIGRATION.read_text())
            (root / "env.py").write_text("""from alembic import context
connection = context.config.attributes['connection']
context.configure(connection=connection, development_admin_promotion=context.config.attributes.get('selection', {}))
with context.begin_transaction():
    context.run_migrations()
""")
            config = Config()
            config.set_main_option("script_location", str(root))
            engine = sa.create_engine("sqlite:///:memory:")
            metadata = sa.MetaData()
            users = users_table(metadata)
            metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(
                    users.insert().values(
                        id=TARGET,
                        email="admin@memstack.ai",
                        is_active=True,
                        is_superuser=False,
                    )
                )
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                self.assertEqual(
                    connection.exec_driver_sql(
                        "SELECT version_num FROM alembic_version"
                    ).scalar_one(),
                    "d10a27f4c901",
                )
                config.attributes["selection"] = OPTIONS
                command.upgrade(config, "head")
                self.assertIs(
                    connection.execute(sa.select(users.c.is_superuser)).scalar_one(),
                    False,
                )
            engine.dispose()


if __name__ == "__main__":
    unittest.main(verbosity=2)
