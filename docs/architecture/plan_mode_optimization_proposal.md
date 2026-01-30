# Plan Mode 架构优化方案

## 一、当前架构分析

### 1.1 现有组件概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Domain 层                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  Plan          - Plan Mode 计划文档（Markdown 格式，用户可编辑）               │
│  WorkPlan      - 多层级思考的工作计划（基于 workflow pattern）                │
│  ExecutionPlan - 执行计划（Plan Mode 执行阶段使用，含依赖关系）                │
│  PlanStep      - 工作计划步骤                                                │
│  ExecutionStep - 执行计划步骤                                                │
│  PlanSnapshot  - 计划快照（用于回滚）                                         │
│  ReflectionResult - 反思结果                                                │
│  StepResult    - 步骤执行结果                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Application 层                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  EnterPlanModeUseCase  - 进入 Plan Mode                                      │
│  ExitPlanModeUseCase   - 退出 Plan Mode                                      │
│  UpdatePlanUseCase     - 更新计划文档                                        │
│  GetPlanUseCase        - 获取计划                                            │
│  PlanWorkUseCase       - 生成工作计划（基于 LLM）                             │
│  ExecuteStepUseCase    - 执行计划步骤                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Infrastructure 层                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  Plan Mode Detection:                                                        │
│    - HybridPlanModeDetector   - 混合检测器（启发式 + LLM）                    │
│    - FastHeuristicDetector    - 快速启发式检测                              │
│    - LLMClassifier            - LLM 分类器                                  │
│                                                                              │
│  Plan Mode Orchestration:                                                    │
│    - PlanModeOrchestrator     - 协调生成->执行->反思->调整流程               │
│    - PlanGenerator            - LLM 生成执行计划                             │
│    - PlanExecutor             - 执行计划（支持串行/并行）                     │
│    - PlanReflector            - 反思执行结果                                 │
│    - PlanAdjuster             - 调整计划                                     │
│                                                                              │
│  Tools:                                                                      │
│    - PlanEnterTool            - 进入 Plan Mode 工具                         │
│    - PlanExitTool             - 退出 Plan Mode 工具                         │
│    - PlanUpdateTool           - 更新计划工具                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Repository 层                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  PlanRepository      (SqlPlanRepository)        - Plan 文档持久化           │
│  WorkPlanRepository  (SQLWorkPlanRepository)    - WorkPlan 持久化           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 当前问题分析

#### 问题 1: 概念重叠与命名混乱

```python
# 三个不同的 "Plan" 概念容易混淆

# 1. Plan - Plan Mode 计划文档（Markdown）
class Plan:
    """Plan document created during Plan Mode"""
    content: str  # Markdown format
    status: PlanDocumentStatus  # DRAFT -> REVIEWING -> APPROVED -> ARCHIVED

# 2. WorkPlan - 多层级思考的工作计划
class WorkPlan:
    """Work-level plan for executing complex queries"""
    steps: list[PlanStep]
    status: PlanStatus  # PLANNING -> IN_PROGRESS -> COMPLETED/FAILED

# 3. ExecutionPlan - Plan Mode 执行计划
class ExecutionPlan:
    """Execution plan for Plan Mode"""
    steps: list[ExecutionStep]
    status: ExecutionPlanStatus  # DRAFT -> APPROVED -> EXECUTING -> COMPLETED/FAILED
```

**问题**: 
- `WorkPlan` 和 `ExecutionPlan` 功能重叠，都用于执行
- 命名不清晰，难以区分使用场景
- `PlanStep` 和 `ExecutionStep` 重复定义

#### 问题 2: Plan Mode 工作流程不完整

当前实现存在两条独立的流程：

1. **Plan Mode 文档流程**（Plan Entity）：
   - EnterPlanModeUseCase → PlanEnterTool → Plan 文档
   - ExitPlanModeUseCase → PlanExitTool → 退出
   - 文档存储在 PostgreSQL，供用户查看和编辑

2. **Plan Mode 执行流程**（ExecutionPlan Entity）：
   - PlanGenerator → ExecutionPlan
   - PlanExecutor 执行
   - PlanReflector 反思
   - PlanAdjuster 调整

**问题**：这两个流程之间缺乏明确的关联，ExecutionPlan 没有与 Plan 文档关联。

#### 问题 3: 缺少 Repository 抽象一致性

