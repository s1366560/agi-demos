# 插件市场收尾验收（2026-09-23）

仓库示例插件及自有 OAuth 服务范围内的本轮收尾验收已完成。双端真实模型、
App 渲染、停用与卸载均已实测；签名 V2 与外部服务的具体覆盖边界另列如下。
没有自动提交代码，未改动其他部署环境。

## 当前原生验收状态

- 再次检查磁盘（175 GiB 可用）并通过规范 Make 入口重建、恢复同一隔离 profile。
  切换 Electron 为全屏后，画面、下拉选项及键盘交互恢复。
- 自有 OAuth 服务重新授权成功。真实 Kimi 模型按批准计划加载 Skill，并调用 Demo
  和受保护 OAuth echo；两个工具实际返回 `MARKETPLACE_NATIVE_MODEL_OK`，持久调用
  记录均为 `completed`。结果保存在 `native-model-tools-results.json`。
- 通过真实原生界面从独立本地来源安装 Native Update Demo 1.0.0，成功更新到 2.0.0。
  3.0.0 候选实际 MCP 初始化失败，界面报告 JSON-RPC 错误，原 2.0.0 保持启用，
  再次可用性验证成功。未修改仓库示例源；截图与只读结果分别为
  `marketplace-native-update-rollback.jpg`、`native-update-readback.json`。
- Hook 持久审计已在新的真实模型会话中确认 `session_start`、`before_request`、
  `after_tool_execute` 三类事件成功；诊断管道与隔离测试边界见文末。
- 原生 App 事件已接入实际 MCP 调用，工具和资源共用同一代租约。实际验收发现并
  修复沙箱静态页缺失：仅开放固定 HTML 的精确路径，API 仍受鉴权保护。
  重建后 Demo、更新 2.0 和受保护 OAuth App 均在真实 Electron 双层 iframe 中渲染；
  截图为 `marketplace-native-demo-app-rendered.jpg`、
  `marketplace-native-updated-app-rendered.jpg`、`marketplace-native-oauth-app-rendered.jpg`。
- OAuth 真实模型运行 `abf0ecc3-df21-5768-b078-421c22d71e7c` 调用返回
  `MARKETPLACE_NATIVE_OAUTH_FINAL_OK`，运行已完成；跨重启保留的 vault 授权经刷新
  读取受保护 App。记录为 `native-model-oauth-results.json`。
- 三个插件通过原生界面停用后，新会话 `657614fd-6888-53e5-8192-c622780f3ca7`
  实际加载 Skill 被拒绝，三个精确 MCP 工具均未提供。随后全部卸载，新会话
  `86a546c7-19d5-58fc-af6d-6f2a2823d449` 得到相同结果；两次模型运行正常完成。
  记录为 `native-model-disabled-results.json`、`native-model-uninstalled-results.json`。
- 更新示例实际模型工具返回 `NATIVE_UPDATE_V2 MARKETPLACE_NATIVE_FINAL_OK`。
  该多步骤运行后续遇到模型 45 秒超时，完整运行不计成功；已完成工具与 App 结果
  保存在 `native-model-app-results.json`，后续独立 OAuth 与负向运行均正常完成。
- 卸载后所属 MCP、Apps、代际记录、租约及插件 vault 记录为零，两个 Skills 为
  deleted，活动快照删除。历史 OAuth 回执残留已修复；规范重启自动清理三条旧回执，
  再全新安装、真实授权、启用、卸载后，回执及服务授权元数据也立即归零。
  记录为 `native-oauth-restart-cleanup.json` 和 `native-oauth-cleanup-retest-after.json`。
- 最终原生实例、OAuth fixture 及任务浏览器标签已关闭，常规 API 8000 健康 200。
  `native-qa-service-cleanup.json` 记录 18891、18000、3001、5173 均不再监听。
  备份、截图、隔离 profile/workspace 保留。

## 已验证

- 签名 V2：真实 PostgreSQL、两个租户及多个项目的安装、发布、停用、恢复、
  卸载隔离通过；实际 Wasmtime 调用使用签名包，旧调用可以完成。
- OAuth：自有授权服务覆盖 PKCE、资源绑定、回调单次使用、取消、刷新、
  跨作用域拒绝及专属凭证清理。Web 与 Electron 均完成过真实浏览器授权回调；
  Electron 已显示已连接并启用。此结论不涵盖第三方授权服务。
