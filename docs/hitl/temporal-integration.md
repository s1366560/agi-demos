# Temporal 工作流集成

本文档说明 HITL 系统如何与 Temporal 工作流引擎集成。

## 概述

HITL 使用 Temporal 的 Signal 机制实现 Agent 暂停/恢复：

1. Agent 遇到 HITL 请求时抛出 `HITLPendingException`
2. Activity 捕获异常，保存状态，返回 pending 标记
3. Workflow 进入等待状态，监听 Signal
4. 用户响应触发 Signal，Workflow 恢复执行

## 核心组件

### 1. HITLPendingException

```python
# src/domain/model/agent/hitl_types.py

@dataclass
class HITLPendingException(Exception):
    """Agent 请求 HITL 时抛出的异常。"""
    
    request_id: str
    hitl_type: HITLType
    request_data: Dict[str, Any]
    conversation_id: str
    message_id: Optional[str] = None
    timeout_seconds: float = 300.0
    
    def __str__(self):
        return f"HITL request pending: {self.hitl_type.value} ({self.request_id})"
```

### 2. TemporalHITLHandler

统一处理 4 种 HITL 请求的处理器：

```python
# src/infrastructure/agent/hitl/temporal_hitl_handler.py

class TemporalHITLHandler:
    """统一 HITL 处理器，使用策略模式处理不同类型。"""
    
    async def request_clarification(
        self,
        question: str,
        options: List[Dict],
        clarification_type: str = "custom",
        allow_custom: bool = True,
        timeout_seconds: float = 300.0,
        context: Optional[Dict] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """请求用户澄清。"""
        ...
    
    async def request_decision(
        self,
        question: str,
        options: List[Dict],
        decision_type: str = "branch",
        allow_custom: bool = False,
        timeout_seconds: float = 300.0,
        context: Optional[Dict] = None,
        default_option: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """请求用户决策。"""
        ...
    
    async def request_env_var(
        self,
        tool_name: str,
        fields: List[Dict],
        message: Optional[str] = None,
        allow_save: bool = True,
        timeout_seconds: float = 300.0,
        context: Optional[Dict] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """请求环境变量。"""
        ...
    
    async def request_permission(
        self,
        tool_name: str,
        action: str,
        risk_level: str = "medium",
        details: Optional[Dict] = None,
        description: Optional[str] = None,
        allow_remember: bool = True,
        timeout_seconds: float = 60.0,
        default_action: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """请求操作权限。"""
        ...
```

### 3. HITLStateStore

保存 Agent 状态以支持恢复：

```python
# src/infrastructure/agent/hitl/state_store.py

@dataclass
class HITLAgentState:
    """Agent 暂停时的状态快照。"""
    
    request_id: str
    conversation_id: str
    message_id: Optional[str]
    agent_state: Dict[str, Any]  # 序列化的 Agent 状态
    hitl_type: str
    created_at: datetime

class HITLStateStore:
    """Redis 状态存储。"""
    
    def __init__(self, redis_client):
        self._redis = redis_client
    
    async def save_state(
        self,
        conversation_id: str,
        message_id: str,
        request_id: str,
        agent_state: Dict,
        hitl_type: str,
        ttl_seconds: int = 360,
    ) -> str:
        """保存 Agent 状态。"""
        key = f"hitl:agent_state:{conversation_id}:{message_id}"
        state = HITLAgentState(
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=message_id,
            agent_state=agent_state,
            hitl_type=hitl_type,
            created_at=datetime.utcnow(),
        )
        await self._redis.setex(key, ttl_seconds, serialize(state))
        return key
    
    async def load_state(self, key: str) -> Optional[HITLAgentState]:
        """加载 Agent 状态。"""
        data = await self._redis.get(key)
        return deserialize(data) if data else None
    
    async def delete_state(self, key: str) -> bool:
        """删除状态。"""
        return await self._redis.delete(key) > 0
```

## Workflow 实现

### ProjectAgentWorkflow

