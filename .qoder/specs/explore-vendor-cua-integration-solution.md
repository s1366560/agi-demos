# CUA 与 MemStack 集成方案

## 概述

本方案将 **CUA (Computer Use Agent)** 集成到 MemStack 系统中，使 MemStack Agent 具备完整的计算机操作能力（UI 自动化、浏览器交互、表单填写等）。

## 用户需求确认

| 决策项 | 选择 | 说明 |
|--------|------|------|
| 运行环境 | **Docker 容器** | 提供安全隔离，需要配置 Docker 提供商 |
| 使用场景 | **通用计算机操作** | 浏览器 + 桌面 UI 完整能力 |
| 集成深度 | **完整三层集成** | L1 工具层 + L2 技能层 + L3 子代理层 |

## 1. CUA 项目分析

### 1.1 CUA 核心组件

**CUA** 是一个开源平台，用于构建能够与计算机交互的 AI 代理。

```
vendor/cua/libs/python/
├── core/                  # 核心功能、遥测
├── agent/                 # AI 代理框架（主要集成点）
│   ├── agent.py          # ComputerAgent 主类
│   ├── tools/base.py     # BaseTool 工具基类
│   ├── callbacks/base.py # AsyncCallbackHandler 回调
│   └── loops/            # 15+ 种代理循环实现
├── computer/             # 计算机控制接口
│   ├── computer.py       # Computer 主类
│   └── providers/        # VM 提供商 (Docker, Cloud, Lume)
└── som/                  # Set-of-Mark 解析器
```

### 1.2 核心类分析

| 类名 | 文件位置 | 职责 |
|------|----------|------|
| `ComputerAgent` | `agent/agent.py` | 主代理类，自动选择代理循环，流式输出 |
| `Computer` | `computer/computer.py` | 计算机控制接口，跨平台支持 |
| `BaseTool` | `agent/tools/base.py` | 工具基类，OpenAI Function Calling 格式 |
| `AsyncCallbackHandler` | `agent/callbacks/base.py` | 异步回调处理器 |

### 1.3 CUA 关键特性

- **多模型支持**：通过 LiteLLM 支持 15+ LLM 提供商
- **跨平台**：macOS, Linux, Windows, Android
- **VM 隔离**：支持 Docker, Cloud, Apple Vz (Lume)
- **回调系统**：完整的生命周期钩子
- **工具系统**：`@register_tool` 装饰器全局注册

## 2. MemStack 现有架构

### 2.1 Agent 核心组件

```
src/infrastructure/agent/
├── core/
│   ├── react_agent.py    # ReActAgent 主类
│   ├── processor.py      # SessionProcessor 会话处理器
│   └── events.py         # SSE 事件定义
├── tools/
│   └── base.py           # AgentTool 工具基类
├── permission/           # PermissionManager
├── cost/                 # CostTracker
└── doom_loop/            # DoomLoopDetector
```

### 2.2 ReActAgent 多层架构

- **L1 工具层**：原子操作工具
- **L2 技能层**：Skill 声明式工具组合
- **L3 子代理层**：SubAgent 专业代理路由

## 3. 集成架构设计

### 3.1 三层集成模型

```
┌─────────────────────────────────────────────────────────┐
│                   MemStack ReActAgent                   │
│                    (L4 - Agent Layer)                   │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
┌───────▼──────────┐    ┌────────▼────────┐
│  SubAgent Router │    │  Skill Executor │
│  (L3 Layer)      │    │  (L2 Layer)     │
└───────┬──────────┘    └────────┬────────┘
        │                         │
        │   ┌─────────────────────┘
        │   │
┌───────▼───▼──────────────────────────────────┐
│          CUA Integration Layer               │
│  ┌──────────────┐  ┌────────────────────┐   │
│  │ CUA SubAgent │  │ CUA Skill Manager  │   │
│  └──────┬───────┘  └────────┬───────────┘   │
│         │                    │               │
│         └────────┬───────────┘               │
│                  │                           │
│       ┌──────────▼──────────┐                │
│       │  CUA Tool Adapter   │                │
│       └──────────┬──────────┘                │
└──────────────────┼───────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │  CUA ComputerAgent  │
        │  (vendor/cua)       │
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │  Computer Interface │
        │  (macOS/Linux/Win)  │
        └─────────────────────┘
```

### 3.2 集成层次说明

| 层次 | 职责 | 适用场景 |
|------|------|----------|
| L1 工具层 | CUA 操作包装为 AgentTool | LLM 自由组合操作 |
| L2 技能层 | CUA 任务模式化为 Skill | 常见任务预定义 |
| L3 子代理层 | CUA ComputerAgent 封装为 SubAgent | 复杂任务委托 |