- Web：真实安装页显示 Demo 和 OAuth 插件均已启用，OAuth 状态已连接；
  已在真实会话画布的隔离 iframe 中分别渲染示例 App 与受保护 OAuth App。
  截图保存在 `artifacts/plugin-marketplace-20260923/`：
  `marketplace-web-live-oauth-enabled.jpg`、`marketplace-web-model-app-rendered.jpg`、
  `marketplace-web-oauth-app-rendered.jpg`。
- OAuth 真实模型会话调用返回 `MARKETPLACE_OAUTH_MODEL_OK`；从该工具结果的
  “打开应用”按钮进入画布，受保护 App 实际渲染成功，截图
  `marketplace-web-oauth-model-app-rendered.jpg`。模型文本称“没有 App”的描述与
  实际工具事件、按钮及渲染结果不符，未用于验收判断。
- 云端真实模型已加载 `plugin-demo`，经权限确认调用示例 MCP 返回
  `MARKETPLACE_CLOUD_MODEL_OK`，三个 Hook 均有成功记录，App 事件包含实际 HTML。
  HTTP MCP 授权头修复后，OAuth 工具发现、调用及受保护 App 读取均已实际通过；
  任务 sandbox 使用仓库 MCP manager 包，没有替换其他部署的镜像标签。
- 已通过真实 Web 停用 Demo 与 OAuth 插件；安装卡片均显示已停用，App 入口显示
  “暂无可用 MCP 应用”。截图为 `marketplace-web-disabled.jpg` 与
  `marketplace-web-disabled-app-menu.jpg`。修复 Skills 运行时授权检查后，新会话
  `7de5d41e-4730-4eb6-8ce6-fd5ba08ce563` 实际调用 `skill_loader` 返回
  `Plugin skill is disabled or unavailable`，两个精确 MCP echo 均未提供；
  事件保存在 `cloud-model-disabled-results.json`。
- 两插件均已通过 Web 卸载，安装列表为空，截图 `marketplace-web-uninstalled.jpg`。
  只读检查该测试项目的 Skills、MCP 服务、Apps、两个安装的运行快照登记及专属
  OAuth 记录均为零；配置已删除，安装历史保留为 `uninstalled`。
  检查结果保存在 `cloud-uninstall-resource-cleanup.json`。
- 卸载后的新会话 `11453112-36ad-44f0-b354-e982a73f1637` 实际加载 Skill 被拒绝，
  两个精确 MCP echo 均未提供，事件保存在 `cloud-model-uninstalled-results.json`。
  模型额外请求的 bash 目录探查已拒绝；未批准未知工具或创建替代服务。
- 快照：真实 PostgreSQL 锁、慢进程、最后租约释放、删除失败重试和崩溃后保留
  活动进程目录通过；启动恢复使用已有项目 sandbox，不创建新 sandbox。
- 历史清理：仅删除一个已撤销的第三方目录记录及一个已撤销授权，退役两个旧
  会话作用域引用。未删除文件、共享缓存或业务数据。精确备份位于
  `artifacts/plugin-marketplace-20260923/legacy-cleanup/`。
- 本地原 API 已优雅停止并通过 `make dev-backend` 恢复，健康检查返回 200。
- 云端任务环境已收尾：通过项目 sandbox 接口终止唯一 QA sandbox（HTTP 200，
  后续查询 404，容器已退出），随后停止任务 API 18000 与 Web 3001。
  未使用的任务镜像 `marketplace-qa-20260923:runtime` 已删除；无任务浏览器标签残留。
  常规 API 8000 保留。此前原生实例和 OAuth fixture 的停止记录属于中间收尾，
  随后的验收曾重新启动二者；最终已再次关闭，以最新
  `native-qa-service-cleanup.json` 为准。
  精确记录见 `cloud-qa-service-cleanup.json`；项目数据、截图、备份与目录配置保留。
- Electron 使用隔离 profile/workspace，由 `make -C agi-stack run-desktop` 构建并
  启动，随后使用同一 profile 重建并重启。已验证本地市场安装不依赖云端登录，
  以及 Kimi 环境凭证连接测试、模型发现和默认模型选择。

## 回归测试

- 原生 MCP App 接线：12 项 Rust MCP 回归通过，包含真实 stdio 调用生成 HTML
  事件、敏感输入脱敏、版本切换窗口内旧代 App 读取、资源失败保留原工具结果；
  画布事件与隔离生命周期 11 项测试通过。实际 Electron App 渲染仍单独验收。
- 真实慢 App `resources/read` 跨卸载回归 1 项通过：读取已开始且未完成时执行
  卸载，旧 HTML 文件保持可读，新 Apps/服务入口消失；读取成功返回后，最后
  catalog 租约释放才回收旧文件和服务。
