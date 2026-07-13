# LLM Provider 配置 UX 研究与设计决策

更新日期：2026-07-11

## 1. 研究问题

原型原先以“模型”为一级对象，直接编辑 Provider Model ID、Fallback 和预算。这种设计把 Provider 连接、凭据、模型发现、模型启用和工作区路由混在同一个模型详情中，无法表达 OAuth、API Key、本地端点、OpenAI-compatible 网关、同一 Provider 多模型，以及同一模型由不同 Provider 托管等真实场景。

本轮研究回答两个问题：

1. 常用开源 Agent / LLM 工具如何建立 Provider、Credential、Endpoint、Model 和 Routing 的对象关系？
2. 桌面客户端怎样让普通用户完成配置，同时保留企业级网关、自托管和故障转移能力？

## 2. 上游产品证据

### 2.1 Hermes Agent

- `hermes model` 是完整配置向导，用于添加 Provider、OAuth、API Key 和自定义 Endpoint；会话内 `/model` 只切换已经配置好的 Provider / Model。Setup 与 Selection 被明确分离。
- Custom Endpoint 向导要求 Base URL、API Key、Model Name，并将 Provider、Model 与 Base URL 持久化到 `config.yaml` 单一事实源。
- 支持 OAuth、API Key、AWS Credentials、无需认证的本地运行时，以及 OpenAI-compatible、Anthropic Messages 等 API Mode。
- 对兼容端点优先调用 `/models` 自动发现；无法发现时允许保存手动 Model ID。
- 支持 Named Custom Providers、单 Provider 多模型、Provider-aware context length，以及有序 Fallback Providers。

来源：[Hermes AI Providers](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md)、[Hermes Configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/)

### 2.2 OpenCode

- `/connect` 先保存 Provider 凭据，`/models` 再选择该 Provider 下的模型。
- OpenAI 等 Provider 可以在 OAuth 与手动 API Key 之间选择；远程环境可使用 Device Code。
- Custom Provider 有稳定 Provider ID、Display Name、Base URL、SDK/API Mode、Headers 和 Models Map。
- Model ID 使用 `provider_id/model_id`，避免同名模型来源不明确。
- 支持模型 whitelist / blacklist，避免网关返回数百或数千模型时污染选择器。

来源：[OpenCode Providers](https://opencode.ai/docs/providers)

### 2.3 Open WebUI

- Provider 连接入口位于 Admin Settings → Connections，最小配置是 URL + API Key。
- 保存前通过 `/models` 验证连接并自动发现模型；同时明确提示部分 Provider 不实现标准 `/models`。
- 自动发现失败时用 Model IDs Filter 手动允许列表；OpenRouter 等超大目录也推荐主动筛选。
- Provider 连接可以停用而无需删除配置。

来源：[Open WebUI Connect a Provider](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/)、[OpenAI-compatible Provider](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/)

### 2.4 Dify

- Provider Credential 是一级对象；预定义模型只需配置一次 Provider Credential 即可使用全部模型。
- 自定义模型在 Provider Credential 之外增加 Model UID、Context、能力或其它模型级参数。
- 同一 Provider 可以同时包含 predefined-model 与 customizable-model。

来源：[Dify Model Provider Plugin](https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/creating-new-model-provider)

### 2.5 OpenHands

- 基础 UI 顺序为 LLM Provider → LLM Model → API Key，适合低认知负担的首次配置。
- Provider 前缀可隐式确定 Base URL；高级配置再暴露自定义 Base URL 和 Headers。

来源：[OpenHands LLM Provider](https://docs.openhands.dev/openhands/usage/llms/openhands-llms)、[OpenHands LLM Architecture](https://docs.openhands.dev/sdk/arch/llm)

### 2.6 LiteLLM

- `model_list` 把对用户暴露的 Model Alias 与底层 Provider Deployment 分开；底层配置包含 provider/model、api_base、api_key、api_version。
- Gateway 层承担统一协议、健康、异常映射、重试、Fallback、预算与用量，不应与单个模型的展示资料混为一体。

来源：[LiteLLM Getting Started](https://docs.litellm.ai/)

## 3. 共识模式

研究样本虽然面向 CLI、WebUI、Agent IDE 和企业 Gateway，但对象模型高度一致：

1. **Provider first**：先建立 Provider 连接，再选择 Model。
2. **Credential belongs to Provider**：API Key、OAuth Token、AWS Credential 和环境密钥属于 Provider，不属于单个 Model。
3. **Endpoint is advanced by default**：官方 Provider 预填默认 Endpoint；Gateway、本地和企业云再显式编辑。
4. **Verify before save**：测试 Auth、Endpoint 与协议；模型发现是验证结果的一部分，但 `/models` 失败不等于推理一定失败。
5. **Discovery with manual escape hatch**：优先自动发现，失败或目录过大时允许精确 Model ID / Allowlist。
6. **Enablement is distinct from discovery**：发现的模型不应全部进入 Agent 选择器；管理员只启用需要的模型。
7. **Routing is workspace policy**：Default、Fast、Coding、Vision、Embedding 与 Fallback 是工作区策略，不是 Provider Credential 字段。
8. **Provider-aware identity**：运行时身份至少是 `provider/model`；同一模型经不同 Provider 服务时，上下文、价格和能力可能不同。

## 4. 原型现状审计

### P1 — 配置对象错误

原界面左侧列出 GPT、Claude、Gemini 等模型，右侧直接编辑 Provider Model ID 与 Fallback。用户无法知道 API Key 配在哪里，也无法复用一个 Provider Credential 连接多个模型。

### P1 — 缺少可完成的连接流程

原界面没有 Provider 选择、Auth Method、Base URL、连接测试、模型发现与失败恢复，因此“编辑配置”并不能真正完成 LLM 接入。

### P1 — 模型与路由耦合

Fallback 被放在单模型配置中，无法表达 Default / Fast / Coding / Vision 的工作负载分工，也无法表达有序跨 Provider Fallback。

### P2 — 自托管与网关不可表达

Ollama、LM Studio、LiteLLM、OpenRouter、Azure OpenAI 和 Bedrock 所需字段差异很大，原来的统一文本表单无法覆盖 OAuth、API Mode、Region、Deployment 和手动 Model ID。

## 5. 新交互模型

Settings → Models 保留名称，但内部一级对象改为 **Providers**：

1. Provider Catalog：OpenAI、Anthropic、Google AI、OpenRouter、Ollama，以及用户新增的企业云或自定义 Endpoint。
2. Overview：连接健康、认证类型、Endpoint、已启用模型和当前工作区路由。
3. Connection：Auth Method、Encrypted Secret、Base URL、Advanced API Mode / Headers / Timeout、Test Connection。
4. Models：自动发现、搜索、Enable / Disable、Capabilities、Context，以及手动 Model ID。
5. Routing：Default、Fast、Coding、Vision 的模型分工与有序 Fallback Chain。
6. Usage：Provider 级成功率、延迟、费用、模型数量和连接活动。
7. Add Provider：Choose Provider → Authenticate & Verify → Enable Models 三步向导。

## 6. 设计边界

- 原型只模拟凭据与请求，不保存真实密钥，也不执行外部 Provider API。
- Provider 连接、模型启用和路由选择需要分别产生审计事件；生产实现不得把密钥写入前端状态或日志。
- 自动发现失败必须区分 Auth Error、Endpoint Error、Protocol Error 与 Unsupported `/models`；后者允许继续手动添加 Model ID。
- 新增 Provider 不自动改变 Default Model 或 Agent 配置，必须由用户在 Routing 中显式分配。
