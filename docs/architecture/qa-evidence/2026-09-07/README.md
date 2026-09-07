# 2026-09-07 Web / Desktop QA 证据

本目录保存[功能QA报告](../../web-desktop-functional-qa-2026-09-07.md)引用的精简验收记录。记录只包含非秘密状态、计数、公开契约摘要及必要的QA资源标识；不归档凭据文件、认证头、完整对话正文或API请求/响应正文。

| 文件 | 用途与范围 |
|---|---|
| [backend-final-audit-summary.json](backend-final-audit-summary.json) | 当前16095个唯一测试节点的多轮通过汇总；不是当前提交一次不间断全量。完整节点审计仍保留于本地QA目录。 |
| [backend-ledger-regression-summary.json](backend-ledger-regression-summary.json) | 三项95路由回归的后续通过映射，记录本地原始报告行号。 |
| [automation-results-summary.json](automation-results-summary.json) | Web3656、Desktop4238、Rust sidecar641通过；Electron构建与parity通过，附源日志SHA256和已修正的两项前序验收失败。 |
| [web-governance-report.md](web-governance-report.md) | 治理读取与角色边界，区分空状态及无样本操作。 |
| [web-agent-extensions-report.md](web-agent-extensions-report.md) | 智能体绑定和ACP配置闭环，保留外部连接未验限制。 |
| [web-final-routes-report.md](web-final-routes-report.md) | 辅助路由实测；其中3650为较早历史运行，最新Web计数为3656。 |
| [web-identity-boundaries-report.md](web-identity-boundaries-report.md) | 邀请修复和身份边界，不代替真实SSO/有效邀请闭环。 |
| [api-infrastructure-status-evidence.md](api-infrastructure-status-evidence.md) | 原始API日志的方法、路径和状态摘录；按时间保留故障及复验，不包含正文。 |
| [native-cloud-terminal-summary.json](native-cloud-terminal-summary.json) | 原生云端回复标记已持久化且停止运行；不证明知识协作功能。 |
| [native-cloud-functional-summary.json](native-cloud-functional-summary.json) | 原生云端知识读取、10个协作页签、唯一回复写入与刷新通过，保留partial及空状态边界。 |
| [graph-node-type-regression-summary.json](graph-node-type-regression-summary.json) | 图谱真实结构类别契约修复、回归和原生4节点读取结果。 |
| [root-recovery-three-plane-readiness.json](root-recovery-three-plane-readiness.json) | ROOT 6三数据面同版本/摘要ACK；已省略发布nonce。 |

原始材料来自本轮本地QA运行。日期目录中的报告保留子任务观察，最终验收状态以主报告为准。公开SHA256用于证据或契约一致性，属于非秘密摘要。