- 原生固定 iframe 启动页路由回归 1 项通过：仅 `/static/sandbox_proxy.html`
  可匿名读取固定 HTML，API 和其他静态路径仍返回 401，POST 返回 405；既有
  HTTP/WebSocket 启动能力鉴权回归 1 项通过。未放宽 API 会话鉴权。
- 最终 Python OAuth、统一安装服务、格式解析、Hooks、快照、恢复、日志脱敏及
  MCP 边界组合：116 项通过（以下定向组与此组合可能重叠，不相加计数）。
- 启动恢复与作用域边界：7 项通过，包括真实运行时 provider 和 SQL 服务。
- 会话数据库上下文与 Hooks：43 项定向测试通过，覆盖实际运行时 provider、三个
  Hook 事件、取消释放及 Hook 失败终止操作；云端真实模型复验已通过。
- OAuth 回调日志脱敏：5 项通过，覆盖默认 Uvicorn 访问日志的 code/state 参数。
- V2 作用域组合：85 项通过；随后会话恢复 22 项及路由 8 项定向测试通过。
- Sandbox HTTP MCP 与后端发现：分别 41 项、26 项通过。
- OAuth 定向组 18 项通过，包含真实刷新令牌旋转后启用/更新失败、提交后再次刷新，
  以及旧失效授权存在时再次授权的轮询状态。安装服务 19 项通过，包含只恢复安装自有
  App、保持其他插件 App 停用的回归；这些组与前述组合存在重叠。
- 模型 MCP 声明及权限确认边界：52 项通过；多服务发现配对组合 18 项通过
  （与前一组有重复，不相加作为唯一测试总数）。
- Desktop marketplace 最终 Rust 定向组 25 项通过；此前 MCP 回归 29 项通过。
  Web/desktop OAuth 界面
  16 项、桌面入口路由 7 项通过。双端 TypeScript 检查通过。

## 验收覆盖边界

- 原生隔离 profile 未配置签名 V2 信任密钥，界面正确拒绝安装；本轮未实操原生
  签名包 UI 安装链路。签名 V2 的真实 PostgreSQL、多作用域及 Wasmtime 验收，
  与原生签名生命周期测试分别证明各自范围，不宣称每种格式均双端 UI 全覆盖。
- OAuth 实测使用仓库自有授权与受保护 MCP 服务，结论不涵盖第三方服务配置。
- 慢 Hook、MCP、App 读取、进程死亡及崩溃恢复由真实进程集成测试覆盖；原生
  窗口覆盖正常重启、更新回退及完整卸载，不宣称所有崩溃窗口均经 GUI 注入。
- `native-model-partial-results.json` 及多步骤模型超时记录保留为中间结果；最终
  OAuth、停用和卸载后模型运行均正常完成。未运行全仓测试，类型检查范围见下文。

修改以直接调用关系、定向测试和实际运行结果核对。没有自动提交代码。

## 云端 Python 最终定向核对

以下组合在上述真实停用及卸载验收后重新运行，46 项通过。覆盖实际 HTTP OAuth
过期令牌刷新后的模型工具发现、失败服务不改变其他服务的工具归属、模型 MCP 显式
权限声明、旧缓存与新 SkillLoader 均拒绝停用及卸载的插件技能，以及签名 V2
作用域生命周期和本地历史清理防护。此组合与前述测试重叠，不叠加计算总数。

```bash
uv run pytest \
  src/tests/unit/application/services/test_marketplace_agent_discovery.py \
  src/tests/unit/application/services/test_marketplace_skill_runtime.py \
  src/tests/unit/infrastructure/mcp/test_marketplace_tool_declarations.py \
  src/tests/unit/infrastructure/agent/tools/test_skill_loader_runtime.py \
  src/tests/unit/infrastructure/agent/state/test_parallel_mcp_discovery.py \
  src/tests/unit/infrastructure/agent/state/test_parallel_discovery_timeout.py \
  src/tests/unit/infrastructure/plugins/v2/test_agent_turn_requirements_v2.py \
  src/tests/unit/application/services/test_marketplace_signed_scope_v2.py \
  src/tests/unit/application/services/test_marketplace_legacy_cleanup_v2.py -q --tb=short
uv run python scripts/generate_plugin_protocol_v2.py --check
```

签名产物生成器检查通过。上述运行入口、声明、相关测试及 V2 清理模块的定向 Ruff
检查通过。扩大 Pyright 检查到 MCP/Skill、V2 作用域及清理模块后，结果为
0 errors、82 warnings；警告主要涉及动态 SQL/JSON 类型、可空值及未使用返回值，
并包含 SkillLoader 的既有警告。因此未宣称全仓类型检查或零警告通过。

