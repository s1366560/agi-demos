# 沙箱代码操作架构设计文档

**日期**: 2025-01-15
**版本**: 1.0
**状态**: 设计已完成

---

## 概述

本文档描述了在 MemStack 项目中整合 AI 编程工具（Claude Code、Gemini CLI、OpenCode）的架构设计。核心思想是通过**抽象集成层**和**沙箱隔离**机制，让 React Agent 能够安全地在任意项目上执行代码操作。

### 核心目标

- **增强 Agent 能力**：让 React Agent 能够执行代码编辑、测试、构建、Git 操作
- **安全隔离**：所有代码操作在沙箱环境中执行，不影响宿主机
- **提供者抽象**：支持多种 AI 编程工具后端，可灵活切换
- **生产就绪**：完善的错误处理、重试机制、监控告警

---

## 目录

1. [架构概览](#架构概览)
2. [Domain 层设计](#domain-层设计)
3. [Application 层设计](#application-层设计)
4. [Infrastructure 层设计](#infrastructure-层设计)
5. [Agent Tools 集成](#agent-tools-集成)
6. [数据流与交互](#数据流与交互)
7. [安全设计](#安全设计)
8. [错误处理](#错误处理)
9. [测试策略](#测试策略)
10. [实施路线图](#实施路线图)

---

## 架构概览

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    MemStack Backend (Host)                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              React Agent (LangGraph)                      │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │         Code Operations Tools                        │  │  │
│  │  │   CodeReadTool, CodeEditTool, TestTool, GitTool     │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                       │
│                          │ gRPC / WebSocket / REST               │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │         Sandbox Manager (NEW)                             │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │  │
│  │  │  Pool Mgmt   │  │  Lifecycle   │  │  Communica-  │   │  │
│  │  │              │  │  Control     │  │  tion Layer  │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ Docker / Firecracker / VM
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Sandbox Environments                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Sandbox #1  │  │  Sandbox #2  │  │  Sandbox #3  │         │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │         │
│  │  │Claude  │  │  │  │Gemini  │  │  │  │Open    │  │         │
│  │  │Code    │  │  │  │CLI     │  │  │  │Code    │  │         │
│  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │         │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │         │
│  │  │Project │  │  │  │Project │  │  │  │Project │  │         │
│  │  │Volume  │  │  │  │Volume  │  │  │  │Volume  │  │         │
│  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术 |
|------|------|
| 沙箱运行时 | Docker, Firecracker (可选), Kubernetes (可选) |
| 容器通信 | gRPC, WebSocket, REST |
| 资源管理 | 沙箱池，异步任务队列 |
| 安全 | seccomp, AppArmor, capabilities, network namespace |

---

## Domain 层设计

### SandboxPort 接口

```python
# src/domain/ports/services/sandbox_port.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum
from datetime import datetime

class SandboxProvider(Enum):
    DOCKER = "docker"
    FIRECRACKER = "firecracker"
    KUBERNETES = "kubernetes"
    PODMAN = "podman"

class SandboxStatus(Enum):
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    ERROR = "error"

@dataclass
class SandboxConfig:
    provider: SandboxProvider
    image: str  # e.g., "memstack/claude-code-sandbox:latest"
    cpu_limit: str = "2"
    memory_limit: str = "4G"
    timeout_seconds: int = 300
    network_isolated: bool = True
    security_profile: Optional[str] = "standard"

@dataclass
class SandboxInstance:
    id: str
    status: SandboxStatus
    config: SandboxConfig
    project_path: str
    endpoint: Optional[str]
    created_at: datetime
    terminated_at: Optional[datetime] = None

@dataclass
class CodeOperationRequest:
    sandbox_id: str
    operation: str
    parameters: dict

@dataclass
class CodeOperationResponse:
    success: bool
    result: dict
    error: Optional[str]
    execution_time_ms: int

class SandboxPort(ABC):
    """沙箱管理抽象接口"""

    @abstractmethod
    async def create_sandbox(
        self,
        project_path: str,
        config: SandboxConfig
    ) -> SandboxInstance:
        """创建新的沙箱实例"""
        pass

    @abstractmethod
    async def get_sandbox(self, sandbox_id: str) -> Optional[SandboxInstance]:
        """获取沙箱状态"""
        pass

    @abstractmethod
    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """终止沙箱"""
        pass

    @abstractmethod
    async def execute_operation(
        self,
        request: CodeOperationRequest
    ) -> CodeOperationResponse:
        """在沙箱中执行代码操作"""
        pass

    @abstractmethod
    async def stream_operation(
        self,
        request: CodeOperationRequest
    ):
        """流式执行操作（用于 SSE）"""
        pass

    @abstractmethod
    async def list_sandboxes(self) -> List[SandboxInstance]:
        """列出所有活跃沙箱"""
        pass
```

### Domain Entities

```python
# src/domain/model/code_operations/code_operation.py

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class CodeOperation:
    id: str
    operation_type: str  # read, edit, test, build, git_commit, git_pr
    sandbox_id: str
    project_path: str
    status: str  # pending, in_progress, completed, failed
    result: Optional[dict]
    error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    execution_time_ms: Optional[int]
```

### Domain Errors

```python
# src/domain/model/code_operations/errors.py

class CodeOperationError(Exception):
    """代码操作错误基类"""
    def __init__(self, message: str, sandbox_id: str = None, operation: str = None):
        self.message = message
        self.sandbox_id = sandbox_id
        self.operation = operation
        super().__init__(self.message)

class SandboxTimeoutError(CodeOperationError):
    """沙箱执行超时"""
    pass

class SandboxResourceError(CodeOperationError):
    """沙箱资源耗尽"""
    pass

class SandboxSecurityError(CodeOperationError):
    """安全违规"""
    pass

class SandboxConnectionError(CodeOperationError):
    """沙箱连接失败"""
    pass

class CodeOperationValidationError(CodeOperationError):
    """输入验证失败"""
    pass
```

---

## Application 层设计

### Use Cases

```python
# src/application/use_cases/sandbox/create_sandbox_use_case.py

class CreateSandboxUseCase:
    def __init__(self, sandbox_service: SandboxPort):
        self.sandbox_service = sandbox_service

    async def execute(
        self,
        project_path: str,
        provider: str = "docker",
        security_profile: str = "standard"
    ) -> SandboxInstance:
        """为项目创建隔离沙箱"""
        config = SandboxConfig(
            provider=SandboxProvider(provider),
            image=self._get_image_for_provider(provider),
            security_profile=security_profile
        )
        return await self.sandbox_service.create_sandbox(project_path, config)

# src/application/use_cases/sandbox/execute_code_operation_use_case.py

class ExecuteCodeOperationUseCase:
    def __init__(self, sandbox_service: SandboxPort):
        self.sandbox_service = sandbox_service

    async def execute(
        self,
        sandbox_id: str,
        operation: str,
        **params
    ) -> CodeOperationResponse:
        """在沙箱中执行代码操作"""
        request = CodeOperationRequest(
            sandbox_id=sandbox_id,
            operation=operation,
            parameters=params
        )
        return await self.sandbox_service.execute_operation(request)
```

---

## Infrastructure 层设计

### Docker 沙箱适配器

```python
# src/infrastructure/adapters/secondary/sandbox/docker_sandbox_adapter.py

import docker
import uuid
from datetime import datetime

class DockerSandboxAdapter(SandboxPort):
    """Docker 沙箱实现"""

    SANDBOX_IMAGES = {
        "claude-code": "memstack/claude-code-sandbox:latest",
        "gemini-cli": "memstack/gemini-cli-sandbox:latest",
        "opencode": "memstack/opencode-sandbox:latest",
        "native": "memstack/code-sandbox:latest"
    }

    def __init__(self):
        self.docker_client = docker.from_env()
        self.active_containers = {}

    async def create_sandbox(
        self,
        project_path: str,
        config: SandboxConfig
    ) -> SandboxInstance:
        sandbox_id = str(uuid.uuid4())
        image = self.SANDBOX_IMAGES.get(config.image, config.image)

        volumes = {
            project_path: {
                'bind': '/workspace/project',
                'mode': 'rw'
            }
        }

        container = self.docker_client.containers.run(
            image,
            detach=True,
            volumes=volumes,
            cpu_quota=int(float(config.cpu_limit) * 100000),
            mem_limit=config.memory_limit,
            network_mode="none" if config.network_isolated else "bridge",
            ports={50051: 50051},
            environment={
                "SANDBOX_ID": sandbox_id,
                "PROJECT_PATH": "/workspace/project",
            },
            name=f"sandbox-{sandbox_id}"
        )

        return SandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.RUNNING,
            config=config,
            project_path=project_path,
            endpoint=f"localhost:{container.ports[50051][0]['HostPort']}",
            created_at=datetime.now()
        )
```

### 沙箱池管理

```python
# src/infrastructure/adapters/secondary/sandbox/sandbox_pool.py

import asyncio
from typing import Dict

class SandboxPool:
    """沙箱池，预创建和复用沙箱实例"""

    def __init__(self, adapter: SandboxPort, pool_size: int = 5):
        self.adapter = adapter
        self.pool_size = pool_size
        self.idle_sandboxes: asyncio.Queue[SandboxInstance] = asyncio.Queue()
        self.active_sandboxes: Dict[str, SandboxInstance] = {}

    async def initialize(self):
        """预创建沙箱池"""
        for _ in range(self.pool_size):
            sandbox = await self._create_idle_sandbox()
            await self.idle_sandboxes.put(sandbox)

    async def acquire(self, project_path: str) -> SandboxInstance:
        """获取一个沙箱"""
        try:
            sandbox = await asyncio.wait_for(
                self.idle_sandboxes.get(),
                timeout=5.0
            )
            sandbox.project_path = project_path
        except asyncio.TimeoutError:
            sandbox = await self.adapter.create_sandbox(
                project_path,
                SandboxConfig(provider=SandboxProvider.DOCKER)
            )

        self.active_sandboxes[sandbox.id] = sandbox
        return sandbox

    async def release(self, sandbox_id: str):
        """归还沙箱到池中"""
        if sandbox_id in self.active_sandboxes:
            sandbox = self.active_sandboxes.pop(sandbox_id)
            await self._cleanup_sandbox(sandbox)
            await self.idle_sandboxes.put(sandbox)
```

---

## Agent Tools 集成

### 代码操作工具

```python
# src/infrastructure/agent/tools/code_operations_tool.py

from langchain.tools import BaseTool
from typing import Optional

class CodeEditTool(BaseTool):
    name = "code_edit"
    description = "Edit files in a project using sandboxed AI coding tools"

    def __init__(self, sandbox_service: SandboxPort):
        self.sandbox_service = sandbox_service

    async def _arun(
        self,
        sandbox_id: str,
        file_path: str,
        content: str
    ) -> dict:
        request = CodeOperationRequest(
            sandbox_id=sandbox_id,
            operation="edit_file",
            parameters={"path": file_path, "content": content}
        )
        response = await self.sandbox_service.execute_operation(request)
        return response.result

class TestRunTool(BaseTool):
    name = "run_tests"
    description = "Run tests in sandboxed environment"

    async def _arun(self, sandbox_id: str, target: Optional[str] = None) -> dict:
        request = CodeOperationRequest(
            sandbox_id=sandbox_id,
            operation="run_tests",
            parameters={"target": target} if target else {}
        )
        response = await self.sandbox_service.execute_operation(request)
        return response.result

class GitCommitTool(BaseTool):
    name = "git_commit"
    description = "Commit changes in sandboxed environment"

    async def _arun(self, sandbox_id: str, message: str) -> dict:
        request = CodeOperationRequest(
            sandbox_id=sandbox_id,
            operation="git_commit",
            parameters={"message": message}
        )
        response = await self.sandbox_service.execute_operation(request)
        return response.result
```

### 工具注册

```python
# src/infrastructure/agent/langgraph_graph.py

def get_code_operations_tools(sandbox_service: SandboxPort) -> List[BaseTool]:
    """获取代码操作工具集"""
    return [
        CodeReadTool(sandbox_service),
        CodeEditTool(sandbox_service),
        SearchFilesTool(sandbox_service),
        TestRunTool(sandbox_service),
        BuildRunTool(sandbox_service),
        GitCommitTool(sandbox_service),
        GitCreatePRTool(sandbox_service),
    ]
```

---

## 数据流与交互

### Agent 与沙箱的完整交互流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户请求                                     │
│  "帮我给 MemStack 添加用户认证功能，包括测试"                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    1. Agent 规划阶段                                 │
│  PlanWorkUseCase → 生成工作计划                                      │
│                                                                      │
│  Plan Steps:                                                         │
│  1. 分析现有代码结构 (CodeReadTool)                                  │
│  2. 识别需要修改的文件 (SearchFilesTool)                             │
│  3. 实现 User 模型 (CodeEditTool)                                   │
│  4. 实现 AuthService (CodeEditTool)                                 │
│  5. 添加测试用例 (CodeEditTool)                                     │
│  6. 运行测试验证 (TestRunTool)                                      │
│  7. 提交代码 (GitCommitTool)                                        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    2. 创建沙箱环境                                   │
│  CreateSandboxUseCase.execute(                                      │
│      project_path="/path/to/memstack",                              │
│      provider="claude-code"                                         │
│  )                                                                  │
│    → 返回: sandbox_id="sb_abc123"                                   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    3. 执行代码操作 (SSE 流式)                        │
│  POST /api/v1/agent/chat (SSE)                                      │
│                                                                      │
│  ├─ event: plan                                                     │
│  │  data: { "steps": [...] }                                        │
│  ├─ event: step_start                                               │
│  ├─ event: observation (沙箱返回)                                    │
│  ├─ event: test_output (流式测试输出)                                │
│  ├─ event: result                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### SSE 事件格式

```typescript
// 前端接收的事件类型

interface SandboxEvent {
  type: "sandbox_created" | "sandbox_ready" | "code_operation" | "test_output"
  data: {
    sandbox_id?: string
    operation?: string
    result?: any
    output?: string
    status?: string
  }
}
```

---

## 安全设计

### 五层安全架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        安全分层设计                                   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Layer 1: 网络隔离 (Network Isolation)                       │  │
│  │  - 默认无网络访问 (network_mode="none")                      │  │
│  │  - 可配置白名单访问特定资源                                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Layer 2: 文件系统隔离 (Filesystem Isolation)                │  │
│  │  - 路径遍历防护                                              │  │
│  │  - 符号链接检查                                              │  │
│  │  - 文件大小限制                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Layer 3: 资源限制 (Resource Constraints)                    │  │
│  │  - CPU 配额限制                                              │  │
│  │  - 内存限制 + OOM kill                                       │  │
│  │  - 执行超时强制终止                                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Layer 4: 权限控制 (Permission Control)                     │  │
│  │  - 非 root 用户运行                                          │  │
│  │  - capability 限制 (DROP ALL)                               │  │
│  │  - seccomp 配置文件                                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Layer 5: 审计与监控 (Audit & Monitoring)                   │  │
│  │  - 所有操作日志记录                                          │  │
│  │  - 文件访问审计                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 安全配置

```python
# src/infrastructure/adapters/secondary/sandbox/security_config.py

@dataclass
class SecurityProfile:
    network_isolated: bool = True
    allowed_domains: List[str] = None
    cpu_limit: str = "2"
    memory_limit: str = "4G"
    execution_timeout: int = 300
    max_file_size_mb: int = 10
    drop_capabilities: List[str] = None

class SecurityProfiles:
    @staticmethod
    def strict() -> SecurityProfile:
        """最严格配置"""
        return SecurityProfile(
            network_isolated=True,
            cpu_limit="1",
            memory_limit="2G",
            execution_timeout=120,
            drop_capabilities=["ALL"]
        )

    @staticmethod
    def standard() -> SecurityProfile:
        """标准配置"""
        return SecurityProfile(
            network_isolated=True,
            allowed_domains=["pypi.org", "npmjs.org", "github.com"],
            cpu_limit="2",
            memory_limit="4G"
        )
```

### 路径验证

```python
class PathValidator:
    FORBIDDEN_PATTERNS = ["..", "~/.ssh", "/etc/", "/sys/", "/proc/"]

    @classmethod
    async def validate(cls, path: str, project_root: str) -> tuple[bool, str]:
        root = Path(project_root).resolve()
        target = (root / path).resolve()

        if not str(target).startswith(str(root)):
            return False, f"Path traversal detected: {path}"

        for pattern in cls.FORBIDDEN_PATTERNS:
            if pattern in str(target):
                return False, f"Forbidden path pattern: {pattern}"

        return True, str(target.relative_to(root))
```

---

## 错误处理

### 错误分类与映射

```python
class SandboxErrorHandler:
    ERROR_MAPPING = {
        "OSError: [Errno 28] No space left": SandboxResourceError,
        "Cannot connect to Docker daemon": SandboxConnectionError,
        "permission denied": SandboxSecurityError,
        "command timeout": SandboxTimeoutError,
    }

    @classmethod
    async def handle(cls, error: Exception, context: dict) -> CodeOperationError:
        error_msg = str(error)
        for pattern, error_class in cls.ERROR_MAPPING.items():
            if pattern in error_msg:
                return error_class(
                    message=error_msg,
                    sandbox_id=context.get("sandbox_id"),
                    operation=context.get("operation")
                )
        return CodeOperationError(message=f"Unexpected error: {error_msg}")
```

### 重试策略

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class CodeOperationsRetryService:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(SandboxConnectionError)
    )
    async def execute_with_retry(self, request: CodeOperationRequest):
        return await self.sandbox.execute_operation(request)
```

---

## 测试策略

### 测试金字塔

```
                    ┌─────────┐
                    │  E2E    │  真实 Docker 集成测试
                    └─────────┘
                   ┌───────────┐
                   │  集成测试  │  Mock Docker API
                   └───────────┘
                  ┌─────────────┐
                  │  单元测试    │  完全 Mock
                  └─────────────┘
```

### 单元测试示例

```python
@pytest.mark.asyncio
async def test_create_sandbox_use_case():
    mock_sandbox = MockSandboxAdapter()
    use_case = CreateSandboxUseCase(mock_sandbox)

    result = await use_case.execute("/tmp/test-project", "docker")

    assert result.status == SandboxStatus.RUNNING
    assert result.id is not None
```

---

## 实施路线图

### Phase 1: 基础架构 (2-3 周)
- [ ] 创建 Domain 层：SandboxPort, CodeOperationError
- [ ] 实现 DockerSandboxAdapter (基础功能)
- [ ] 创建基础 Agent Tools
- [ ] 单元测试覆盖 80%+
- [ ] 基础安全配置

### Phase 2: 核心功能 (3-4 周)
- [ ] 完善所有 Agent Tools
- [ ] 实现沙箱池管理
- [ ] SSE 流式输出支持
- [ ] Claude Code 适配器
- [ ] 集成测试覆盖

### Phase 3: 多提供者支持 (2-3 周)
- [ ] Gemini CLI 适配器
- [ ] OpenCode 适配器
- [ ] 原生 Python 后备适配器
- [ ] 自动回退机制

### Phase 4: 生产就绪 (2 周)
- [ ] 完整安全审计
- [ ] 性能优化和压力测试
- [ ] 监控和告警
- [ ] 文档完善

### Phase 5: 高级特性 (可选)
- [ ] Firecracker 微虚机支持
- [ ] Kubernetes 部署支持
- [ ] IDE 插件集成

---

## 配置参考

### 环境变量

```bash
# 沙箱配置
SANDBOX_DEFAULT_PROVIDER=docker
SANDBOX_POOL_SIZE=5
SANDBOX_MAX_CONCURRENT=10

# Docker 配置
DOCKER_REGISTRY=ghcr.io/memstack
SANDBOX_IMAGE_VERSION=latest

# 安全配置
SANDBOX_NETWORK_ISOLATED=true
SANDBOX_CPU_LIMIT=2
SANDBOX_MEMORY_LIMIT=4G
SANDBOX_TIMEOUT_SECONDS=300
```

---

## 附录

### A. 沙箱 gRPC 服务定义

```protobuf
syntax = "proto3";

service SandboxCodeService {
    rpc ReadFile(ReadRequest) returns (ReadResponse);
    rpc EditFile(EditRequest) returns (EditResponse);
    rpc RunTest(TestRequest) returns (TestResponse);
    rpc RunBuild(BuildRequest) returns (BuildResponse);
    rpc GitCommit(GitRequest) returns (GitResponse);
    rpc StreamCommand(StreamRequest) returns (stream StreamResponse);
}

message ReadRequest {
    string path = 1;
}

message ReadResponse {
    bool success = 1;
    string content = 2;
    string error = 3;
}
```

### B. 相关文档

- [MemStack 架构文档](../../architecture.md)
- [Agent 系统设计](../agent/agent-design.md)
- [安全最佳实践](../security/best-practices.md)

---

**文档版本**: 1.0
**最后更新**: 2025-01-15
**维护者**: MemStack 团队