```python
# PlanRepository - 返回 None 表示未找到
async def find_by_id(self, plan_id: str) -> Optional[Plan]:
    ...

# WorkPlanRepository - 返回 WorkPlan 或 None 不一致
async def get_by_id(self, plan_id: str) -> WorkPlan | None:
    ...

# 方法命名不一致：save vs update_status
```

#### 问题 4: Plan Mode 与 ReAct Agent 集成不充分

- `ReActAgent` 有 `plan_mode_detector` 参数，但集成逻辑不清晰
- `SessionProcessor` 有 work plan 跟踪，但没有 Plan Mode 状态管理
- Plan Mode 事件未完全集成到 SSE 事件流

#### 问题 5: 缺少 Plan Mode 状态持久化

- `ExecutionPlan` 只在内存中，没有持久化到数据库
- `PlanSnapshot` 没有对应的 Repository
- 无法恢复中断的 Plan Mode 执行

## 二、架构优化方案

### 2.1 概念统一与命名规范化

#### 方案：合并 WorkPlan 和 ExecutionPlan

```python
# 统一为 PlanExecution（执行计划）
@dataclass(kw_only=True)
class PlanExecution(Entity):
    """
    执行计划 - 统一的计划执行实体。
    
    用途：
    1. 作为 WorkPlan 的替代，用于多层级思考
    2. 作为 Plan Mode 的执行计划
    
    关联：
    - plan_id: 可选关联到 Plan 文档（Plan Mode 时使用）
    - conversation_id: 关联到对话
    """
    conversation_id: str
    plan_id: Optional[str] = None  # 关联 Plan 文档（Plan Mode 时）
    
    # 执行步骤
    steps: list[ExecutionStep]
    current_step_index: int = 0
    completed_step_indices: list[int] = field(default_factory=list)
    failed_step_indices: list[int] = field(default_factory=list)
    
    # 状态
    status: ExecutionStatus  # PENDING -> RUNNING -> COMPLETED/FAILED/CANCELLED
    
    # 执行配置
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL  # SEQUENTIAL / PARALLEL
    max_parallel_steps: int = 3
    
    # 反思配置
    reflection_enabled: bool = True
    max_reflection_cycles: int = 3
    current_reflection_cycle: int = 0
    
    # 元数据
    workflow_pattern_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"  # 支持暂停/恢复
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
```

#### PlanStep 和 ExecutionStep 合并

```python
@dataclass(frozen=True)
class ExecutionStep:
    """
    执行步骤 - 统一的步骤定义。
    
    用途：
    1. 作为 PlanStep 的替代
    2. 作为 ExecutionStep 的替代
    """
    step_id: str
    step_number: int  # 用于排序和显示
    
    # 描述
    description: str
    thought_prompt: str  # 任务级思考提示
    expected_output: str
    
    # 执行
    tool_name: str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    
    # 依赖
    dependencies: list[str] = field(default_factory=list)  # step_id 列表
    
    # 状态（运行时更新）
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 执行统计
    execution_time_ms: int = 0
    retry_count: int = 0


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"  # 依赖已满足，准备执行
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
```

### 2.2 Plan Mode 完整工作流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Plan Mode 完整工作流程                               │
└─────────────────────────────────────────────────────────────────────────────┘

Phase 1: 检测与触发 (Detection)
══════════════════════════════════════════════════════════════════════════════

User Query
    │
    ▼
┌─────────────────┐
│ Hybrid Detector │  ← 三层检测：启发式 → LLM 分类 → 缓存
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
 触发      不触发
    │         │
    ▼         ▼
 Plan Mode  直接执行 (ReAct)


Phase 2: 进入 Plan Mode (Enter)
══════════════════════════════════════════════════════════════════════════════

进入 Plan Mode
    │
    ├──→ Create Plan 文档 (Markdown)
    │      - title
    │      - content (模板)
    │      - status: DRAFT
    │
    ├──→ Update Conversation
    │      - current_mode: PLAN
    │      - current_plan_id: plan.id
    │
    └──→ Emit SSE: PLAN_MODE_ENTERED


Phase 3: 探索与规划 (Explore & Plan)
══════════════════════════════════════════════════════════════════════════════

Plan Mode 对话
    │
    ├──→ Agent 使用探索工具（只读）
    │      - 代码搜索
    │      - 文件读取
    │      - 架构分析
    │
    ├──→ 更新 Plan 文档
    │      - plan_update tool
    │      - 记录探索发现
    │      - 设计决策
    │
    └──→ 用户可随时查看和编辑 Plan 文档


