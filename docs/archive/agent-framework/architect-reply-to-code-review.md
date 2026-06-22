# 架构师回复 Code Reviewer 的 5 个问题

## 问题分析

### 1. @tool 装饰器与现有 Tool 定义冲突

**分析**：
- 现有 `AgentTool` 类继承自 `AgentToolBase` (domain port)
- 已有 `truncate_output` 功能处理大输出
- 装饰器与类继承不是冲突关系，而是两种注册方式

**回复**：
```python
# 保留两种方式，装饰器作为语法糖

# 方式1: 类继承 (现有方式)
class MyTool(AgentTool):
    def __init__(self):
        super().__init__(name="my_tool", description="...")

    async def execute(self, **kwargs) -> str:
        ...

# 方式2: 装饰器 (新增语法糖)
@tool
async def my_tool(**kwargs) -> str:
    ...
```

**决策**：接受建议，保留两种方式并存。

---

### 2. @handoff 与现有 SubAgent 语义不匹配

**分析**：
- 现有 `SubAgent` 有 `allowed_tools`, `allowed_skills`, 统计追踪
- `@handoff` 确实是简化的切换机制

**回复**：
```
@handoff 用于简单场景：
- 快速切换到另一个 Agent
- 不需要权限控制
- 不需要统计追踪

SubAgent 用于复杂场景：
- 需要权限控制
- 需要使用统计
- 需要 custom model 配置

两者共存，不冲突。
```

**决策**：接受建议，`@handoff` 仅作为简单切换的语法糖。

---

### 3. 事件类型与现有不兼容

**分析**：
- 设计文档只列了 6 种基础事件类型
- 现有 `AgentEventType` 有 50+ 事件类型

**回复**：
```
设计文档的 6 种是"流式事件"（LangGraph 风格）
现有 50+ 种是"完整事件系统"（MemStack 风格）

框架应支持两者：
- 基础流式事件 (TEXT_START, TEXT_DELTA, TOOL_CALL...)
- 完整领域事件 (THOUGHT, ACT, OBSERVE, CLARIFICATION_ASKED...)
```

**决策**：修正设计文档，明确兼容现有事件系统。

---

### 4. 框架与现有代码的依赖问题

**分析**：
- 现有 `domain/` 包含业务模型 (SubAgent, Skill...)
- 框架需要 Infrastructure，不应依赖 Domain

**回复**：
```
分层策略：

1. 框架层
   - 仅包含基础设施代码
   - 定义 Protocol/ABC 接口
   - 不依赖 MemStack domain 模型

2. 现有代码
   - 实现 framework 定义的接口
   - 可继续使用 domain 模型

3. 迁移适配器
   - 桥接 framework 接口和现有实现
   - 逐步替换，非完全重写
```

**决策**：框架独立，通过适配器桥接。

---

### 5. Checkpoint 与现有状态管理关系

**分析**：
- 现有使用 `AgentExecution` 表存储状态
- Checkpoint 是新需求

**回复**：
```
Checkpoint 作为适配器层实现：

class CheckpointProtocol(ABC):
    async def save(self, agent_id, state) -> str: ...
    async def load(self, checkpoint_id) -> Optional[State]: ...

class PostgresCheckpoint(CheckpointProtocol):
    # 基于 AgentExecution 表实现
    ...
```

**决策**：Checkpoint 作为可选特性，适配器模式实现。

---

## 总结

| 问题 | 决策 |
|------|--------|
| @tool 装饰器 | 保留两种方式并存 |
| @handoff | 简单切换，SubAgent 用于复杂场景 |
| 事件类型 | 兼容现有 50+ 事件类型 |
| 依赖管理 | 框架独立，适配器桥接 |
| Checkpoint | 可选特性，适配器实现 |

所有建议均已接受，设计文档将相应更新。
