# 插件源码导航

先按用户要完成的业务找目录。每个业务目录有自己的发布入口。签名归档中的贡献声明决定该版本实际交付的工具、命令、页面和权限。一个包可以有多个模块、进程和执行目标。独立对接外部服务、需要单独信任和撤销的集成，放在适配器目录。

| 业务包 | 已接入独立发布的能力 | 继续迁移的边界 |
| --- | --- | --- |
| [Agent](business/agent/README.md) | 同一个包拥有 ReAct 与 SessionProcessor 的实现、循环控制、会话重命名、云端流式对话、取消、P5 只读回放、Skill 校验、审阅 SubAgent 和会话执行统计 | 聊天传输、模型及实际工具调用仍通过已授权运行上下文 |
| [Knowledge](business/knowledge/README.md) | 一次发布包含记忆列表、详情、创建与修订、概览插槽、云端图投影和设备侧检索，设备单独授权 | 图存储、索引更新及检索管线 |
| [Workspace](business/workspace/README.md) | 项目概览、工作区创建、详情、改名、归档、目录和 CSV 导出 | 工作区协作、成员管理和项目视图 |
| [Automation](business/automation/README.md) | Asyncio 工作流引擎、签名工作流编辑、保存、执行、定时作业编辑与项目剧本读取 | 外部事件消费、Webhook 和已授权的持久化任务执行上下文 |
| [Environments](business/environments/README.md) | Sandbox 生命周期及 MCP 工具源码、隔离补丁计算、集群指标、项目 Sandbox 准备和按运行代授权终端 | 实例与部署所需的基础设施权限、Sandbox WebSocket 服务的配置 |
| [Billing](business/billing/README.md) | 报价、项目发票开具及列表、共享 React 发票表、租户用量和授权套餐变更 | 全量账务流程和租户配额接口 |

[模型适配器](adapters/models)分别对接 OpenAI、DeepSeek 和 Cohere。[渠道适配器](adapters/channels/feishu)负责飞书。发布者可以独立更新和授权各适配器。增加业务工具时，先定位持有数据及规则的业务包。增加模型厂商或渠道时，先检查账号凭据、网络出口和可撤销权限是否需要独立安装。通用设备授权在宿主；现有 Computer Use 的原生实现仍在桌面 Sidecar。

## 原有功能如何归组

下表给旧代码指定迁移目的地。表中的页面与服务仍可从原入口运行。迁移时同一业务的 API、页面、CLI、事件处理和数据变更一起移交，独立 worker 数量可随隔离需要调整。

| 在产品里看到的功能 | 归属及理由 |
| --- | --- |
| 登录、设备批准、租户与项目选择、邀请、角色、授权审计、插件中心 | 宿主维护访问主体、当前作用域、信任根、发布审批、撤权和恢复。这些操作在空项目也要可用。业务规则产生的决策理由与业务报表随对应包发布。 |
| 会话、模型调度、工具、计划模式、HITL、Canvas、Skill 演化、SubAgent、运行日志与用量统计 | Agent 管理同一次 run 的状态和行为。模型协议转换按厂商交给适配器，凭据读取走宿主授权。 |
| 记忆、实体、社区、图谱、图来源、增强搜索、图 schema、知识同步及存储后端选择 | Knowledge 管理从摄取、索引到检索的数据生命周期。嵌入与重排供应商按适配器授权。 |
| 工作区、成员协作、任务、黑板、计划节点、评审、交付与协作恢复 | Workspace 管理跨参与者的工作记录和事务。单次 Agent 执行的内部计划保留在 Agent。 |
| 工作流编辑与运行、定时作业、Webhook 触发、重投与死信处理 | Automation 持有自动化定义、执行记录和幂等语义。渠道回调验签与传输由该渠道适配器负责。 |
| 集群与资源池、实例、镜像与模板、部署、环境文件、沙箱、终端及设备能力 | Environments 管理资源配置、分配与生命周期。宿主提供受限进程与设备句柄；操作系统权限复核留在设备。 |
| 套餐、报价、发票、权益、账期和财务报表 | Billing 管理金额及计费语义。租户身份和配额写授权由宿主持有。 |
| 管理控制台、设置、通知与报表 | 由拥有操作和数据的业务包贡献相应页面。通用导航、凭据、通知投递与审计基础设施归宿主。 |

## 跨包调用和数据归属

| 调用 | 授权与数据流 |
| --- | --- |
| Agent 调用工具或适配器 | 宿主按项目与 run 固定工具版本和已批准权限。模型厂商授权、设备授权各自检查。 |
| Billing 调整租户配额 | Billing 计算套餐权益，租户服务持有配额写权限。项目发票使用按包、项目和租户限定的记录接口。 |
| Knowledge 处理数据 | 云端 worker 接收已准入的投影输入；设备 worker 接收当次检索提供的文档。发布版本共享，执行许可分别申请。 |
| Workspace 导出成员可见目录 | Workspace Core 根据实际成员关系筛选，业务 Wasm 对已授权的目录页做 CSV 转换。 |
| Automation 与 Environments | 调度器持有作业注册和派发，调度预览使用同一触发规则。环境包接收数值计算集群指标，凭据留在供应商集成端。 |

