# MemStack Drone Contract

Use this reference when changing workspace metadata, frontend workspace configuration, backend defaults, or tests for Drone CI/CD.

## Key Files

- Infrastructure: `docker-compose.yml`, `.env.example`, `Makefile`
- Backend workspace creation: `src/infrastructure/adapters/primary/web/routers/workspaces.py`
- Pipeline contract parser: `src/infrastructure/agent/workspace_plan/pipeline.py`
- Drone provider: `src/infrastructure/agent/workspace_plan/drone.py`
- Frontend create/settings: `web/src/utils/workspaceConfig.ts`, `web/src/pages/tenant/WorkspaceCreate.tsx`, `web/src/pages/tenant/WorkspaceSettings.tsx`, `web/src/pages/tenant/workspaceSettingsModel.ts`
- Tests: `src/tests/unit/routers/test_workspaces_router.py`, `src/tests/unit/workspace_plan/test_drone_pipeline.py`, `web/src/test/pages/tenant/WorkspaceCreate.test.tsx`, `web/src/test/pages/tenant/WorkspaceSettingsPanel.test.tsx`

## Workspace Metadata Shape

Programming workspaces can use Drone through `metadata.delivery_cicd`:

```json
{
  "source_control": {
    "provider": "github",
    "repo": "memstack/my-app",
    "default_branch": "main",
    "server_url": "https://github.com",
    "clone_url": "https://github.com/memstack/my-app.git",
    "auth_token_env": "GITHUB_TOKEN"
  },
  "delivery_cicd": {
    "provider": "drone",
    "code_root": "/workspace/my-app",
    "agent_managed": false,
    "contract_source": "workspace_defaults",
    "contract_confidence": 1,
    "timeout_seconds": 600,
    "auto_deploy": false,
    "drone": {
      "repo": "memstack/my-app",
      "branch": "main",
      "server_url_env": "DRONE_SERVER_URL",
      "token_env": "DRONE_TOKEN",
      "poll_interval_seconds": 5,
      "deploy": {
        "enabled": false,
        "mode": "cli",
        "stage": "deploy",
        "required": true,
        "target": "staging",
        "docker": {
          "registry": "registry.example.com",
          "image": "registry.example.com/memstack/my-app",
          "context": ".",
          "dockerfile": "Dockerfile",
          "tags": ["latest"],
          "username_secret": "docker_username",
          "password_secret": "docker_password"
        },
        "kubernetes": {
          "namespace": "default",
          "manifest_paths": ["k8s/*.yaml"],
          "kubeconfig_secret": "kubeconfig",
          "context": "staging",
          "kubectl_image": "bitnami/kubectl:latest"
        },
        "cli": {
          "image": "alpine:3.20",
          "commands": ["./scripts/deploy.sh"]
        }
      },
      "source_control": {
        "provider": "github",
        "repo": "memstack/my-app",
        "default_branch": "main",
        "server_url": "https://github.com",
        "clone_url": "https://github.com/memstack/my-app.git",
        "auth_token_env": "GITHUB_TOKEN"
      },
      "environment": {
        "api": {
          "server_url_env": "DRONE_SERVER_URL",
          "token_env": "DRONE_TOKEN"
        },
        "server": {
          "server_port": 8080,
          "server_host": "localhost:8080",
          "server_proto": "http",
          "rpc_secret_env": "DRONE_RPC_SECRET",
          "user_create": "username:memstack,admin:true",
          "source_provider": "github",
          "github_server": "https://github.com",
          "github_client_id_env": "DRONE_GITHUB_CLIENT_ID",
          "github_client_secret_env": "DRONE_GITHUB_CLIENT_SECRET",
          "gitlab_server": "https://gitlab.com",
          "gitlab_client_id_env": "DRONE_GITLAB_CLIENT_ID",
          "gitlab_client_secret_env": "DRONE_GITLAB_CLIENT_SECRET",
          "git_always_auth": false
        },
        "runner": {
          "runner_port": 3001,
          "runner_capacity": 2,
          "runner_name": "memstack-drone-runner",
          "rpc_proto": "http",
          "rpc_host": "drone-server",
          "rpc_secret_env": "DRONE_RPC_SECRET"
        }
      }
    }
  }
}
```

