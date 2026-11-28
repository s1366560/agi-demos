# MemStack Helm Chart

A fresh deployment starts the standalone package kernel, PostgreSQL, Redis and the package Web client. First startup provisions one project and enables the six signed archives in [the deployment selection](files/standard-packages.json). The first owner and all six installations commit together. A restart leaves later upgrades, withdrawals and rollbacks under project control.

## Prepare a new installation

Run `make helm-build-images` or publish equivalent kernel and Web images. Provide a read-only volume claim named `memstack-official-packages` containing the six archives named `memstack-<domain>.mspkg`. The publisher can assemble them with the official SDK from its own checkout:

```bash
PYTHONPATH=.:sdk/memstack-plugin-sdk/src uv run python -m scripts.build_standard_packages \
  --agent-image "$AGENT_DIGEST_REF" --knowledge-image "$KNOWLEDGE_DIGEST_REF" \
  --automation-image "$AUTOMATION_DIGEST_REF" --environments-image "$ENVIRONMENTS_DIGEST_REF" \
  --billing-image "$BILLING_DIGEST_REF" --device-wasm "$DEVICE_WASM" \
  --key "$SIGNER_FILE" --out "$NEW_ARCHIVE_DIRECTORY"
```

Create the `memstack-initial-project` Secret from administrator-provided files. `owner.json` contains `email`, `password`, `tenant_name` and `project_name`. `publisher.pem` contains the trusted Ed25519 public key. `worker-registries.json` contains the JSON array of approved registry origins. `docker-host` contains the execution daemon endpoint. Configure its TLS client certificate, key and CA via a Secret volume, `DOCKER_TLS_VERIFY` and `DOCKER_CERT_PATH` in `api.extraEnv`. All replicas need access to the approved worker images. The signing private key stays with the publisher.

For an existing full-schema installation, overlay `values-existing-full.yaml` after the environment-specific values. For an independently provisioned kernel on shared cloud identities, use `values-package-kernel.yaml`.

Install into a namespace:

```bash
helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts
helm repo add redis https://helm.redis.io
helm repo add neo4j https://helm.neo4j.com/neo4j
helm repo add minio-operator https://operator.min.io
helm repo update
helm dependency build ./charts/memstack
helm upgrade --install memstack ./charts/memstack \
  --namespace memstack --create-namespace \
  --wait --wait-for-jobs --timeout 15m
```

Port-forward:

```bash
kubectl port-forward -n memstack svc/memstack-web 3000:80
kubectl port-forward -n memstack svc/memstack-api 8000:8000
```

## Configuration

The default chart provisions PostgreSQL and Redis and consumes the release inputs described above. For production, start from `values-production-ha.yaml`, provide real secrets and storage classes, and review the commercial/license requirements for Redis Enterprise and Neo4j Enterprise:

```bash
helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts
helm repo add redis https://helm.redis.io
helm repo add neo4j https://helm.neo4j.com/neo4j
helm repo add minio-operator https://operator.min.io
helm repo update
helm dependency build ./charts/memstack
helm upgrade --install memstack ./charts/memstack \
  --namespace memstack --create-namespace \
  -f ./charts/memstack/values-production-ha.yaml \
  --wait --wait-for-jobs --timeout 30m
```

The production profile uses the initial-project inputs above and the secrets for each enabled service:

- `memstack-secrets`: application secrets plus provider keys, `neo4j-password`, `aws-access-key-id`, and `aws-secret-access-key`.
- `memstack-redis-db`: Redis database password under key `password`.
- `memstack-redis-license`: Redis Enterprise license under key `license`.
- `memstack-neo4j-auth`: Neo4j chart password under key `NEO4J_AUTH`, formatted as `neo4j/<password>`.
- `memstack-minio-env`: MinIO tenant environment under key `config.env`.