Phase 4: 生成执行计划 (Generate Execution Plan)
══════════════════════════════════════════════════════════════════════════════

用户确认完成规划
    │
    ▼
PlanGenerator (LLM)
    │
    ├──→ 输入：Plan 文档内容 + 用户原始查询
    │
    ├──→ 输出：PlanExecution
    │      - steps (带依赖关系)
    │      - execution_mode
    │      - reflection_enabled
    │
    └──→ 保存到数据库
           - PlanExecutionRepository.save()
           - 关联 plan_id


Phase 5: 执行与反思 (Execute & Reflect)
══════════════════════════════════════════════════════════════════════════════

PlanModeOrchestrator
    │
    ├──→ PlanExecutor
    │      - 执行步骤（串行/并行）
    │      - 更新步骤状态
    │      - Emit SSE: STEP_STARTED, STEP_COMPLETED, STEP_FAILED
    │
    ├──→ PlanReflector（如需反思）
    │      - 评估执行结果
    │      - 决定：继续 / 调整 / 完成 / 失败
    │      - Emit SSE: REFLECTION_COMPLETED
    │
    ├──→ PlanAdjuster（如需调整）
    │      - 修改步骤
    │      - 添加/删除步骤
    │      - Emit SSE: PLAN_ADJUSTED
    │
    └──→ 循环直到完成或最大反思次数


Phase 6: 退出 Plan Mode (Exit)
══════════════════════════════════════════════════════════════════════════════

执行完成
    │
    ├──→ 更新 Plan 文档
    │      - status: APPROVED / ARCHIVED
    │      - 记录执行结果摘要
    │
    ├──→ Update Conversation
    │      - current_mode: BUILD
    │      - current_plan_id: None
    │
    ├──→ Emit SSE: PLAN_MODE_EXITED
    │
    └──→ 进入 Build Mode 实施变更
```

### 2.3 统一 Repository 接口

```python
# 统一 Repository 接口风格

class PlanExecutionRepository(ABC):
    """Repository for PlanExecution entities."""
    
    @abstractmethod
    async def save(self, execution: PlanExecution) -> PlanExecution:
        """Save or update a plan execution."""
        ...
    
    @abstractmethod
    async def find_by_id(self, execution_id: str) -> Optional[PlanExecution]:
        """Find by ID."""
        ...
    
    @abstractmethod
    async def find_by_plan_id(self, plan_id: str) -> list[PlanExecution]:
        """Find all executions for a plan."""
        ...
    
    @abstractmethod
    async def find_by_conversation(
        self, 
        conversation_id: str,
        status: Optional[ExecutionStatus] = None
    ) -> list[PlanExecution]:
        """Find executions for a conversation."""
        ...
    
    @abstractmethod
    async def find_active_by_conversation(
        self, 
        conversation_id: str
    ) -> Optional[PlanExecution]:
        """Find active (running/paused) execution."""
        ...
    
    @abstractmethod
    async def update_status(
        self, 
        execution_id: str, 
        status: ExecutionStatus
    ) -> Optional[PlanExecution]:
        """Update execution status."""
        ...
    
    @abstractmethod
    async def update_step(
        self, 
        execution_id: str, 
        step: ExecutionStep
    ) -> Optional[PlanExecution]:
        """Update a step within an execution."""
        ...
    
    @abstractmethod
    async def delete(self, execution_id: str) -> bool:
        """Delete an execution."""
        ...


class PlanSnapshotRepository(ABC):
    """Repository for PlanSnapshot entities."""
    
    @abstractmethod
    async def save(self, snapshot: PlanSnapshot) -> PlanSnapshot:
        """Save a snapshot."""
        ...
    
    @abstractmethod
    async def find_by_id(self, snapshot_id: str) -> Optional[PlanSnapshot]:
        """Find by ID."""
        ...
    
    @abstractmethod
    async def find_by_execution(
        self, 
        execution_id: str
    ) -> list[PlanSnapshot]:
        """Find snapshots for an execution."""
        ...
    
    @abstractmethod
    async def find_latest_by_execution(
        self, 
        execution_id: str
    ) -> Optional[PlanSnapshot]:
        """Find latest snapshot for an execution."""
        ...
    
    @abstractmethod
    async def delete_by_execution(self, execution_id: str) -> int:
        """Delete all snapshots for an execution."""
        ...
