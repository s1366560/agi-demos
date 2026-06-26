# MemStack Helm Chart

This chart installs MemStack with the core API, web frontend, and official Helm chart/operator backed middleware for PostgreSQL with pgvector, Redis Enterprise, Neo4j, and MinIO.

## Local install

Build or load the application images first:

```bash
docker build -t memstack-api:latest .
docker build -t memstack-web:latest web
```

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

Default values are self-contained and include in-cluster official dependencies. For production, start from `values-production-ha.yaml`, provide real secrets and storage classes, and review the commercial/license requirements for Redis Enterprise and Neo4j Enterprise:

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

The production profile expects these secrets to exist:

- `memstack-secrets`: application secrets plus provider keys, `neo4j-password`, `aws-access-key-id`, and `aws-secret-access-key`.
- `memstack-redis-db`: Redis database password under key `password`.
- `memstack-redis-license`: Redis Enterprise license under key `license`.
- `memstack-neo4j-auth`: Neo4j chart password under key `NEO4J_AUTH`, formatted as `neo4j/<password>`.
- `memstack-minio-env`: MinIO tenant environment under key `config.env`.

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
