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

## Deploy Stage Modes

Workspace metadata can declare `delivery_cicd.drone.deploy.mode` as `docker`, `kubernetes`, or
`cli`. Keep the Drone stage or step name aligned with `delivery_cicd.drone.deploy.stage`
(default `deploy`) so MemStack can record deployment evidence from the Drone build.

### Docker Deploy

Use Docker deploy when the pipeline builds and publishes an image. Store registry credentials as
Drone secrets, referenced by name only:

```yaml
kind: pipeline
type: docker
name: workspace-ci

steps:
  - name: test
    image: node:22-bookworm
    commands:
      - corepack enable
      - pnpm install --frozen-lockfile
      - pnpm test

  - name: deploy-docker
    image: plugins/docker
    settings:
      repo: registry.example.com/memstack/my-app
      dockerfile: Dockerfile
      context: .
      tags:
        - latest
      username:
        from_secret: docker_username
      password:
        from_secret: docker_password
    when:
      event:
        - promote
        - custom
```

### Kubernetes Deploy

Use Kubernetes deploy when Drone should apply manifests from the repository. Kubernetes pipelines
require a self-hosted Drone server and Kubernetes runner; Docker pipelines can also run `kubectl`
inside a deploy step when the cluster credential is provided as a secret.

```yaml
kind: pipeline
type: docker
name: workspace-ci

steps:
  - name: deploy-kubernetes
    image: bitnami/kubectl:latest
    environment:
      KUBECONFIG_DATA:
        from_secret: kubeconfig
    commands:
      - mkdir -p "$HOME/.kube"
      - printf "%s" "$KUBECONFIG_DATA" > "$HOME/.kube/config"
      - kubectl --namespace default apply -f k8s/
    when:
      event:
        - promote
        - custom
```

### CLI Deploy

Use CLI deploy for repository-owned deployment scripts or tools. Keep commands explicit and avoid
embedding secret values:

```yaml
kind: pipeline
type: docker
name: workspace-ci

steps:
  - name: deploy
    image: alpine:3.20
    commands:
      - apk add --no-cache bash curl
      - ./scripts/deploy.sh
    when:
      event:
        - promote
        - custom
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