此前实际 PostgreSQL 隔离测试使用下列命令，通过一个真实签名 WASM 集成场景，
涵盖两个租户、多项目、运行器重启及 SQL 授权。测试创建隔离 schema 并在结束时
清理该 schema，不复用验收项目，也不打印数据库连接信息；本轮最终检查未重复运行。

```bash
uv run python - <<'PY'
import os
import pytest
from src.configuration.config import get_settings

os.environ["PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL"] = get_settings().postgres_url
raise SystemExit(pytest.main([
    "src/tests/integration/test_signed_marketplace_scopes_postgres.py",
    "-q", "--tb=short",
]))
PY
```

覆盖边界：OAuth HTTP 回归使用仓库自有服务，不能替代第三方服务客户端配置验收；
Skill 回归证明当次已读取的内容快照保留及下一次调用拒绝，不将技能文本读取等同于
外部资源的长时进程租约。最终定向检查没有运行全仓测试，也没有启动或停止服务。

## Desktop Hooks 审计与快照测试边界

Electron 的 `sidecarSupervisor` 丢弃通用 sidecar stderr，因此早期只增加 tracing
无法为实际模型运行提供持久 Hook 记录。该诊断缺口已经修正：新的规范 Make
二进制在真实模型会话中记录了 `session_start`、`before_request`、
`after_tool_execute` 三个成功事件。早期缺日志不再作为当前未完成项。

项目作用域 `plugin-marketplace-v3/<scope-hash>/hooks-audit.jsonl` 仅保存
`timestamp_ms`、`installation_id`、`plugin_id`、`version`、`event`、
`success`、`latency_ms` 七个字段，不保存命令、事件输入或子进程输出。
文件使用私有权限并同步写入，达到 1 MiB 后保留一个 `.previous.jsonl` 文件；
拒绝符号链接目的地。通用 stderr 仍不转发。

最终桌面市场 Rust 定向组 **25 项通过、0 失败**，包含持久化三类事件和失败结果的
字段白名单、日志轮转、符号链接拒绝，以及既有 OAuth、更新和租约测试：

```bash
cargo test -p agistack-desktop-sidecar plugin_marketplace_v3 \
  --manifest-path agi-stack/Cargo.toml -- --nocapture
```

新增的实际慢 Hook 测试分别在进程等待期间完成更新、卸载；确认旧目录一直保留，
释放进程后仍读取旧版本内容，最后租约释放才回收旧快照。既有异常退出恢复测试
启动独立进程持有 OS 文件锁，验证存活进程目录保留、进程被终止后可回收；
发布日志恢复与运行器重新打开测试同时通过。这些是隔离后端测试，不代表已在
Electron 窗口完成崩溃或卸载交互验收。原生更新与失败保留旧版本已由实际界面另行
验证；最终 App 渲染、停用和卸载也已通过真实原生界面及新模型会话验证。

直接调用核对范围为 Hooks 捕获、模型请求包装器及工具执行包装器。

### Native 卸载后只读存储核对

本轮通过 UI 卸载三项安装并结束原生进程后，以 SQLite `mode=ro`、
`query_only=ON` 检查隔离 profile：这些安装所属 MCP server、App、generation、
snapshot lease 均为 0；作用域内 MCP credential binding/cleanup 均为 0；
两个插件技能记录均为 `deleted`。Vault 仅查询记录键前缀的数量，OAuth grant、
binding、remote/stdio credential 均为 0，没有读取密文、令牌或主密钥。
三个活动安装快照已删除；剩余一个失败 3.0 更新的预检快照属于 24 小时缓存。
Hook 日志保持 68 条，最后为 2026-09-23 12:53:54.288+08，停用卸载后没有新增。

此前发现已卸载记录残留三个 OAuth 幂等回执和历史 `connected` 状态；
修复加入正常卸载及启动恢复的安装归属清理，并在回放 OAuth 回执前检查安装
仍存活。现已完成真实原生复验：规范 Make 重启清理旧回执，新安装通过系统
浏览器授权后再经 UI 卸载。最终只读检查四个安装均为 `uninstalled`、
`oauth_services` 均为空、OAuth 回执为 0；四个安装所属 MCP、Apps、generation、
快照/调用租约、凭证绑定与专属 vault 记录均为 0，活动快照均已删除。
仅剩失败 3.0 候选的预检缓存，属于既定 24 小时过期策略。
证据：`artifacts/plugin-marketplace-20260923/native-uninstall-final-resource-cleanup.json`。
