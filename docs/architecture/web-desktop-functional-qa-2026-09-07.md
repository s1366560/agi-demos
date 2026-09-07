# MemStack Web 与原生 Desktop 功能 QA 报告

日期：2026-09-07。起始基线：`main@88957e04d`；最终生产修复：`a79ea6c7b`；最终Desktop全量验收提交：`aef301278`。以下记录已验证结果和明确边界。

本轮已验证主要 Web 与原生本地业务闭环，并验证原生云端登录、真实回复和跨端历史恢复。报告涵盖 66 项能力，分别保留闭环通过、读取/空状态通过、权限受限、能力未实现和缺样本的实际边界，不能作为“所有功能均通过”的证明。

## 实测结果

| 范围 | 已验证结果 |
|---|---|
| Web 对话与智能体 | 管理员登录；真实模型回复 `WEB_QA_20260907_OK`；刷新恢复历史；自定义智能体执行 `CUSTOM_AGENT_QA_OK`；实际 `skill_loader` 加载并返回 `WEB_SKILL_QA_OK`；builtin绑定创建、匹配、停用后不匹配、删除闭环。 |
| Web 知识与工作空间 | QA项目创建；文本记忆抽取、编辑后版本2；实体及关系详情；3节点3关系图；重建1社区、3成员；语义检索及图遍历；自定义schema创建/编辑/删除；工作空间目标、任务、讨论、笔记和目录操作。 |
| 原生本地执行 | 通过规范 `make -C agi-stack run-desktop` 启动Electron与私有侧车；Kimi配置、模型发现、真实回复 `NATIVE_QA_20260907_OK`；submit_plan、批准计划、执行 `NATIVE_PLAN_OK` 并审查至completed；同一隔离profile重启后历史和默认模型恢复。 |
| 原生智能体、技能与MCP | 自定义智能体创建/启停与真实执行 `NATIVE_CUSTOM_AGENT_OK`；技能创建/编辑/版本/重启及真实调用 `NATIVE_SKILL_QA_OK`；子智能体实际委派 `NATIVE_SUBAGENT_QA_OK`；MCP注册、握手、发现及授权调用返回 `MCP_QA_OK: NATIVE_MCP_AUTHORIZED_20260907`，审查后completed；只读权限工具过滤验证通过。 |
| 原生云端 | 实际回复 `NATIVE_CLOUD_QA_20260907_OK`，终态completed、实时连接connected，Web跨端历史可见。ROOT 6 三数据面真实ACK已确认ready；项目统计1条记忆、3个实体节点、59B。实际读取同一记忆、3实体、1社区及包含社区的4个图谱节点。协作10个页签读取通过，回复 `NATIVE_CLOUD_COLLAB_QA_20260907_OK` 写入并刷新保留。 |
| 治理与基础设施 | 用户搜索/角色过滤、审计详情/分页、DLQ管理员200与普通用户403；各空目录和表单按矩阵记录。隔离实例、集群、模板、graph/retrieval store、禁用webhook配置API CRUD及清理通过；ACP禁用配置UI CRUD及清理通过。未执行部署、发布或外部发送。 |
| 身份与导航边界 | 已登录及匿名邀请首次加载直接显示无效邀请；匿名OAuth缺state拒绝；设备短码批准禁用；空密码表单必填校验；创建租户空名称禁用和取消；404返回租户首页。 |

## 已修复并复验

