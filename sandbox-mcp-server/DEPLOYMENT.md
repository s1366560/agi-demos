# Deployment Guide

**Version**: 2.0
**Environment**: Production
**Last Updated**: 2026-01-28

This guide covers production deployment of the Sandbox MCP Server with XFCE desktop environment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Deploy](#quick-deploy)
3. [Production Deployment](#production-deployment)
4. [Docker Deployment](#docker-deployment)
5. [Kubernetes Deployment](#kubernetes-deployment)
6. [Monitoring](#monitoring)
7. [Security](#security)
8. [Maintenance](#maintenance)

---

## Prerequisites

### System Requirements

**Minimum**:
- CPU: 2 cores
- RAM: 2 GB
- Disk: 10 GB
- Network: 2 Mbps bandwidth per user

**Recommended**:
- CPU: 4+ cores
- RAM: 4+ GB
- Disk: 20+ GB
- Network: 5+ Mbps bandwidth per user

### Software Requirements

- Docker 20.10+ (or Kubernetes 1.25+)
- Docker Compose 2.0+ (optional)
- Port 8765 (MCP server)
- Port 7681 (Web terminal)
- Port 6080 (noVNC)

---

## Quick Deploy

### Development/Test

```bash
# Clone repository
git clone https://github.com/your-org/sandbox-mcp-server.git
cd sandbox-mcp-server

# Build image
docker build -t sandbox-mcp-server:latest .

# Run container
docker run -d \
  --name sandbox-mcp \
  -p 8765:8765 \
  -p 7681:7681 \
  -p 6080:6080 \
  -v $(pwd)/workspace:/workspace \
  sandbox-mcp-server:latest

# Verify
docker logs sandbox-mcp
curl http://localhost:8765/health
```

---

## Production Deployment

### Environment Variables

Create `.env` file:

```bash
# MCP Server
MCP_HOST=0.0.0.0
MCP_PORT=8765
MCP_WORKSPACE=/workspace

# Desktop Configuration
DESKTOP_ENABLED=true
DESKTOP_RESOLUTION=1280x720
DESKTOP_PORT=6080
VNC_SERVER_TYPE=tigervnc  # Options: tigervnc (default), x11vnc

# Terminal Configuration
TERMINAL_PORT=7681

# Security (optional)
SESSION_TIMEOUT=1800
TOKEN_EXPIRY=3600
MAX_CONCURRENT_SESSIONS=10

# Logging
LOG_LEVEL=INFO
DEBUG=false
```

### Production Docker Command

```bash
docker run -d \
  --name sandbox-mcp-prod \
  --restart unless-stopped \
  --cpus=2 \
  --memory=4g \
  --memory-swap=4g \
  -p 8765:8765 \
  -p 7681:7681 \
  -p 6080:6080 \
  -v /opt/sandbox/workspace:/workspace \
  -v /opt/sandbox/sessions:/sessions \
  --env-file .env \
  --health-cmd "curl -f http://localhost:8765/health || exit 1" \
  --health-interval 30s \
  --health-timeout 10s \
  --health-retries 3 \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  sandbox-mcp-server:latest
```

---

## Docker Deployment

### Docker Compose (Recommended)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  sandbox-mcp:
    image: sandbox-mcp-server:latest
    container_name: sandbox-mcp-prod
    restart: unless-stopped

    # Resource limits
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G

    # Ports
    ports:
      - "8765:8765"  # MCP server
      - "7681:7681"  # Web terminal
      - "6080:6080"  # noVNC

    # Volumes
    volumes:
      - ./workspace:/workspace
      - ./sessions:/sessions
      - ./logs:/logs

    # Environment
    env_file:
      - .env

    # Health check
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s

    # Logging
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: 3

    # Security
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
```

**Deploy**:
```bash
docker-compose up -d
docker-compose logs -f
```

### Multi-Instance Deployment

```yaml
version: '3.8'

services:
  sandbox-mcp-1:
    image: sandbox-mcp-server:latest
    container_name: sandbox-mcp-1
    ports:
      - "8765:8765"
      - "7681:7681"
      - "6080:6080"
    volumes:
      - ./workspace-1:/workspace

  sandbox-mcp-2:
    image: sandbox-mcp-server:latest
    container_name: sandbox-mcp-2
    ports:
      - "8766:8765"
      - "7682:7681"
      - "6081:6080"
    volumes:
      - ./workspace-2:/workspace

  # nginx reverse proxy
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

---

## Kubernetes Deployment

### Deployment Manifest

Create `deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sandbox-mcp
  labels:
    app: sandbox-mcp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: sandbox-mcp
  template:
    metadata:
      labels:
        app: sandbox-mcp
    spec:
      containers:
      - name: sandbox-mcp
        image: sandbox-mcp-server:latest
        imagePullPolicy: Always
        ports:
        - name: mcp
          containerPort: 8765
        - name: terminal
          containerPort: 7681
        - name: vnc
          containerPort: 6080

        # Resources
        resources:
          requests:
            cpu: 1000m
            memory: 2Gi
          limits:
            cpu: 2000m
            memory: 4Gi

        # Environment
        envFrom:
        - configMapRef:
            name: sandbox-mcp-config

        # Health check
        livenessProbe:
          httpGet:
            path: /health
            port: 8765
          initialDelaySeconds: 20
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 3

        readinessProbe:
          httpGet:
            path: /health
            port: 8765
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3

        # Volume mounts
        volumeMounts:
        - name: workspace
          mountPath: /workspace

      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: sandbox-workspace-pvc
```

### Service Manifest

Create `service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: sandbox-mcp-service
spec:
  type: LoadBalancer
  selector:
    app: sandbox-mcp
  ports:
  - name: mcp
    port: 8765
    targetPort: 8765
  - name: terminal
    port: 7681
    targetPort: 7681
  - name: vnc
    port: 6080
    targetPort: 6080
```

### ConfigMap Manifest

Create `configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: sandbox-mcp-config
data:
  MCP_HOST: "0.0.0.0"
  MCP_PORT: "8765"
  DESKTOP_ENABLED: "true"
  DESKTOP_RESOLUTION: "1280x720"
  DESKTOP_PORT: "6080"
  TERMINAL_PORT: "7681"
  LOG_LEVEL: "INFO"
```

**Deploy to Kubernetes**:
```bash
kubectl apply -f configmap.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml

# Verify
kubectl get pods
kubectl logs -f deployment/sandbox-mcp
```

---

## Monitoring

### Health Checks

```bash
# Container health
docker ps
docker inspect sandbox-mcp-prod | grep -A 10 Health

# Service health
curl http://localhost:8765/health

# Desktop status
curl http://localhost:6080/vnc.html
```

### Metrics to Monitor

| Metric | Tool | Alert Threshold |
|--------|------|-----------------|
| CPU Usage | docker stats | >80% |
| Memory Usage | docker stats | >3.5 GB |
| Disk Usage | df -h | >80% |
| Container Uptime | docker ps | <99% |
| Response Time | curl | >500ms |

### Logging

```bash
# View logs
docker logs -f sandbox-mcp-prod

# Export logs
docker logs sandbox-mcp-prod > sandbox-mcp.log

# Log aggregation (optional)
docker run -d \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/docker/containers:/var/lib/docker/containers \
  --name logspout \
  gliderlabs/logspout
  syslog://logs.example.com:514
```

---

## Security

### Container Security

```bash
# Run as non-root (already configured)
docker run --user 1001:1001 ...

# Read-only filesystem
docker run --read-only --tmpfs /tmp ...

# Drop capabilities
docker run --cap-drop=ALL --cap-add=CAP_NET_BIND_SERVICE ...

# Security options
docker run --security-opt=no-new-privileges ...
```

### Network Security

```bash
# Isolate networks
docker network create sandbox-network
docker run --network sandbox-network ...

# Firewall rules
ufw allow 8765/tcp  # MCP server
ufw allow 7681/tcp  # Web terminal
ufw allow 6080/tcp  # noVNC
```

### VNC Security

**Note**: VNC authentication is disabled by default (container-safe).

For production, consider:
- Reverse proxy with authentication (nginx, traefik)
- VPN access only
- Network isolation
- Session timeout enforcement

---

## Maintenance

### Updates

```bash
# Pull latest image
docker pull sandbox-mcp-server:latest

# Stop old container
docker stop sandbox-mcp-prod

# Remove old container
docker rm sandbox-mcp-prod

# Start new container
docker run -d ... (see production command above)

# Verify
docker logs sandbox-mcp-prod
curl http://localhost:8765/health
```

### Backup

```bash
# Backup workspace
docker run --rm \
  -v /opt/sandbox/workspace:/data \
  -v /backup:/backup \
  alpine tar czf /backup/workspace-$(date +%Y%m%d).tar.gz /data

# Backup container config
docker inspect sandbox-mcp-prod > sandbox-mcp-config.json
```

### Restore

```bash
# Restore workspace
docker run --rm \
  -v /opt/sandbox/workspace:/data \
  -v /backup:/backup \
  alpine tar xzf /backup/workspace-20260128.tar.gz -C /
```

### Performance Tuning

See `PERFORMANCE.md` for detailed tuning guide.

Quick tips:
- **Increase CPU**: More concurrent users
- **Add RAM**: Larger desktop sessions
- **SSD storage**: Faster file operations
- **Reduce resolution**: Lower bandwidth usage

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs sandbox-mcp-prod

# Check resource usage
docker stats sandbox-mcp-prod

# Verify configuration
docker inspect sandbox-mcp-prod
```

### Desktop Not Accessible

```bash
# Check processes
docker exec sandbox-mcp-prod ps aux | grep -E "Xvfb|xfce|vnc"

# Check ports
docker exec sandbox-mcp-prod netstat -tlnp

# Test VNC
curl http://localhost:6080/vnc.html
```

### Performance Issues

```bash
# Check resources
docker stats sandbox-mcp-prod

# Reduce load
# 1. Lower resolution: DESKTOP_RESOLUTION=1024x576
# 2. Increase compression: Modify -compression value in code
# 3. Limit concurrent users: MAX_CONCURRENT_SESSIONS=5
```

---

## Scaling

### Horizontal Scaling

Multiple instances behind load balancer:

```yaml
# docker-compose.yml
services:
  sandbox-mcp:
    image: sandbox-mcp-server:latest
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1'
          memory: 2G

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

### Vertical Scaling

Increase resources per instance:

```bash
docker run -d \
  --cpus=4 \
  --memory=8g \
  --memory-swap=8g \
  ...
```

---

## Support

### Getting Help

- **Documentation**: README.md, TROUBLESHOOTING.md, PERFORMANCE.md
- **Issues**: GitHub Issues
- **Community**: GitHub Discussions

### Diagnostic Information

When reporting issues, include:

```bash
# System info
docker version
docker info

# Container info
docker ps
docker stats
docker logs sandbox-mcp-prod

# Health check
curl -v http://localhost:8765/health
```

---

## Summary

**Production Checklist**:

- [ ] Prerequisites met (CPU, RAM, disk)
- [ ] Environment variables configured
- [ ] Resource limits set (CPU, RAM)
- [ ] Health checks enabled
- [ ] Logging configured
- [ ] Backup strategy in place
- [ ] Monitoring setup
- [ ] Security hardening applied
- [ ] Rollback plan tested

**Estimated Deployment Time**: 30 minutes

**Production Ready**: ✅ Yes

---

**Last Updated**: 2026-01-28
**Deployment Guide Version**: 2.0
**Status**: Production Ready ✅