## Parser Behavior

- `build_pipeline_contract_from_metadata()` accepts provider config from `delivery_cicd.provider_config`, `delivery_cicd.drone`, or top-level Drone keys.
- `DronePipelineConfig.from_contract()` requires `repo` as `<owner>/<repo>`.
- `server_url` can be set directly, but the workspace default should use `server_url_env`.
- `token_env` defaults to `DRONE_TOKEN`.
- `branch`, `commit`, `target`, `params`, `build_params`, and `poll_interval_seconds` are optional.
- `deploy` can be declared under `delivery_cicd.drone.deploy` or `delivery_cicd.deploy`.
- `deploy.mode` supports `docker`, `kubernetes`, and `cli`; unsupported values normalize to `cli`.
- When `deploy.enabled=true`, the Drone provider passes non-secret deploy metadata as build params such as `MEMSTACK_DEPLOY_MODE`, `MEMSTACK_DEPLOY_STAGE`, and `MEMSTACK_DEPLOY_TARGET`.
- A configured deploy run must report a matching Drone stage/step (default `deploy`, also matches common names like `deploy-docker`) or the workspace pipeline result is marked failed with `deployment_status=missing`.
- Deploy secret fields such as `username_secret`, `password_secret`, and `kubeconfig_secret` are secret names only. The actual values must live in Drone secrets or environment-backed secret storage.
- `environment.*` is workspace configuration metadata for API/server/runner setup; the current provider reads `server_url_env` and `token_env` for API access.
- `metadata.source_control` is the workspace-level source-of-truth for GitHub or GitLab.
- `metadata.delivery_cicd.drone.source_control` mirrors the workspace SCM config so Drone agents can configure `.drone.yml`, repository activation, and provider-specific server settings from one shape.
- For GitHub, Drone server setup uses `DRONE_GITHUB_SERVER`, `DRONE_GITHUB_CLIENT_ID`, and `DRONE_GITHUB_CLIENT_SECRET`.
- For GitLab, Drone server setup uses `DRONE_GITLAB_SERVER`, `DRONE_GITLAB_CLIENT_ID`, `DRONE_GITLAB_CLIENT_SECRET`, and optional `DRONE_GIT_ALWAYS_AUTH`.

## Infrastructure Defaults

Local Drone runs behind the optional Compose profile:

```bash
make drone-up
make drone-logs
make drone-down
```

Equivalent direct command:

```bash
docker compose --profile drone up -d drone-server drone-runner-docker
```

The local server is exposed at `http://localhost:${DRONE_SERVER_PORT:-8080}`. The runner dashboard port defaults to `${DRONE_RUNNER_PORT:-3001}`.

## Verification

Use the smallest checks that prove the changed behavior:

```bash
uv run pytest src/tests/unit/routers/test_workspaces_router.py src/tests/unit/workspace_plan/test_drone_pipeline.py -q
pnpm --dir web test --run src/test/pages/tenant/WorkspaceCreate.test.tsx src/test/pages/tenant/WorkspaceSettingsPanel.test.tsx
pnpm --dir web type-check
pnpm --dir web lint
docker compose -f docker-compose.yml --profile drone config
```

Run full backend/web suites only when shared schema, routing, or pipeline runtime behavior changed.

## Safety Rules

- Do not commit real Drone tokens, OAuth client secrets, RPC secrets, or generated bearer tokens.
- Do not switch an existing `sandbox_native` workspace to `drone` unless requested.
- Keep code roots isolated under `/workspace/<name>` for programming workspaces.
- Preserve `server_url_env` and `token_env` top-level Drone fields for provider compatibility even when adding `environment.api`.
