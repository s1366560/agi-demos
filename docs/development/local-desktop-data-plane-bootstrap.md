# Local desktop data-plane provisioning

The native cloud shell uses dedicated deployment grants for `desktop-sidecar-v2`
and `desktop-renderer-v2`. A user login session is not a deployment grant. Grant
secrets remain in Electron's trusted startup environment and the application vault;
they must never be exposed to the renderer.

For a local development API and loopback PostgreSQL, run from the repository root:

```sh
PYTHONPATH=. uv run python scripts/bootstrap-local-desktop-grants.py \
  --api-base http://localhost:8000 \
  --output /tmp/desktop-grants.env \
  --metadata-output /tmp/desktop-grants-metadata.json
```

Both paths must be unused. The command writes them with mode 0600 and prints only
paths, plane IDs, and expiration. Do not print or commit the environment file.
Source it in the trusted launch shell, then use the canonical desktop command:

```sh
source /tmp/desktop-grants.env
make -C agi-stack run-desktop
```

The application bootstrap requires `ENVIRONMENT=development` and loopback API and
database hosts. It inserts a new randomly named platform administrator, refuses
any existing email, authenticates through the normal HTTP login, issues two
24-hour grants through the platform-admin API, and verifies each grant against
`GET /api/v1/platform-plugins/v2/distribution`. The temporary administrator is
then deactivated, retaining identity and issuance history for audit. Existing
user privileges are never changed. On partial failure the command attempts to
revoke every grant it issued before retiring that administrator.

Each grant is bound to its named data plane. The existing protocol exposes the
published ROOT distribution and enforces the plane on receipt submission; it does
not support tenant/project restrictions on these deployment credentials. This
bootstrap cannot publish or change the ROOT profile. Both deployment grants enable acknowledgement participation because the renderer
requires it to submit its verified receipt and establish cloud authority.

The metadata file contains the bootstrap user/run IDs, grant IDs, issuer,
creation and expiration timestamps. It contains no grant secret or password.
Grants expire after 24 hours; a platform administrator can revoke a grant earlier
through the normal data-plane credential endpoint. Remove the temporary
credential file once the intended desktop profile has imported it. Repeating the
bootstrap creates a fresh audit identity and new expiring grants.