## 4. 文件结构

### 4.1 新建文件

```
src/infrastructure/agent/cua/
├── __init__.py
├── adapter.py                    # CUA Agent 适配器（核心）
├── tool_adapter.py              # CUA 工具适配器（L1）
├── skill_manager.py             # CUA 技能管理器（L2）
├── subagent.py                  # CUA 子代理（L3）
├── callbacks/
│   ├── __init__.py
│   ├── memstack_callback.py     # MemStack 回调适配器
│   └── sse_bridge.py            # SSE 事件桥接
├── tools/
│   ├── __init__.py
│   ├── computer_action.py       # 计算机操作工具
│   ├── browser_action.py        # 浏览器操作工具
│   └── screenshot.py            # 截图工具
└── config.py                    # CUA 配置管理

src/configuration/
├── cua_factory.py               # CUA 组件工厂

src/application/services/
├── cua_service.py               # CUA 应用服务
```

### 4.2 修改的文件

- `src/configuration/config.py` - 添加 CUA 配置项
- `src/configuration/di_container.py` - 注册 CUA 组件

## 5. 核心接口设计

### 5.1 CUA 工具适配器 (L1)

```python
# src/infrastructure/agent/cua/tool_adapter.py

from src.infrastructure.agent.tools.base import AgentTool

class CUAToolAdapter(AgentTool):
    """将 CUA Computer 操作包装为 MemStack AgentTool"""
    
    def __init__(self, computer: Computer, action_type: str):
        self._computer = computer
        self._action_type = action_type
        super().__init__(
            name=f"cua_{action_type}",
            description=f"CUA {action_type} operation"
        )
    
    async def execute(self, **kwargs) -> str:
        """执行 CUA 操作"""
        method = getattr(self._computer, self._action_type)
        result = await method(**kwargs)
        return json.dumps(result)
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        """返回操作参数 Schema"""
        # 根据 action_type 返回对应的参数 Schema
        pass
```

### 5.2 CUA Skill 定义 (L2)

```python
# src/infrastructure/agent/cua/skill_manager.py

from src.domain.model.agent.skill import Skill, SkillStatus

class CUASkillManager:
    """CUA 技能管理器"""
    
    @staticmethod
    def get_builtin_skills() -> List[Skill]:
        return [
            Skill(
                id="cua_web_search",
                name="web_search_skill",
                description="在浏览器中搜索并提取信息",
                tools=["cua_browser_navigate", "cua_screenshot", "cua_click"],
                triggers=["在网页上搜索", "打开浏览器搜索"],
                status=SkillStatus.ACTIVE,
            ),
            Skill(
                id="cua_form_fill",
                name="form_fill_skill",
                description="填写网页表单",
                tools=["cua_click", "cua_type", "cua_screenshot"],
                triggers=["填写表单", "输入信息到网页"],
                status=SkillStatus.ACTIVE,
            ),
        ]
```

### 5.3 CUA SubAgent (L3)

```python
# src/infrastructure/agent/cua/subagent.py

from src.domain.model.agent.subagent import SubAgent

class CUASubAgent(SubAgent):
    """CUA 子代理定义"""
    
    def __init__(self, config: CUAConfig):
        super().__init__(
            id="cua_computer_agent",
            name="cua_computer_agent",
            display_name="计算机操作助手",
            description="执行计算机操作和 UI 自动化任务",
            triggers=["操作电脑", "点击按钮", "浏览网页", "自动化任务"],
            model_override=config.model,
            tool_filter=["cua_*"],  # 只允许 CUA 工具
        )
        self._config = config
        self._computer_agent = None
```

### 5.4 回调适配器

```python
# src/infrastructure/agent/cua/callbacks/memstack_callback.py

from agent.callbacks.base import AsyncCallbackHandler
from src.infrastructure.agent.core.events import SSEEvent, SSEEventType

class MemStackCallbackAdapter(AsyncCallbackHandler):
    """将 CUA 回调转换为 MemStack SSE 事件"""
    
    def __init__(self, event_queue: asyncio.Queue):
        self._event_queue = event_queue
    
    async def on_computer_call_start(self, item: Dict) -> None:
        await self._event_queue.put(SSEEvent(
            type=SSEEventType.ACT,
            data={
                "tool_name": f"cua_{item.get('action', {}).get('type')}",
                "tool_input": item.get("action", {}),
                "status": "running"
            }
        ))
    
    async def on_computer_call_end(self, item: Dict, result: List) -> None:
        await self._event_queue.put(SSEEvent(
            type=SSEEventType.OBSERVE,
            data={
                "tool_name": f"cua_{item.get('action', {}).get('type')}",
                "result": result,
                "status": "completed"
            }
        ))
    
    async def on_screenshot(self, screenshot: str, name: str) -> None:
        await self._event_queue.put(SSEEvent(
            type=SSEEventType.SCREENSHOT,
            data={
                "image_base64": screenshot,
                "name": name
            }
        ))
```