```python
# src/infrastructure/adapters/secondary/temporal/workflows/project_agent_workflow.py

@workflow.defn
class ProjectAgentWorkflow:
    """项目 Agent 工作流。"""
    
    def __init__(self):
        self._hitl_responses: Dict[str, Any] = {}
        self._pending_hitl: Optional[str] = None
    
    @workflow.signal
    async def handle_hitl_response(self, request_id: str, response: Dict):
        """处理 HITL 响应 Signal。"""
        workflow.logger.info(f"Received HITL response: {request_id}")
        self._hitl_responses[request_id] = response
    
    @workflow.update
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """处理聊天请求。"""
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # 执行 Agent
            result = await workflow.execute_activity(
                execute_project_chat_activity,
                request,
                schedule_to_close_timeout=timedelta(minutes=10),
            )
            
            # 检查是否需要 HITL
            if result.get("hitl_pending"):
                request_id = result["hitl_request_id"]
                self._pending_hitl = request_id
                
                workflow.logger.info(f"HITL pending: {request_id}")
                
                # 等待用户响应
                response = await self._wait_for_hitl_response(
                    request_id=request_id,
                    timeout_seconds=result.get("timeout_seconds", 300),
                )
                
                # 恢复执行
                result = await workflow.execute_activity(
                    continue_project_chat_activity,
                    {
                        "agent_state_key": result["agent_state_key"],
                        "hitl_response": response,
                        **request,
                    },
                    schedule_to_close_timeout=timedelta(minutes=10),
                )
                
                if not result.get("hitl_pending"):
                    return result
            else:
                return result
        
        raise Exception("Max HITL iterations exceeded")
    
    async def _wait_for_hitl_response(
        self,
        request_id: str,
        timeout_seconds: float,
    ) -> Dict:
        """等待 HITL 响应。"""
        async def check_response():
            return request_id in self._hitl_responses
        
        try:
            await workflow.wait_condition(
                check_response,
                timeout=timedelta(seconds=timeout_seconds),
            )
            return self._hitl_responses.pop(request_id)
        except asyncio.TimeoutError:
            raise HITLTimeoutException(request_id)
```

## Activity 实现

### execute_project_chat_activity

```python
# src/infrastructure/adapters/secondary/temporal/activities/project_agent.py

@activity.defn
async def execute_project_chat_activity(request: Dict) -> Dict:
    """执行 Agent 聊天。"""
    try:
        # 创建 Agent 并执行
        agent = create_agent(request)
        result = await agent.chat(request["message"])
        return {"status": "completed", "result": result}
        
    except HITLPendingException as e:
        # 保存状态
        state_key = await state_store.save_state(
            conversation_id=e.conversation_id,
            message_id=e.message_id,
            request_id=e.request_id,
            agent_state=agent.get_state(),
            hitl_type=e.hitl_type.value,
        )
        
        return {
            "status": "hitl_pending",
            "hitl_pending": True,
            "hitl_request_id": e.request_id,
            "hitl_type": e.hitl_type.value,
            "agent_state_key": state_key,
            "timeout_seconds": e.timeout_seconds,
        }
```

### continue_project_chat_activity

```python
@activity.defn
async def continue_project_chat_activity(request: Dict) -> Dict:
    """恢复 Agent 执行。"""
    state_key = request["agent_state_key"]
    hitl_response = request["hitl_response"]
    
    # 加载状态
    state = await state_store.load_state(state_key)
    if not state:
        raise Exception(f"Agent state not found: {state_key}")
    
    # 恢复 Agent
    agent = create_agent(request)
    agent.restore_state(state.agent_state)
    
    # 注入 HITL 响应
    agent.inject_hitl_response(hitl_response)
    
    try:
        # 继续执行
        result = await agent.continue_execution()
        
        # 清理状态
        await state_store.delete_state(state_key)
        
        return {"status": "completed", "result": result}
        
    except HITLPendingException as e:
        # 又遇到 HITL，保存新状态
        new_state_key = await state_store.save_state(...)
        return {
            "status": "hitl_pending",
            "hitl_pending": True,
            ...
        }
```

## Signal 发送

### TemporalHITLService

```python
# src/infrastructure/adapters/secondary/temporal/services/temporal_hitl_service.py

class TemporalHITLService:
    """Temporal HITL 服务。"""
    
    def __init__(self, temporal_client: Client):
        self._client = temporal_client
    
    async def send_hitl_response_signal(
        self,
        workflow_id: str,
        request_id: str,
        response: Dict,
    ) -> bool:
        """发送 HITL 响应 Signal。"""
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.signal(
                "handle_hitl_response",
                args=[request_id, response],
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send signal: {e}")
            return False
```

