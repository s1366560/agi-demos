# Environments

This business package owns cluster management, instance templates, deployments, instance files and channels. The corresponding application services live in `backend/`. The tenant cluster HTTP adapter supplies the status and timestamp. Its utilization calculation lives in `backend/cluster_health.py` and also runs as the independent `cluster_health` MCP tool.

The signed tool takes numeric node counts, CPU readings and memory readings. It returns the node count and utilization percentages. Missing utilization is returned as JSON null. Project authorization, release verification and worker supervision belong to the host. Provider credentials stay with the provider integration.

[backend/sandbox/](backend/sandbox/) owns project provisioning, leases, sandbox images, health and the tool registry. [sandbox-mcp-server/](sandbox-mcp-server/) owns the standalone WebSocket service, workspace tools, tests and container build. Run `make sandbox-build` from the repository root to build that service. Export a fresh `SANDBOX_SERVICE_AUTH_TOKEN` before `make sandbox-run`. The command binds MCP, terminal and desktop ports to loopback and uses the package Chromium seccomp profile. The signed `patch_text` worker applies the same unified-diff implementation to caller-supplied text. The WebSocket tool authenticates its project session before applying a patch to a workspace file.

## Release the Environments worker

Build and push the worker image from this directory. Use the digest returned by your registry as `IMAGE` (registry/repository@sha256:digest). With the publisher SDK installed, stage the pinned worker descriptor and sign the archive:

```sh
stage=$(mktemp -d)
cp package.json contributions.json "$stage/"
mkdir "$stage/ui"
cp ui/settings.json "$stage/ui/"
python - "$IMAGE" "$stage/worker.json" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[2]).write_text(json.dumps({
    "schema": "memstack.mcp-oci-worker/1",
    "image": sys.argv[1],
    "entrypoint": "/app/worker",
}))
PY
memstack-plugin-pack "$stage/package.json" --key "$SIGNING_KEY" --out "$stage/environments.mspkg"
```

Install the archive through the project package API with the `tools.execute` and `ui.slot` permissions and enable the release. The host must trust the signer and allow the worker registry. Tests for the projection and application services live in `tests/`. The signed install and container execution test lives in `src/tests/integration/test_environments_package.py`.