## 6. 配置管理

### 6.1 配置项

```python
# src/configuration/config.py (新增)

class Settings(BaseSettings):
    # === CUA Integration ===
    CUA_ENABLED: bool = False
    CUA_MODEL: str = "claude-sonnet-4"
    CUA_TEMPERATURE: float = 0.0
    CUA_MAX_STEPS: int = 20
    CUA_SCREENSHOT_DELAY: float = 0.5
    
    # Computer provider (Docker 为主)
    CUA_COMPUTER_PROVIDER: str = "docker"  # docker, local, cloud
    CUA_DOCKER_IMAGE: str = "cua/desktop:latest"  # Docker 镜像
    CUA_DOCKER_DISPLAY: str = "1920x1080"
    CUA_DOCKER_MEMORY: str = "4GB"
    CUA_DOCKER_CPU: str = "2"
    
    # Permission defaults (Docker 环境下可以放宽)
    CUA_ALLOW_SCREENSHOT: bool = True
    CUA_ALLOW_MOUSE_CLICK: bool = True  # Docker 隔离，默认允许
    CUA_ALLOW_KEYBOARD_INPUT: bool = True
    CUA_ALLOW_BROWSER_NAVIGATION: bool = True
    
    # SubAgent/Skill (完整三层)
    CUA_SUBAGENT_ENABLED: bool = True
    CUA_SKILL_ENABLED: bool = True
    CUA_SUBAGENT_MATCH_THRESHOLD: float = 0.7
    CUA_SKILL_MATCH_THRESHOLD: float = 0.8
```

### 6.2 Docker 环境配置

```yaml
# docker-compose.cua.yml (新增)
version: '3.8'
services:
  cua-desktop:
    image: cua/desktop:latest
    container_name: memstack-cua-desktop
    environment:
      - DISPLAY_WIDTH=1920
      - DISPLAY_HEIGHT=1080
    ports:
      - "5900:5900"  # VNC
      - "6080:6080"  # noVNC Web
    volumes:
      - cua-data:/home/user/data
    networks:
      - memstack-network
    restart: unless-stopped

volumes:
  cua-data:

networks:
  memstack-network:
    external: true
```

### 6.2 依赖注入

```python
# src/configuration/cua_factory.py

class CUAFactory:
    """CUA 组件工厂"""
    
    @staticmethod
    def create_computer(config: CUAConfig) -> Computer:
        """创建 Computer 实例"""
        from computer import Computer
        return Computer(
            os_type=platform.system().lower(),
            provider_type=config.provider,
        )
    
    @staticmethod
    def create_tools(computer: Computer) -> Dict[str, AgentTool]:
        """创建 CUA 工具集"""
        return {
            "cua_click": CUAClickTool(computer),
            "cua_type": CUATypeTool(computer),
            "cua_screenshot": CUAScreenshotTool(computer),
            "cua_scroll": CUAScrollTool(computer),
            "cua_browser_navigate": CUABrowserNavigateTool(computer),
        }
```

## 7. SSE 事件映射

| CUA Callback | MemStack SSE Event | 说明 |
|--------------|-------------------|------|
| `on_computer_call_start()` | `ACT` | 计算机操作开始 |
| `on_computer_call_end()` | `OBSERVE` | 计算机操作结果 |
| `on_function_call_start()` | `ACT` | 函数调用开始 |
| `on_function_call_end()` | `OBSERVE` | 函数调用结果 |
| `on_screenshot()` | `SCREENSHOT` (新增) | 截图事件 |
| `on_usage()` | `COST_UPDATE` | 成本更新 |
| `on_text()` | `TEXT_DELTA` | 文本输出 |

## 8. 实现步骤（完整三层集成）

### Phase 1: 基础框架 + Docker 配置 (3-4 天)

**任务清单**:
1. 创建 `src/infrastructure/agent/cua/` 目录结构
2. 实现配置管理 `config.py`（含 Docker 配置）
3. 实现工厂类 `cua_factory.py`
4. 基础适配器 `adapter.py`
5. 添加 `docker-compose.cua.yml`
6. 更新 `Makefile` 添加 CUA 相关命令

**产出**:
- `src/infrastructure/agent/cua/__init__.py`
- `src/infrastructure/agent/cua/config.py`
- `src/configuration/cua_factory.py`
- `docker-compose.cua.yml`

### Phase 2: L1 工具层 (4-5 天)