## 从请求读到业务代码

1. 从[最小宿主入口](../src/host/transport/package_kernel.py)进入。宿主的 [identity](../src/host/identity) 校验项目或设备主体，[packages](../src/host/packages)记录已批准的版本，[runtime](../src/host/runtime)管理执行租约，[operations](../src/host/operations)处理就绪与审计。通用签名归档、协议和代次实现仍在 [plugins/v2](../src/infrastructure/plugins/v2)。
2. 打开业务包根目录的 `package.json` 查看包身份、版本和执行目标。按其中的路径找到贡献声明、worker 或 Wasm。查看包内 `tests/` 的调用示例，然后跟到具体业务实现。含外部服务或启动完整宿主的集成测试还在 [src/tests/integration](../src/tests/integration)。
3. 使用各包 README 的构建命令签名。项目审批、独立升级、在途调用和回退的语义见[架构说明](../docs/architecture/independent-business-packages.md)。对实际部署选择运行 `python -m scripts.package_release_counts --trusted-key publisher.pub *.mspkg` 可以分别统计业务包、适配器、模块和制品。多目标包按一个安装身份计数，设备子归档及其内容纳入制品数。

完整 API 的兼容组合仍由 [production_bundle.py](../src/infrastructure/plugins/v2/production_bundle.py) 装配。迁移新的能力时，把规则、实现及测试移入所属业务目录，更新实际调用入口，再通过签名安装和业务调用检验发布边界。基础包整体替换前，旧适配层仍承担部分生产流量。

## 在空项目启用六个业务包

默认开发环境与 Helm 从空宿主首装六包。已有项目也可以使用下面的命令调整选择。各包可以来自不同发布者。按各包 README 构建，把本次选定的六个签名归档放入发布目录。以下示例使用 Billing 的报价版本；启用带有发票记录能力的版本时，还需要管理员批准该版本声明的存储权限。

```sh
memstack packages --tenant "$TENANT" --project "$PROJECT" inspect knowledge.mspkg
memstack packages --tenant "$TENANT" --project "$PROJECT" install \
  --approve tools.execute --approve subagents.register --approve agent.loop.drive \
  --approve graph.projection.compute --approve app.knowledge.memories.read --approve ui.slot \
  agent.mspkg knowledge.mspkg workspace.mspkg automation.mspkg environments.mspkg billing.mspkg
memstack packages --tenant "$TENANT" --project "$PROJECT" list
```

命令逐包验签、核对实际声明的权限并启用。中途失败时，CLI 显示已经启用的包，项目管理员可以从失败项继续。项目使用哪家模型、是否连接飞书、哪台设备可以执行检索，分别在选定适配器及设备授权时决定。


默认客户端从已签名的 `contributions.json` 读取路由与页面。开发业务功能时先找 `plugins/business/<包>/ui`。其中 `ui/web` 与 `ui/desktop` 也存放完整旧客户端仍在使用的视图和控制器。新增的共享页使用独立发布的 [页面 SDK](../sdk/memstack-plugin-sdk/src/pageRuntime.ts)。[Web 宿主](../web/src/projectPackages) 和 [桌面宿主](../agi-stack/apps/desktop/src/packageHost) 负责身份、作用域、页面装载和授权。

跨业务小组件也由所属包签名发布。Workspace 概览声明 `slots: ["recent-memories@1"]`。Knowledge 的最近记忆页面声明 `contributes_to: "memstack-workspace/recent-memories@1"` 和空路由。两包在同一项目启用后，宿主将组件挂入独立 iframe，使用 Knowledge 的摘要及权限读取数据。更换 Knowledge 版本无需重新构建 Workspace。

单独构建 Workspace 时，只需提供该包的发布输入和一个新的输出目录。带有 worker 的包另外传入对应的不可变 OCI 镜像引用，Knowledge 还需要设备 Wasm。

```sh
PYTHONPATH=.:sdk/memstack-plugin-sdk/src uv run python -m scripts.build_standard_packages \
  --package workspace --key "$PUBLISHER_KEY" --out "$RELEASE_DIR"
```

验证默认业务时，在独立目录执行 `STANDARD_DIRECTORY="$QA_DIR" MEMSTACK_DEV_PROFILE=standard make dev`。使用该实例的 Web 地址和目录执行下列测试。测试会在该项目内创建发票、安装签名版本并回退。

```sh
MEMSTACK_QA_STANDARD_DIRECTORY="$QA_DIR" MEMSTACK_QA_STANDARD_ORIGIN=http://127.0.0.1:3000 \
  uv run pytest src/tests/integration/test_standard_project_pages.py
```
