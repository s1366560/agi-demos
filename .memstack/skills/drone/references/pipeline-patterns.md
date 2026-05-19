# Drone Pipeline Patterns

Use this reference when creating, reviewing, or debugging `.drone.yml`.

## Official References

Check official Drone docs before changing provider-specific behavior or unfamiliar runner settings:

- Server GitHub provider: `https://docs.drone.io/server/provider/github/`
- Server RPC secret: `https://docs.drone.io/server/reference/drone-rpc-secret/`
- Docker runner installation: `https://docs.drone.io/runner/docker/installation/linux/`
- Docker runner configuration reference: `https://docs.drone.io/runner/docker/configuration/reference/`

## Minimum Docker Pipeline

Prefer simple Docker pipeline steps that run the same commands used locally:

```yaml
kind: pipeline
type: docker
name: default

trigger:
  branch:
    - main
    - develop

steps:
  - name: lint
    image: node:22-bookworm
    commands:
      - corepack enable
      - pnpm install --frozen-lockfile
      - pnpm lint

  - name: test
    image: node:22-bookworm
    commands:
      - corepack enable
      - pnpm install --frozen-lockfile
      - pnpm test
```

Adapt images and commands to the repository. Do not invent commands; inspect `Makefile`, `package.json`, `pyproject.toml`, lockfiles, and existing CI first.

## Python With uv

```yaml
kind: pipeline
type: docker
name: backend

steps:
  - name: lint
    image: ghcr.io/astral-sh/uv:python3.12-bookworm
    commands:
      - uv sync --frozen
      - uv run ruff check .

  - name: test
    image: ghcr.io/astral-sh/uv:python3.12-bookworm
    commands:
      - uv sync --frozen
      - uv run pytest -q
```

Use narrower test paths for workspace-specific pipelines when the goal is a fast feature gate.

## Monorepo Frontend + Backend

Split independent lanes when one repo contains backend and web code:

```yaml
kind: pipeline
type: docker
name: backend

steps:
  - name: backend-tests
    image: ghcr.io/astral-sh/uv:python3.12-bookworm
    commands:
      - uv sync --frozen
      - uv run pytest src/tests/unit -q

---
kind: pipeline
type: docker
name: web

steps:
  - name: web-tests
    image: node:22-bookworm
    commands:
      - corepack enable
      - cd web
      - pnpm install --frozen-lockfile
      - pnpm type-check
      - pnpm test --run
```

## Secrets

Reference Drone secrets by name:

```yaml
steps:
  - name: publish
    image: plugins/docker
    settings:
      username:
        from_secret: docker_username
      password:
        from_secret: docker_password
```

Never paste secret values into `.drone.yml` or workspace metadata. If a pipeline needs a missing secret, report the secret name to create in Drone.

## Common Failures

- `delivery_cicd.drone.repo must be '<owner>/<repo>'`: fix the repo slug in workspace metadata.
- `DRONE_SERVER_URL is required`: set the env var named by `delivery_cicd.drone.server_url_env`.
- `DRONE_TOKEN is required`: set the env var named by `delivery_cicd.drone.token_env`.
- Runner does not pick up builds: verify `DRONE_RPC_HOST`, `DRONE_RPC_PROTO`, and the shared RPC secret env name match the server.
- Builds stay pending: confirm the repo is activated in Drone, the runner is online, and the pipeline `type` matches the available runner.
- Clone or webhook failures: confirm GitHub OAuth app callback, repository permissions, and webhook activation.
- Docker build failures through runner: remember the local Docker runner mounts `/var/run/docker.sock`; treat it as privileged host access.

## Evidence To Capture

When a Drone run is part of the task, record:

- repo slug, branch, and build number
- final status
- failing stage/step
- relevant log excerpt with secrets redacted
- local command or test that reproduces the failure when possible