```

### 2.4 数据库 Schema 优化

```sql
-- 统一的 plan_executions 表（替代 work_plans）
CREATE TABLE plan_executions (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    plan_id UUID REFERENCES plan_documents(id) ON DELETE SET NULL,  -- 可选关联
    
    -- 执行配置
    execution_mode VARCHAR(20) DEFAULT 'sequential',
    max_parallel_steps INTEGER DEFAULT 3,
    
    -- 状态
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    -- 反思配置
    reflection_enabled BOOLEAN DEFAULT TRUE,
    max_reflection_cycles INTEGER DEFAULT 3,
    current_reflection_cycle INTEGER DEFAULT 0,
    
    -- 步骤（JSONB 存储）
    steps JSONB NOT NULL DEFAULT '[]',
    current_step_index INTEGER DEFAULT 0,
    completed_step_indices JSONB DEFAULT '[]',
    failed_step_indices JSONB DEFAULT '[]',
    
    -- 元数据
    workflow_pattern_id UUID,
    metadata JSONB DEFAULT '{}',
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- 索引
    CONSTRAINT valid_status CHECK (status IN (
        'pending', 'running', 'paused', 'completed', 'failed', 'cancelled'
    ))
);

CREATE INDEX idx_plan_executions_conversation ON plan_executions(conversation_id);
CREATE INDEX idx_plan_executions_plan ON plan_executions(plan_id);
CREATE INDEX idx_plan_executions_status ON plan_executions(status);
CREATE INDEX idx_plan_executions_conversation_status ON plan_executions(conversation_id, status);

