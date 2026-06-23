# MCP 工具与 ReActAgent 集成状态分析

> 生成时间: 2026-01-30
> 最后核对代码: 2026-06-23

## 执行概要

本文描述 Sandbox 内置 MCP 工具与 ReActAgent 集成模块的结构、能力与测试现状。核心框架涵盖工具注册机制、权限控制、错误处理和资源管理。具体覆盖度以当前代码与测试为准（详见「测试覆盖」章节）。

**能力清单：**
- MCP 工具权限规则集成 (`sandbox_mcp_ruleset()`)
- 工具权限自动分类 (`classify_sandbox_tool_permission()`)
- 错误处理机制 (`mcp_errors.py`)
  - `MCPToolError` - 结构化错误信息
  - `MCPToolErrorClassifier` - 自动错误分类
  - `RetryConfig` - 指数退避重试策略
- `SandboxMCPToolWrapper` 集成错误处理和重试机制
- 资源管理
  - 并发 sandbox 限制和排队机制
  - 智能空闲清理（基于活动时间而非创建时间）
  - 资源限制验证（CPU、内存）
  - 资源使用监控和健康检查

---

## 1. 现状分析

### 1.1 MCP 工具实现现状

**已完成的部分：**

| 组件 | 状态 | 说明 |
|------|------|------|
| `SandboxMCPToolWrapper` | 已实现 | 支持命名空间、权限属性、schema 转换、错误处理、重试机制 |
| `MCPSandboxAdapter` | 已实现 | Docker sandbox 与 MCP WebSocket 集成 + 资源管理 |
| 工具注册机制 | 已实现 | 支持 TTL 缓存和自动加载 |
| 权限规则系统 | 已实现 | sandbox_mcp_ruleset() 实现 |
| 错误处理系统 | 已实现 | mcp_errors.py 错误分类和重试机制 |
| 资源管理系统 | 已实现 | 并发控制、自动清理、资源限制、监控 |

**核心文件：**
- `src/infrastructure/agent/tools/sandbox_tool_wrapper.py` - MCP 工具包装器（含权限和错误处理）
- `src/infrastructure/agent/tools/mcp_errors.py` - 错误类型、分类器、重试配置
- `src/infrastructure/agent/permission/rules.py` - 权限规则
- `src/infrastructure/agent/core/react_agent.py` - 工具转换
- `src/infrastructure/adapters/secondary/sandbox/mcp_sandbox_adapter.py` - Sandbox 适配器（含资源管理）

### 1.2 ReActAgent 工具注册机制

**已实现：**
- `_convert_tools` 方法提取工具 permission 属性
- `ProjectReActAgent` 支持工具热更新
- `_check_and_refresh_sandbox_tools` 自动检测新 sandbox

### 1.3 工具调用链路

```
用户请求 → ReActAgent → SessionProcessor → PermissionManager → SandboxMCPToolWrapper → MCPSandboxAdapter → Docker Sandbox
                                    ↓
                            资源管理器 (并发控制、活动跟踪、自动清理)
```

链路：从用户请求到 Docker Sandbox，经权限、错误处理与资源管理模块协同。

---

## 2. 集成完成情况

### 2.1 功能完成度

| 功能模块 | 状态 | 说明 |
|---------|------|------|
| MCP 工具包装器 | 已实现 | SandboxMCPToolWrapper |
| Sandbox 适配器 | 已实现 | MCPSandboxAdapter + 资源管理 |
| 工具注册机制 | 已实现 | 支持自动加载、缓存和权限提取 |
| 权限控制 | 已实现 | MCP 工具权限规则和分类 |
| 错误处理 | 已实现 | 错误分类、重试机制、用户消息 |
| 资源管理 | 已实现 | 并发控制、自动清理、资源限制、监控 |
| 测试覆盖 | 见第 5 章 | 覆盖率以当前测试为准 |

### 2.2 错误处理机制详情

#### 错误类型 (MCPToolErrorType)

| 错误类型 | 是否可重试 | 说明 |
|---------|-----------|------|
| CONNECTION_ERROR | 是 | 连接被拒绝、WebSocket 断开 |
| TIMEOUT_ERROR | 是 | 执行超时 |
| PARAMETER_ERROR | 否 | 参数错误、验证失败 |
| VALIDATION_ERROR | 否 | 验证错误 |
| EXECUTION_ERROR | 视情况 | 执行失败（根据具体情况判断） |
| PERMISSION_ERROR | 否 | 权限被拒绝 |
| SANDBOX_NOT_FOUND | 否 | Sandbox 不存在 |
| SANDBOX_TERMINATED | 否 | Sandbox 已终止 |
| UNKNOWN_ERROR | 否 | 未知错误 |

