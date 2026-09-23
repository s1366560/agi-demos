# Web 治理功能 QA — 2026-09-07

工具：真实 Chrome 浏览器独立标签页，经 Browser runtime 操作；当前登录 Default Admin。只操作自身QA草稿，未发送邀请、未更改成员权限、未变更信任授权。

| 功能 | 实测结果 | 范围和限制 |
| --- | --- | --- |
| 用户管理 | 通过 | 真实2成员列表；不存在姓名筛选变0条；清除过滤；所有者角色仅Default Admin1条。未发邀请、未改真实角色。 |
| 审计日志 | 通过 | 70条记录，20条/页4页；首条详情显示runtime hook结构；下一页显示21–40。未验证导出文件。 |
| 事件日志 | 空状态通过 | 页面正常显示暂无事件；类型筛选列表暂无数据，无真实事件可供过滤/详情测试。 |
| 死信队列 | 已修复并复验 | 原统计与列表HTTP500 / MissingGreenlet；commit 4dbba75f2后restart7真实UI显示统计0、健康空列表，无加载错误。真实API管理员stats/messages均200，普通用户均403。无失败消息，未执行重试/丢弃/清理。 |
| 信任策略 | 指定工作空间读取通过 | 默认workspace返回Workspace not found；输入真实QA workspace后空列表正常。创建表单打开并取消；未提交安全授权。 |
| 决策记录 | 指定工作空间读取通过 | 默认workspace不存在；输入QA workspace后正常空列表。无决策可供详情/审批测试。 |
| 组织设置 | 读取及草稿通过 | 显示Default Tenant、3项目2成员59B存储；编辑入口打开。描述草稿变更使保存按钮启用；恢复原值后禁用，未持久化变更。集群统计显示不可用，属已有平台能力状态。 |
| 个人资料 | 表单读取通过 | 基本资料/联系/偏好/安全区加载；未修改密码、邮箱、个人资料。 |
| 工作空间范围 | 既有设计确认 | 租户级列表按currentProject或tenantProjects[0]回退；项目详情→项目工作区→工作空间正确显示QA空间1项。root确认不扩修。 |

QA workspace: `b30bf32d-36f0-4832-bcca-252a8df18b15`，名称 QA Web Workspace 20260907；项目 `738ace12-0d21-48ca-847d-cd0c2802816d`。ID通过项目内真实工作空间链接获取，与服务器查证一致。

DLQ修复：`admin_dlq_application_authority_v2.py`增加异步按需加载User.roles→UserRole.role，再交给原管理员检查；排除tenant/project scoped角色作为ROOT管理员。权限集合及服务依赖保持。新增真实SQLite ORM请求回归从4个500失败转为global-admin200、普通/租户/项目管理员403。DLQ相关17测试通过，Ruff通过；root合并本批共55 focused tests、Pyright、hooks与gitleaks通过。

API复验（2026-09-07，restart7）：
- admin GET /api/v1/admin/dlq/stats → 200，总数0。
- admin GET /api/v1/admin/dlq/messages?limit=20&offset=0 → 200，messages=[]。
- user 相同两接口 → 403，Admin access required。

本报告不将空状态视为写操作验收，不将没有样本的重试/决策/事件流程标记完成。
