# Web 身份与导航边界

2026-09-07，独立Chrome QA标签，保留现有管理员登录。未退出其他会话、发送邮件、签发设备API密钥、修改密码或创建租户。

| 项目 | 路由与守卫 | 实际验证与限制 |
|---|---|---|
| OAuth | /login/callback/:provider；已有token时返回根路由 | /login/callback/google?error=access_denied实际回租户概览；独立匿名来源缺state实测显示“登录请求缺失或已过期”；未验真实SSO |
| Invite | /invite/:token公开页；verify后才可accept | 已修复generation未就绪及匿名验证鉴权缺陷；localhost已有会话和127.0.0.1匿名首次加载均直接无效邀请；未验有效邀请 |
| Device | /device，App登录守卫；8位码才启用批准 | ?code=QA1显示账号/授权说明和禁用批准；未签发任何API密钥，缺真实等待设备样本 |
| Password | /force-change-password；登录守卫，根路由/租户shell检查must_change_password | 当前用户为自愿改密模式；空提交出现三项必填错误；未改密码，强制标志用户未验 |
| Tenant | /tenants/new，NewTenantRouteV2登录守卫 | 名称/描述/套餐正常；空名称创建禁用；取消正常；未实际创建 |
| 404 | App的* fallback | /qa-not-found-20260907显示404，返回首页恢复租户概览 |

源码依据：web/src/App.tsx；web/src/routes/v2/webBusinessRouteGuardsV2.tsx；web/src/routes/v2/webDefaultBusinessRouteElementsV2.tsx；web/src/pages/{OAuthCallback,InviteAccept,DeviceApprove,ForceChangePassword,NotFound}.tsx。

邀请修复：InviteAccept订阅既有operation availability，登录会话待generation就绪才校验/显示接受入口；公开verify采用既有kernel身份传输，仅/invitations/verify路径段加入no-auth清单，accept和租户邀请管理仍需认证/运行时。后端verify明确匿名端点；它会将过期邀请标为expired，但不会接受邀请或添加成员。匿名UI复测使用127.0.0.1独立来源，随后访问login确认没有既有登录会话。没有通用绕过客户端或延时重试。

回归：deferred generation测试修复前失败；修复后InviteAccept3项、invitationService2项、httpClient38项共43通过；OAuthCallback和oauthLoginService另9通过。ESLint0错误（kernel现有4警告）。GitNexus页面/verify LOW；共享认证判断HIGH（115间接引用），仅扩展既有公开验证路径。

自动化补充证据（不能替代真实外部闭环）：
- web/src/test/pages/OAuthCallback.test.tsx：可信会话写入/服务端指定返回路径、无效state理由、缺state传输前拒绝。
- web/src/test/services/oauthLoginService.test.ts：OAuth服务协议；以上属于12:29完整3650测试通过运行。
- web/src/test/services/tenantService.test.ts：创建成功及失败传播，属于同次完整Web通过运行。
- src/tests/unit/routers/test_auth_oauth.py：OAuth绑定/已验证身份/无效state/跨域返回等边界。
- src/tests/unit/routers/test_auth_device_code.py：批准取消竞态、撤销范围和幂等性。
- src/tests/unit/infrastructure/plugins/v2/test_builtin_invitations_public_http_routes_v2.py：公开邀请generation dispatcher和handler委派。
- 后端采用[节点审计摘要](backend-final-audit-summary.json)中的多轮去重通过证据，不声称单次全量后端通过。

最终完整Web单次运行：397文件、3656测试、0失败，56.74s。已归档[自动化摘要及原始日志哈希](automation-results-summary.json)。
