# Plugin marketplace

The Web plugin hub and Electron plugin settings expose Discover, Installed, and Sources.
The authenticated cloud catalog includes signed V2 packages alongside Codex-style packages. V2 cards hand off
to the existing verified installer; discovery does not grant signature trust or permissions.
Local desktop installations belong to the selected local project and do not require a cloud
account. Cloud mutations require authorization for the selected tenant and project.

## Sources and compatibility

Administrators can export `PLUGIN_MARKETPLACE_CURATED_DIRECTORY` to a trusted catalog
directory and `PLUGIN_MARKETPLACE_CATALOG_URL` to a public HTTPS catalog. No production
catalog URL is assumed. For local development, the executable example source is:

```text
<repository>/plugins/marketplace-examples
```

Supply these variables in the API or desktop process environment before startup.

Users can add HTTPS catalogs or HTTPS Git repositories. Electron also supports local directory
imports. Cloud HTTP does not accept arbitrary server filesystem paths. Source trust must be
confirmed before installation. Downloads reject redirects, non-public network destinations,
archive traversal, links, and size-limit violations. Git content is materialized as an immutable
snapshot; installations do not follow changes to the original checkout or directory.

A local catalog can contain:

```json
{"plugins": [{"path": "plugins/my-plugin"}]}
```

A remote catalog can contain:

```json
{"plugins": [{"source": {"url": "https://your-registry.example/my-plugin.zip"}, "sha256": "<archive SHA256>"}]}
```

Catalog paths are relative to the source root. A package root contains
`.codex-plugin/plugin.json`. Skills use `skills/*/SKILL.md`; MCP declarations use `.mcp.json`
or inline `mcpServers`. `${PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_ROOT}` refer to the installed
snapshot. Executable MCP commands run in the project execution environment, never in the
Web browser. Ordinary command names are resolved by the desktop host before registration.

MemStack supports the following companion extensions without claiming compatibility with
Codex-private services:

```json
{"hooks": [{"event": "before_request", "command": "python3 ${PLUGIN_ROOT}/scripts/check.py", "timeout_seconds": 30}]}
```

Place this in `hooks/hooks.json`. Supported events are `session_start`, `before_request`, and
`after_tool_execute`. Commands read an event JSON object on standard input. A nonzero exit
or timeout fails the triggering operation; disable the plugin or correct it before retrying.
The maximum timeout is 30 seconds. Hook output cannot silently modify permissions or grant
authority. Cloud commands execute inside the owning project's sandbox.

Apps reference a declared, reachable MCP server:

```json
{"apps": {"my-app": {"mcp_server": "my-server", "resource_uri": "ui://my-app/index.html"}}}
```

Place this in `.app.json`. The server advertises its application resource through the existing
MCP application protocol. A Codex-only connector ID without a reachable MCP server is reported
as incompatible. Unknown Hook events are also incompatible, not silently ignored.

## Lifecycle and credentials

Preflight fixes a package digest and lists required permissions. Installation requires explicit
permission approval and an idempotency key. A package may be downloaded, awaiting configuration,
enabled, disabled, failed, or uninstalled; the interface displays the server's actual state.
Cloud packages that are downloaded must be enabled after selecting a project with a working
sandbox. Failed downloads or candidate activation do not replace the active version.

Credentials are configured through the installed plugin. Desktop secrets use the application
vault. Cloud secrets require a stable `LLM_ENCRYPTION_KEY` and are encrypted before persistence;
they are decrypted only when constructing sandbox transport configuration. Installation responses
omit credentials and package file payloads. Provider-specific OAuth still requires that provider's
application/client configuration and an accessible MCP integration. The repository's account-login
OAuth flow does not authorize MCP plugins. Plugin services use a separate authorization-code
flow with PKCE, resource binding and encrypted grant storage. The installed card displays the
server-reported connection state and supports connect, cancel, disconnect and retrying missing
client configuration. Providers without usable client registration remain blocked; a manifest
alone is not authorization. A loopback-only fixture and its protocol tests live in
`plugins/marketplace-examples/oauth-fixture/`; real third-party provider acceptance requires
that provider's configured client and service.
The authenticated transport supports Streamable HTTP, including initialization, tool discovery,
tool calls and App resource reads. OAuth declarations on legacy SSE, WebSocket or stdio transports
are rejected during compatibility checks and authorization. Stdio plugins can still configure
manual environment credentials.

Updates require a new preflight and approval, including additional permissions. Installation-owned
resources are tracked separately from user-created resources. Disable removes future availability;
uninstall removes only owned resources and credentials. Source removal is refused while it has
active installations. Existing V2 package verification and trust policies are unchanged.
Signed V2 installations appear in the unified installed list with their original signed installer
as the update authority. Cloud V2 requests retain the existing `/packages/{plugin_id}/install`,
`approve`, and `uninstall` paths: `tenant_id` selects a tenant, while optional `project_id` selects
that exact project. Tenant/project administrators authorize these mutations. Publication uses the
existing scoped initializer, immutable desired revisions, archive signature verification and
ACK/NACK receipts; it never installs a tenant package into the shared ROOT runtime. Uninstall
removes only that scope's desired reference and grants, leaving another scope's installation and
the immutable shared package bytes available. Global publisher revocation remains a platform-admin
operation. Signed external execution retains the existing restricted WASM runtime policy; this
change does not permit arbitrary external Python execution.

