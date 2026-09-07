# Web 剩余路由实际验证

日期：2026-09-07。Chrome 独立 QA 标签，Default Tenant，QA 项目 738ace12-0d21-48ca-847d-cd0c2802816d。以下记录为 UI 实际观察，空目录不等同于完整业务闭环通过。

| 页面 | 实际证据 | 限制 |
|---|---|---|
| Tasks | 3 个已完成任务，ID片段3ea2cf8a搜索仅1条命中 | 无失败任务，恢复按钮禁用，未重试 |
| Analytics | 1记忆、3项目、59B存储；30天趋势与项目存储图表加载 | 未导出 |
| Tenant Settings | 描述草稿编辑、恢复及保存状态 | 未持久化共享变更 |
| Runtimes | 3个 sandbox 显示健康/运行 | Pool状态和实例均Global admin access required |
| Pool | 两个读取面板稳定返回403 | 当前用户仅租户管理员；后端要求superuser或全局SYSTEM_ADMIN，未放宽鉴权 |
| Deploy | 空列表；原创建按钮因缺少instanceId点击无效 | 已修复禁用并说明“请从实例页面发起部署。”；UI复验通过；未创建部署 |
| Genes | 基因与基因组标签均0条，切换正常 | 未发布/安装 |
| Project Agent | 活跃和最近运行0条；查看全部日志跳转正常 | 无详情样本 |
| Project Agent Logs | 空日志；已完成状态选择正常 | 无运行样本 |
| Project Agent Patterns | 空目录；明确租户共享/项目只读范围 | 无详情样本 |
| Support | 文档/API/FAQ链接，工单空列表，新工单主题/优先级/描述表单打开后取消 | 未访问外部文档，未提交工单 |
| Playbooks | 运行手册0、反思裁决0，刷新正常 | 无手册样本 |
| Providers | 3条启用且健康；Ollama搜索仅1条；新增向导33种提供商；路由显示嵌入Ollama配置 | 新增向导取消；未修改既有凭据/共享路由 |
| MCP | 服务器/工具/应用/提示词0条；日志无服务器选择时按钮禁用；创建表单含项目/名称/STDIO/配置JSON | 表单关闭，未启动外部服务；原生MCP调用证据在总矩阵 |

部署修复：DeployProgress 缺少 instanceId 时禁用创建按钮并显示双语说明；新增2项行为回归，加既有4项SSE测试共6通过。相关修复已纳入本轮变更。

本路由子集结束时的历史全量运行（最终Web结果以automation-results-summary.json的3656通过为准）：原始日志名memstack-qa-20260907-web-latest-final.log；完整单次运行395文件、3650测试通过，0失败，耗时52.69秒。
