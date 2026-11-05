# Development startup and restart

Run from the repository root:

```bash
make dev           # Ensure infrastructure, migrate, build changed services, start API/Web
make restart       # Restart API/Web and reconcile changed images/configuration
make restart-full  # Also force Ray and WorkspaceCore processes to stop and restart
make stop          # Stop this checkout's managed application/compute processes
make status
```

PostgreSQL, Redis, Neo4j, MinIO and their volumes are retained by all these commands.
`reset`, `fresh` and Docker cleanup commands have separate destructive semantics.

Startup waits for shared infrastructure, applies the existing Alembic migrations,
and synchronizes initialized builtin references while preserving custom scopes before starting the application.
Ray and WorkspaceCore builds run concurrently; API and Vite then launch concurrently.
The one-shot MinIO setup job must finish with exit code zero. It is not treated as
an always-running health-checked service.

`restart` retains unchanged healthy containers. Runtime source, dependency lock or
Compose configuration changes still trigger image rebuild/recreation. Use
`restart-full` when the purpose is to discard all compute-process state even if
there are no source or configuration changes.

The Ray head, worker and actor use one Compose development configuration and the
same locked dependency environment. Dependencies are installed while building the
image, never by resolving packages on every container start. Changing `pyproject.toml`
or `uv.lock` requires a matching locked rebuild, which `make dev` performs. The
actor health check reads the registered HITL router's running/listening state and
performs a bounded Redis PING; a running container alone is insufficient.

WorkspaceCore retains its normal source compilation and image validation. A
BuildKit Cargo target cache reuses compiler outputs, while a Dockerfile-specific
ignore file excludes unrelated build output and private state from its context.
Both image builds stream a filtered gzip archive to Docker, avoiding repeated
Docker Desktop per-file filesystem synchronization while retaining normal Dockerfile
compilation and layer-cache checks.

The API/Web process manager stores non-secret launch identities under
`logs/dev-services/`, and appends output to `logs/api.log` and `logs/web.log`.
It validates kernel process identity, checkout, role, launch marker and listener
ownership before accepting health or sending signals. It never kills by port or
global process-name pattern. Legacy PID files do not grant termination authority.
Manually launched foreground servers remain under their original terminal's control;
stop those with Ctrl+C before using the managed startup on the same ports.

`DEV_STARTUP_TIMEOUT` bounds readiness waiting after builds; `DEV_STOP_TIMEOUT`
bounds managed process shutdown. Individual HTTP and Compose probes also have
timeouts. Early child exit, failed setup, bad health, foreign listeners and stale
identities fail explicitly, and startup failure cleans up only processes created
by that invocation. Compilation and first-time dependency downloads are separate
from the readiness timeout.

The native Electron client remains a separate workflow:

```bash
make -C agi-stack run-desktop
```
