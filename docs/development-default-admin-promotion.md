# Promote an existing local development administrator

Revision `d10a27f4c901` is an explicit, one-time data migration for an existing
`admin@memstack.ai` account. It changes only `users.is_superuser` from false to
true. It does not create an account, activate an inactive account, change
credentials or membership, or alter the behavior of future default-user creation.

The migration requires `settings.environment == "development"`, a database host
of `localhost`, `127.0.0.1`, or `::1`, and both an exact canonical user UUID and
the exact default email. The email must identify exactly one active row with
the selected UUID. An already privileged matching account is unchanged. Invalid
identity, environment, host, inactive account, or offline SQL generation fails
without account promotion.

First inspect the intended development database and record the existing account
UUID, active flag, privilege flag, and current Alembic revision. Then run the
explicit upgrade **before starting the API**:

```sh
PYTHONPATH=. uv run alembic \
  -x development_admin_user_id=<verified-existing-user-uuid> \
  -x development_admin_email=admin@memstack.ai \
  upgrade d10a27f4c901
```

No selection means no account query or update, but Alembic still records this
revision as applied. API startup calls `upgrade head` without selection; if it
consumes this revision first, a later selected `upgrade head` will not rerun it.
Resolve that case with a separately reviewed follow-up migration; do not stamp,
downgrade, or update the account directly. The migration has no automatic
downgrade because it cannot safely infer whether access should be revoked.

After the upgrade, verify the stored revision and the selected account's
`is_active` and `is_superuser` fields, then start the API through `make dev-backend`.
An authenticated `/auth/me` check must confirm the same identity before using
administrator-only application endpoints.

The data-only revision was reviewed after autogenerating an empty schema delta
against an isolated users fixture. This does not assert that a deployed database
matches every current ORM model. The accompanying unit tests use isolated SQLite
and actual Alembic operations, including the one-time no-selection behavior.
