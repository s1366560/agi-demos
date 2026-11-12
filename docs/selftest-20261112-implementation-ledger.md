# 2026-11-12 自测实施核对清单

口径保持原报告：81 行结果，35 PASS / 4 FAIL / 4 PARTIAL / 38 UNAUTHORIZED；记录到的工具调用 201；报告自称 72；夹具覆盖 10 测试 / 67 语句 100%，只覆盖 `/workspace/src/pkg`。`not_tested=0` 不是全量覆盖。38 项 UNAUTHORIZED 是 `read_only` 拒绝，不是实现失败，本轮没有扩大权限。

会话 `cd9755fd-39f1-4485-8a96-77d3234179e0`，主运行 `fcb999ea-248d-48af-8b81-e2fcdecd7f7f`，权限档 `read_only` / `ask`。子运行 `c9137e8a`、`58784810` 仍按原指示保留，没有在本轮停止。

## F01 聊天授权披露

- 现象：拒绝文案没有写出当前档，界面容易把 build 模式当成可写。
- 复现：`format_chat_tool_denial` 在未绑定守卫时返回 `permission_mode=unbound`；`ask` 映射 `read_only`。
- 根因：拒绝文本原先只有“Chat run does not authorize this operation”。build 模式不是工具授权。
- 变更：PR #18 已写入结构化拒绝。本轮补了 `canvas_create` 在 `ask` 下显示 `permission_profile=read_only` 的测试。
- 回归：`uv run pytest src/tests/unit/application/services/test_chat_tool_denial_message.py src/tests/unit/agent/tools/test_session_status_tool.py src/tests/unit/infrastructure/agent/tools/test_session_status_runtime.py -q`，包含在本轮 276 passed 中。
- 边界：没有把 build 聊天改成可写，没有打开 38 个工具。空会话视图仍不硬塞权限行。

## F02 grep 嵌套 glob

- 现象：`*.py` 漏掉子目录。
- 复现与根因：无 `/` 且无 `**` 的 glob 只匹配单段路径。`class` 命中 `dataclass` 是子串，不是 glob 缺陷。`\w` 已与嵌套 glob 分开测。
- 变更：PR #18 已按文件名匹配。本轮重跑 sandbox 文件测试。
- 回归：`cd sandbox-mcp-server && uv run pytest tests/tools/test_file_tools.py tests/tools/test_deps_install_failure.py -q`，21 passed。
- 边界：没有改正则引擎。

## F03 子运行关闭

- 现象：父运行结束后，非显式 detached 的子运行和工具行仍是 running。
- 根因：结算没有关闭挂接子运行。10:00:17 的 stop 只点名已经结束的 `340d35e0`，不能说它停了 10:00:26 的子运行。
- 变更：PR #18 的 `close_attached_child_runs` 跳过 `authorization_snapshot.detached is True`。
- 回归：`test_agent_run_tool_settlement.py` 含在 276 passed 中。
- 边界：只保留显式 `detached: true`。没有新增第二套 detached 语义，也没有停止用户原来的孤儿子运行。

## F04 供应商余额 / 限流

- 现象：Zai `Insufficient balance` 走了通用 `LLM stream error`，父运行继续多次模型调用，且没有说明未切换供应商。
- 复现：`classify_provider_failure(RuntimeError("RateLimitError: Insufficient balance or no resource package"))`。
- 根因：通用异常只用类型名。余额不足仍命中重试正则里的 `rate limit`。
- 变更：余额或资源包不足的稳定字段是 `failure_class=balance`、`code=vendor_balance`，不重试。真正的限流是 `failure_class=rate_limit`、`code=vendor_rate_limit`，仍可重试。错误事件带 `provider_failover=not_authorized`。`resolve_provider_after_failure` 即使测试传入已授权的备用名，也返回当前供应商。
- 回归：`uv run pytest src/tests/unit/infrastructure/agent/core/test_provider_failure_class.py -q`，2 passed。
- 边界：没有实际切换供应商，没有购买额度。初始化时缺少配置而落到本地 ollama 的路径没有在这次失败分类里调用。

## F05 历史读取 / 重开

