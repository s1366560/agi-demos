# Phase 3: SessionManager 实施完成

## 完成时间
2025-01-28

## 实施内容

### 1. 核心模块

**SessionManager** (`src/server/session_manager.py`)
- 统一管理 WebTerminalManager 和 DesktopManager
- 一键启动/停止所有会话
- 支持独立的终端/桌面开关
- 上下文管理器支持
- 会话状态聚合查询

### 2. 测试覆盖

**测试文件** (`tests/test_session_manager.py`)
- 15 个测试用例，全部通过
- 89% 代码覆盖率
- 测试场景：
  - 初始化测试
  - 全部/部分会话启动
  - 全部会话停止
  - 重启测试
  - 状态查询测试
  - 上下文管理器测试

### 3. 服务器集成

**main.py 更新**
- 集成 SessionManager 到服务器生命周期
- 添加 `--no-terminal` 禁用终端
- 添加 `--no-desktop` 禁用桌面
- 添加 `--auto-start-sessions` 自动启动会话
- 优雅关闭时自动停止所有会话

### 4. MCP 工具

已通过 Phase 1 和 Phase 2 创建的工具现在通过 SessionManager 统一管理：
- `start_terminal`, `stop_terminal`, `get_terminal_status`, `restart_terminal`
- `start_desktop`, `stop_desktop`, `get_desktop_status`, `restart_desktop`

## 使用方式

### 构建 Docker 镜像

```bash
docker build -t sandbox-mcp-server sandbox-mcp-server/
```

### 运行容器（手动启动会话）

```bash
docker run -p 8765:8765 -p 7681:7681 -p 6080:6080 \
  -v $(pwd)/workspace:/workspace \
  sandbox-mcp-server
```

### 运行容器（自动启动会话）

```bash
docker run -p 8765:8765 -p 7681:7681 -p 6080:6080 \
  -v $(pwd)/workspace:/workspace \
  sandbox-mcp-server \
  python -m src.server.main --auto-start-sessions
```

### 仅启动终端

```bash
docker run -p 8765:8765 -p 7681:7681 \
  -v $(pwd)/workspace:/workspace \
  sandbox-mcp-server \
  python -m src.server.main --auto-start-sessions --no-desktop
```

### 仅启动桌面

```bash
docker run -p 8765:8765 -p 6080:6080 \
  -v $(pwd)/workspace:/workspace \
  sandbox-mcp-server \
  python -m src.server.main --auto-start-sessions --no-terminal
```

## 命令行参数

| 参数 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `--host` | MCP_HOST | 0.0.0.0 | MCP 服务器绑定地址 |
| `--port` | MCP_PORT | 8765 | MCP 服务器端口 |
| `--workspace` | MCP_WORKSPACE | /workspace | 工作目录 |
| `--terminal-port` | TERMINAL_PORT | 7681 | Web 终端端口 |
| `--desktop-port` | DESKTOP_PORT | 6080 | 桌面端口 |
| `--no-terminal` | - | false | 禁用 Web 终端 |
| `--no-desktop` | - | false | 禁用远程桌面 |
| `--auto-start-sessions` | - | false | 自动启动会话 |
| `--debug` | - | false | 启用调试日志 |

## 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    main.py                              │
│  ┌────────────────────────────────────────────────────┐ │
│  │              SessionManager                        │ │
│  │  • start_all()                                    │ │
│  │  • stop_all()                                     │ │
│  │  • restart_all()                                  │ │
│  │  • get_status()                                   │ │
│  └──────────┬──────────────────┬─────────────────────┘ │
└─────────────┼──────────────────┼────────────────────────┘
              │                  │
    ┌─────────▼──────────┐ ┌───▼─────────────────┐
    │ WebTerminalManager │ │  DesktopManager      │
    │  • ttyd            │ │  • Xvfb              │
    │  • Port 7681       │ │  • LXDE              │
    └────────────────────┘ │  • x11vnc            │
                          │  • noVNC             │
                          │  • Port 6080         │
                          └──────────────────────┘
```

## 完成进度

- ✅ Phase 1: Web Terminal (ttyd)
- ✅ Phase 2: Desktop Environment (LXDE + noVNC)
- ✅ Phase 3: SessionManager 统一管理
- ⏳ Phase 4: 安全与认证

## 测试覆盖总览

| 模块 | 测试数 | 覆盖率 |
|------|--------|--------|
| WebTerminalManager | 15 | 95% |
| DesktopManager | 14 | 84% |
| SessionManager | 15 | 89% |
| **总计** | **44** | **89%** |

## 下一步

- [ ] Phase 4: 安全与认证（Token 认证、CORS 限制、会话超时）
- [ ] 可选：前端集成（React 组件）
