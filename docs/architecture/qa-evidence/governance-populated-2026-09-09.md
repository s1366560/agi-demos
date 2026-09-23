# 治理面填充样本验收证据 — 2026-09-09

批次 B7（计划要求 I5/I6）：为事件、DLQ、运行日志、决策和运行手册建立隔离样本，验证详情、重试、审批与权限，替换 2026-09-07 仅空状态的证据。本文件不将"权限拒绝正确""入口可用""空状态通过"改记为功能完成；下列每项均为填充样本上的完整闭环。

## 隔离样本

脚本 `scripts/qa_governance_fixtures.py`（幂等 seed / status / cleanup，真实 PostgreSQL + Redis 实测通过；二次 seed 应用 0 行，cleanup 后各面计数归 0，DLQ stats 哈希恢复原值）。

- 范围：专用 QA 租户 `QA Governance Tenant`（slug `qa-governance-5785a4b3`），租户 `bc4a7304-8901-5ab7-8fb9-5ce0982f51dd`，项目 `5e15ef03-5da9-5238-bd4f-8300eaca1bdb`，工作空间 `c8f7bdf4-8738-5127-b042-68dbb5fccc48`。所有 ID 由 uuid5(QA 命名空间) 确定性生成，payload 带 `qa_fixture: qa-governance:qa-governance-v1` 标记，无密钥。
- 样本量：事件日志 4（3 种 event_type）；DLQ 4（pending×2、retrying、resolved，真实 Redis 生产键布局）；决策记录 3（pending/approved/rejected）+ 信任策略 1；运行手册（playbook）2 + 执行历史（reflection verdicts）2；审计日志 4。
- 运行日志样本：SubAgentRunRegistry 为进程内注册表（`src/infrastructure/agent/subagent/run_registry.py`），外部脚本无法写入运行中服务器的注册表；测试经由生产写入路径（`create_run`/`mark_running`/`mark_completed`/`mark_failed`）在初始化后的同一代插件运行时内注册 1 条 completed + 1 条 failed 运行（含 summary/error/tokens/trace_id）。

## 各面闭环验证

测试代码：`src/tests/integration/governance/`（conftest 复用 test_app 全量 FastAPI + `initialize_plugin_runtime_v2`，DLQ 走真实 Redis；另有真实 PostgreSQL 私有 schema 仓储层验证）。共 44 个测试。

| 面 | 闭环 | 测试 |
| --- | --- | --- |
| 事件日志 `/api/v1/events` | 列表返回 4 条填充行全字段；event_type 过滤；/types 去重；租户隔离（其他租户 0 条）；成员读 200、外部用户 403 | test_governance_events.py（5） |
| DLQ `/api/v1/admin/dlq` | 列表+stats 计数/错误类型分布；详情全字段（event_data/retry_count/can_retry）；单条 retry pending→resolved（真实 Redis 重新发布）；resolved 再 retry → 409 幂等；discard 保留原因；批量 retry 逐条结果；404；非管理员全部操作 403 | test_governance_dlq.py（9） |
| 决策/审批 `/api/v1/tenants/{t}/trust` | 列表三种 outcome；详情全字段；工作空间串号 404；提交→allow_once→success；提交→deny→rejected；allow_always 生成信任策略且 policies/check trusted=true；成员可提交可读但 resolve 403；外部用户读/提交 403 | test_governance_decisions.py（8） |
| 运行手册 `/api/v1/projects/{p}/playbooks` | 列表 2 条填充 runbook（trigger/steps/hit_count 全字段）；verdict 执行历史 2 条；成员读 200；非成员 403 | test_governance_runbooks.py（4） |
| 运行日志 `/api/v1/agent/trace/runs` | 项目列表含 completed+failed；status 过滤；会话列表+详情（summary/error/tokens/execution_time_ms/trace_id）；trace 链聚合 2 条；成员只见自己会话（空列表）、读他人会话 404；外部用户项目列表 403 | test_governance_run_logs.py（7） |
| 审计与导出 `/api/v1/tenants/{t}/audit-logs` | 列表填充行；action 过滤；export json/csv 均含 4 行（Content-Disposition 附件头、details JSON 回读）；成员可读可导出；外部用户列表/导出 403 | test_governance_audit.py（6） |
| 仓储层（真实 PostgreSQL 16，私有 schema，用完 DROP） | 事件日志 JSONB metadata 回读；租户隔离；决策记录 outcome/proposal；审计 action 过滤；playbook trigger/steps 领域转换 | test_governance_repository_postgres.py（5） |

## 后端改动

- `src/infrastructure/adapters/primary/web/routers/admin_dlq.py`：`DLQRetryError` 由未捕获（500）改映射为 409（gettext 文案），使终态消息重试在 API 层幂等安全。仅此一处；无 schema 变更。

## 验证命令与结果

```bash
uv run pytest src/tests/integration/governance/ -q                       # 44 passed
uv run pytest src/tests/unit/routers/test_admin_dlq_router.py \
  src/tests/unit/routers/test_admin_dlq_router_authority_v2.py \
  src/tests/unit/routers/test_admin_dlq_role_loading.py \
  src/tests/unit/routers/test_audit_export.py \
  src/tests/unit/routers/test_trust_router.py \
  src/tests/unit/infrastructure/plugins/v2/test_builtin_admin_dlq_http_routes_v2.py \
  src/tests/unit/infrastructure/plugins/v2/test_admin_dlq_services_v2.py \
  src/tests/unit/infrastructure/adapters/secondary/messaging/test_redis_dlq.py \
  src/tests/unit/infrastructure/adapters/primary/web/test_admin_dlq_application_authority_v2.py -q  # 46 passed
uv run pytest src/tests/integration/api/test_reflection.py \
  src/tests/unit/infrastructure/adapters/secondary/persistence/test_sql_playbook_repository.py -q   # 8 passed
uv run ruff check + format（触及文件）# 通过
uv run mypy / pyright（scripts/qa_governance_fixtures.py、admin_dlq.py）# 0 errors
PYTHONPATH=. uv run python scripts/qa_governance_fixtures.py seed|status|cleanup  # 实测幂等与回收
```

## 遗留缺口

- 事件日志无按 ID 详情端点（仅列表+/types）；列表项已含全部字段，未新增端点，按缺口报告。
- 运行日志注册表为进程内实现，跨进程/重启不可持久；活环境填充需真实子代理运行，种子脚本无法代写，按缺口报告。
- DLQ 为全局 Redis 键空间（无租户维度），隔离依赖 QA 标记 + 精确回收。