For deployments using the full API, production values set `ENVIRONMENT=production` and require the
`python-api-v2` plugin data plane to acknowledge each immutable V2 publication within 30 seconds.
On startup each API pod writes its PostgreSQL connection URL from the configured credential Secret
to a memory-backed volume mounted read-only at `/app/.env`. A supplied `/app/.env` mount takes
precedence. A pod restart picks up credential rotation.
Each API pod checks its own admitted generation and HTTP table against the latest ROOT publication
at `GET /health/ready`. A lagging pod returns HTTP 503 and reloads the verified package in its
background recovery loop. It becomes ready once its local generation matches the target. The
startup and liveness probes use `GET /health`. The ACK roster identifies logical data planes.
Browser and Desktop clients are ephemeral and are intentionally excluded. If another deployment
template adds a persistent Rust server or sidecar plane, add its stable data-plane ID to
`config.pluginV2RequiredDataPlaneIds`; Helm rejects a production render with an empty roster.

Set `postgres.enabled=false`, `redis.enabled=false`, `neo4j.enabled=false`, or `minio.enabled=false` to use external managed services instead; the corresponding `*.external` endpoint values are required in that mode.

LLM bootstrap keys can be passed with `secrets.providerApiKeys`:

```yaml
secrets:
  providerApiKeys:
    OPENAI_API_KEY: sk-...
```

Ray and the agent actor are optional and disabled by default in `values.yaml`. Enable them
with an override such as:

```yaml
ray:
  enabled: true
agentActor:
  enabled: true
```

## Signed package kernel

Build the kernel API with `docker build -f Dockerfile.kernel -t memstack-kernel:latest .`.
The image installs the locked `package-kernel` dependency group. Model SDKs, Ray, Playwright,
Neo4j and channel connectors are distributed with their respective runtimes. Its Uvicorn factory
serves cloud authentication, device grants, the signed project package
marketplace and project execution. The full API image supplies the existing full-stack profile.
Each operation reads the active project release from PostgreSQL and verifies its signed archive.
Each replica compares its active project releases with PostgreSQL at `/health/ready`. It verifies
and prepares each newly selected digest with its local trust roots before serving traffic.

Build its web client from the same checkout:

```sh
pnpm --dir web run build:project-packages
docker build -t memstack-package-web:latest -f web/Dockerfile.project-packages web
```

The web image serves the package manager at both `/` and `/project-packages.html` and proxies
`/api/` to the kernel. The Helm profile deploys both images; `--set web.enabled=false` selects
API-only deployment.

To render the shared-cloud identity topology with these hosts, supply
`-f charts/memstack/values-production-ha.yaml -f charts/memstack/values-package-kernel.yaml`
in that order. It selects three API replicas and two Web replicas. Each API pod's readiness probe
checks the project releases against its own trust roots and worker daemon. Use the registry
settings and trust files needed by the packages that pod will serve.

For the shared-cloud identity profile, use `-f charts/memstack/values-package-kernel.yaml` and supply the deployment's
`memstack-secrets` Secret, including its `secret-key` and `llm-encryption-key` entries. A production
kernel requires a deployment-specific `SECRET_KEY` shared by its replicas. Create the
`memstack-kernel-config` Secret with a `database.env` key containing
the deployment's `DATABASE_URL` and a `publisher.pem` key containing the trusted Ed25519 public key.
Mount the same files when running the image directly. The shared database mode uses the existing
cloud tenant/project identities and the full schema. The application reads `DATABASE_URL` from the
mounted dotenv file. Setting only an environment variable of that name does not redirect migrations.

For a manually provisioned project with `api.initialProject.enabled=false`, point that file at a dedicated, empty PostgreSQL database and set
`api.extraEnv.PACKAGE_KERNEL_DATABASE_MODE=standalone`. The API creates its own schema and starts
with zero accounts. Provision the first project owner with
`python -m src.cli.package_kernel_owner` inside the API container. See the
[bootstrap command and password input options](../../docs/architecture/independent-business-packages.md#独立数据库).

An authorized project administrator can POST a signed archive to
`/api/v1/platform-plugins/v2/optional-business/install`, enable it, invoke its exported operations
and roll it back. For registry delivery, configure `PLUGIN_MARKETPLACE_ALLOWED_REGISTRIES`
and use `POST /api/v1/plugin-marketplace/packages/{plugin_id}/install`. An OCI worker also needs
a configured execution daemon and a `PLUGIN_WORKER_ALLOWED_REGISTRIES` entry for its image.
The full API owns ROOT publication and distribution of the default multi-client profile.
