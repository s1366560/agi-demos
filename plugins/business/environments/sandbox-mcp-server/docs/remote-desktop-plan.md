# Sandbox 远程桌面和 Shell 支持实施计划

> 创建日期: 2025-01-28
> 状态: 计划中
> 预计工期: 12-16 天

---

## 一、需求概述

为 `sandbox-mcp-server` 增加 Web 终端和远程桌面访问能力，使用户能够通过浏览器直接操作 sandbox 容器。

### 功能目标

1. **Web Terminal** - 浏览器内访问 shell 终端
2. **Remote Desktop** - 完整的图形界面桌面环境

---

## 二、技术选型

### 2.1 Web Terminal

| 选项 | 优势 | 劣势 | 选择 |
|------|------|------|------|
| **ttyd** | 轻量(~2MB)、C实现、纯WebSocket | 功能较少 | ✅ 采用 |
| gotty | Go实现、简单 | 维护较少 | 备选 |
| wetty | 功能丰富 | Node.js依赖重 | 不采用 |

### 2.2 远程桌面

| 组件 | 选择 | 理由 |
|------|------|------|
| Desktop Environment | **LXDE** | 最轻量，~400MB |
| VNC Server | **x11vnc** | 共享现有X11 |
| Web Client | **noVNC** | 纯HTML/JS，无需客户端 |

### 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Browser                              │
├──────────────────────┬──────────────────────────────────┤
│   Web Terminal       │      Remote Desktop              │
│   (ttyd WebSocket)   │      (noVNC)                     │
└──────────┬───────────┴──────────────┬───────────────────┘
           │                          │
           │ Port 7681                │ Port 6080
           │                          │
┌──────────▼──────────────────────────▼───────────────────┐
│                 sandbox-mcp-server                      │
├──────────────────────┬──────────────────────────────────┤
│   ttyd               │   Xvfb :1                        │
│   (shell access)     │   ├─ LXDE                        │
│                      │   ├─ x11vnc (5900)               │
│                      │   └─ websockify (6080)           │
└──────────────────────┴──────────────────────────────────┘
```

---

## 三、端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| 8765 | MCP WebSocket | 现有 |
| 6080 | noVNC | 远程桌面 Web 客户端 |
| 7681 | ttyd | Web Terminal |
| 5900 | x11vnc | 内部使用，不对外暴露 |

---

## 四、环境变量

```bash
# Desktop
DESKTOP_ENABLED=true              # 是否启用桌面
DESKTOP_RESOLUTION=1280x720       # 桌面分辨率
DESKTOP_PORT=6080                 # noVNC 端口

# Terminal
TERMINAL_ENABLED=true             # 是否启用终端
TERMINAL_PORT=7681                # ttyd 端口

