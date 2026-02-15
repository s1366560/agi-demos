# MemStack Agent Framework - Key Design Decisions

## 给后端开发工程师的关键设计决策

### 1. 四层架构

```
L4: Agent (ReAct Loop)
  - ReActAgent: 主入口
  - SessionProcessor: Think -> Act -> Observe

L3: SubAgent (专业化代理)
  - HybridRouter: 关键词 + 语义路由
  - SubAgentProcess: 独立执行引擎

L2: Skill (声明式组合)
  - SkillOrchestrator: 触发匹配
  - 工具编排 (串行/并行)

L1: Tool (原子能力)
  - AgentTool Protocol
  - ToolDefinition (LLM 可见)
```

### 2. 核心接口 (采纳 Code Review 建议)

#### Tool 协议改进

```python
# 原来
async def execute(self, **kwargs) -> str: ...

# 改进后
from typing import TypeVar

T = TypeVar('T')

class ToolResult(Generic[T]):
    content: T
    metadata: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[ArtifactRef] = field(default_factory=list)

class AgentTool(ABC):
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult[T]: ...
```

#### Skill 协议考虑

```python
# 当前设计：纯数据类
@dataclass
class Skill:
    id: str
    tools: List[str]

# 考虑改进：支持自定义执行
class SkillProtocol(ABC):
    @abstractmethod
    async def execute(self, context: AgentContext) -> SkillResult: ...
```

#### 事件脱敏

```python
class AgentEvent(ABC):
    def to_dict(self, sanitize: bool = True) -> Dict[str, Any]:
        data = self._raw_dict()
        if sanitize:
            data = self._sanitize(data)
        return data
```

### 3. 目录结构调整

```
memstack-agent/
|-- src/memstack_agent/
|   |-- core/              # 按职责拆分
|   |   |-- event.py   # EventType
|   |   |-- tool.py    # ToolParam, ToolResult
|   |   |-- message.py # Message, MessageRole
|   |   |-- state.py   # AgentState
|   |
|   |-- tools/
|   |   |-- protocol.py     # AgentTool ABC
|   |   |-- registry.py     # ToolRegistry
|   |   |-- converter.py    # function -> Tool
|   |
|   |-- skills/
|   |   |-- protocol.py     # SkillProtocol (考虑)
|   |   |-- orchestrator.py  # SkillOrchestrator
|   |
|   |-- subagents/
|   |   |-- protocol.py     # SubAgent 数据类
|   |   |-- router.py       # HybridRouter
|   |   |-- process.py      # 独立执行
|   |
|   |-- agent/
|   |   |-- react.py       # ReActAgent
|   |   |-- config.py      # AgentConfig
|   |
|   |-- llm/
|   |   |-- protocol.py     # LLMClient ABC
|   |   |-- stream.py       # LLMStream
|   |
|   |-- events/
|   |   |-- base.py        # AgentEvent ABC
|   |   |-- converter.py    # Event -> SSE dict
|   |
|   |-- checkpoint/
|   |   |-- protocol.py     # CheckpointProtocol
|   |   |-- memory.py       # 内存实现
```

### 4. 装饰器设计 (借鉴 Swarm)

```python
# 函数即工具
def tool(func: Callable) -> AgentTool:
    return FunctionTool(func)

# Agent 切换
def handoff(func: Callable) -> AgentTool:
    return HandoffTool(func)
```

### 5. 迁移注意事项

| 阶段 | 注意点 |
|------|--------|
| 1-5 | **必须在独立包中完成**，无 MemStack 依赖 |
| 6 | 使用适配器桥接新旧接口，保持并行 |
| - | 避免循环依赖：memstack-agent 不依赖 MemStack |

### 6. 实现优先级

1. **P0**: core/ (event.py, tool.py, message.py, state.py)
2. **P1**: tools/protocol.py, tools/converter.py
3. **P2**: skills/protocol.py, skills/orchestrator.py
4. **P3**: agent/react.py (ReActAgent)
