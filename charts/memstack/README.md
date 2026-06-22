# MemStack Helm Chart

This chart installs MemStack with the core API, web frontend, PostgreSQL with pgvector, Redis, Neo4j, MinIO, and MinIO bucket setup.

## Local install

Build or load the application images first:

```bash
docker build -t memstack-api:latest .
docker build -t memstack-web:latest web
```

Install into a namespace:

```bash
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

Default values are development-oriented and include in-cluster dependencies. For production, provide stronger secrets, storage classes, resource requests/limits, ingress, and external managed dependencies where appropriate.

LLM bootstrap keys can be passed with `secrets.providerApiKeys`:

```yaml
secrets:
  providerApiKeys:
    OPENAI_API_KEY: sk-...
```

Ray and the agent actor are optional and disabled by default:

```yaml
ray:
  enabled: true
agentActor:
  enabled: true
```