| 问题 | 最终行为与验证 |
|---|---|
| Web重复技能来源冲突及自定义智能体DB作用域 | 实际模型回复与自定义智能体执行通过；相关作用域回归18项通过。 |
| builtin智能体绑定旧外键与默认渠道NULL匹配 | Alembic `ce113f52d916` 删除过时FK，继续由generation目录校验；默认渠道显式NULL分支。22项回归及真实UI绑定闭环通过。 |
| DLQ异步角色加载MissingGreenlet | 加载角色后按现有权限校验，排除租户/项目角色冒充ROOT权限；17项回归，真实管理员200、普通用户403。 |
| 实例软删除后仍可读取或修改 | 删除实例GET/PUT返回404；21项路由/仓库及17项V2服务工厂回归通过。 |
| Web存储计数、Cron和部署能力展示 | 用量统计已实测；不支持Cron持久化时禁用并说明；缺instanceId时部署创建按钮禁用并说明，6项部署回归及UI复验通过。 |
| 邀请首次加载与匿名校验 | 登录场景订阅既有operation readiness；公开verify使用现有kernel身份通道，仅验证路径加入no-auth清单；接受邀请仍需认证与generation。deferred测试修复前失败，修复后页面/服务/HTTP边界43项通过；已登录和匿名首次加载实测通过。 |
| 原生知识指标、技能seed、context picker | 缺失本地权威指标显示不可用；技能seed补tenant_id；技能和智能体目录选择与真实调用通过，插件云市场限制保留。 |
| 原生云端登录和会话衔接 | 上下文判断、云端API路径及凭据衔接修复后，实际云端回复completed、实时连接和Web历史跨端通过。 |
| 云端能力快照、图谱结构与项目统计 | 修复Tasks/Bindings将cloud来源标记误作semver、主进程统计字段遗漏及renderer严格解码不一致；图谱API从数据库结构标签输出节点类别。原生记忆、实体、社区、图谱读取通过；图谱相关47项回归通过。 |
| 云端协作准入及修订号转发 | 补齐客户端实际使用的精确只读路径和canonical mutation入口，保留工作空间归属、query/body和修订号检查；Python代理转发X-Expected-Revision。原生目标/任务、讨论、文件等10页签读取及回复写入/刷新通过；55项准入、8项代理及17项错误/写入回归通过。 |
| Sandbox文件路径及性能回归环境 | 真实Linux容器正常/缺失/已删除目录三项通过；compose微基准隔离无关pytest堆，保留正常GC、100次采样及100ms阈值，p95为95.71ms。该数字仅代表微基准。 |

上述修复不把尚未实现的本地知识权威、Cron持久化或缺失的外部集成改记为通过。

## 自动化证据

| 范围 | 最新结果 | 证据与口径 |
|---|---|---|
| Web | 397文件、3656测试通过，0失败 | 单次完整运行，56.74s；[自动化摘要](qa-evidence/2026-09-07/automation-results-summary.json)。 |
| Backend | 16095/16095当前收集唯一nodeid均有通过证据 | 多轮基线、续跑和针对性复测去重汇总；缺失0、历史失败无后续通过0。不是当前HEAD一次不间断全量运行。[节点审计摘要](qa-evidence/2026-09-07/backend-final-audit-summary.json)。 |
| Rust sidecar | 641通过，0失败 | [自动化摘要](qa-evidence/2026-09-07/automation-results-summary.json)。 |
| Desktop | 4238通过、0失败、0跳过 | aef301278单次完整运行，124.85s；带真实sidecar与Workspace Core二进制，包含Electron安全边界和进程恢复测试。此前两项证据/旧预期失败已修正后完整重跑；[自动化摘要](qa-evidence/2026-09-07/automation-results-summary.json)。 |
| Electron构建与parity | build:electron通过；v2/v3/v4全部检查通过 | renderer/main/preload类型及产物构建通过；v3/v4结构闭合通过；inventory16项、实现门禁6套、ledger95条路由及9项消费测试通过。 |

## 明确边界

- 原生本地记忆/实体权威服务未实现；界面“不可用”验证通过不代表知识能力已交付。原生云端知识读取已通过，但页面仍明确为partial操作范围；图谱原生页面显示节点列表，未验证完整交互图编辑。
- Web项目Cron后端不支持持久化写入，UI已如实禁用。Runtime Pool要求全局管理员，当前租户管理员403；未放宽鉴权，也未验有权限的Pool完整操作。
- 真实外部SSO、有效邀请接受、真实等待设备授权、强制改密账号、渠道/浏览器扩展连接和签名生产升级缺样本。入口、无效输入和自动化边界不能替代完整流程。
- 未部署集群或实例、安装/发布基因与模板、外发webhook、提交工单、修改成员权限或共享信任策略。基础设施配置CRUD通过仅指配置持久化与清理。
- 空事件、死信、模式、运行手册、项目智能体日志等只验证读取、控件和空状态；无详情/重试/审批样本。审计与分析导出未验。
- Electron安全边界有本机自动化证据；未将macOS上的策略测试当作Windows/Linux实机、生产签名升级或完整浏览器矩阵验收。

## 完整能力矩阵（66项）

