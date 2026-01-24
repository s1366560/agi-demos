# ReActAgent 事件体系重构方案

## 1. 现状分析与问题识别

经过对代码库的深入分析，当前的事件体系主要由两部分组成：
1.  **运行时事件 (`SSEEvent`)**: 位于 `src/infrastructure/agent/core/events.py`，用于 Agent 运行时的流式传输。
2.  **持久化事件 (`AgentExecutionEvent`)**: 位于 `src/domain/model/agent/agent_execution_event.py`，用于数据库存储。

**主要问题：**
*   **职责不清与耦合**: `SSEEvent` 既承载业务逻辑（如 `Thought`, `Act`），又包含传输协议细节（`to_sse_format`）。Agent 核心逻辑直接依赖于基础设施层的 `SSEEvent`，违反了整洁架构原则。
*   **类型安全缺失**: 两个类都大量依赖 `Dict[str, Any]` 来存储事件数据。这意味着编译器无法检查数据结构，容易在运行时引发 `KeyError`。
*   **重复定义**: `SSEEventType` 和 `AgentEventType` 高度重叠，每次添加新事件都需要修改多处代码。
*   **扩展性受限**: 目前的“上帝类”设计（单一类包含所有工厂方法）使得添加自定义事件变得困难。

## 2. 重构目标

1.  **建立统一的领域事件体系**: 在领域层定义强类型的事件模型。
2.  **解耦核心逻辑与传输层**: Agent 核心只产生领域事件，不关心是 SSE 传输还是存入数据库。
3.  **增强类型安全**: 使用 Pydantic 模型定义每个事件的 Payload。

## 3. 详细设计方案

### 3.1 领域事件层 (Domain Layer)

新建 `src/domain/events/agent_events.py`，定义基于 Pydantic 的事件体系。

```python
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime
from enum import Enum

class AgentEventType(str, Enum):
    THOUGHT = "thought"
    ACT = "act"
    OBSERVE = "observe"
    # ... 其他类型

class AgentDomainEvent(BaseModel):
    """领域事件基类"""
    event_type: AgentEventType
    timestamp: float = Field(default_factory=lambda: datetime.utcnow().timestamp())
    
    class Config:
        frozen = True # 不可变对象

class AgentThoughtEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.THOUGHT
    content: str
    thought_level: str = "task"
    step_index: Optional[int] = None

class AgentToolCallEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.ACT
    tool_name: str
    tool_input: Dict[str, Any]
    call_id: Optional[str] = None

# ... 为每种事件定义具体类
```

### 3.2 基础设施层适配 (Infrastructure Layer)

1.  **SSE 适配器**: 修改 `src/infrastructure/agent/core/events.py`，将 `SSEEvent` 改造成一个简单的转换器。

```python
class SSEEvent:
    @staticmethod
    def from_domain_event(event: AgentDomainEvent) -> "SSEEvent":
        # 将强类型的 Domain Event 转换为 SSE 格式
        return SSEEvent(
            type=event.event_type.value,
            data=event.model_dump(exclude={"event_type", "timestamp"}),
            timestamp=event.timestamp
        )
```

2.  **持久化适配器**: 同样地，为 `AgentExecutionEvent` 增加从 `AgentDomainEvent` 转换的方法。

### 3.3 核心逻辑重构

修改 `src/infrastructure/agent/core/processor.py` 和 `react_agent.py`，使其生成领域事件。

```python
# Before
yield SSEEvent.thought(content="thinking...")

# After
yield AgentThoughtEvent(content="thinking...")
```

## 4. 实施步骤

1.  **Step 1: 创建领域事件定义**
    *   在 `src/domain/events/` 下创建新文件，迁移所有枚举和数据结构。

2.  **Step 2: 创建适配器/映射器**
    *   实现 `DomainEvent` -> `SSEEvent` 的转换逻辑。
    *   实现 `DomainEvent` -> `AgentExecutionEvent` 的转换逻辑。

3.  **Step 3: 重构 Agent 核心**
    *   逐步替换 `processor.py` 中的 `yield` 语句，使用新的领域事件类。

4.  **Step 4: 清理旧代码**
    *   将 `SSEEvent` 中的工厂方法标记为废弃或移除，使其专注于传输格式化。

## 5. 预期收益

*   **代码清晰度**: 业务逻辑与传输逻辑分离。
*   **开发体验**: IDE 可以提供完整的代码补全和类型检查。
*   **稳定性**: 编译期即可发现字段拼写错误或类型不匹配。
*   **可测试性**: 领域事件是纯数据对象，易于构造和断言。