- 现象：`public.messages` 为 0 被怀疑成历史丢失。
- 反证：`GET /conversations/{id}/messages` 的 `get_conversation_messages` 调用 `get_events`，读取 `agent_execution_events`。空消息表不是父会话丢失。
- 变更：路由仍读事件流。桌面旅程探针在历史响应含 `timeline` 时记录 `load-history`，不读取 `public.messages`。
- 回归：`node --test agi-stack/apps/desktop/tests/agent-workspace-journey-authority.test.mjs`，14 passed。其中云端探针的 `conversation-lifecycle` 包含 `load-history`。
- 边界：这是自动化探针，不是在浏览器里点击重开会话。桌面窗口本轮另行按官方入口启动，不能把该探针写成点击验证。

## F06 任务完成时间

- 现象：完成后 `completed_at` 为空。
- 根因：完成写入没有补缺失时间。
- 变更：PR #18 只在状态变为 completed 且调用方和时间都缺失时补齐。进行中更新不带该字段。
- 回归：`test_todo_tools.py` 含在 276 passed。
- 边界：不改历史任务的已有时间。

## F07 memory category

- 现象：`category=preference` 仍混入知识图谱的 `fact`。
- 复现：图谱追加固定 `category=fact`。本轮测试让 preference 检索若调用图谱即失败。
- 根因：图谱结果没有按请求类别过滤。
- 变更：只有 `category` 为空或 `fact` 才查图谱，之后按类别精确过滤。响应带上请求的 `category`。
- 回归：`test_memory_category_filter.py` 含在 276 passed。
- 边界：没有改图谱存储里的类别标签。

## F08 技能清单

- 现象：报告称提示词写死了 7 个技能，loader 不一致。
- 反证：`SystemPromptManager._build_skill_section` 只输出 `status=active` 的名称。传入 inactive 的 `darwinian-evolver` 不会出现。loader 未命中时返回 `Available skills:`。
- 变更：新增反证测试，没有改提示词清单。
- 回归：`test_skill_section_matches_loader.py` 含在 276 passed。
- 边界：没有核对线上租户当时的技能库内容。

## F09 request_env_var

- 现象：字符串 `context` 被拒绝，看起来像工具坏了。
- 根因：schema 是 object，字符串拒绝是正确校验。
- 变更：描述已写明字符串会被拒绝。本轮测试字符串返回 `Invalid context payload`，对象通过校验。
- 回归：`test_request_env_var_context.py` 含在 276 passed。
- 边界：没有放宽成接受字符串。

## F10 system_api 路由表

- 现象：`HTTP route table is unavailable for the pinned plugin generation`。
- 反证：`RouteTableRegistryV2.resolve` 在该代没有 staged 表时抛 `route_generation_unavailable`。这是未发布代的失败关闭，不是路由功能缺失。
- 变更：新增未发布代测试。没有为了变绿去发布路由。
- 回归：`test_route_generation_unavailable.py` 含在 276 passed。
- 边界：没有复现当时那一次 pinned generation 的现场数据。

## F11 cron

- 现象：add 失败；status 用 `jobs`，list 用 `items`。
- 根因：手动运行已有回执、修订和幂等命令；创建、更新、删除和切换仍在 `CronJobService` 里直接拒绝。
- 变更：创建改走 `AutomationCommandService.create_job`。同一幂等键重放同一 job，不同内容冲突。任务行、回执和 `record_create` 操作在同一事务写入，操作状态是 `succeeded`，不会被执行队列当成 pending 再跑。status/list 仍同时给出 `jobs` 和 `items`。更新、删除、切换和手动执行仍失败关闭。HTTP 创建要求 `idempotency_key`，能力声明 `create.allowed=true`、`reason_code=durable_command`，`durable_execution` 仍是 false。
- 回归：`uv run pytest src/tests/unit/infrastructure/adapters/secondary/persistence/test_sql_cron_automation_command_repository.py src/tests/unit/application/services/test_cron_service.py src/tests/unit/infrastructure/agent/tools/test_cron_tool.py src/tests/unit/routers/test_cron_router.py -q`。持久创建测试写入名为 `selftest-followthrough-temporary` 的任务，新的 repository 实例能读回，其他 project 列表为空，最后按该 job id 删除任务、操作和回执。
- 边界：测试库事务会回滚；清理只按本次 job id。没有改用户已有定时任务，也没有调用正在运行的 API 去创建。调度器执行仍不可用。`cron_services.py` 的产物摘要已用 `scripts/generate_plugin_protocol_v2.py --refresh-artifacts` 刷新。

