# Performance Tuning Guide

**Version**: 3.0
**Last Updated**: 2026-06-22
**Last checked against code**: 2026-06-22

Optimization guide for Sandbox MCP Server with KDE Plasma desktop served over KasmVNC.

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
time curl -k -u "sandbox:$SANDBOX_TOKEN" https://localhost:6080/

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

KasmVNC replaces the previous TigerVNC + noVNC + websockify stack with a single
all-in-one process. Its configuration model is different: image quality, frame
rate, and resolution are controlled through `/etc/kasmvnc/kasmvnc.yaml` (plus
runtime overrides via the web client and the `change_resolution` MCP tool) — not
through `-encoding` / `-compression` / `-quality` CLI flags. The TigerVNC-style
Tight / ZRLE / H264 encodings described in older revisions of this guide do not
apply to KasmVNC.

### Encoding Configuration

KasmVNC encodes the framebuffer with **WebP** and **JPEG** (with QOI as a fast
path for lossless regions). Quality is a 0-9 scalar per codec, configured under
the `encoding` block of `kasmvnc.yaml`:

```yaml
# /etc/kasmvnc/kasmvnc.yaml
desktop:
  resolution:
    width: 1920
    height: 1080
  allow_resize: true        # live resize via xrandr / web client
  pixel_depth: 24

encoding:
  max_frame_rate: 60        # ceiling; lower to save bandwidth/CPU
  video_encoding_mode:
    jpeg_quality: 8         # 0-9, lower = more compression
    webp_quality: 8         # 0-9, lower = more compression
```

The default shipped with the image targets balanced quality (`*_quality: 8`,
`max_frame_rate: 60`). See `docker/kasmvnc-configs/kasmvnc.yaml` for the full
reference.

### Tuning Quality vs. Bandwidth

**For Low Bandwidth** (<1 Mbps):

```yaml
encoding:
  max_frame_rate: 24
  video_encoding_mode:
    jpeg_quality: 4
    webp_quality: 4
```

**For High Bandwidth** (>5 Mbps):

```yaml
encoding:
  max_frame_rate: 60
  video_encoding_mode:
    jpeg_quality: 9
    webp_quality: 9
```

**For Balanced Performance** (Default):

```yaml
encoding:
  max_frame_rate: 60
  video_encoding_mode:
    jpeg_quality: 8
    webp_quality: 8
```

After editing `/etc/kasmvnc/kasmvnc.yaml`, restart the desktop to pick up the new
values (`restart_desktop` MCP tool or `vncserver -kill :1` then restart). The
web client can also override the items listed under
`runtime_configuration.allow_override_list` at view time.

### Resolution Tuning

| Resolution | Bandwidth | CPU | Best For |
|------------|-----------|-----|----------|
| 2560x1440 | Highest | Highest | Large screens, detail work |
| 1920x1080 | High | High | Default |
| 1600x900 | Medium | Medium | Balanced |
| 1280x720 | Low | Low | Low bandwidth, fast response |

Supported resolutions (from `desktop_tools.py`): `1280x720`, `1600x900`,
`1920x1080`, `2560x1440`. Default is `1920x1080`.

**Change resolution** (live, no restart — KasmVNC supports dynamic resize):
```json
{
  "name": "change_resolution",
  "arguments": {
    "resolution": "1280x720"
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
- Lower resolution (1280x720 via `change_resolution`)
- Lower the KasmVNC frame-rate ceiling (`encoding.max_frame_rate` in `kasmvnc.yaml`)
- Lower WebP/JPEG quality (`encoding.video_encoding_mode.{jpeg,webp}_quality`)
- KasmVNC always runs at `-depth 24`; do not try to set `-depth 16`

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
- The desktop ships KDE Plasma 5.27 from Ubuntu 24.04 LTS; prefer the minimal package set
- Disable KDE Plasma effects or widgets you do not need
- Lower resolution (1280x720 via `change_resolution`)
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

1. **Reduce resolution** (live, via the MCP tool):
   ```json
   {"name": "change_resolution", "arguments": {"resolution": "1280x720"}}
   ```

2. **Lower KasmVNC quality** (in `/etc/kasmvnc/kasmvnc.yaml`):
   ```yaml
   encoding:
     video_encoding_mode:
       jpeg_quality: 4
       webp_quality: 4
   ```

3. **Lower the frame-rate ceiling**:
   ```yaml
   encoding:
     max_frame_rate: 24
   ```

KasmVNC always serves `-depth 24`; lowering color depth is not an available
lever (the TigerVNC-style `-depth 16` trick does not apply).

### Latency Optimization

**For High Latency** (>100ms):

1. **Use local display** (:1)
2. **Reduce frame rate** (`encoding.max_frame_rate` in `kasmvnc.yaml`, or via the web client)
3. **Enable prediction** (client-side)
4. **Use wired connection** instead of WiFi

### Connection Optimization

**KasmVNC Web Server**:
```yaml
# /etc/kasmvnc/kasmvnc.yaml
network:
  protocol: http
  websocket_port: auto
  interface: 0.0.0.0
  use_ipv4: true
  use_ipv6: false
user_session:
  idle_timeout: 0        # 0 = no idle disconnect (raise to enforce one)
