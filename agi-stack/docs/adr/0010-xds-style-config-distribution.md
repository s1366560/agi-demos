# ADR-0010 · xDS 风格版本化 typed 配置分发(version/nonce + ACK/NACK + last-good + 最终一致)

- 状态:**已接受**(设计决策,基于 Istio/Envoy + ztunnel 调研;ACK/NACK reconcile 已 Spike 证伪)
- 日期:2026-06
- 关联:[08-control-data-plane-separation §5/§6](../architecture/08-control-data-plane-separation.md)、[research/istio-k8s-control-data-plane](../research/istio-k8s-control-data-plane.md)、[ADR-0009](0009-control-data-plane-separation.md)、[ADR-0006](0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md)(本 ADR 形式化其 CP/DP 推送草图)

## 背景

[ADR-0009](0009-control-data-plane-separation.md) 确立了控制面/数据面分离为一等轴,但**控制流具体怎么下发**仍是 [ADR-0006](0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md) 的单点草图("`push_config` + hash 幂等")。Istio/Envoy 的 **xDS 协议**给出工业级、超大规模验证的完整答案:

- **typed 资源 + 版本化**:`DiscoveryResponse{version_info, nonce, type_url, resources}`(`envoyproxy/envoy:api/envoy/service/discovery/v3/discovery.proto:L133-165`)。
- **ADS 单流有序**:所有资源类型走单一有序流,避免类型间配置竞态(`envoy:.../ads.proto`、`xds_protocol.rst:L818-832`);istiod PushOrder `CDS→EDS→LDS→RDS`(`istio/istio:pilot/pkg/xds/ads.go:L504-515`)。
- **ACK/NACK + last-good**:NACK 时 client `version_info` 填上一个 good 版本,*"The last valid configuration ... will continue to apply if a configuration update rejection occurs"*(`xds_protocol.rst:L84-87`、`L437-455`)。
- **最终一致**:无全局锁,DP 收敛到最新 version,容忍 istiod 断连(保留 last-good)。
- **Rust 工业参照 ztunnel**:`handle_stream_event` 在 handler 返 `Err(Vec<RejectedConfig>)` 时发 NACK 且**不改 state**,成功才更新(`istio/ztunnel:src/xds/client.rs:L681-746`、`src/xds.rs:L66-93`);`Arc<RwLock<ProxyState>>` 原子状态更新(`src/xds.rs:L104-112`)。这是**同语言**实现,可直接移植。

## 决策

**控制流采用 xDS 风格版本化 typed 配置分发协议。**

1. **快照格式**(镜像 Envoy `DiscoveryResponse`):`ConfigSnapshot{ type_url, version: u64, nonce, resources }`。`type_url` 标识配置类型(`ToolRegistry`/`SkillConfig`/`ProviderConfig` 各一),DP 收到错类型快照即 type-check 拒绝。
2. **version 单调 + 乐观并发**:`ControlPlane::publish()` 单调 bump version(镜像 K8s `ResourceVersion`);DP 拒绝**严格更旧**的 version(陈旧拒绝),**前向跳跃允许**(level-triggered,无需见每个中间版本)。
3. **nonce 防陈旧 ACK**:每次 snapshot 配新 nonce;ACK/NACK 回带 `{version, nonce}`,使重连"同 version 新 nonce"成为干净的幂等重放。
4. **ACK/NACK + last-good**:`ConfigAck::{Ack{version,nonce}, Nack{version,nonce,error}}`。reconciler **validate-build-all-before-mutate**:所有 add/update 在任何 registry 变更**之前**构建,任一失败即 NACK 且 `last_good` 原封不动(原子接受/拒绝,Envoy/ztunnel 语义)。**坏配置不能 brick 数据面。**
5. **最终一致 + 重连全量重同步**:DP 离线用 last-good 自治,重连 CP **全量重发** SSOT(`snapshot()` 同 version 新 nonce),DP reconcile 已收敛即幂等 no-op。
6. **当前 SotW,Delta 留扩展**:Spike 用 State-of-the-World 全量推送(简单、小规模够用);Delta/Incremental xDS(`{added, removed}` + `initial_resource_versions` 重连跳过未变,`discovery.proto:L168-310`)列为大规模时的未来扩展。

## 后果

- ➕ 形式化了 [ADR-0006](0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md) 的"配置 hash 推送":hash → 显式 `version + nonce`,幂等 apply → 完整 ACK/NACK + last-good 状态机。
- ➕ NACK 保留 last-good → 坏配置不致瘫痪,坏租户配置不影响已 good 的端;validate-before-mutate 保原子性。
- ➕ ztunnel(Rust 数据面)证明 ACK/NACK 环、`RejectedConfig` 聚合、原子状态更新可地道移植;agi-stack `ArcSwap<ToolRegistry>` 比其 `RwLock` 读路径更进一步(完全无锁)。
- ➕ typed `type_url` 多类配置(工具/技能/provider)走同一协议,DP 按类型路由到对应 reconciler。
- ➖ SotW 全量在配置量大时带宽/CPU 偏高 → 需在规模化阶段切 Delta(已规划,非当前阻塞)。
- ➖ version/nonce/ACK/NACK 状态机比裸 hash 推送复杂 → 但复杂度被"坏配置隔离 + 断连容忍"价值正当化,且 ztunnel 提供可抄的 Rust 参照。
- ⚠️ ADS 单流有序需传输层保序(服务器 gRPC streaming 天然有序;端上 HTTP long-poll 需序号);属传输层,不入纯同步 reconciler。
- ⚠️ "生成哪份配置/推给谁"是控制面**语义**策略 → 归 agent/策略引擎;version bump、nonce、type-check、diff、ACK/NACK 保持确定性(Agent First 铁律)。