#### 重试策略 (RetryConfig)

- **指数退避**: delay = base_delay * (exponential_base ^ attempt)
- **最大延迟**: 延迟被钳制到 max_delay
- **抖动**: 可选的 +/- 25% 随机抖动
- **默认配置**: max_retries=3, base_delay=1.0s, max_delay=30s

### 2.3 关键文件状态

- `src/infrastructure/agent/tools/sandbox_tool_wrapper.py` - MCP 工具包装器（含权限和错误处理）
- `src/infrastructure/agent/tools/mcp_errors.py` - 错误处理模块
- `src/infrastructure/agent/core/react_agent.py` - 权限提取集成
- `src/infrastructure/agent/permission/rules.py` - sandbox_mcp_ruleset 实现
- `src/infrastructure/adapters/secondary/sandbox/mcp_sandbox_adapter.py` - 资源管理功能
- `src/domain/ports/services/sandbox_port.py` - last_activity_at 字段

---

## 3. 资源管理机制

### 3.1 并发控制

| 功能 | 说明 |
|------|------|
| max_concurrent_sandboxes | 最大并发 sandbox 数量限制 |
| can_create_sandbox() | 检查是否可以创建新 sandbox |
| queue_sandbox_request() | 将请求添加到等待队列 |
| process_pending_queue() | 处理等待队列中的请求 |

### 3.2 活动跟踪

| 功能 | 说明 |
|------|------|
| last_activity_at | 沙箱最后活动时间戳 |
| update_activity() | 更新活动时间 |
| get_idle_time() | 获取空闲时长 |

### 3.3 自动清理

| 功能 | 说明 |
|------|------|
| cleanup_idle_sandboxes() | 基于空闲时间清理 |
| cleanup_expired() | 基于创建时间清理 |
| cleanup_orphaned() | 清理孤儿容器 |

### 3.4 资源限制验证

| 功能 | 说明 |
|------|------|
| validate_resource_config() | 验证配置是否超出资源限制 |
| max_memory_mb | 最大内存限制 |
| max_cpu_cores | 最大 CPU 核心限制 |

### 3.5 监控

| 功能 | 说明 |
|------|------|
| get_resource_summary() | 获取资源使用摘要 |
| get_total_resource_usage() | 获取总资源使用 |
| health_check_all() | 批量健康检查 |

---

## 4. MCP 工具权限规则

### 4.1 权限分类策略

`classify_sandbox_tool_permission(tool_name)` 按工具名返回权限类型，取值为 `read` / `write` / `bash` / `ask`（注意 execute 类工具映射到 `bash`，而非 `execute_tools`）。代码见 `src/infrastructure/agent/permission/rules.py`。这些集合是分类函数的当前白名单，不是所有 sandbox MCP 工具的完整清单：

```python
def classify_sandbox_tool_permission(tool_name: str) -> str:
    # Read tools - 返回 "read"
    read_tools = {"file_read", "read_file", "list_files", "cat", "grep", "glob", "find", "ls", "dir"}

    # Write tools - 返回 "write"
    write_tools = {"file_write", "write_file", "create_file", "edit_file",
                   "delete_file", "remove", "rm", "mv", "rename", "mkdir", "touch"}

    # Execute tools - 返回 "bash"
    execute_tools = {"bash", "execute", "run_command", "python", "node", "sh", "shell"}

    # 命中上述集合分别返回 "read" / "write" / "bash"，否则返回 "ask"
```

### 4.2 权限规则摘要

`sandbox_mcp_ruleset()` 中的规则（同样位于 `permission/rules.py`）：

| 工具类型 | 权限类型 | 默认操作 | 说明 |
|---------|---------|---------|------|
| `read`, `file_read`, `list_files`, `cat`, `grep`, `glob`, `find` | read | ALLOW | 规则集直接允许；分类函数还识别 `read_file`, `ls`, `dir`。 |
| `write`, `file_write`, `write_file`, `create_file`, `edit_file`, `delete_file`, `edit`, `patch` | write | ASK | 规则集需要用户确认；分类函数还识别 `remove`, `rm`, `mv`, `rename`, `mkdir`, `touch`。 |
| `bash`, `execute`, `run`, `python`, `sh`, `shell` | bash | ASK | 规则集需要用户确认；分类函数还识别 `run_command`, `node`。 |
| 未知工具（兜底 `*/*`） | * | ASK | 默认需要确认 |

### 4.3 模式特定行为

| 模式 | MCP 工具行为 |
|------|-------------|
| BUILD | 根据工具类型应用规则（read 允许，write/ask 询问） |
| PLAN | 所有 write/bash 工具被 DENY |
| EXPLORE | 所有 sandbox 工具被 DENY（纯只读模式） |