| ID | 能力 | 领域 | 验证状态 |
|---|---|---|---|
| agent-workspace-tenant-agent-workspace | Agent Workspace | conversation | Web 真实回复、错误展示、历史恢复、自定义 Agent 执行通过 |
| tenant-tenant-overview | Tenant Overview | tenant-operations | Web 实际读取通过；尚非全操作验收 |
| tenant-tenant-projects | Projects | tenant-operations | Web 列表、新建 QA 项目、概览通过 |
| tenant-tenant-workspaces | Tenant Workspaces | tenant-operations | 项目内 QA 空间读取通过；租户页按既有默认项目回退 |
| tenant-tenant-tasks | Task Dashboard | tenant-operations | 3条已完成任务读取、ID片段搜索命中1条通过；无失败样本可验重试 |
| tenant-tenant-analytics | Tenant Analytics | tenant-operations | 记忆/项目/存储指标及30天趋势、项目存储图表真实读取通过；未验导出 |
| tenant-tenant-agent-configuration | Agent Dashboard | agent-ecosystem | 租户策略及 generation Hook 目录读取、编辑表单/取消通过；未改共享配置 |
| tenant-tenant-agent-definitions | Agent Definitions | agent-ecosystem | Web 创建、详情、新会话、真实执行通过；原生创建/启停通过 |
| tenant-tenant-agent-bindings | Agent Bindings | agent-ecosystem | 旧FK与默认渠道匹配已修复；Web builtin创建/路由命中/停用后不匹配/删除闭环通过 |
| tenant-tenant-skills | Skills | agent-ecosystem | Web导入/查询/预览/编辑通过；原生创建/编辑/版本/重启通过，真实调用 NATIVE_SKILL_QA_OK 通过；Web 实际 skill_loader 加载后返回 WEB_SKILL_QA_OK |
| tenant-tenant-evolution | Skill Evolution | agent-ecosystem | 32采集会话、3技能证据、25任务真实读取通过；最新进化任务0，未触发发布 |
| tenant-tenant-patterns | Workflow Patterns | agent-ecosystem | 空状态、搜索、排序、刷新通过；无模式样本可验详情/弃用 |
| tenant-tenant-plugins | Plugin Marketplace | extensions | V2市场空目录、QA项目范围切换及刷新通过；未安装/连接外部渠道 |
| tenant-tenant-mcp-servers | MCP Servers | extensions | Web服务器/工具/应用/提示词/日志空状态及创建表单取消通过；原生MCP真实调用通过 |
| tenant-tenant-acp | Agent Client Protocol | extensions | 禁用QA配置创建/编辑/删除及会话事件空状态通过；未启动外部进程 |
| tenant-tenant-templates | Template Marketplace | extensions | 空目录及搜索读取通过；未初始化共享模板或安装 |
| tenant-tenant-providers | Model Providers | extensions | Web3条健康目录、搜索、新增向导取消、路由读取通过；原生Kimi配置/真实调用/重启通过 |
| tenant-tenant-webhooks | Webhooks | extensions | 隔离禁用 webhook 配置 API CRUD 与清理通过；未外发 |
| tenant-tenant-runtimes | Unified Runtimes | runtime-infrastructure | 3个sandbox健康/运行状态读取通过；Pool状态与实例返回全局管理员权限403 |
| tenant-tenant-pool | Runtime Pool | runtime-infrastructure | 当前租户管理员读取Pool状态/实例均403；需全局管理员权限，未降低鉴权 |
| tenant-tenant-instances | Runtime Instances | runtime-infrastructure | 隔离实例配置 API CRUD 通过；软删除 GET/PUT404 已修复复验；未部署 |
| tenant-tenant-clusters | Clusters | runtime-infrastructure | 隔离 cluster 配置 API CRUD 与清理通过；未连接基础设施 |
| tenant-tenant-deploy | Deployments | runtime-infrastructure | 空部署列表读取；缺少实例时创建按钮禁用和说明已修复/实测，6项回归通过；未部署 |
| tenant-tenant-instance-templates | Instance Templates | runtime-infrastructure | 隔离模板 API CRUD 与清理通过；未发布 |
| tenant-tenant-genes | Gene Market | runtime-infrastructure | 基因/基因组双标签空目录读取通过；未发布或安装 |
| tenant-tenant-users | Users and Invitations | tenant-governance | 真实2成员列表、搜索、角色过滤通过；未发邀请/改角色 |
| tenant-tenant-audit-logs | Audit Logs | tenant-governance | 70条记录、详情、第2页读取通过；导出未验 |
| tenant-tenant-events | Tenant Events | tenant-governance | 空状态和类型筛选读取通过；无事件样本 |
| tenant-tenant-dead-letter-queue | Dead Letter Queue | tenant-governance | MissingGreenlet 已修复；真实管理员200、普通用户403，统计及空队列通过；无重试样本 |
| tenant-tenant-trust-policies | Trust Policies | tenant-governance | 指定 QA workspace 读取通过；未提交授权策略 |
| tenant-tenant-decision-records | Decision Records | tenant-governance | 指定 QA workspace 读取通过；无决策样本 |
| tenant-tenant-billing | Billing | commercial | Web 实际用量和配额读取通过，存储计数错误已修复 |
| tenant-tenant-org-settings | Organization Settings | organization-governance | 读取/编辑草稿/恢复原值通过；未更改组织设置 |
| tenant-tenant-settings | Tenant Settings | tenant-governance | 真实租户设置读取、描述草稿变更/恢复和保存按钮状态通过；未持久化共享变更 |
| project-project-overview | Project Overview | project-operations | Web读取通过；原生云端1条记忆、3实体节点、59B统计通过；原生本地部分权威能力不可用 |
| project-project-workspaces | Project Workspaces | workspace | Web/原生本地创建、目标、任务、讨论、笔记及回复通过；原生云端10个协作页签读取、回复写入及刷新通过；ROOT 6三数据面receipt已ACK |
| project-blackboard-dynamic-project-blackboard | Project Blackboard | workspace | Web QA 工作空间目标/任务/文件/笔记投影通过；目录创建/重命名/删除实际通过 |
| project-project-team | Project Team | project-governance | 真实成员与8智能体列表、角色过滤通过；未发邀请/改角色 |
| project-project-memories | Project Memories | knowledge | Web 创建、提取、编辑版本2通过；原生云端读取同一已编辑记忆与内容通过；原生本地权威未实现 |
| project-project-entities | Project Entities | knowledge | Web 抽取实体和详情关系通过；原生云端读取3条实体通过，操作范围为partial；原生本地权威未实现 |
| project-project-communities | Project Communities | knowledge | Web实际重建产生1社区3成员，摘要与3成员详情通过；原生云端读取1条社区及摘要通过，操作范围为partial |
| project-project-graph | Project Knowledge Graph | knowledge | Web实际3实体节点3关系；键盘选择节点后详情/连接数2/类型/描述通过。原生云端显示含社区的4节点列表，API/decoder接受6边；未验原生交互图编辑 |
| project-project-search | Project Advanced Search | knowledge | Web 语义检索及图遍历详情通过 |
| project-project-schema | Project Schema | knowledge-configuration | Web 自定义 schema 创建、编辑、删除 QA 数据通过 |
| project-project-channels | Project Channels | extensions | 目录/QA项目范围/Feishu配置表单读取通过；缺外部渠道凭据，未连接 |
| project-project-maintenance | Project Maintenance | knowledge-configuration | 实际统计3实体1社区6关系；去重/陈旧边只读检查200；未破坏性合并清理 |
| project-project-cron-jobs | Project Cron Jobs | automations | 后端持久化写入未实现；禁用提示已修复并实际验证 |
| project-project-settings | Project Settings | project-configuration | QA描述编辑保存成功；沙箱状态读取通过；未删除项目 |
| project-agent-dashboard | Project Agent Dashboard | agent-ecosystem | QA项目活跃/最近运行0条读取通过；查看全部日志跳转通过 |
| project-agent-logs | Project Agent Activity Logs | agent-ecosystem | QA项目空运行日志及已完成状态筛选读取通过；无详情样本 |
| project-agent-patterns | Project Agent Patterns | agent-ecosystem | 租户共享只读范围提示及空模式列表读取通过；无模式样本 |
| authentication-and-account-entry | Authentication and Account Entry | identity | Web管理员、本地身份、原生云端登录通过；12:35云端真实回复completed、实时connected，Web历史跨端复验通过 |
| oauth-callback | OAuth Callback | identity | 已有会话返回首页、匿名缺state显示登录失败实际通过；缺真实SSO样本，未端到端；OAuth自动化通过 |
| invitation-acceptance | Invitation Acceptance | identity | 首次加载generation及匿名验证鉴权缺陷已修复；已登录/匿名直接显示无效邀请通过；43项边界通过；缺有效邀请样本 |
| device-approval | Device Approval | identity | 已登录入口与短码批准禁用通过；未签发CLI密钥；设备批准/撤销竞态有后端自动化，缺真实设备码闭环 |
| forced-password-change | Forced Password Change | identity | 自愿改密入口、空表单3项必填校验通过；未改密码；缺must_change_password用户，强制守卫未端到端 |
| tenant-creation | Tenant Creation | tenant-operations | 创建表单/套餐读取、空名称创建禁用、取消返回通过；未创建租户，service创建/失败自动化通过 |
| user-profile | User Profile | identity | 资料/联系/偏好/安全表单读取通过；未更改个人账号 |
| backend-stores | Backend Stores | runtime-infrastructure | graph/retrieval store 隔离 API CRUD 与清理通过；未替换当前存储 |
| project-support | Project Support | project-operations | 支持中心链接/工单空列表读取，新工单表单打开/取消通过；未提交或外发 |
| project-playbooks | Project Playbooks | agent-ecosystem | 运行手册0/反思裁决0空状态和刷新读取通过；无手册样本 |
| not-found | Not Found and Safe Route Recovery | navigation | 未知路由404及返回首页恢复到租户概览实际通过 |
| electron-security-boundary | Electron Security Boundary | native-security | Desktop最终4238/4238包含可信origin/IPC、凭据隔离、云请求scope、私有控制管道和进程恢复等边界；Electron构建通过；限本机开发构建证据 |
| private-sidecar-control-pipe | Private Sidecar Control Pipe | native-runtime | 规范Make启动及原生真实会话通过；Rust sidecar最新全量641项通过 |
| application-encrypted-vault | Application-Managed Encrypted Vault | native-security | 原生 Kimi 配置、真实调用及重启默认模型恢复通过 |
| signed-update-and-release-boundary | Signed Update and Release Boundary | native-release | 开发构建更新页明确不可用；未执行签名生产升级 |

