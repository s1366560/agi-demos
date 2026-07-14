# Model Provider 配置体验审计

日期：2026-07-11
范围：Settings → Models
用户目标：连接一个 LLM Provider，验证凭据与 Endpoint，选择可用模型，并分配工作区路由。

## 审计证据

1. 原模型详情：`qa/model-provider-audit-before.png`
2. Provider 总览：`qa/model-provider-overview-final.png`
3. Connection 验证：`qa/model-provider-connection.png`
4. Add Provider 向导：`qa/model-provider-add-wizard.png`
5. 1100×800 Routing：`qa/model-provider-routing-1100.png`

## 原体验问题

- P1：一级对象是模型，不是 Provider，API Key、OAuth 和 Endpoint 无处归属。
- P1：Edit config 不能完成连接，没有 Test connection、模型发现和错误恢复。
- P1：单模型 Fallback 与 Credential 混在一起，无法表达工作区 Default / Fast / Coding / Vision 与跨 Provider 故障转移。
- P2：Ollama、OpenRouter、Azure、Bedrock 和自定义 OpenAI-compatible Endpoint 无法用同一文本表单正确表达。

## 改版流程健康度

1. Provider Catalog — 健康。连接状态、连接类型和启用模型数量可扫描，Connected / Needs model filter / Offline 不只依赖颜色。
2. Provider Overview — 健康。先回答“连接是否可用、哪些模型已启用、当前路由是什么”，再进入细节。
3. Connection — 健康。认证、Endpoint 和高级协议字段分层，Test connection 提供明确成功状态。
4. Models — 健康。自动发现和启用状态分离；`/models` 不可用时有手动 Model ID 逃生路径。
5. Routing — 健康。Default / Fast / Coding / Vision 与有序 Fallback 独立于 Credential。
6. Add Provider — 健康。Choose → Connect & Verify → Enable Models 三步向导有清晰进度与禁用条件。
7. Compact desktop — 健康。1100×800 无横向溢出，主操作、Provider Catalog 和 Routing 保持可用。

## 可访问性与证据限制

- 已确认语义按钮、表单标签、对话框、状态文本、可见焦点和无颜色状态表达。
- 已通过浏览器检查键盘可达的核心控件与 1100px 重排。
- 原型不连接真实 Provider，因此未验证真实 OAuth 回调、错误码映射、屏幕阅读器播报和 200% 文本缩放；生产实现需补充自动化与辅助技术测试。
