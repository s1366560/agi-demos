# MemStack Kubernetes Deployment

This directory contains Kubernetes manifests for deploying MemStack in a production environment with autoscaling support for 1000+ concurrent users.

## Prerequisites

1. Kubernetes cluster (v1.25+)
2. NGINX Ingress Controller installed
3. Prometheus Operator installed (for ServiceMonitor)
4. External services: Neo4j, PostgreSQL, Redis (or use the included docker-compose services)

## Quick Start

### 1. Create namespace and apply configuration

```bash
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
```

### 2. Configure secrets

Edit `secrets.yaml` with your actual values, then:

```bash
kubectl apply -f secrets.yaml
```

**For production**, use a secret manager like:
- [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets)
- [External Secrets Operator](https://external-secrets.io/)
- [Vault Secret Operator](https://developer.hashicorp.com/vault/docs/platform/k8s)

### 3. Deploy applications

```bash
# Deploy API
kubectl apply -f api-deployment.yaml

# Deploy Workers
kubectl apply -f worker-deployment.yaml

# Deploy Ingress
kubectl apply -f ingress.yaml

# Deploy Monitoring (requires Prometheus Operator)
kubectl apply -f prometheus-service-monitor.yaml
```

### 4. Verify deployment

```bash
# Check pods
kubectl get pods -n memstack

# Check HPA status
kubectl get hpa -n memstack

# Check services
kubectl get svc -n memstack

# View logs
kubectl logs -f deployment/memstack-api -n memstack
kubectl logs -f deployment/memstack-worker -n memstack
```

## Architecture

```
                    ┌─────────────────┐
                    │   Ingress       │
                    │   (nginx)       │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  MemStack API   │
                    │  (HPA: 3-20)    │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼──────┐    ┌───────▼──────┐    ┌───────▼──────┐
│    Neo4j     │    │  PostgreSQL  │    │    Redis     │
│  (external)  │    │  (external)  │    │  (external)  │
└──────────────┘    └──────────────┘    └──────────────┘
        │                    │
        └────────────────────┼────────────────────┐
                             │                    │
                    ┌────────▼────────┐   ┌──────▼──────┐
                    │ MemStack Worker │   │  Prometheus │
                    │  (HPA: 2-15)    │   │  Operator   │
                    └─────────────────┘   └─────────────┘
```

## Autoscaling Configuration

### API Autoscaling (HPA)
- **Min replicas**: 3
- **Max replicas**: 20
- **Target CPU**: 70%
- **Target Memory**: 80%
- **Scale up**: Up to 100% increase per 30s
- **Scale down**: Max 50% decrease per 60s

### Worker Autoscaling (HPA)
- **Min replicas**: 2
- **Max replicas**: 15
- **Target CPU**: 70%
- **Target Memory**: 80%
- **Scale up**: Up to 50% increase per 60s
- **Scale down**: Max 30% decrease per 90s

## Resource Limits

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| API       | 500m        | 2000m     | 512Mi          | 2Gi          |
| Worker    | 500m        | 2000m     | 512Mi          | 2Gi          |

## Monitoring

### Metrics Endpoints
- API: `http://memstack-api.memstack.svc:9090/metrics`
- Worker: `http://memstack-worker.memstack.svc:9090/metrics`

### Alerts
- **HighErrorRate**: Error rate > 5% for 5 minutes
- **HighLatency**: P99 latency > 1s for 10 minutes
- **APINotReady**: API down for 2 minutes
- **HighMemoryUsage**: Memory > 90% for 10 minutes
- **HighCPUUsage**: CPU > 80% for 10 minutes

## High Availability

### Pod Disruption Budgets
- **API**: Min 2 available during maintenance
- **Worker**: Min 1 available during maintenance

### Pod Anti-Affinity
Pods are spread across different nodes for better fault tolerance.

## External Services

### Neo4j
Recommended configuration for high concurrency:
```yaml
# Environment variables in Neo4j
NEO4J_dbms_memory_heap_max__size: 4G
NEO4J_dbms_memory_pagecache_size: 1G
```

### PostgreSQL
Recommended connection pool settings:
```yaml
POSTGRES_POOL_SIZE: 20
POSTGRES_MAX_OVERFLOW: 40
POSTGRES_POOL_RECYCLE: 3600
POSTGRES_POOL_PRE_PING: true
```

### Redis
Recommended memory policy:
```bash
redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
```

## Capacity Planning

For **1000+ concurrent users**:

| Metric                | Value              |
|-----------------------|--------------------|
| Max API Pods          | 20                 |
| Max Worker Pods       | 15                 |
| Total CPU Capacity    | 70 cores (2000m x 35) |
| Total Memory Capacity | 70 Gi (2Gi x 35)   |
| Expected Throughput   | ~1000 req/sec      |

## Troubleshooting

### Check HPA status
```bash
kubectl describe hpa memstack-api-hpa -n memstack
```

### Check resource usage
```bash
kubectl top pods -n memstack
kubectl top nodes
```

### View scaling events
```bash
kubectl get events -n memstack --sort-by='.lastTimestamp'
```

### Force scale (for testing)
```bash
kubectl scale deployment memstack-api --replicas=10 -n memstack
```

## Cleanup

```bash
kubectl delete namespace memstack
```
