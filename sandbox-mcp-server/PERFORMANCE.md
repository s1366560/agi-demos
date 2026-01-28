# Performance Tuning Guide

**Version**: 2.0
**Last Updated**: 2026-01-28

Optimization guide for Sandbox MCP Server with XFCE desktop environment.

---

## Table of Contents

1. [Performance Targets](#performance-targets)
2. [VNC Performance](#vnc-performance)
3. [Resource Optimization](#resource-optimization)
4. [Network Optimization](#network-optimization)
5. [Desktop Optimization](#desktop-optimization)
6. [Scaling Strategies](#scaling-strategies)

---

## Performance Targets

### Baseline Metrics

| Metric | Target | Acceptable | Poor |
|--------|--------|------------|------|
| **Startup Time** | <5s | 5-10s | >10s |
| **Frame Rate** | >20 FPS | 15-20 FPS | <15 FPS |
| **Latency** | <100ms | 100-150ms | >150ms |
| **Bandwidth (idle)** | <200 Kbps | 200-500 Kbps | >500 Kbps |
| **Bandwidth (active)** | <1.5 Mbps | 1.5-2 Mbps | >2 Mbps |
| **Memory (idle)** | <400 MB | 400-512 MB | >512 MB |
| **Memory (active)** | <550 MB | 550-700 MB | >700 MB |

### Measuring Performance

```bash
# Startup time
time curl http://localhost:6080/vnc.html

# Frame rate (via browser DevTools)
# Chrome: DevTools > Rendering > Frame Rendering Stats

# Latency
ping -c 10 localhost

# Bandwidth
iftop -i eth0 -f "port 6080"

# Memory usage
docker stats <container>
```

---

## VNC Performance

### Encoding Options

**Tight Encoding** (Default):
```python
"-encoding", "Tight",
"-compression", "5",    # 0-9, higher = more compression
"-quality", "8",        # 0-9, higher = better quality
```

**Pros**: Best for web VNC, good compression
**Cons**: Higher CPU usage
**Best for**: General use, mixed content

**ZRLE Encoding**:
```python
"-encoding", "ZRLE",
"-compression", "5",
```

**Pros**: Low CPU, good compression
**Cons**: Lower quality on photos
**Best for**: Low-bandwidth connections

**H264 Encoding**:
```python
"-encoding", "H264",
```

**Pros**: Best for video, high compression
**Cons**: Not always available
**Best for**: Video playback, animations

### Tuning Compression

**For Low Bandwidth** (<1 Mbps):
```python
"-encoding", "ZRLE",
"-compression", "7",    # High compression
"-quality", "5",        # Lower quality
```

**For High Bandwidth** (>5 Mbps):
```python
"-encoding", "Tight",
"-compression", "3",    # Low compression
"-quality", "9",        # High quality
```

**For Balanced Performance** (Default):
```python
"-encoding", "Tight",
"-compression", "5",    # Medium compression
"-quality", "8",        # Good quality
```

### Resolution Tuning

| Resolution | Bandwidth | CPU | Best For |
|------------|-----------|-----|----------|
| 1920x1080 | High | High | Large screens, detail work |
| 1280x720 | Medium | Medium | Default, general use |
| 1024x576 | Low | Low | Low bandwidth, fast response |

**Change resolution**:
```json
{
  "name": "start_desktop",
  "arguments": {
    "resolution": "1024x576"
  }
}
```

---

## Resource Optimization

### CPU Optimization

**Limit CPU per container**:
```bash
docker run --cpus=2 ...
```

**CPU Pinning** (advanced):
```bash
docker run --cpuset-cpus=0,1 ...
```

**Monitor CPU usage**:
```bash
docker stats <container>
docker exec <container> top
```

**Reduce CPU usage**:
- Lower resolution (1024x576)
- Increase compression (-compression 7)
- Use ZRLE encoding instead of Tight
- Reduce color depth (-depth 16)

### Memory Optimization

**Limit memory**:
```bash
docker run -m 2g --memory-swap=2g ...
```

**Monitor memory**:
```bash
docker stats <container>
docker exec <container> free -h
docker exec <container> ps aux --sort=-%mem | head -10
```

**Reduce memory usage**:
- Use XFCE instead of GNOME (already done)
- Disable XFCE plugins
- Reduce desktop effects
- Limit concurrent sessions:
  ```bash
  MAX_CONCURRENT_SESSIONS=5
  ```

### Disk Optimization

**Use SSD storage**:
```bash
docker run --storage-opt size=20G ...
```

**Monitor disk I/O**:
```bash
docker exec <container> iotop
```

**Reduce disk usage**:
- Clean cache regularly:
  ```bash
  docker exec <container> rm -rf /workspace/.cache/*
  ```
- Use tmpfs for temporary files:
  ```bash
  docker run --tmpfs /tmp:rw,noexec,nosuid,size=1g ...
  ```

---

## Network Optimization

### Bandwidth Optimization

**For Low Bandwidth** (<2 Mbps):

1. **Reduce resolution**:
   ```json
   {"resolution": "1024x576"}
   ```

2. **Increase compression**:
   ```python
   "-compression", "7"
   "-quality", "5"
   ```

3. **Use ZRLE encoding**:
   ```python
   "-encoding", "ZRLE"
   ```

4. **Reduce color depth**:
   ```python
   "-depth", "16"  # Instead of 24
   ```

### Latency Optimization

**For High Latency** (>100ms):

1. **Use local display** (:1)
2. **Reduce frame rate** (client-side)
3. **Enable prediction** (client-side)
4. **Use wired connection** instead of WiFi

### Connection Optimization

**WebSocket Configuration**:
```python
# noVNC websockify settings
"--vnc", "localhost:5901",
"--listen", "6080",
"--timeout", "5",           # Connection timeout
"--idle-timeout", "60",     # Idle timeout
```

---

## Desktop Optimization

### XFCE Configuration

**Disable startup applications**:
```bash
# Edit autostart
rm /etc/xdg/autostart/xfce4-notifyd.desktop
```

**Reduce desktop effects**:
```xml
<!-- ~/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml -->
<property name="use_compositing" type="bool" value="false"/>
```

**Optimize panel**:
```xml
<!-- Remove plugins -->
<!-- Keep only essential plugins -->
```

### Session Management

**Limit session duration**:
```bash
SESSION_TIMEOUT=1800  # 30 minutes
```

**Auto-cleanup**:
```python
# Clean up inactive sessions
timeout_mgr.start_autocleanup(interval=60)
```

### Concurrent Users

**Per-instance user limit**:
```bash
MAX_CONCURRENT_SESSIONS=10
```

**Horizontal scaling**:
```yaml
# Multiple instances behind load balancer
services:
  sandbox-mcp:
    deploy:
      replicas: 3
```

---

## Scaling Strategies

### Vertical Scaling

**Add resources per instance**:
```bash
docker run \
  --cpus=4 \
  -m 8g \
  ...
```

**Benefits**:
- Simpler architecture
- No load balancer needed
- Lower latency

**When to use**:
- <10 concurrent users
- Single instance sufficient
- Low to medium traffic

### Horizontal Scaling

**Multiple instances**:
```yaml
version: '3.8'
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

**Load balancer configuration** (nginx.conf):
```nginx
upstream sandbox_mcp {
    least_conn;
    server sandbox-mcp-1:8765;
    server sandbox-mcp-2:8765;
    server sandbox-mcp-3:8765;
}

server {
    listen 80;
    location / {
        proxy_pass http://sandbox_mcp;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

**Benefits**:
- Better resource utilization
- Higher availability
- Easier scaling

**When to use**:
- 10+ concurrent users
- High traffic
- Need high availability

### Caching Strategy

**Workspace caching**:
```bash
# Use volume for persistent workspace
-v /opt/sandbox/workspace:/workspace
```

**Session caching**:
```python
# Cache session state
sessions = {}
```

---

## Performance Monitoring

### Metrics to Track

**System Metrics**:
```bash
# CPU
docker stats --format "table {{.Name}}\t{{.CPUPerc}}"

# Memory
docker stats --format "table {{.Name}}\t{{.MemUsage}}"

# Network
docker stats --format "table {{.Name}}\t{{.NetIO}}"
```

**Application Metrics**:
```bash
# Desktop status
curl http://localhost:8765/tools/call \
  -d '{"name": "get_desktop_status"}'

# Health check
curl http://localhost:8765/health
```

### Performance Profiling

**Profile VNC performance**:
```bash
# Check VNC process
docker exec <container> ps aux | grep vnc

# Monitor VNC traffic
tcpdump -i any -n 'tcp port 5901' -w vnc.pcap

# Analyze with Wireshark
```

**Profile XFCE performance**:
```bash
# Check XFCE process
docker exec <container> ps aux | grep xfce

# Monitor X11 traffic
docker exec <container> xrestop -display :1
```

---

## Performance Benchmarks

### Test Environment

- **CPU**: 4 cores
- **Memory**: 4 GB
- **Disk**: SSD
- **Network**: 1 Gbps

### Benchmark Results

| Configuration | Startup | Bandwidth | Memory | CPU |
|---------------|---------|-----------|--------|-----|
| 1920x1080, Tight, comp=3 | 4.2s | 2.1 Mbps | 580 MB | 25% |
| 1280x720, Tight, comp=5 | 3.8s | 1.4 Mbps | 520 MB | 20% |
| 1024x576, ZRLE, comp=7 | 3.5s | 0.8 Mbps | 480 MB | 15% |

**Recommended**: 1280x720, Tight, comp=5 (default)

---

## Optimization Checklist

### Quick Wins (5 minutes)

- [ ] Reduce resolution to 1024x576
- [ ] Increase compression to 7
- [ ] Disable compositing in XFCE
- [ ] Clean workspace cache

### Medium Optimization (15 minutes)

- [ ] Adjust VNC encoding (ZRLE for low bandwidth)
- [ ] Limit concurrent sessions
- [ ] Enable session timeout
- [ ] Add resource limits

### Advanced Optimization (1 hour)

- [ ] Tune kernel parameters
- [ ] Optimize Docker storage driver
- [ ] Implement load balancing
- [ ] Set up monitoring

---

## Common Performance Issues

### Issue: High Bandwidth Usage

**Symptoms**: >2 Mbps active usage

**Solutions**:
1. Reduce resolution
2. Increase compression
3. Use ZRLE encoding
4. Reduce color depth

### Issue: High CPU Usage

**Symptoms**: CPU >80%

**Solutions**:
1. Increase CPU limit
2. Reduce resolution
3. Use ZRLE instead of Tight
4. Limit concurrent users

### Issue: High Memory Usage

**Symptoms**: Memory >700 MB

**Solutions**:
1. Increase memory limit
2. Disable XFCE plugins
3. Limit concurrent sessions
4. Restart container regularly

---

## Tuning Profiles

### Low Bandwidth Profile

```python
# <2 Mbps connections
"-encoding", "ZRLE",
"-compression", "7",
"-quality", "5",
"-geometry", "1024x576",
"-depth", "16"
```

### Balanced Profile (Default)

```python
# 2-5 Mbps connections
"-encoding", "Tight",
"-compression", "5",
"-quality", "8",
"-geometry", "1280x720",
"-depth", "24"
```

### High Quality Profile

```python
# >5 Mbps connections
"-encoding", "Tight",
"-compression", "3",
"-quality", "9",
"-geometry", "1920x1080",
"-depth", "24"
```

---

## Summary

**Key Optimization Points**:

1. **Resolution**: Biggest impact on bandwidth
2. **Compression**: Trade-off between CPU and bandwidth
3. **Encoding**: Tight for general, ZRLE for low bandwidth
4. **Resources**: CPU and memory limits
5. **Scaling**: Vertical (simple) vs horizontal (scalable)

**Performance Targets**:

- ✅ Startup: <5 seconds
- ✅ Frame rate: >20 FPS
- ✅ Latency: <150ms
- ✅ Bandwidth: <2 Mbps active
- ✅ Memory: <512 MB idle

---

**Last Updated**: 2026-01-28
**Performance Guide Version**: 2.0
**Status**: Comprehensive ✅
