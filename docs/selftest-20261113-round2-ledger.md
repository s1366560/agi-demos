# 2026-11-13 完全访问报告第二轮核对

本清单只记录这一轮云端分支相对 PR #19 `161ec6bdf2d9c8bf76332da70e590c7b9649a7de` 的增量。它不代替 `docs/selftest-20261112-implementation-ledger.md`。没有合并 PR #19 或 PR #20，没有改 `.github/workflows/ci.yml` 或 `scripts/ci/plugins_g_files.txt`，也没有访问用户 Mac 上的 3000/8000/5173 进程。

## 基线

- `origin/main` 仍是 `086310035`（PR #18）。PR #19、PR #20 都还开着，基线都是这个 main。
- PR #19 HEAD `161ec6bdf`。用户确认其 40 项检查已成功，工作区干净，仍未合并。本分支从该 HEAD 拉出，PR 叠在 #19 上。
- PR #20 HEAD `fcda0b142`。本轮没有改它的 Desktop Bundle 拆分，也没有重写 plugins-g 从 `test_route_registration_v2.py` 到 `test_workspace_collaboration_proxy_headers_v2.py` 的分片步骤名。
- 报告会话 `c43d277f-6766-468c-8081-5040729f34fb`，项目 `9fa840d9-f0b4-4ab0-9ff1-5aeac420dcb8`，北京时间 2026-11-13 08:43–08:55。报告没有构建 SHA。不能把这次运行写成 main 或 PR #19 的某一个提交。

报告里的错误串 `Create requires durable automation command processing; no job was created` 在 main 上是 `create_job` 的无条件拒绝。在 PR #19 上，同一句话只在 `CronJobService` 没有注入 `AutomationCommandService` 时出现。因此这次运行要么还在未含 PR #19 接线的进程上，要么工具进程没有拿到这条命令服务。两种情况都不是“命令契约没写”。本轮没有重写创建、更新、删除、启停和手动排队。

## 探针重算

JSON 84 行，加总一致：39 PASS、38 UNAUTHORIZED、1 ENV_MISSING、1 NOT_APPLICABLE、4 FAIL、1 PARTIAL。39/84 = 46.4%。带 `equivalent` 字段的行正好 15 行，(39+15)/84 = 64.3%。这 15 行只是文件系统编辑 7 行、代码分析 5 行、测试 3 行。

不能把 64.3% 或 bash 等价当成工具实现健康。Markdown 第六节把 export、platform、git、plugin、deps_install 也写进“15 项等价成功”，JSON 的 `equivalent` 字段没有这些行。缺陷正文里的 39.7% 和 27/58 与 84 行对不上。

4 个 FAIL 是：子代理执行（JSON 探针名误写成 DEFECT D4）、`system_api`、`cron(add)`、`cron(add agent_turn)`。`cicd_run_pipeline` 的证据是 “not invoked / no token”，不是一次真实调用的授权结论。`github` 的 ENV_MISSING 来自调用方自己传入的 `check_env_vars` 名单。`get_env_var` 被记成 PASS，证据却是 PATH 语义不一致。`agent_sessions` 和 `register_mcp_server` 各占了两行。10 个测试、67 条语句、100% 覆盖只描述报告夹具里的小样例。

## D1 完全访问与拒绝