Cloud V2 records report enabled only after an accepted publication actually includes the package.
A package targeting another runtime remains downloaded. Failed updates restore the prior desired
reference and retain the prior runtime generation. Existing calls hold generation leases until
completion. Before subsequent session operations, recorded inherited-plugin bindings reconcile
that plugin's disable/enable, updated version, or uninstall without rewriting private profile
sources. They do not add newly installed parent packages to an already independent session.
Restart recovery re-verifies exact archives and scope-specific grants. SQL WASM authorization
checks the owning tenant/project installation and its publication, so another tenant's grant
cannot authorize the tool.

Historical ROOT installations have no trustworthy tenant attribution; permission grants are not
used to invent it. The authorized local development cleanup removed the inactive historical test
package after publishing real replacement generations for its two historical session snapshots.
Its backups and dry-run reports are under
`artifacts/plugin-marketplace-20260923/legacy-cleanup/`: `scope-retirement-backup.json` preserves
prior desired records, and `catalog-and-grants-backup.json` supports exact catalog/grant restoration.
`scope-retirement-readback.json` records the two ACKs, and `final-dry-run.json` has no candidates.
The cleanup deleted one revoked package row and one revoked permission row; no files were deleted.
Builtin bundles, business data, immutable publication history, new scoped installations, unknown
files and shared/download caches were preserved. No attribution migration was performed.

The cleanup tool defaults to dry run and refuses non-development or non-loopback databases:

```bash
PYTHONPATH=. uv run python scripts/cleanup_local_marketplace_v2.py
# Apply only a reviewed unchanged dry-run digest; backup creation is exclusive and mode 0600.
PYTHONPATH=. uv run python scripts/cleanup_local_marketplace_v2.py --apply-digest <digest> --backup <new-backup.json>
# Restore inactive catalog/grant rows without overwriting existing rows.
PYTHONPATH=. uv run python scripts/cleanup_local_marketplace_v2.py --restore <backup.json>
```

Active desired references, applied snapshots, calls and backend selections block cleanup.
`--retire-applied` requires the same digest and a separate backup, and uses real scoped publication
rather than fabricating apply receipts. Its maintenance host activates only the operation boundary
and an unavailable sandbox service; it does not start HTTP routes, schedulers, health loops or
Docker maintenance. Long-lived local API processes must be gracefully restarted to retire any
old in-memory authorities; database cleanup alone does not prove process retirement.
Immutable package snapshots remain protected while an installation, valid preflight or running
call references them. Cloud preflights expire after 24 hours. Cloud cleanup uses scoped database
leases and rejects symlink or path escapes before removing a registered sandbox directory.
A Linux process check also retains snapshots referenced by a live process command, working
directory or open descriptor when an API crash has released its database lease. Deferred
removal records a safe error and attempt count for retry.
Successful lifecycle mutations and final running-call release retry retirement cleanup; dedicated
OAuth state is purged only after owned runtime roots are gone and the caller transaction releases
its credential locks. Cleanup failures retain registration for a later retry. The Sources tab
provides cache accounting and explicit cleanup; only server-reported reclaimable entries are removed.
Cloud startup starts a recovery pass, repeated every 60 seconds, for scopes with registered
snapshots. Each pass verifies project ownership and resolves the scoped sandbox authority;
the same lease, active-reference and remote-process checks protect live snapshots. A failed
pass retains the registration for retry. Startup wiring has unit coverage; crash recovery also
has a PostgreSQL integration test with a real slow sandbox process.

## API and development checks

Unified endpoints are under `/api/v1/plugin-marketplace/v3`:

| Endpoint | Purpose |
| --- | --- |
| `GET /catalog` | Public cloud catalog; selected local project's catalog on desktop |
| `GET /catalog/scoped` | Authenticated cloud catalog including private sources |
| `GET, POST /sources` | List or add sources |
| `DELETE /sources/{id}` | Remove an unused custom source |
| `POST /preflight` | Fix content and inspect permissions/compatibility |
| `GET, POST /installations` | List scoped installations or install a preflight |
| `POST /installations/{id}/{action}` | `enable`, `disable`, `configure`, `verify`, `update`, `uninstall` |
| `GET /cache`, `POST /cache/cleanup` | Scoped cache accounting and safe cleanup |
| `GET /installations/{id}/oauth/{server}/status` | Public authorization state without tokens |
| `POST /installations/{id}/oauth/{server}/{action}` | `start`, `cancel`, `disconnect` |
| `GET /jobs/{id}` | Scoped durable lifecycle stage, status and error |
| `GET /jobs` | Discover scoped operations, including running tasks |

Mutations carry `tenant_id`, `project_id`, and `idempotency_key` where applicable. Configuration
uses a `credentials` string map. Update carries `preflight_id` and `approved_permissions`.
Installation responses include `job_id` for querying saved lifecycle results. A failed update
retains the previous installation and records the failed operation; retrying the same idempotency
key returns the same outcome. Installation status remains authoritative.
Changing the request content while reusing its key is rejected. Desktop tasks continue if the
client disconnects. Desktop MCP versions are published as separate generations: existing runs
retain the previous generation until their leases end, while new runs use the active version.

Apply the reviewed Alembic migration before starting the cloud API. The production route provider
is a V2 contribution, so deployments must publish the refreshed built-in bundle using the existing
bundle upgrade process. A running API without reload needs a restart to load new Python routes.

Run the focused Python marketplace and Hook tests, the desktop `plugin_marketplace_v3` Rust
tests, and the Web/desktop marketplace UI tests. Native acceptance must use
`make -C agi-stack run-desktop` with an isolated temporary QA profile, then exercise actual
installation, MCP calls, Hook execution, application resources, updates and uninstall. A renderer
test alone does not validate the native lifecycle.