-- plan_snapshots 表（新增）
CREATE TABLE plan_snapshots (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES plan_executions(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- 快照数据
    step_states JSONB NOT NULL DEFAULT '{}',
    
    -- 元数据
    auto_created BOOLEAN DEFAULT TRUE,
    snapshot_type VARCHAR(50) DEFAULT 'auto',
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_plan_snapshots_execution ON plan_snapshots(execution_id);
CREATE INDEX idx_plan_snapshots_created ON plan_snapshots(created_at);

-- 废弃 work_plans 表（迁移数据后删除）
-- DROP TABLE work_plans;
```

### 2.5 事件系统集成

```python
# Plan Mode 专用事件

@dataclass
class PlanModeEnteredEvent(AgentDomainEvent):
    """Emitted when entering Plan Mode."""
    plan_id: str
    title: str
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_MODE_ENTERED


@dataclass
class PlanModeExitedEvent(AgentDomainEvent):
    """Emitted when exiting Plan Mode."""
    plan_id: str
    approved: bool
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_MODE_EXITED


@dataclass
class PlanExecutionStartedEvent(AgentDomainEvent):
    """Emitted when plan execution starts."""
    execution_id: str
    plan_id: Optional[str]
    total_steps: int
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_EXECUTION_STARTED


@dataclass
class PlanExecutionCompletedEvent(AgentDomainEvent):
    """Emitted when plan execution completes."""
    execution_id: str
    status: ExecutionStatus
    completed_steps: int
    failed_steps: int
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_EXECUTION_COMPLETED


@dataclass
class PlanStepStartedEvent(AgentDomainEvent):
    """Emitted when a plan step starts."""
    execution_id: str
    step_id: str
    step_number: int
    description: str
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_STEP_STARTED


@dataclass
class PlanStepCompletedEvent(AgentDomainEvent):
    """Emitted when a plan step completes."""
    execution_id: str
    step_id: str
    step_number: int
    result: str
    execution_time_ms: int
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_STEP_COMPLETED


@dataclass
class PlanStepFailedEvent(AgentDomainEvent):
    """Emitted when a plan step fails."""
    execution_id: str
    step_id: str
    step_number: int
    error: str
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_STEP_FAILED


@dataclass
class PlanReflectionCompletedEvent(AgentDomainEvent):
    """Emitted when plan reflection completes."""
    execution_id: str
    assessment: str  # on_track, needs_adjustment, off_track, complete, failed
    has_adjustments: bool
    reasoning: str
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_REFLECTION_COMPLETED


@dataclass
class PlanAdjustedEvent(AgentDomainEvent):
    """Emitted when plan is adjusted."""
    execution_id: str
    adjustment_count: int
    adjustments: list[dict]
    
    @property
    def event_type(self) -> AgentEventType:
        return AgentEventType.PLAN_ADJUSTED
```

### 2.6 DI 容器配置

```python
# di_container.py 新增

class DIContainer:
    # ... existing code ...
    
    # === Plan Mode Repositories ===
    
    def plan_execution_repository(self) -> PlanExecutionRepository:
        """Get PlanExecutionRepository for plan execution persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_plan_execution_repository import (
            SQLPlanExecutionRepository,
        )
        return SQLPlanExecutionRepository(self._db)
    
    def plan_snapshot_repository(self) -> PlanSnapshotRepository:
        """Get PlanSnapshotRepository for snapshot persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_plan_snapshot_repository import (
            SQLPlanSnapshotRepository,
        )
        return SQLPlanSnapshotRepository(self._db)
    
    # === Plan Mode Use Cases ===
    
    def enter_plan_mode_use_case(self) -> EnterPlanModeUseCase:
        """Get EnterPlanModeUseCase."""
        from src.application.use_cases.agent.enter_plan_mode import (
            EnterPlanModeUseCase,
        )
        return EnterPlanModeUseCase(
            plan_repository=self.plan_repository(),
            conversation_repository=self.conversation_repository(),
        )
    
    def exit_plan_mode_use_case(self) -> ExitPlanModeUseCase:
        """Get ExitPlanModeUseCase."""
        from src.application.use_cases.agent.exit_plan_mode import (
            ExitPlanModeUseCase,
        )
        return ExitPlanModeUseCase(
            plan_repository=self.plan_repository(),
            conversation_repository=self.conversation_repository(),
        )
    
    def generate_plan_execution_use_case(self, llm) -> GeneratePlanExecutionUseCase:
        """Get GeneratePlanExecutionUseCase."""
        from src.application.use_cases.agent.generate_plan_execution import (
            GeneratePlanExecutionUseCase,
        )
        return GeneratePlanExecutionUseCase(
            plan_execution_repository=self.plan_execution_repository(),
            plan_generator=self.plan_generator(llm),
        )
    
    def execute_plan_use_case(self, llm) -> ExecutePlanUseCase:
        """Get ExecutePlanUseCase."""
        from src.application.use_cases.agent.execute_plan import (
            ExecutePlanUseCase,
        )
        return ExecutePlanUseCase(
            plan_execution_repository=self.plan_execution_repository(),
            plan_snapshot_repository=self.plan_snapshot_repository(),
            plan_mode_orchestrator=self.plan_mode_orchestrator(llm),
        )
    
    # === Plan Mode Infrastructure ===
    
    def plan_generator(self, llm) -> PlanGenerator:
        """Get PlanGenerator."""
        from src.infrastructure.agent.planning.plan_generator import PlanGenerator
        return PlanGenerator(
            llm_client=llm,
            available_tools=[],  # Will be set at runtime
        )
    
    def plan_executor(self, llm) -> PlanExecutor:
        """Get PlanExecutor."""
        from src.infrastructure.agent.planning.plan_executor import PlanExecutor
        return PlanExecutor(
            session_processor=self.session_processor(llm),
            event_emitter=None,  # Will be set at runtime
        )
    
    def plan_mode_orchestrator(self, llm) -> PlanModeOrchestrator:
        """Get PlanModeOrchestrator."""
        from src.infrastructure.agent.planning.plan_mode_orchestrator import (
            PlanModeOrchestrator,
        )
        return PlanModeOrchestrator(
            plan_generator=self.plan_generator(llm),
            plan_executor=self.plan_executor(llm),
            plan_reflector=self.plan_reflector(llm),
            plan_adjuster=self.plan_adjuster(),
            event_emitter=None,  # Will be set at runtime
        )
    
    def plan_reflector(self, llm) -> PlanReflector:
        """Get PlanReflector."""
        from src.infrastructure.agent.planning.plan_reflector import PlanReflector
        return PlanReflector(llm_client=llm)
    
    def plan_adjuster(self) -> PlanAdjuster:
        """Get PlanAdjuster."""
        from src.infrastructure.agent.planning.plan_adjuster import PlanAdjuster
        return PlanAdjuster()
    
    def hybrid_plan_mode_detector(self, llm) -> HybridPlanModeDetector:
        """Get HybridPlanModeDetector."""
        from src.infrastructure.agent.planning import (
            HybridPlanModeDetector,
            FastHeuristicDetector,
            LLMClassifier,
        )
        return HybridPlanModeDetector(
            heuristic_detector=FastHeuristicDetector(),
            llm_classifier=LLMClassifier(llm_client=llm),
            cache=None,  # Optional: add Redis cache
        )
```

## 三、迁移计划

### Phase 1: 数据模型重构（1-2 天）

1. **创建新表**
   - `plan_executions` 表
   - `plan_snapshots` 表

2. **创建新 Domain 模型**
   - `PlanExecution`（合并 WorkPlan + ExecutionPlan）
   - `ExecutionStep`（合并 PlanStep + ExecutionStep）
   - 保留 `Plan`（Plan Mode 文档）

3. **迁移数据**
   - work_plans → plan_executions
   - 废弃 work_plans 表

### Phase 2: Repository 重构（1-2 天）

1. **创建新 Repository**
   - `PlanExecutionRepository`
   - `PlanSnapshotRepository`

2. **废弃旧 Repository**
   - 标记 `WorkPlanRepository` 为废弃
   - 保留兼容层直到完全迁移

### Phase 3: Application 层重构（2-3 天）

1. **重构 Use Cases**
   - 更新 `PlanWorkUseCase` → `GeneratePlanExecutionUseCase`
   - 更新 `ExecuteStepUseCase` → `ExecutePlanUseCase`
   - 保留 `EnterPlanModeUseCase`, `ExitPlanModeUseCase`

2. **更新 DI 容器**

### Phase 4: Infrastructure 层重构（2-3 天）

1. **重构 Plan Mode Orchestration**
   - 更新 `PlanGenerator` 生成 `PlanExecution`
   - 更新 `PlanExecutor` 使用 `PlanExecution`
   - 更新 `PlanModeOrchestrator` 集成快照

2. **添加快照功能**
   - 在 `PlanExecutor` 中自动创建快照
   - 支持回滚

### Phase 5: 事件集成（1-2 天）

1. **添加新事件类型**
2. **更新 ReAct Agent 集成**
3. **更新 SSE 事件流**

### Phase 6: 测试与验证（2-3 天）

1. **单元测试**
2. **集成测试**
3. **端到端测试**

## 四、API 变更

### 新增 API

```python
# POST /api/v1/agent/plan-mode/enter
@router.post("/plan-mode/enter")
async def enter_plan_mode(
    data: EnterPlanModeRequest,
    ...
) -> PlanResponse:
    """Enter Plan Mode for a conversation."""

# POST /api/v1/agent/plan-mode/exit
@router.post("/plan-mode/exit")
async def exit_plan_mode(
    data: ExitPlanModeRequest,
    ...
) -> PlanResponse:
    """Exit Plan Mode."""

# GET /api/v1/agent/plan-executions/{execution_id}
@router.get("/plan-executions/{execution_id}")
async def get_plan_execution(
    execution_id: str,
    ...
) -> PlanExecutionResponse:
    """Get plan execution status."""

# POST /api/v1/agent/plan-executions/{execution_id}/pause
@router.post("/plan-executions/{execution_id}/pause")
async def pause_plan_execution(
    execution_id: str,
    ...
) -> PlanExecutionResponse:
    """Pause a running plan execution."""

# POST /api/v1/agent/plan-executions/{execution_id}/resume
@router.post("/plan-executions/{execution_id}/resume")
async def resume_plan_execution(
    execution_id: str,
    ...
) -> PlanExecutionResponse:
    """Resume a paused plan execution."""

# POST /api/v1/agent/plan-executions/{execution_id}/rollback
@router.post("/plan-executions/{execution_id}/rollback")
async def rollback_plan_execution(
    execution_id: str,
    data: RollbackRequest,  # snapshot_id or steps_back
    ...
) -> PlanExecutionResponse:
    """Rollback plan execution to a snapshot."""
```

## 五、预期收益

1. **概念清晰**: 统一 Plan 和 Execution 概念，减少混淆
2. **代码简化**: 删除重复代码，减少维护成本
3. **功能完整**: 实现完整的 Plan Mode 工作流
4. **可扩展性**: 更容易添加新功能（如暂停/恢复、回滚）
5. **可观测性**: 完整的事件流，更好的调试体验

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 数据迁移失败 | 高 | 备份数据，逐步迁移，保留回滚能力 |
| API 不兼容 | 中 | 提供兼容层，逐步废弃旧 API |
| 功能回归 | 中 | 完整测试覆盖，灰度发布 |
| 性能下降 | 低 | 基准测试，必要时添加缓存 |
