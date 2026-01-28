# Troubleshooting Guide

**Version**: 2.0
**Last Updated**: 2026-01-28

Common issues and solutions for Sandbox MCP Server with XFCE desktop.

---

## Table of Contents

1. [Desktop Issues](#desktop-issues)
2. [VNC Connection Issues](#vnc-connection-issues)
3. [Performance Issues](#performance-issues)
4. [Container Issues](#container-issues)
5. [MCP Tool Issues](#mcp-tool-issues)
6. [Resource Issues](#resource-issues)

---

## Desktop Issues

### Desktop Won't Start

**Symptoms**:
- VNC connection times out
- "Desktop not running" status
- Error in logs: "Desktop components not installed"

**Diagnosis**:
```bash
# Check if XFCE is installed
docker exec <container> dpkg -l | grep xfce4

# Check VNC process
docker exec <container> ps aux | grep vnc

# Check Xvfb process
docker exec <container> ps aux | grep Xvfb
```

**Solutions**:

1. **Rebuild image with XFCE**:
   ```bash
   docker build -t sandbox-mcp-server .
   ```

2. **Verify installation**:
   ```bash
   docker run --rm sandbox-mcp-server dpkg -l | grep xfce4
   ```

3. **Check logs**:
   ```bash
   docker logs <container> | grep -i desktop
   ```

### Desktop Crashes Immediately

**Symptoms**:
- Desktop starts then crashes
- "Xvfb exited immediately" error
- Return code 1 or 139

**Diagnosis**:
```bash
# Check Xvfb logs
docker exec <container> cat /tmp/Xvfb.log

# Check display conflicts
docker exec <container> ls -la /tmp/.X11-unix/
```

**Solutions**:

1. **Change display number**:
   ```json
   {
     "name": "start_desktop",
     "arguments": {
       "display": ":2"
     }
   }
   ```

2. **Reduce resolution**:
   ```json
   {
     "resolution": "1024x576"
   }
   ```

3. **Check for conflicts**:
   ```bash
   docker exec <container> pkill Xvfb
   docker exec <container> pkill vncserver
   ```

### Desktop Freezes

**Symptoms**:
- Desktop becomes unresponsive
- Mouse/keyboard don't work
- VNC connection alive but no updates

**Diagnosis**:
```bash
# Check XFCE process
docker exec <container> ps aux | grep xfce4-session

# Check CPU usage
docker exec <container> top
```

**Solutions**:

1. **Restart desktop**:
   ```json
   {
     "name": "restart_desktop"
   }
   ```

2. **Check resource limits**:
   ```bash
   docker stats <container>
   ```

3. **Increase container memory**:
   ```bash
   docker run -m 4g ...
   ```

---

## VNC Connection Issues

### "Connection Refused"

**Symptoms**:
- Browser shows "Connection refused"
- `curl http://localhost:6080` fails
- Port not accessible

**Diagnosis**:
```bash
# Check if container is running
docker ps

# Check port mapping
docker port <container>

# Check noVNC process
docker exec <container> ps aux | grep websockify
```

**Solutions**:

1. **Verify port mapping**:
   ```bash
   docker run -p 6080:6080 ...
   ```

2. **Check firewall**:
   ```bash
   sudo ufw allow 6080/tcp
   ```

3. **Restart container**:
   ```bash
   docker restart <container>
   ```

### "VNC Authentication Failed"

**Symptoms**:
- Browser shows authentication prompt
- Password doesn't work
- Access denied

**Diagnosis**:
```bash
# Check VNC security settings
docker exec <container> ps aux | grep vnc | grep -o "\-securitytypes [^ ]*"
```

**Solutions**:

1. **Verify no authentication** (default):
   ```bash
   # Should show: -securitytypes None
   ```

2. **If authentication enabled**:
   - Check VNC password file
   - Verify password in ~/.vnc/passwd
   - Disable authentication for container use

### Slow VNC Performance

**Symptoms**:
- Laggy desktop response
- Low frame rate
- High latency

**Diagnosis**:
```bash
# Check bandwidth usage
docker stats <container>

# Check VNC encoding
docker exec <container> ps aux | grep vnc
```

**Solutions**:

1. **Reduce resolution**:
   ```json
   {"resolution": "1024x576"}
   ```

2. **Adjust compression** (modify code):
   ```python
   "-compression", "7",  # Higher = more compression
   ```

3. **Check network bandwidth**:
   ```bash
   # Minimum 2 Mbps required
   speedtest-cli
   ```

---

## Performance Issues

### High CPU Usage

**Symptoms**:
- CPU >80%
- Container throttled
- Slow response

**Diagnosis**:
```bash
# Check CPU usage
docker stats <container>

# Check top processes
docker exec <container> top
```

**Solutions**:

1. **Increase CPU limit**:
   ```bash
   docker run --cpus=2 ...
   ```

2. **Reduce resolution**:
   ```json
   {"resolution": "1024x576"}
   ```

3. **Limit concurrent users**:
   ```bash
   MAX_CONCURRENT_SESSIONS=5
   ```

### High Memory Usage

**Symptoms**:
- Memory >3.5 GB
- OOM killer kills processes
- Container restarts

**Diagnosis**:
```bash
# Check memory usage
docker stats <container>

# Check memory details
docker exec <container> free -h
```

**Solutions**:

1. **Increase memory limit**:
   ```bash
   docker run -m 4g ...
   ```

2. **Stop unused desktops**:
   ```json
   {"name": "stop_desktop"}
   ```

3. **Restart container**:
   ```bash
   docker restart <container>
   ```

### Slow Startup

**Symptoms**:
- Desktop takes >10 seconds to start
- Long delay before VNC available

**Diagnosis**:
```bash
# Check startup time
time docker exec <container> start_desktop

# Check startup logs
docker logs <container> | grep -i "starting"
```

**Solutions**:

1. **Use SSD storage**:
   ```bash
   --storage-opt size=20G
   ```

2. **Pre-pull image**:
   ```bash
   docker pull sandbox-mcp-server:latest
   ```

3. **Check system resources**:
   ```bash
   docker info
   ```

---

## Container Issues

### Container Won't Start

**Symptoms**:
- `docker run` fails immediately
- Error message about ports or volumes
- Container exits with code 1

**Diagnosis**:
```bash
# Check error logs
docker logs <container>

# Check port conflicts
netstat -tlnp | grep -E "8765|7681|6080"
```

**Solutions**:

1. **Fix port conflicts**:
   ```bash
   # Change ports
   docker run -p 8766:8765 ...
   ```

2. **Fix volume permissions**:
   ```bash
   sudo chown -R 1001:1001 ./workspace
   ```

3. **Check image**:
   ```bash
   docker images | grep sandbox-mcp
   docker build -t sandbox-mcp-server .
   ```

### Container Exits Unexpectedly

**Symptoms**:
- Container stops without warning
- Restart loop
- No clear error message

**Diagnosis**:
```bash
# Check exit code
docker ps -a | grep <container>

# Check logs
docker logs <container> --tail 100

# Check health status
docker inspect <container> | grep -A 10 Health
```

**Solutions**:

1. **Check resource limits**:
   ```bash
   docker stats
   ```

2. **Check OOM killer**:
   ```bash
   dmesg | grep -i kill
   ```

3. **Enable restart policy**:
   ```bash
   docker run --restart unless-stopped ...
   ```

---

## MCP Tool Issues

### Tools Not Responding

**Symptoms**:
- MCP tools timeout
- No response from server
- "Tool not found" error

**Diagnosis**:
```bash
# Check MCP server
curl http://localhost:8765/health

# Check logs
docker logs <container> | grep -i mcp

# Test WebSocket connection
wscat -c ws://localhost:8765
```

**Solutions**:

1. **Restart MCP server**:
   ```bash
   docker restart <container>
   ```

2. **Verify tool registration**:
   ```bash
   # Check tools/list response
   ```

3. **Check WebSocket**:
   ```bash
   # Verify WebSocket is accessible
   curl -i -N \
     -H "Connection: Upgrade" \
     -H "Upgrade: websocket" \
     http://localhost:8765
   ```

### "get_desktop_status" Returns Wrong Info

**Symptoms**:
- Status shows not running when it is
- PID doesn't match actual process
- Port numbers incorrect

**Diagnosis**:
```bash
# Check actual processes
docker exec <container> ps aux | grep -E "Xvfb|vnc"

# Compare with status
curl -X POST http://localhost:8765/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "get_desktop_status"}'
```

**Solutions**:

1. **Restart desktop**:
   ```json
   {"name": "restart_desktop"}
   ```

2. **Clear cache**:
   ```bash
   docker exec <container> pkill -9 -f xfce
   docker exec <container> pkill -9 -f vnc
   ```

3. **Verify DesktopManager state**:
   ```bash
   # Check if processes are tracked correctly
   ```

---

## Resource Issues

### Out of Memory

**Symptoms**:
- Container killed by OOM
- "Cannot allocate memory"
- Processes die randomly

**Diagnosis**:
```bash
# Check memory usage
docker stats <container>

# Check OOM events
dmesg | grep -i oom

# Check container limits
docker inspect <container> | grep -i memory
```

**Solutions**:

1. **Increase memory**:
   ```bash
   docker run -m 4g --memory-swap=4g ...
   ```

2. **Limit desktop sessions**:
   ```bash
   MAX_CONCURRENT_SESSIONS=3
   ```

3. **Add swap space**:
   ```bash
   --memory-swap=8g
   ```

### Disk Space Full

**Symptoms**:
- "No space left on device"
- Cannot write files
- Container crashes

**Diagnosis**:
```bash
# Check disk usage
docker exec <container> df -h

# Check Docker disk usage
docker system df

# Find large files
docker exec <container> du -sh /workspace/* | sort -rh | head -10
```

**Solutions**:

1. **Clean workspace**:
   ```bash
   docker exec <container> rm -rf /workspace/.cache/*
   ```

2. **Increase disk size**:
   ```bash
   docker run --storage-opt size=20G ...
   ```

3. **Clean Docker system**:
   ```bash
   docker system prune -a
   ```

---

## Getting Help

### Diagnostic Information

When reporting issues, collect:

```bash
# System info
docker version
docker info
uname -a

# Container info
docker ps -a
docker stats
docker logs <container> --tail 100

# Desktop info
docker exec <container> ps aux | grep -E "Xvfb|xfce|vnc"
docker exec <container> df -h
docker exec <container> free -h

# Network info
docker port <container>
netstat -tlnp | grep -E "8765|7681|6080"
```

### Where to Get Help

1. **Documentation**: README.md, DEPLOYMENT.md, PERFORMANCE.md
2. **GitHub Issues**: Create issue with diagnostic info
3. **Logs**: Always include relevant log excerpts
4. **Steps to Reproduce**: Clear reproduction steps

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| "Desktop components not installed" | XFCE missing | Rebuild image |
| "Connection refused" | Port not mapped | Add `-p 6080:6080` |
| "Xvfb exited immediately" | Display conflict | Change display number |
| "Cannot allocate memory" | OOM | Increase memory limit |
| "No space left on device" | Disk full | Clean workspace |
| "Tool not found" | Server restart needed | Restart container |
| "VNC authentication failed" | Auth enabled | Disable for container |

---

## Quick Reference

### Essential Commands

```bash
# Check container health
docker ps
docker stats
docker logs -f <container>

# Restart services
docker restart <container>
docker exec <container> pkill -HUP xfce4-session

# Clean up
docker exec <container> rm -rf /tmp/.X11-unix/*
docker exec <container> vncserver -kill :1

# Test connection
curl http://localhost:8765/health
curl http://localhost:6080/vnc.html
```

---

**Last Updated**: 2026-01-28
**Troubleshooting Guide Version**: 2.0
**Status**: Comprehensive ✅
