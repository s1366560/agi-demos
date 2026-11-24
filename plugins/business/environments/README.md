# Environments

This business package owns cluster management, instance templates, deployments, instance files and channels. The corresponding application services live in `backend/`. The tenant cluster HTTP adapter supplies the status and timestamp. Its utilization calculation lives in `backend/cluster_health.py` and also runs as the independent `cluster_health` MCP tool.

The signed tool takes numeric node counts, CPU readings and memory readings. It returns the node count and utilization percentages. Missing utilization is returned as JSON null. Project authorization, release verification and worker supervision belong to the host. Provider credentials stay with the provider integration.

[backend/sandbox/](backend/sandbox/) owns project provisioning, leases, sandbox images, health and the tool registry. [sandbox-mcp-server/](sandbox-mcp-server/) owns the standalone WebSocket service, workspace tools, tests and container build. Run `make sandbox-build` from the repository root to build that service. Export a fresh `SANDBOX_SERVICE_AUTH_TOKEN` before `make sandbox-run`. The command binds MCP, terminal and desktop ports to loopback and uses the package Chromium seccomp profile. The signed `patch_text` worker applies the same unified-diff implementation to caller-supplied text. The WebSocket tool authenticates its project session before applying a patch to a workspace file.

## Release the Environments worker

From the repository root, build the package pages and sign the release using the published worker image's immutable digest. Set `IMAGE` to the full image reference and `OUT` to a new output directory.

```sh
corepack pnpm --dir plugins/business/environments/ui/signed install --frozen-lockfile
node plugins/business/environments/ui/signed/build.mjs
PYTHONPATH=.:sdk/memstack-plugin-sdk/src uv run python -m scripts.build_standard_packages \
  --package environments --environments-image "$IMAGE" --key "$SIGNING_KEY" --out "$OUT"
```

Install the archive through the project package API after approving the tool, page, sandbox and terminal permissions shown by package inspection and enable the release. The host must trust the signer and allow the worker registry. Tests for the projection and application services live in `tests/`. The signed install and container execution test lives in `src/tests/integration/test_environments_package.py`.

## Project sandbox and run terminal

Open the signed **Project sandbox** page to query or prepare the current project's sandbox. Project and tenant identifiers come from the installed package's authenticated scope. The page shows the terminal capability declared by that project's authority. An available terminal requires the current run ID and its exact revision. The terminal service rechecks the user's access to the running full-access environment. The page receives the expiry and run binding. Session credentials, working directories, and internal network addresses stay with the authority.

The full API uses its project sandbox routes by default. Its Python sandbox router reports the resumable terminal-v2 authority as unavailable. Set `PROJECT_SANDBOX_AUTHORITY_URL` on the full API to the deployment's trusted Gateway origin when its Rust sandbox service supplies terminal-v2 authorization. An empty host can delegate signed application commands to that full API using `PACKAGE_APPLICATION_RUNTIME_URL`.

To verify a signed terminal authorization and trusted-client shell input on a disposable project, build the native server and the sandbox image, then run from the repository root:

```sh
cargo build --manifest-path agi-stack/Cargo.toml -p agistack-server --bin agistack-server
make sandbox-build
RUST_SANDBOX_TERMINAL_TESTS=1 OCI_WORKER_DOCKER_TESTS=1 uv run pytest -q src/tests/integration/test_environments_terminal_docker.py
```

The test starts PostgreSQL, Redis, Rust and a project sandbox on loopback, installs a signed Environments archive, verifies rejection of a stale run revision, and checks a shell-generated value through the trusted client's terminal session. Set `AGISTACK_TERMINAL_TEST_IMAGE` to select a locally built sandbox image.