### REST API

```python
# src/infrastructure/adapters/primary/web/routers/agent/hitl.py

@router.post("/respond")
async def respond_to_hitl(
    request: HITLRespondRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """响应 HITL 请求。"""
    # 获取 HITL 请求
    hitl_request = await repo.get_by_id(request.request_id)
    if not hitl_request:
        raise HTTPException(404, "Request not found")
    
    # 更新数据库状态
    await repo.update_response(
        request_id=request.request_id,
        response=request.response,
        response_metadata=request.metadata,
    )
    
    # 构建 Workflow ID
    workflow_id = f"project_agent_{hitl_request.tenant_id}_{hitl_request.project_id}_default"
    
    # 发送 Signal
    success = await temporal_service.send_hitl_response_signal(
        workflow_id=workflow_id,
        request_id=request.request_id,
        response={
            "request_id": request.request_id,
            "hitl_type": hitl_request.request_type,
            "response_data": request.response,
        },
    )
    
    if not success:
        raise HTTPException(500, "Failed to send response")
    
    return {"status": "ok"}
```

## 超时处理

### Workflow 超时

```python
async def _wait_for_hitl_response(self, request_id: str, timeout_seconds: float):
    try:
        await workflow.wait_condition(
            lambda: request_id in self._hitl_responses,
            timeout=timedelta(seconds=timeout_seconds),
        )
        return self._hitl_responses.pop(request_id)
    except asyncio.TimeoutError:
        # 标记超时
        await workflow.execute_activity(
            mark_hitl_timeout_activity,
            request_id,
        )
        raise HITLTimeoutException(request_id)
```

### 默认值处理

```python
# 在 TemporalHITLHandler 中
if timeout_reached and self._default_value:
    return self._default_value
else:
    raise HITLTimeoutException(request_id)
```

## Worker 重启恢复

### RecoveryService

```python
# src/infrastructure/agent/hitl/recovery_service.py

class HITLRecoveryService:
    """HITL 恢复服务。"""
    
    async def recover_on_startup(self):
        """Worker 启动时恢复未处理的请求。"""
        # 获取所有 ANSWERED 但未 COMPLETED 的请求
        pending = await repo.get_unprocessed_answered_requests()
        
        for request in pending:
            workflow_id = build_workflow_id(request)
            
            # 重新发送 Signal
            await temporal_service.send_hitl_response_signal(
                workflow_id=workflow_id,
                request_id=request.id,
                response=request.response_data,
            )
            
            logger.info(f"Recovered HITL request: {request.id}")
```

### Worker 启动钩子

```python
# src/agent_worker.py

async def main():
    # 初始化 Recovery 服务
    recovery_service = HITLRecoveryService(...)
    await recovery_service.recover_on_startup()
    
    # 启动 Worker
    worker = Worker(...)
    await worker.run()
```

## 监控与日志

### 关键日志点

```python
# Workflow 层
workflow.logger.info(f"HITL pending: request_id={request_id}, type={hitl_type}")
workflow.logger.info(f"HITL response received: {request_id}")
workflow.logger.info(f"Continuing chat with HITL response: {request_id}")

# Activity 层
activity.logger.info(f"[HITL Activity] Created request: {request_id}")
activity.logger.info(f"[HITL Activity] Saved state: {state_key}")
activity.logger.info(f"[HITL Activity] Restored state: {state_key}")
```

### Temporal UI

在 Temporal UI (http://localhost:8080) 中可以查看：

- Workflow 状态 (Running/Waiting)
- Signal 历史
- Activity 执行记录
- 错误堆栈

## 最佳实践

1. **超时设置**: 根据请求类型设置合理超时
   - Permission: 60s (需要快速决策)
   - Decision/Clarification: 300s
   - EnvVar: 300s

2. **状态精简**: 只序列化必要的 Agent 状态

3. **幂等性**: Signal 处理应该是幂等的

4. **监控告警**: 监控 HITL 超时率和响应时间

5. **测试**: 使用 Temporal 测试框架进行集成测试