**任务清单**:
1. 实现 `CUAToolAdapter` 基类
2. 实现计算机操作工具:
   - `CUAClickTool` - 鼠标点击
   - `CUATypeTool` - 键盘输入
   - `CUAScreenshotTool` - 截图
   - `CUAScrollTool` - 滚动
   - `CUADragTool` - 拖拽
3. 实现浏览器操作工具:
   - `CUABrowserNavigateTool` - 导航
   - `CUABrowserBackTool` - 后退
   - `CUABrowserRefreshTool` - 刷新
4. 工具参数 Schema 定义
5. 注册到 MemStack 工具系统

**产出**:
- `src/infrastructure/agent/cua/tool_adapter.py`
- `src/infrastructure/agent/cua/tools/computer_action.py`
- `src/infrastructure/agent/cua/tools/browser_action.py`
- `src/infrastructure/agent/cua/tools/screenshot.py`

### Phase 3: 回调系统 (3 天)

**任务清单**:
1. 实现 `MemStackCallbackAdapter`
2. 实现 `SSEBridge` 事件桥接
3. 集成 PermissionManager
4. 集成 CostTracker
5. 实现截图存储（Base64 / 文件）

**产出**:
- `src/infrastructure/agent/cua/callbacks/memstack_callback.py`
- `src/infrastructure/agent/cua/callbacks/sse_bridge.py`

### Phase 4: L2 技能层 (3 天)

**任务清单**:
1. 实现 `CUASkillManager`
2. 定义内置 Skill:
   - `web_search_skill` - 网页搜索
   - `form_fill_skill` - 表单填写
   - `ui_automation_skill` - UI 自动化
   - `screenshot_analyze_skill` - 截图分析
3. 集成到 SkillExecutor
4. 实现 Skill 触发规则

**产出**:
- `src/infrastructure/agent/cua/skill_manager.py`

### Phase 5: L3 子代理层 (3 天)

**任务清单**:
1. 实现 `CUASubAgent` 类
2. 实现 `CUASubAgentExecutor`
3. 配置 SubAgent 路由规则
4. 实现 ComputerAgent 生命周期管理
5. 实现工具权限过滤

**产出**:
- `src/infrastructure/agent/cua/subagent.py`

### Phase 6: 应用服务 + DI 集成 (2 天)

**任务清单**:
1. 实现 `CUAService`
2. 更新 `DIContainer` 注册 CUA 组件
3. 更新 `config.py` 添加配置项
4. 集成到 `AgentService`

**产出**:
- `src/application/services/cua_service.py`
- 更新 `src/configuration/di_container.py`
- 更新 `src/configuration/config.py`

### Phase 7: 测试 (4-5 天)

**任务清单**:
1. 单元测试（Mock Docker/Computer）
2. 集成测试（真实 Docker 环境）
3. 端到端测试
4. 性能测试

**产出**:
- `src/tests/unit/cua/`
- `src/tests/integration/cua/`
- `src/tests/e2e/cua/`

### 总工期估计: 22-25 天

## 9. 关键文件清单

| 文件 | 优先级 | 职责 |
|------|--------|------|
| `adapter.py` | P0 | CUA 与 MemStack 核心桥接 |
| `tool_adapter.py` | P0 | L1 工具层实现 |
| `memstack_callback.py` | P0 | 事件系统桥接 |
| `subagent.py` | P1 | L3 子代理层实现 |
| `cua_factory.py` | P1 | 依赖注入工厂 |
| `skill_manager.py` | P2 | L2 技能层实现 |
| `config.py` | P2 | 配置管理 |

## 10. 测试验证

### 10.1 验证步骤

1. **工具层验证**: 调用 CUA 截图工具，验证返回 base64 图像
2. **事件流验证**: 执行 CUA 操作，验证 SSE 事件正确发送
3. **子代理验证**: 发送 "帮我点击网页上的按钮" 验证路由到 CUA SubAgent
4. **权限验证**: 执行敏感操作时验证权限请求

### 10.2 测试命令

```bash
# 单元测试
uv run pytest src/tests/unit/cua/ -v

# 集成测试
uv run pytest src/tests/integration/cua/ -v -m integration

# 运行所有 CUA 测试
uv run pytest src/tests/ -k "cua" -v
```

## 11. 安全考虑

1. **默认禁用**: CUA 功能默认禁用，需要显式启用
2. **权限控制**: 所有写操作（点击、输入）默认需要用户确认
3. **VM 隔离**: 推荐使用 Docker 或 Cloud VM 执行
4. **审计日志**: 所有 CUA 操作记录到审计日志

## 12. 后续扩展

- 支持更多 VM 提供商
- 支持视觉元素定位 (SoM)
- 支持录制回放
- 支持 MCP 服务器集成