- 原探针：`edit`、`batch_edit`、`patch`、`run_tests` 等返回授权拒绝；`read`、`bash`、`write` 通过。执行体标签是 `builtin:all-access`。
- 复现：`classify_sandbox_tool_permission("edit")` 原先落到哨兵 `"ask"`。`ChatRunToolPermissionV2.decision` 对不在 `_READ`/`_MUTATION` 里的类别直接 `deny`，所以显式 `full_access` 也到不了放行分支。`bash` 已是 `bash`，`write` 在带 workspace write contract 时是 `workspace_file_write`，两者都能在 `full_access` 下通过。这解释了报告里的分裂，不是标签本身等于授权。
- 前轮：PR #18/#19 的结构化拒绝保留。`format_chat_tool_denial` 没有改回旧的泛化句子。报告引用的句子是结构化拒绝里的后半句，不是另一套实现。
- 本轮：已有名字的沙箱工具映射到现有类别（`edit`、`patch`、`write`、`bash`、`read`、`mcp`、`plugin_manager`）。`unknown_tool` 和 `docker_compose` 仍是 `"ask"`，`full_access` 继续拒绝。`ask` 对 `edit` 返回人工确认，`automatic` 只放行 `workspace_file_write` / `workspace_task_write`。`canvas_*` 从 `permission=None` 改为已声明的 `write`。`ask_clarification` 仍是未声明类别，继续拒绝。
- 回归：`test_full_access_declared_tool_grant.py`，以及原 sandbox 权限测试。
- 边界：没有补全局 allowlist，没有 wildcard，没有用 bash 绕过拒绝。子运行天花板仍由 `peer_chat_permission_v2` 取父档与工作区档的较低者。显式 `detached: true` 的跳过逻辑没有改。

## D2 子运行只有 request

- 原探针：两次 `agent_spawn` 返回 spawn/run/trace，`agent_history` 只有一条 request，状态约 4 分钟保持 running，之后手工 stop。
- 复现：spawn 记录创建时默认 `running`，request 在执行器之前写入消息总线。`execute_project_chat` 只有在进入模型循环后才会写终态和 history response。准入或初始化在此之前失败时，本地路径只结算根运行，actor 路径会让后台任务带异常退出，父会话仍看到 running 和一条 request。
- 前轮：`_record_child_result_history` 是终态清理。它不负责把还没进入模型的子运行唤醒。成功的 session 模式仍保持 running，这是既有测试 `test_finalize_child_session_keeps_session_mode_running`。
- 本轮：失败的 run 和 session 都记为 `failed`。未进入 `execute_project_chat` 的子运行调用 `publish_child_bootstrap_failure`，history 里带 `failure_class=backend` 和错误码，父会话看得到。没有加“60 秒无文本即失败”。没有改显式 detached 跳过。
- 回归：`test_child_bootstrap_failure.py` 4 passed；`test_execution.py` 29 passed。
- 边界：没有用真实 MiniMax 跑 echo 或 5 步链，也没有在用户 Mac 上派生子代理。受控测试证明的是失败可见和成功 session 不误杀，不是外部模型已经产出工具事件。

## D3 system_api 代际

- 原探针：两次调用都是 `HTTP route table is unavailable for the pinned plugin generation`，报告记 FAIL，不是 UNAUTHORIZED。
- 复现：`RouteTableRegistryV2.resolve` 只按钉住的 descriptor 查找。当前代表另一代时不会拿来顶上。
- 前轮：PR #19 的 `test_route_generation_unavailable.py` 锁住未发布代的 fail-closed。本轮没有关掉它。
- 本轮：同代已发布表仍由 `resolve` 命中，并用 `openapi.descriptor` 核对。未发布代在 `system_api` 返回 `failure_class=backend`、`code=route_generation_unavailable`、`generation_status=unpublished`。文案不含 “does not authorize”。
- 回归：`test_same_generation_route_table.py`、`test_system_api_generation_status.py`、PR #19 的 unavailable 测试。
- 边界：没有把不匹配代的路由拼进权限。报告当时的进程里这张表确实不可用；单测不能证明那次沙箱进程已经发布了同代路由。

## D4 cron

- 原探针：`cron(status/list)` PASS；两种 add 都是 durable command 那句拒绝。
- 对照：PR #19 的 `cron_tool._build_service` 已经注入 `AutomationCommandService`，创建、更新、删除、启停和手动排队带项目、revision 和幂等键。调度器真实执行仍未启动。
- 本轮：没有改 `cron_service.py`、`cron_tool.py`、`automation_command_service.py`。重跑 `test_cron_tool.py` 10 passed。
- 结论：报告中的那句错误是“命令服务没接到这次运行”，不是契约缺失。新运行要在含 PR #19 接线的进程上再测 add。不要在这个环境创建定时跟踪，也没有动用户已有 job。

