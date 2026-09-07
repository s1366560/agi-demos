# Web 智能体与扩展 QA — 2026-09-07

真实 Chrome 独立标签页；Default Admin，tenant 02f6fccc-0ac9-4729-bac7-38e77d1c61ef。未安装插件、未建立外部连接。

| 功能 | 实测结果 | 证据与限制 |
| --- | --- | --- |
| 智能体配置 / Agent Dashboard | 读取与编辑入口通过 | `/agents`现为租户运行时策略页；模型default、温度0.7、5000计划步、30秒工具超时；编辑表单最终加载当前策略和generation Hook目录，关闭未保存。轨迹面板暂无轨迹；未变更共享策略。 |
| 智能体绑定 | 修复后完整UI闭环通过 | builtin Sisyphus + 任意渠道 + qa-binding-20260907创建1条；Web聊天测试命中sisyphus、分数2、1候选已选择；停用后无匹配0候选；删除后列表0。 |
| 进化 | 真实数据读取通过 | 32已采集会话、5归因、3技能证据；任务页25项真实历史条目；最新任务0空状态。人工审核、调度60分钟；未修改全租户策略或强制运行历史批次。 |
| 工作流模式 | 空状态与筛选控件通过 | 总数0，搜索QA标识、按名称排序、刷新均正常空状态；无样本可测详情或弃用。 |
| 插件 / V2市场 | 读取与范围切换通过 | 无可用V2 Bundle；默认→QA项目切换与重新加载正常，频道为空，目录显示Feishu builtin-feishu schema。未安装或连接。 |
| 模板市场 | 空状态/搜索通过 | 未找到模板；搜索控件正常；页面提供初始化内置模板入口，本轮未初始化共享目录或安装模板。 |
| ACP | 禁用配置CRUD通过 | qa-acp-20260907创建，enabled=false、stdio /usr/bin/false；重新加载后编辑名称为Edited成功，删除后Agents0。会话/事件页为空；未启动进程或运行连接测试。 |

绑定故障与修复（commit db07bb53b，API restart9）：
- 真实创建原HTTP500：`agent_bindings_agent_id_fkey`拒绝generation catalog-only的`builtin:sisyphus`。
- 移除过时SQL FK和无消费者ORM relationship，继续由AgentBindingServiceV2解析active generation并验证tenant scope。
- Alembic autogenerate后审查仅保留该FK删除，revision ce113f52d916已应用；未包含其他schema差异。降级仅恢复FK，catalog-only行存在时会拒绝而不会删数据。
- 回归另暴露SQL IN(type,NULL)漏掉默认渠道，两个resolve路径改为显式OR IS NULL。
- 22 focused tests通过：builtin与persisted agent、默认与显式渠道CRUD/resolve、unknown和跨tenant拒绝；Ruff通过。测试从3失败4通过转7新增全绿。

ACP观察：第一次创建后立即打开编辑时保存按钮曾持续loading，API没有PUT记录、PG无Lock。reload后编辑成功，后端核对PUT200耗时36ms、无reload/deadlock；未稳定复现。保留了前端create后await loadStatus再finally复位saving的时序线索，未据此修改代码。QA配置已删除。

所有本报告创建的QA绑定与ACP配置均已通过UI删除。空目录只代表空状态读取通过，未标记安装、进化执行或外部ACP运行通过。