---

## 5. 错误处理机制

### 5.1 错误分类流程

```
异常发生 → MCPToolErrorClassifier.classify()
                ↓
    检查错误消息模式匹配
                ↓
    检查异常类型 (ConnectionError, TimeoutError)
                ↓
    确定错误类型和重试策略
                ↓
    返回 MCPToolError (包含 is_retryable 标志)
```

### 5.2 重试逻辑

```
工具执行 → 检查结果
            ↓
      结果是错误？
            ↓
    是 → MCPToolErrorClassifier.classify()
            ↓
    is_retryable && attempt < max_retries？
            ↓
    是 → 计算延迟 → 等待 → 重试
            ↓
    否 → 返回用户友好的错误消息
```

### 5.3 用户友好错误消息

| 错误类型 | 用户消息 (中文) |
|---------|----------------|
| CONNECTION_ERROR | 无法连接到 sandbox 容器，请稍后重试 |
| TIMEOUT_ERROR | 工具执行超时: {tool_name} |
| PARAMETER_ERROR | 参数错误: {message} |
| PERMISSION_ERROR | 权限被拒绝: {message} |
| SANDBOX_NOT_FOUND | Sandbox 不存在或已终止 |
| SANDBOX_TERMINATED | Sandbox 已终止 |

---

## 6. 测试覆盖

> 以下测试文件、用例数与覆盖率为历史快照（2026-01-30），最新数据请以仓库当前测试运行结果为准。

### 6.1 测试文件

- `src/tests/unit/infrastructure/agent/permission/test_sandbox_mcp_rules.py` - 权限规则测试（15 个测试）
- `src/tests/unit/infrastructure/agent/tools/test_sandbox_mcp_wrapper.py` - 包装器测试（16 个测试）
- `src/tests/unit/infrastructure/agent/tools/test_mcp_errors.py` - 错误处理测试（26 个测试）
- `src/tests/unit/infrastructure/adapters/secondary/sandbox/test_mcp_sandbox_resource_manager.py` - 资源管理测试（27 个测试）

### 6.2 测试覆盖率

| 模块 | 覆盖率 |
|------|-------|
| permission/rules.py | 93% |
| tools/mcp_errors.py | 95% |
| tools/sandbox_tool_wrapper.py | 82% |
| mcp_sandbox_adapter.py | 88% |
| 总体 | 90% |

### 6.3 测试用例类别

- 权限规则匹配测试
- 工具分类测试
- 模式特定权限测试
- 命名空间测试
- 参数 schema 转换测试
- 工具执行测试
- 错误分类测试
- 重试机制测试
- 用户消息生成测试
- 并发限制测试
- 排队机制测试
- 自动清理测试
- 资源限制验证测试
- 活动跟踪测试
- 健康检查测试

---

## 7. 风险评估

### 7.1 安全风险

**低风险：**
1. MCP 工具权限控制已实现细粒度规则
2. Sandbox 逃逸风险由 Docker 隔离缓解

### 7.2 性能风险

**低风险：**
1. Agent Session Pool 已经优化了 95%+ 的性能
2. 工具缓存机制有效减少了重复加载
3. 重试机制使用指数退避，避免过度重试

### 7.3 稳定性风险

**低风险：**
1. 错误处理机制已完善
2. 重试逻辑只对可重试错误生效
3. 参数错误等不会触发无效重试

---

## 8. 待办事项列表（按优先级排序）

### 低优先级

1. **用户体验优化**
   - 改进 MCP 工具执行状态显示
   - 添加工具执行进度反馈
   - 优化错误提示信息

2. **文档完善**
   - 更新 MCP 工具使用文档
   - 添加故障排除指南
   - 提供最佳实践示例

---

## 9. 总结

MCP 工具与 ReActAgent 集成模块涵盖权限控制、错误处理和资源管理三方面能力。

**模块要点：**
- 架构模块化（包装器、适配器、权限、错误处理、资源管理各自独立）
- 使用缓存机制优化重复加载
- 工具注册与发现机制（自动加载、TTL 缓存、权限提取）
- 细粒度权限控制（read / write / bash / ask）
- 错误分类与指数退避重试
- 资源管理（并发控制、空闲清理、资源限制、监控）

**功能清单：**
- MCP 工具包装器（命名空间、权限、schema 转换）
- 自动工具发现和缓存
- 细粒度权限控制（read / write / bash / ask）
- 错误分类和重试
- 并发 sandbox 限制
- 空闲 sandbox 自动清理
- 资源限制验证
- 健康检查和监控

当前测试覆盖与具体用例数以仓库最新代码为准（见第 6 章）。