## F12 Canvas / A2UI

- 现象：read_only 下全部 UNAUTHORIZED。
- 可测部分：`ask` 档对 `canvas_create` 的拒绝保持 `permission_profile=read_only`。已授权的渲染模型能把 v0.8 JSONL 变成 `status=ready` 的表面，标题文本是 `Release approval`，增量更新会替换组件。
- 变更：没有放宽工具权限，也没有绕过拒绝去调用工具。
- 回归：`node --test agi-stack/apps/desktop/tests/a2ui-surface-model.test.mjs`，7 passed。拒绝文案测试仍在 `test_chat_tool_denial_message.py`。
- 边界：通过的是表面模型和权限拒绝，不是 Electron 里打开 Canvas 后的像素。`A2UIViewer` 的真实画面需要父任务在桌面会话中打开含 A2UI 的消息。预期：表面显示 “Release approval”，允许的动作来自持久化 allow-list；`ask` 档直接调用 `canvas_create` 仍被拒绝。

## F13 MCP 版本文档

- 现象：报告担心文档写成 SDK 2.x / `mcp==2.3.0`。
- 反证：仓库 `.memstack/skills/mcp-builder/scripts/requirements.txt` 是 `mcp>=1.1.0`，没有 `mcp==2.3.0`。本机已安装 `mcp 1.25.0`，`mcp.server.fastmcp` 可导入。`fastmcp` 独立包未安装。
- 变更：新增 pin 反证测试。没有改文档。
- 回归：`test_mcp_skill_version_pin.py` 含在 276 passed。`uv run python -c` 打印 `mcp 1.25.0`。
- 边界：CI 环境的安装版本可能不是 1.25.0；契约只锁定仓库 pin。

## F14 安装环境限制

- 现象：pip 写 `/opt/sandbox-mcp-venv` 出现 `Errno 13`。
- 根因：目标目录不可写，不是包缺失，也不是工具未授权。
- 变更：stderr 含 `Permission denied` 或 `Errno 13` 时前缀 `environment_not_writable`。没有 chmod，也没有改 `/opt/sandbox-mcp-venv`。
- 回归：`cd sandbox-mcp-server && uv run pytest tests/tools/test_deps_install_failure.py -q`，3 passed。其中一项把临时目录收成只读后真实写入，捕获操作系统的 Permission denied，再分类，并在 finally 里恢复目录权限后由临时目录删除。
- 边界：这是隔离临时目录，不是容器里的 `/opt/sandbox-mcp-venv`。没有对用户沙箱执行 pip。

## F15 browser bridge

- 现象：启动日志有 `bridge.sock` `ECONNREFUSED`，主窗口仍起来。
- 反证：`iab-backend-reconnect.test.mjs` 对不可达 socket 记录 `iab bridge connect failed`，失败连接不会打开后的 onClose，也不留下活句柄。
- 变更：没有改启动路径。
- 回归：`node --test agi-stack/apps/desktop/tests/iab-backend-reconnect.test.mjs`，7 passed。
- 边界：本轮桌面进程不在 `:5173`，没有为这项重启 Electron。

## F16 取消 IPC

- 现象：用户取消被记成 handler 异常 `cloud request was cancelled`。
- 根因：`abort()` 的拒绝发生在 IPC `await`，套在 `abort()` 外的 try 接不住监听器里的异步抛出。
- 变更：`settleCloudRequest` 包住 `cloud_request` 的 await。明确取消返回 `{cancelled: true, kind: 'cancelled'}`。超时和 `vendor_balance` 继续抛出。成功结果原样返回。
- 回归：`node --test agi-stack/apps/desktop/tests/cloud-request-cancel-class.test.mjs`，3 passed。
- 边界：这是 IPC 边界函数的集成，不是在 Electron 窗口里点击停止。点击验证需要父任务在桌面会话中发起云请求后取消。预期：取消返回 cancelled，超时仍是错误，其他异常不被吞掉。

## F17 报告口径