```

KasmVNC serves the VNC protocol, WebSocket, and the built-in web client from a
single process on the `DESKTOP_PORT` (default 6080). There is no separate
websockify to tune.

---

## Desktop Optimization

### KDE Plasma Configuration

The desktop environment is KDE Plasma 5.27 from Ubuntu 24.04 LTS (the image no longer ships XFCE).
Plasma configs are baked into the image under `/etc/xdg/` (`kdeglobals`,
`kwinrc`, `katerc`, `dolphinrc`, `konsolerc`) and per-user under `~/.config/`.

**Disable startup applications**: remove or override the corresponding
`.desktop` autostart entries under `/etc/xdg/autostart/` or
`~/.config/autostart/`.

**Reduce desktop effects** (compositor):
```ini
# ~/.config/kwinrc
[Compositing]
CompositingEnabled=false
```

**Optimize panel / widgets**: trim widgets and effects you don't need through
*System Settings* (or by editing `~/.config/plasma-org.kde.plasma.desktop-appletsrc`).

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

**Profile KasmVNC performance**:
```bash
# Check KasmVNC X server process
docker exec <container> ps aux | grep -E "Xkasmvnc|vncserver"

# Monitor web/VNC traffic (KasmVNC serves WebSocket on DESKTOP_PORT, default 6080)
tcpdump -i any -n 'tcp port 6080' -w kasmvnc.pcap

# Analyze with Wireshark
```

**Profile KDE Plasma performance**:
```bash
# Check Plasma processes
docker exec <container> ps aux | grep -E "startplasma|plasmashell|kwin"

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
| 1920x1080, webp/jpeg q=9, 60 FPS | 4.2s | 2.1 Mbps | 580 MB | 25% |
| 1920x1080, webp/jpeg q=8, 60 FPS (default) | 3.9s | 1.6 Mbps | 540 MB | 22% |
| 1280x720, webp/jpeg q=4, 24 FPS | 3.5s | 0.8 Mbps | 480 MB | 15% |

**Recommended**: 1920x1080 at the shipped default quality (`*_quality: 8`,
`max_frame_rate: 60`); drop to `1280x720` + lower quality on constrained links.

---

## Optimization Checklist

### Quick Wins (5 minutes)

- [ ] Reduce resolution to 1280x720 (`change_resolution` tool)
- [ ] Lower `encoding.video_encoding_mode.{jpeg,webp}_quality` to 5 in `kasmvnc.yaml`
- [ ] Disable KDE Plasma compositing (`~/.config/kwinrc`)
- [ ] Clean workspace cache

### Medium Optimization (15 minutes)

- [ ] Lower `encoding.max_frame_rate` in `kasmvnc.yaml`
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
1. Reduce resolution (1280x720)
2. Lower `encoding.video_encoding_mode.{jpeg,webp}_quality`
3. Lower `encoding.max_frame_rate`
4. KasmVNC is fixed at `-depth 24`; color depth is not a lever

### Issue: High CPU Usage

**Symptoms**: CPU >80%

**Solutions**:
1. Increase CPU limit
2. Reduce resolution
3. Lower `encoding.max_frame_rate`
4. Limit concurrent users

### Issue: High Memory Usage

**Symptoms**: Memory >700 MB

**Solutions**:
1. Increase memory limit
2. Trim KDE Plasma widgets/effects
3. Limit concurrent sessions
4. Restart container regularly

---

## Tuning Profiles

All profiles are expressed as snippets of `/etc/kasmvnc/kasmvnc.yaml`.
Resolution can also be changed at runtime through the `change_resolution` MCP
tool without restarting the desktop.

### Low Bandwidth Profile

```yaml
# <2 Mbps connections
desktop:
  resolution:
    width: 1280
    height: 720
encoding:
  max_frame_rate: 24
  video_encoding_mode:
    jpeg_quality: 4
    webp_quality: 4
```

### Balanced Profile (Default)

```yaml
# 2-5 Mbps connections
desktop:
  resolution:
    width: 1920
    height: 1080
encoding:
  max_frame_rate: 60
  video_encoding_mode:
    jpeg_quality: 8
    webp_quality: 8
```

### High Quality Profile

```yaml
# >5 Mbps connections
desktop:
  resolution:
    width: 2560
    height: 1440
encoding:
  max_frame_rate: 60
  video_encoding_mode:
    jpeg_quality: 9
    webp_quality: 9
```

---

## Summary

**Key Optimization Points**:

1. **Resolution**: Biggest impact on bandwidth (1280x720 → 2560x1440)
2. **Quality (WebP/JPEG)**: 0-9 scalar, trade-off between CPU and bandwidth
3. **Frame rate**: `encoding.max_frame_rate` caps throughput
4. **Resources**: CPU and memory limits
5. **Scaling**: Vertical (simple) vs horizontal (scalable)

**Performance Targets**:

- ✅ Startup: <5 seconds
- ✅ Frame rate: >20 FPS
- ✅ Latency: <150ms
- ✅ Bandwidth: <2 Mbps active
- ✅ Memory: <512 MB idle

---

**Last Updated**: 2026-06-22
**Performance Guide Version**: 3.0
**Status**: Comprehensive ✅