## D5 依赖安装

- 原探针：`deps_install` 在报告里是 UNAUTHORIZED。另一次 bash `pip` 写 `/opt/sandbox-mcp-venv` 得到 Errno 13。后者不是产品工具的返回值。
- 前轮：`classify_install_failure` 保留 `environment_not_writable`。没有 chmod。
- 本轮：调用方给出的 `venv_path` 保持原样。解释器前缀可写时仍用默认 pip。前缀不可写时改到工作区 `.deps-venv`，不改 `PYTHONPATH`，也不 chmod site-packages。
- 回归：`sandbox-mcp-server` 下 `test_deps_install_target.py` 与 `test_deps_install_failure.py`。
- 边界：本云端没有对系统前缀执行安装。授权仍由 D1 的档位决定，`deps_install` 不是因为换了目录就对 `ask` 放开。

## D6 GitHub / CI 凭据

- 原探针：`check_env_vars` 报 `GITHUB_TOKEN` 和 `ANTHROPIC_API_KEY` 都缺失。工具实现里 GitHub 写操作只要求 `GITHUB_TOKEN`（`github_capabilities._token_from_env`）。`cicd_run_pipeline` 走插件配置，不读取 `ANTHROPIC_API_KEY`。
- 本轮：`check_env_vars` 对这两个工具名返回 `declared_required`、`declared_missing`、`not_declared`。`ANTHROPIC_API_KEY` 对 github 标成 not declared。响应不回显环境值。
- 回归：`test_declared_tool_credentials.py`。
- 结论：缺凭据不是实现损坏。没有读取或接入新的 token。

## D7 pkg 与 src/pkg

- 原探针：沙箱里同时有 `/workspace/pkg` 和 `/workspace/src/pkg`。仓库里没有这份用户目录，不能删。
- 根因：覆盖率把 import root 和工作区根一起放进 `PYTHONPATH`，同名包会抢先命中另一份。
- 本轮：同时存在顶层 `pkg` 和 `src/pkg` 时，`src/pkg` 下的文件用 `src` 做 import root，模块名是 `pkg.*`，并用 `module_origin_for` 核对文件就是被测源文件。只剩 `src/pkg` 时仍用 `src.pkg`。工作区根不再额外塞进这条 `PYTHONPATH`。两份目录都保留。
- 回归：`test_module_origin.py`。

## D8 get_env_var 与 PATH

- 原探针：工具对 bash 的 PATH 返回 not configured，shell 里 PATH 存在。该行仍被报告记为 PASS。
- 根因：工具读的是托管工具配置，不是进程环境。
- 本轮：响应带 `source=managed_tool_config`、`exists`、`scope`。找不到时 `process_environment=not_consulted`，文案说明 shell PATH 是另一来源。秘密值增加 `redacted_preview`，已授权的托管读取仍返回原值，测试不回显进程里的 PATH 或密钥。
- 回归：`test_declared_tool_credentials.py` 和原 `test_env_var_tools.py`。

## 上一轮清单里仍未在本环境验证的真实操作

这些不是本轮单测能替代的：

- 旧会话 `cd9755fd` 的时间线重开。
- A2UI 消息在窗口里的真实组件。
- 窗口里取消云请求。
- 原容器 `/opt/sandbox-mcp-venv` 上的真实 pip 拒绝。分类函数有单测，没有在那只读前缀上再跑 pip。
- API 在线时旧会话 messages 本页 5 条且 `has_more=true`，这不是消息丢失的证明。

## 第二阶段：受控执行证据

这一阶段没有付费模型和用户凭据。替代层只写在每一项下面。报告那次运行的 snapshot 和 SHA 仍然不可得，不能倒推那次进程的版本。

### D2 执行唤醒