## 环境与证据索引

Web `http://localhost:3000`，API `http://localhost:8000`。QA项目：`738ace12-0d21-48ca-847d-cd0c2802816d`。原生使用隔离QA profile/workspace；密钥经环境变量和应用加密vault管理，本报告不包含凭据。

已将精简、无凭据的验收记录归档至[日期证据目录](qa-evidence/2026-09-07/README.md)。归档保留实际观察时间与范围，历史子任务运行计数不替代本报告的最新汇总。完整后端逐节点记录仍是本地审计材料；仓库中的摘要明确标注多轮合并口径。

- [Backend节点审计](qa-evidence/2026-09-07/backend-final-audit-summary.json)：16095个当前唯一nodeid均有通过证据，缺失0；[三项95路由ledger回归](qa-evidence/2026-09-07/backend-ledger-regression-summary.json)已记录后续通过。
- [自动化验收摘要](qa-evidence/2026-09-07/automation-results-summary.json)：Web、Desktop与Rust sidecar最终计数、Electron构建、parity及原始日志摘要哈希。
- [Web治理](qa-evidence/2026-09-07/web-governance-report.md)、[智能体与扩展](qa-evidence/2026-09-07/web-agent-extensions-report.md)、[其他路由](qa-evidence/2026-09-07/web-final-routes-report.md)、[身份边界](qa-evidence/2026-09-07/web-identity-boundaries-report.md)：真实操作与限制。
- [基础设施HTTP状态](qa-evidence/2026-09-07/api-infrastructure-status-evidence.md)：按时间顺序保留配置CRUD、清理和软删除复验状态，省略请求/响应正文。
- [原生云端终态](qa-evidence/2026-09-07/native-cloud-terminal-summary.json)：真实回复持久化及is_running=false。
- [原生云端知识与协作](qa-evidence/2026-09-07/native-cloud-functional-summary.json)：实际读取、协作回复唯一写入及刷新恢复；[图谱契约回归](qa-evidence/2026-09-07/graph-node-type-regression-summary.json)记录结构类别修复。
- [ROOT 6三数据面确认](qa-evidence/2026-09-07/root-recovery-three-plane-readiness.json)：同一version/digest的真实ACK与ready状态。

## 运行时与变更证据

- 正式Core镜像与原生客户端均已重建，95条实际路由的Rust声明、Python严格兼容门槛、生成ledger对齐；六套真实门禁和9项消费测试通过。
- ROOT 5保留Python真实NACK（旧92条Python兼容门槛），修复后正常启动生成ROOT 6；Python、sidecar、renderer三方确认同一version 6和digest，readiness为ready。[已归档三方确认记录](qa-evidence/2026-09-07/root-recovery-three-plane-readiness.json)。
- 本地开发凭据通过正式接口签发，临时bootstrap身份已停用；密钥仅保存在0600临时文件和应用加密vault，报告不含凭据。两项数据面开发凭据有效期至2026-09-08 12:16（北京时间），后续刷新发布需有效凭据。
- 密钥扫描对ledger的`implementedRouteKeysSha256`产生一条误报；已与Rust公开路由哈希核对，采用仅该提交/文件/行的fingerprint豁免复扫通过，未放宽仓库扫描规则。
