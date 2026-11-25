# Workspace

Web and Electron render the directory, tasks, overview, group chat and blackboard from the same signed [page entries](ui/signed/build.mjs). Edit their original components in [ui/web](ui/web). The chat page also mounts inside the Agent collaboration pane. CSV exports use a project-scoped command and the host's download or native save dialog.

Workspace Core owns membership, task and collaboration transactions. The independently installable Workspace package contributes the directory, workspace creation, project overview, workspace details, general settings, member management, blackboard posts, task editing and CSV export. Code under `backend/` authorizes and projects the request. `src/lib.rs` formats the CSV in a Wasm guest. Run `uv run pytest plugins/business/workspace/tests` for the boundary tests.

## Directory CSV export

The full API can export the current user's page of workspaces. Workspace Core authorizes the caller, filters by tenant, project and workspace membership, applies the requested pagination, and reads its PostgreSQL records. The isolated Wasm package receives four fields from each returned workspace: its ID, name, office status and archived flag. It formats an RFC 4180-style UTF-8 attachment and keeps spreadsheet cells containing user-provided names literal. The host validates its output and pins one package release across the page.

## Workspace lifecycle

Both renderers load the same signed pages. The directory lists the workspaces visible to the current user. Creation preserves use case, collaboration mode and the programming sandbox directory. General settings edit the name, description and archive status. The package passes the authenticated user and project to Workspace Core. Workspace Core checks membership, persists writes and deduplicates retries by request ID. Saving settings includes the revision observed when the editor loaded.

## Publish and install

From this package directory, build and sign the release using a publisher-managed Ed25519 key.

```sh
cargo build --locked --release --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/memstack_workspace.wasm directory.wasm
uv run --with ../../../sdk/memstack-plugin-sdk memstack-plugin-pack package.json \
  --key "$PUBLISHER_KEY" --out directory.mspkg
memstack packages --tenant "$TENANT_ID" --project "$PROJECT_ID" install \
  --approve ui.slot --approve tools.execute --approve app.workspace.directory.read \
  --approve app.workspace.detail.read --approve app.workspace.create \
  --approve app.workspace.settings.update \
  --approve app.workspace.members.read --approve app.workspace.members.write \
  --approve app.workspace.posts.read --approve app.workspace.posts.write \
  --approve app.workspace.tasks.read --approve app.workspace.tasks.write directory.mspkg
```

Configure the API's trusted publisher via `PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES`. The API needs its usual Workspace Core and project-package connections. The exporter uses `tools.execute`. Its optional Web and desktop settings page uses `ui.slot` and invokes the same signed command.

## Read and roll back

Adding `export_package=memstack-workspace` to the existing workspace list explicitly selects the CSV representation. A normal list request returns Core's regular JSON. Pagination uses Core's existing `limit` and `offset`.

```sh
curl --fail --get "$MEMSTACK_API_URL/api/v1/tenants/$TENANT_ID/projects/$PROJECT_ID/workspaces" \
  -H "Authorization: Bearer $MEMSTACK_API_KEY" \
  --data-urlencode "export_package=memstack-workspace" \
  --data-urlencode "limit=50" --output workspaces.csv
memstack packages --tenant "$TENANT_ID" --project "$PROJECT_ID" rollback memstack-workspace
```

`WORKSPACE_DIRECTORY_DOCKER_TESTS=1 uv run pytest src/tests/integration/test_workspace_directory_package.py` starts independent PostgreSQL, Redis and Workspace Core containers. The test uses the installed Core image, defaults to `agi-demos-memstack-workspace-core:latest`, and accepts `WORKSPACE_DIRECTORY_CORE_IMAGE` for a pinned test image. Workspace data is created through Core's HTTP API.