入口是生产 `AgentOrchestrator.spawn_agent`：注册 spawn、写 request、调用 spawn executor。执行器用生产 `SessionProcessor._process_step` 调真实工具函数。模型层是测试里的 `LLMStream.generate` 脚本，不调用供应商。history 用进程内 `AgentMessageBusPort`，父会话通过 `get_agent_history` 读取。

- echo：工具输出 `echo: ping`，history 是 request 然后 response，spawn 状态 `completed`。
- 5 步：`step_1` 到 `step_5` 串成 `step-5:...:start`，`tool_steps == 6`（5 次工具加最后文本）。
- 工具抛错：父 history 含 `failure_class=backend`，状态 `failed`。
- 工具先 `sleep(0.2)` 再返回，状态仍是 `completed`。这条路径没有无文本计时器。

未覆盖：插件代际准入、Ray actor、本地队列进程、`ProjectReActAgent.initialize`。模型脚本不可用不能当成这些层正常。父结束时显式 `detached: true` 的子运行跳过，已有 `test_agent_run_tool_settlement.py` 用 SQL snapshot 锁住，本阶段没有重写它。

### D1 三档同一 snapshot

`test_edit_reaches_sandbox_only_for_explicit_full_access` 用 `chat_guard_case` 写入 SQL run authority。`ask` 的决定是 `ask`，`automatic` 是 `deny`，只有 `full_access` 调用 sandbox `call_tool`。守卫的 `mode` 等于写入的档。`edit` 重映射没有让非 full 档执行沙箱写。子运行伪造 `full_access` metadata 仍被 `test_permission_provenance_v2.py` 拒绝。没有把报告那次不可得的 snapshot 写成某个提交。

### D4

`_build_service` 接上真实 `AutomationCommandService` 和测试库。同一幂等键创建两次得到同一个 job，`list_jobs` 能看见它，`CronJobRunModel` 行数是 0，然后按 revision 删除。没有注册 APScheduler，也没有创建 Grok Bot routine。调度器真实执行没有做，不能叫自动化已恢复。

### D3

`openapi_for_published_generation` 只返回 descriptor 完全相同的已发布表。`system_api` list 通过这个函数看到 `/api/value`。另一代仍是 `route_generation_unavailable`。没有启动完整 API 进程。

### D5

本地 wheel `fixturepkg` 装进显式 workspace venv，该 venv 的解释器能 `import fixturepkg`。系统 `sys.prefix` 不是这个 venv。工作区外的 wheel 被拒绝。没有 chmod，没有访问 Mac 上的 `/opt/sandbox-mcp-venv`。

### D7

双份 `pkg` 与 `src/pkg` 时，执行导入的 `__file__` 是 `src/pkg/service.py`，值是 `requested`。只有 `src/pkg` 时模块名仍是 `src.pkg.service`，`__file__` 是那一个文件。覆盖率 pytest 的 cwd 改为 import root，避免工作区根上的同名包抢先。

### D6 / D8

没有新增读取 `os.environ` 来回答 `get_env_var`。托管秘密的 `redacted_preview` 是 `***`，已授权读取仍返回原值，日志测试继续禁止明文。`ANTHROPIC_API_KEY` 对 github 仍是 `not_declared`。

## 这一轮实际跑过的测试

- `uv run pytest` 上述新测试，加上 `test_execution.py`、`test_sandbox_mcp_rules.py`、`test_rules_enhanced.py`、`test_system_api_tool.py`、`test_env_var_tools.py`：修复后 15 + 4 + 原套件通过。最终相关集合在提交前为 175 项里先有 3 个断言失败，修正 mock 和 frozen dataclass 后再跑新测试通过。
- `test_cron_tool.py` 与 `test_route_generation_unavailable.py`：11 passed。
- `cd sandbox-mcp-server && PYTHONPATH=. uv run pytest tests/tools/test_deps_install_target.py tests/tools/test_module_origin.py tests/tools/test_deps_install_failure.py`：8 passed。
- 没有改 compose 的 wall p95 100ms 门禁，CPU 仍只是诊断字段。没有跑完整 CI，也没有创建定时跟踪去等 CI。
