# ADR-0009 · 控制流/数据流分离为一等架构轴(CP=SSOT + 声明式 level-triggered 数据面)

- 状态:**已接受**(设计决策,基于 Kubernetes 调研;reconcile 协议已 Spike 证伪)
- 日期:2026-06
- 关联:[08-control-data-plane-separation §1-§4/§7](../architecture/08-control-data-plane-separation.md)、[research/istio-k8s-control-data-plane](../research/istio-k8s-control-data-plane.md)、[06-agent-core-design §5/§6](../architecture/06-agent-core-design.md)、[ADR-0005](0005-round-boundary-checkpoint.md)、[ADR-0010](0010-xds-style-config-distribution.md)

## 背景

agi-stack 一份核心同时跑在**云端**(多租户、权威、SSOT)与**端/边**(离线、自治)。既有设计已有 CP/DP 线索但都是**单点机制**:[ADR-0006](0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md) 借 Kong 做"配置 hash 推送";[06](../architecture/06-agent-core-design.md)/[ADR-0004](0004-plan-as-append-only-dag.md)/[ADR-0005](0005-round-boundary-checkpoint.md) 借 Argo 做"reconcile 幂等"。缺一个把"控制流/数据流分离"升格为一等轴的形式化决策。

Kubernetes 给出超大规模验证的答案:
- **API server = 单一真相源(SSOT)**:etcd 只能经 apiserver 访问,数据面是缓存 + 执行,可从 SSOT 重建(`kubernetes/kubernetes:apiserver/pkg/storage/interfaces.go`)。
- **声明式 spec/status**:控制面发期望态,数据面观测 + 自算 diff 收敛(`kubernetes/community:api-conventions.md:L280-313`)。
- **level-triggered 而非 edge-triggered**:*"behavior is level-based rather than edge-based ... robust in the presence of missed intermediate state changes"*;controller-runtime 的 `Request` 只含 key 不含 delta(`controller-runtime:pkg/reconcile/reconcile.go:L90-107`)。
- **节点本地自治**:控制面短暂不可达时节点继续跑(`pkg/kubelet/kubelet.go`)。

## 决策

**把"控制流/数据流分离"确立为继"可移植核心""可扩展插件"之后的第三条一等架构轴。**

1. **两条流分两条路**:
   - **控制流**(配置/策略分发、工具 enable/disable、runtime 选择、plan/路由、生命周期、HITL 批准)—— 低频、需有序/一致 —— 走 **CP 路径**:版本化、reconcile、最终一致、ACK/NACK。
   - **数据流**(episode/memory 负载、LLM token 流、工具 I/O、向量检索)—— 高频、需吞吐 —— 走 **DP 路径**:流式、本地、高吞吐;**LLM token 永不每 token 回 CP**。
2. **云端控制面 = SSOT**:持权威多租户配置(`DesiredConfig`,spec),存 Postgres;端/边数据面是缓存 + 执行(观测态),可从 SSOT 重建。
3. **数据面声明式 + level-triggered reconcile**:CP 发期望态全量,DP `reconcile(snapshot)` 观测本地 registry → 算 `added/removed/updated` diff → 收敛(非命令式逐事件)。漏推自愈、重复幂等、乱序无关、前向跳跃允许。
4. **配置热应用在轮次边界**(衔接 [ADR-0005](0005-round-boundary-checkpoint.md)):`ArcSwap` 换表只在 ReAct 轮次边界,不打断飞行轮次。
5. **reconciler 纯同步、运行时无关**:无 tokio/`std::time`,传输出核 —— 协议与传输分离本身就是 CP/DP 分离应用于自身代码,故服务器/桌面/移动/浏览器同实现一套。

(xDS 风格的版本化 typed 分发协议 —— version/nonce/ACK/NACK/last-good —— 由 [ADR-0010](0010-xds-style-config-distribution.md) 专门决策。)

## 后果

- ➕ "重/轻 runner"([06 §6](../architecture/06-agent-core-design.md))、"热插拔换表"([07](../architecture/07-plugin-runtime-architecture.md))、"local-first 离线"([01](../architecture/01-portable-core.md))统一到一条轴:云端 CP + 端/边 DP。
- ➕ level-triggered 自愈:DP 漏推/重启/乱序后读当前期望态即收敛,不卡错态;同态重放幂等 no-op(Spike 用 `Arc::ptr_eq` 证无 churn)。
- ➕ DP 可从 SSOT 重建 → 端上无需持久权威态,只需缓存 + 重连重同步。
- ➕ reconciler 纯同步 → 端上(无 tokio)与服务器同实现,沿用核心运行时无关不变量([01](../architecture/01-portable-core.md))。
- ➖ 最终一致(非强一致):各 DP 独立收敛,跨端无全局事务 —— 对 local-first 是**必需特性**,但需接受"CP SSOT 可短暂领先 DP applied 版本"(Spike 中 CP v3 / DP v2 的良性分叉)。
- ➖ 引入 spec/status 双态需明确授权域(CP 写 spec、DP 写 status),避免端篡改权威配置。
- ⚠️ "推哪些配置给哪个租户/会话"是**语义**策略 → 归 agent/控制面策略引擎;version 单调、diff、集合收敛保持确定性(Agent First 铁律)。
- ⚠️ informer 式 watch 流 / 去抖属**传输层**,按平台实现(服务器 gRPC streaming、端上 HTTP long-poll),不入核心。