- 现象：Markdown 把 grep 算了两次 FAIL，把 `request_env_var` 标成 PARTIAL，把 `memory_search` 标成 PASS；JSON 分别是 FAIL。实现层评级 A 和“被拦工具都用 bash 复现”不成立。
- 变更：本清单保留 35/4/4/38、201、72、81 和夹具 10/67。没有发布新的自测运行。
- 边界：这是口径记录，不是新的产品统计接口。

## F18 异步索引

- 现象：检索看不到处理中的记忆，容易当成丢失。
- 根因：`memory_get` 已能返回 `processing` / “indexing has not completed yet”；检索结果原先不带 `processing_status`。
- 变更：检索条目在块对象带有 `processing_status` 时原样返回。没有把异步索引改成默认同步等待。
- 回归：preference 检索测试断言 `processing_status=PENDING`，含在 276 passed。
- 边界：没有等待真实索引完成，也没有宣称数据丢失已修复。

## U01 实际权限档

- 变更：拒绝和 `session_status` 显示 `permission_mode` / `permission_profile`。空视图不补假行。
- 回归：见 F01。
- 边界：没有视觉重设计，也没有在浏览器里点开会话栏。

## U02 最后活动

- 变更：`SpawnRecord.last_activity_at` 在状态更新时写成当前时间；缺省时读取回到 `created_at`。`agent_sessions` 输出该字段。
- 回归：`test_spawn_record.py`、`test_spawn_manager.py`、`test_redis_spawn_manager.py` 含在 276 passed。
- 边界：这是状态更新时间，不是语义上的 stalled 判定。

## U03 停止反馈

- 变更：`agent_stop` 结果增加 `requested_session_id`，并继续返回实际 `stopped_sessions`。空列表仍表示点名对象已经结束。
- 回归：`test_agent_tools.py` 含在 276 passed。
- 边界：不会把未纳入级联的兄弟运行停掉，也不会把它们伪装成已停止。

## U04 可行动错误

- 变更：余额错误、安装不可写、工具拒绝都带稳定前缀和原因。没有新增视觉组件。
- 回归：见 F04、F09、F12、F14。

## U05 报告可观测

- 变更：本文件。没有新的自测报告生成器。

## 本轮命令

- `uv run pytest` 上述 Python 文件：276 passed。
- sandbox 文件与安装分类：21 passed。
- 桌面取消分类：2 passed。IAB 不可达桥：7 passed。
- `uv run pyright --level error` 对 11 个改动生产文件：0 errors。

## 第一阶段边界复核

- F01：`test_chat_run_tool_permission_boundary.py` 在刷新 `cron_services.py` 产物摘要后 17 passed。普通 ask 聊天在声明写入前仍要确认，权限档保持 read_only。
- F03：`test_agent_run_tool_settlement.py` 仍通过。显式 detached 不关闭，挂接子运行在父结束后取消。

## 仍未落地

- build 聊天是否可写：保持当前档，不扩大。
- 除 `detached: true` 以外的正式 detached：保持现有跳过规则。
- 备用供应商：分类函数不切换。没有把余额失败接到初始化时的 ollama 回退。
- cron 的更新、删除、切换和手动执行仍不可用。创建不会启动 durable execution。
- 浏览器点击重开、Electron 点击取消、A2UIViewer 像素、容器内 pip：自动化探针已做，点击和像素未做。

## 本轮桌面启动

先前 `:5173` 没有监听。`agi-demos-desktop` 会话里的上一次 `make -C agi-stack run-desktop` 已停在 `Electron desktop startup failed Error: sidecar stopped`。本轮在同一会话重新执行官方入口，没有重启 PID 39283 的 Web `:3000` 和 PID 39304 的 API `:8000`。

当前证据：渲染器 `http://127.0.0.1:5173/` 返回 200，监听进程是 electron-vite PID 44242，Electron 主进程 PID 44257。日志有一条非致命的 `iab bridge connect failed ... ECONNREFUSED ... bridge.sock`。没有截图。父任务若要做点击验证：打开桌面里的一条含 A2UI 的会话，预期表面文本为模型测试中的 `Release approval`；对云请求点取消，预期结果是 `{cancelled: true, kind: 'cancelled'}`，超时仍报错。