# Session
SESSION_TIMEOUT=1800              # 会话超时(秒)，默认30分钟
```

---

## 五、实施计划

### Phase 1: Web Terminal (ttyd) [2-3 天]

**目标**: 实现浏览器内 shell 终端访问

**任务清单**:

1. **Dockerfile 修改**
   ```dockerfile
   # 安装 ttyd
   RUN ARCH=$(dpkg --print-architecture) && \
       curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.4/ttyd.linux_${ARCH}.tar.gz \
       | tar -xz -C /usr/local/bin && \
       chmod +x /usr/local/bin/ttyd
   ```

2. **创建 WebTerminalManager**
   - 管理 ttyd 子进程
   - 启动/停止/状态查询
   - 端口配置

3. **添加路由**
   - `/terminal` - 重定向到 ttyd WebSocket
   - `/terminal/status` - 终端状态 API

4. **MCP 工具**
   - `create_terminal_session` - 创建终端会话
   - `get_terminal_status` - 获取状态

5. **测试**
   - ttyd 启动成功
   - WebSocket 连接正常
   - 命令执行正确

**Deliverables**:
- `src/server/web_terminal.py`
- `src/tools/terminal_tools.py`
- 测试文件 `tests/test_web_terminal.py`

---

### Phase 2: Desktop Environment [3-4 天]

**目标**: 实现 LXDE 桌面环境 + noVNC

**任务清单**:

1. **Dockerfile 修改**
   ```dockerfile
   # 安装桌面环境
   RUN apt-get update && apt-get install -y --no-install-recommends \
       xorg openbox lxde lxde-core lxterminal \
       x11vnc \
       vim geany \
       && rm -rf /var/lib/apt/lists/*

   # 安装 noVNC
   ENV NOVNC_VERSION=1.5.0
   RUN curl -fsSL https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz \
       | tar -xz -C /opt && \
       mv /opt/noVNC-${NOVNC_VERSION} /opt/noVNC
   ```

2. **启动脚本**
   ```bash
   #!/bin/bash
   export DISPLAY=:1
   Xvfb :1 -screen 0 1280x720x24 &
   startlxde &
   x11vnc -display :1 -forever -nopw -shared &
   /opt/noVNC/utils/novnc_proxy --vnc localhost:5900 --listen 6080
   ```

3. **进程管理**
   - Xvfb 虚拟显示
   - LXDE 桌面环境
   - x11vnc VNC 服务器
   - websockify WebSocket 代理

4. **测试**
   - 桌面启动成功
   - noVNC 可访问
   - 鼠标键盘响应正常

**Deliverables**:
- `scripts/start-desktop.sh`
- Dockerfile 更新
- 测试文件 `tests/test_desktop.py`

---

### Phase 3: Python 集成 [2-3 天]

**目标**: 会话管理和 MCP 工具集成

**任务清单**:

1. **SessionManager 类**
   ```python
   class SessionManager:
       """管理桌面和终端会话"""

       async def start_all(self)
       async def stop_all(self)
       async def get_status(self) -> SessionStatus
   ```

2. **MCP 工具**
   - `start_desktop_session` - 启动桌面
   - `stop_desktop_session` - 停止桌面
   - `get_desktop_status` - 桌面状态
   - `create_terminal_session` - 创建终端
   - `get_session_info` - 会话信息

3. **服务器集成**
   - 与 MCPWebSocketServer 集成
   - 启动时自动启动会话
   - 关闭时优雅停止

4. **测试**
   - 会话生命周期
   - 多会话管理
   - 异常恢复

**Deliverables**:
- `src/server/session_manager.py`
- `src/tools/desktop_tools.py`
- 测试文件

---

### Phase 4: 安全与认证 [2 天]

**目标**: 实现安全机制

**任务清单**:

1. **Token 认证**
   - 生成一次性访问 token
   - 验证 token 有效性
   - token 过期机制

2. **WebSocket 安全**
   - CORS 限制
   - Origin 验证
   - 连接频率限制

3. **会话管理**
   - 空闲超时自动关闭
   - 资源使用限制
   - 进程看门狗

4. **命令安全**
   - 危险命令黑名单
   - 资源限制 (ulimit)
   - sudo 权限控制

5. **测试**
   - 认证流程测试
   - 超时测试
   - 安全边界测试

**Deliverables**:
- `src/server/auth_middleware.py`
- 安全测试套件

---

### Phase 5: 前端集成（可选）[3-4 天]

**目标**: React 组件集成

**任务清单**:

1. **组件开发**
   - `RemoteDesktop.tsx` - 桌面 iframe 组件
   - `WebTerminal.tsx` - 终端 WebSocket 组件
   - `SessionControl.tsx` - 会话控制面板

2. **功能实现**
   - 连接状态指示
   - 分辨率调整
   - 全屏切换
   - 断线重连

3. **集成测试**
   - E2E 测试
   - 性能测试

**Deliverables**:
- React 组件
- E2E 测试

---

## 六、风险评估

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 资源耗尽 | 高 | 中 | Docker 限制 + 会话超时 |
| 安全漏洞 | 高 | 低 | Token 认证 + 命令黑名单 |
| 会话状态问题 | 中 | 中 | 看门狗进程 + 健壮生命周期 |
| 性能下降 | 中 | 中 | LXDE 最小化 + 禁用动画 |
| 端口冲突 | 低 | 低 | 可配置端口 + 健康检查 |

---

## 七、复杂度评估

| Phase | 复杂度 | 预计时间 |
|-------|--------|----------|
| Phase 1: Web Terminal | 中 | 2-3 天 |
| Phase 2: Desktop Environment | 高 | 3-4 天 |
| Phase 3: Python 集成 | 中 | 2-3 天 |
| Phase 4: 安全与认证 | 中 | 2 天 |
| Phase 5: 前端集成 | 低-中 | 3-4 天 |
| **总计** | **高** | **12-16 天** |

---

## 八、关键文件

| 文件 | 说明 |
|------|------|
| `sandbox-mcp-server/Dockerfile` | 安装依赖 |
| `sandbox-mcp-server/src/server/main.py` | 服务器入口 |
| `sandbox-mcp-server/src/server/web_terminal.py` | 终端管理器 |
| `sandbox-mcp-server/src/server/session_manager.py` | 会话管理器 |
| `sandbox-mcp-server/src/tools/desktop_tools.py` | 桌面 MCP 工具 |
| `sandbox-mcp-server/scripts/start-desktop.sh` | 桌面启动脚本 |

---

## 九、依赖检查

- [x] Dockerfile 可用
- [x] 基础镜像 ubuntu:24.04
- [x] Python 3.12 环境
- [x] aiohttp 已安装

---

## 十、下一步

开始 **Phase 1: Web Terminal (ttyd) 实现**

1. 修改 Dockerfile 添加 ttyd
2. 创建 WebTerminalManager 类
3. 实现路由和 MCP 工具
4. 编写测试
