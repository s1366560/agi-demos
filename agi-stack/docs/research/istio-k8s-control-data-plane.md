# Istio / Kubernetes 控制面-数据面分离 内部设计调研

> [08-control-data-plane-separation](../architecture/08-control-data-plane-separation.md) 的**证据基**。目的不是集成 Istio/K8s,而是**学习其控制流/数据流(控制面/数据面)分离的内部机制**,映射到 agi-stack 的可移植 Rust 核心(云端控制面 + 端/边数据面)。
>
> 调研标的:`kubernetes/kubernetes`(commit `d94f14c3`)、`kubernetes/community`、`kubernetes-sigs/controller-runtime`、`istio/istio`、`envoyproxy/envoy`(+ `envoyproxy/data-plane-api`)、`istio/ztunnel`。
>
> 引用格式 `owner/repo:path[:line]`,指向上游;行号为调研时点近似。两节(Kubernetes 声明式调和 / Istio xDS 分发)各含:核心机制(带源码引用)→ 机制 → Rust 映射表 → 关键引用汇总。
>
> **最有价值的发现**:Istio 的 **ztunnel 数据面本身是 Rust 写的**(`istio/ztunnel`),其 `handle_stream_event` 的 ACK/NACK 循环、`RejectedConfig` 错误聚合、`Arc<RwLock<ProxyState>>` 原子状态更新可**直接移植**到 agi-stack —— 不是类比,是同语言的工业级实现参照。

---

## 第一节 · Kubernetes:声明式调和(控制面 = SSOT,数据面自调和)

### 1.1 控制面 vs 节点(数据面)的硬切分

Kubernetes 在**控制面**("大脑":期望态管理、调度、API 面)与**数据面**("肌肉":节点上真实跑负载)间画了一条硬线。中心规则:**etcd 只能经 kube-apiserver 访问** —— 没有任何 controller / kubelet / scheduler 直连 etcd,所有参与系统状态的组件都通过读写 API server 完成,API server 是唯一的守门人(`kubernetes/kubernetes:staging/src/k8s.io/apiserver/pkg/storage/interfaces.go`,`storage.Interface` 是所有 apiserver 请求处理器使用的抽象,~L168-260)。

| 组件 | 角色 | 面 |
|---|---|---|
| **kube-apiserver** | REST API 网关;**etcd 唯一读写者**;校验并持久化全部资源变更;处理 watch 流 | 控制面 |
| **etcd** | 分布式 KV,存全部 API 对象的序列化态;只被 apiserver 经 `storage.Interface` 触碰 | 控制面 |
| **kube-scheduler** | watch 未调度 Pod,把 `.spec.nodeName` 绑定写回 apiserver | 控制面 |
| **kube-controller-manager** | 托管全部内置 controller,各自经 apiserver 读写调和期望态 | 控制面 |
| **kubelet** | watch 本节点 PodSpec → 经 CRI 驱动容器运行时;**不碰 etcd** | 数据面 |
| **kube-proxy** | watch Service/EndpointSlice → 编程本地 iptables/ipvs | 数据面 |

> **关键架构后果(数据面自治)**:节点用**本地缓存**(而非直连 etcd)调和期望态,所以**控制面短暂不可达时节点仍继续执行**(已起容器继续跑、流量继续路由)。控制面挂掉不杀在跑的负载。这正是数据面独立性的本质。— `kubernetes/kubernetes:pkg/kubelet/kubelet.go`(kubelet 订阅 `coreinformersv1` 经 informer 缓存收 PodSpec → `podWorkers.UpdatePod`),`pkg/kubelet/kubelet.go:L44-86`(import CRI `internalapi "k8s.io/cri-api/pkg/apis"`)

### 1.2 声明式模型:`spec`(期望)vs `status`(观测)+ level-triggered

api-conventions 是权威出处:

> *"By convention, the Kubernetes API makes a distinction between the specification of the desired state of an object (`spec`) and the status of the object at the current time (`status`)... When a new version of an object is POSTed or PUT, the spec is updated and available immediately. Over time the system will work to bring the status into line with the spec. The system will drive toward the most recent spec regardless of previous versions... In other words, the system's behavior is **level-based** rather than **edge-based**. This enables robust behavior in the presence of missed intermediate state changes."*
> — `kubernetes/community:contributors/devel/sig-architecture/api-conventions.md:L280-313`

每个持久化对象内嵌 `metav1.ObjectMeta`,其中两个字段是调和的关键(`kubernetes/kubernetes:staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go:L129-296`):
- **`ResourceVersion`**(L182-192):对象内部版本不透明值,用于**乐观并发、变更检测、watch**。
- **`Generation`**(L194-197):期望态的世代序号,spec 每变 +1;controller 写 `status.observedGeneration` 标记"已处理到哪一代"。

`spec`/`status` 分离还映射到**分离的授权域**:写 `spec` 走主 REST 端点,写 `status` 走 `/status` 子资源(独立 RBAC)。`PUT /pods/<name>` 静默丢弃 `status` 改动,`/pods/<name>/status` 丢弃 `spec` 改动(`api-conventions.md:L301-304`)。

### 1.3 Controller 调和环(Observe → Diff → Act)

权威设计文档给出的范式:

> *"A Kubernetes controller is an active reconciliation process. It watches some object for the world's desired state, and it watches the world's actual state, too. Then, it sends instructions to try and make the world's current state be more like the desired state."*
> — `kubernetes/community:contributors/devel/sig-api-machinery/controllers.md:L1-5`

最简形式就是 `for { desired := getDesiredState(); current := getCurrentState(); makeChanges(desired, current) }`;informer、workqueue 都是这个环的优化。`DeploymentController` 是端到端范例:

- **结构**:controller 持 informer 缓存的 lister(`dLister/rsLister/podLister`)和 workqueue,**从不直连 etcd**(`kubernetes/kubernetes:pkg/controller/deployment/deployment_controller.go:L67-101`)。
- **`syncDeployment`** = Observe(从 informer 缓存读当前态,非直问 apiserver)→ Diff(是否 scaling/rollback 事件)→ Act(调 `dc.client.AppsV1().ReplicaSets(...).Create/Update()` 即 apiserver HTTP 写)(`deployment_controller.go:L572-660`)。

`kubernetes-sigs/controller-runtime` 把这一切收敛成 operator 通用的 `Reconciler` 接口 —— 关键是 **`Request` 只含 `NamespacedName`,不含事件类型、不含对象 delta**:

> *"Reconciliation is level-based, meaning action isn't driven off changes in individual Events, but instead is driven by actual cluster state read from the apiserver or a local cache. For example if responding to a Pod Delete Event, the Request won't contain that a Pod was deleted, instead the reconcile function observes this when reading the cluster state and seeing the Pod as missing."*
> — `kubernetes-sigs/controller-runtime:pkg/reconcile/reconcile.go:L90-107`

错误处理也在接口里:返回非 nil error → 用**指数退避**重新入队(除非是 `TerminalError`);返回 `Result{RequeueAfter}` → 定时重新入队(`reconcile.go:L108-125`)。

### 1.4 level-triggered 的机械实现:workqueue 去重 + ResourceVersion 跳过

level-triggered 不只是理念,有机械落地:

- **workqueue 去重**:`workqueue.Typed[T].Add` 先查 `dirty.Has(item)`,若已在 dirty 集则**不重复入队**。50 个快速 spec 变更在 worker 取走第一个前会**坍缩为一次** reconcile(读到最新态)—— 设计性幂等(`kubernetes/kubernetes:staging/src/k8s.io/client-go/util/workqueue/queue.go`,`Add` 方法的 `dirty.Has` 检查)。
- **ResourceVersion 跳过 no-op resync**:`updateReplicaSet` 里 `if curRS.ResourceVersion == oldRS.ResourceVersion { return }` 挡掉周期性 resync 的无变更事件(`deployment_controller.go:L292-296`)。

为什么这对健壮性是决定性的:

| 场景 | edge-triggered(错) | level-triggered(对) |
|---|---|---|
| controller 重启漏了 10 个事件 | 漏 10 次跃迁,卡错态 | 重启重读当前态 → 收敛 |
| 重复投递的 watch 事件 | 处理两次,可能双重 apply | 调和当前态,已收敛则 no-op |
| 事件乱序到达 | 可能在新态后 apply 旧态 | 总读当前态,顺序无关 |
| watch 流断开重连 | 可能漏掉 创建/删除 | 从当前 RV 重 list,全量重同步 |

### 1.5 informer / list-watch / ResourceVersion:高效传播 + 乐观并发

client-go 的 informer 是**分层流水线**:`apiserver →(HTTP long-poll watch)→ Reflector(ListAndWatch)→ DeltaFIFO → Indexer/Store(内存缓存)→ ResourceEventHandler → workqueue`。

- **Reflector** 的 `RunWithContext` 用指数退避循环 `ListAndWatchWithContext`(失败总重试);后者执行 **list-then-watch**:先全量 list 填充 store,再从 `lastSyncResourceVersion` watch(`kubernetes/kubernetes:staging/src/k8s.io/client-go/tools/cache/reflector.go:L106-171` 结构,`L423-435` Run,`L470-509` ListAndWatch,`L589-598` watch 带 `ResourceVersion`)。
- **断线自愈**:watch 失败(网络断、或 RV 过期返回 HTTP 410 Gone)→ Reflector 回退到全量 `list(ctx)` → `Replace()` 整个 store。任何断连后本地缓存都收敛到当前权威态(`reflector.go` `RunWithContext`)。
- **SharedInformer** 的缓存"**eventually consistent with the authoritative state**",多 controller 共享一个 reflector + 一份缓存(`staging/src/k8s.io/client-go/tools/cache/shared_informer.go:L60-70`、`controllers.md:L22-28` 明令"Use SharedInformers")。
- **乐观并发**:`Preconditions.Check` 比对 `ResourceVersion`,不符则 `Precondition failed`;`GuaranteedUpdate` 实现读-改-写重试环 —— 冲突时用最新对象重调 `tryUpdate`,**无分布式锁的并发更新**(`staging/src/k8s.io/apiserver/pkg/storage/interfaces.go`,`Preconditions.Check` ~L113-165,`GuaranteedUpdate` ~L175-220)。

### 1.6 CRD + Operator:扩展控制面

CRD 本身是个 K8s 资源,创建后令 apiserver 动态服务一个**新 typed REST 端点**(`kubernetes/kubernetes:staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:L41-73`,`CustomResourceDefinitionSpec{Group,Names,Scope,Versions}`)。**Operator** = CRD + 一个 watch 该 CRD 并 reconcile 的自定义 controller —— 与内置 controller 用同一套 informer/workqueue/leader-election/乐观并发。这就是"**扩展控制面可识别的资源类型**"的工业范式(衔接 agi-stack 的插件清单 + 能力注册扩展配置类型)。

### 1.7 机制 → agi-stack Rust 映射(Kubernetes)

| Kubernetes 机制 | 来源 · 引用 | agi-stack Rust 落地 |
|---|---|---|
| apiserver = etcd 唯一网关(SSOT) | `apiserver/pkg/storage/interfaces.go` | 云端 **Config Store 服务**(Postgres + REST)是 SSOT;端 agent 从不直连库,读写都过 Config API |
| `spec`(期望)/ `status`(观测)分离 | `api-conventions.md:L280-313` | `DesiredConfig`(spec,CP 下发,DP 不可改)vs `ObservedStatus`(status,DP 回报);分离授权域 |
| `ResourceVersion` + 乐观并发 | `storage/interfaces.go` `Preconditions.Check`/`GuaranteedUpdate` | 每条 `DesiredConfig` 带 `version: u64`;写带 `If-Match`,冲突 409 重读重试;陈旧版本拒绝 |
| controller reconcile(Observe→Diff→Act) | `deployment_controller.go:L572-660` | `DataPlaneReconciler::reconcile(snapshot)`:观测本地 registry → 算 diff → apply |
| **level-triggered**(非 edge) | `controllers.md:L30-35`、`reconcile.go:L90-107` | reconcile 到当前期望态(非逐事件);漏推自愈、重复幂等、乱序无关 |
| workqueue `dirty` 去重 | `util/workqueue/queue.go` `Add` | 同 key 快速变更坍缩为一次 reconcile;重放即幂等 no-op |
| informer/SharedInformer 本地缓存 | `shared_informer.go:L60-70` | DP 本地 `DesiredConfig` 缓存(long-poll/SSE 填充);多子系统共享,eventually consistent |
| Reflector list-then-watch + 410 重 list | `reflector.go:L470-509` | DP 启动/重连先 list 全量,再 watch `?since=version`;过期则全量重 list(断线自愈) |
| CRD + Operator(扩展控制面) | `apiextensions/v1/types.go:L41-73` | 插件清单 + 能力注册扩展 CP 可识别的配置资源类型(**衔接 07**) |
| Leader election(Lease) | `client-go/tools/leaderelection/leaderelection.go:L116-222` | 云端 reconciler 用分布式锁(Redis/DB advisory lock)保每分片单活,心跳续租 |
| `Generation` / `ObservedGeneration` | `apimachinery/.../types.go:L194-197` | `DesiredConfig.version` 单调 + DP 写 `processedVersion`;UI 显示 pending vs applied |

### 1.8 关键引用汇总(Kubernetes)

1. **apiserver = SSOT / 存储接口 + 乐观并发**:`kubernetes/kubernetes:staging/src/k8s.io/apiserver/pkg/storage/interfaces.go`(`storage.Interface`、`GuaranteedUpdate`、`Preconditions.Check`)
2. **spec/status + level-based 权威表述**:`kubernetes/community:contributors/devel/sig-architecture/api-conventions.md:L280-313`
3. **level-driven controller 指南**:`kubernetes/community:contributors/devel/sig-api-machinery/controllers.md:L30-35`
4. **controller-runtime `Reconciler`(level-based 注释 + 退避语义)**:`kubernetes-sigs/controller-runtime:pkg/reconcile/reconcile.go:L63-125`
5. **DeploymentController(SharedInformer + queue)/ syncDeployment**:`kubernetes/kubernetes:pkg/controller/deployment/deployment_controller.go:L67-101`、`L572-660`、`L292-296`
6. **workqueue 去重(dirty 集)**:`kubernetes/kubernetes:staging/src/k8s.io/client-go/util/workqueue/queue.go`(`Add`)
7. **Reflector list-watch + 断线重 list**:`kubernetes/kubernetes:staging/src/k8s.io/client-go/tools/cache/reflector.go:L106-171`、`L423-435`、`L470-509`
8. **SharedInformer eventually-consistent 缓存**:`kubernetes/kubernetes:staging/src/k8s.io/client-go/tools/cache/shared_informer.go:L45-259`
9. **ObjectMeta `ResourceVersion`/`Generation`**:`kubernetes/kubernetes:staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go:L129-296`
10. **CRD 类型定义**:`kubernetes/kubernetes:staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:L41-73`
11. **kubelet 数据面(CRI、不碰 etcd)**:`kubernetes/kubernetes:pkg/kubelet/kubelet.go:L44-86`、`pkg/kubelet/pod_workers.go`
12. **Leader election(Lease,acquire/renew)**:`kubernetes/kubernetes:staging/src/k8s.io/client-go/tools/leaderelection/leaderelection.go:L116-222`

---

## 第二节 · Istio:xDS 分发(istiod = 控制面,Envoy/ztunnel = 数据面)

### 2.1 控制面 istiod vs 数据面 Envoy + istio-agent

Istio 强制分离:**istiod 永不在请求数据路径上**。它纯控制面 —— watch 配置与服务态、算 xDS 资源、经 gRPC 推给每个代理;无生产流量过它。Envoy 处理全部数据面流量,只查本地缓存的 xDS 态。

istiod 是单二进制,合并了三个历史 daemon(`istio/istio:pilot/pkg/bootstrap/server.go:L104-160`,`Server` 结构持 `XDSServer *xds.DiscoveryServer`、`CA *ca.IstioCA`、`configController`):
- **Pilot**:watch K8s Service/Endpoint/Istio CRD → 算 xDS snapshot → `s.XDSServer.AdsPushAll(req)`(`pilot/pkg/xds/ads.go:L565-578`)。
- **Citadel/CA**:签 SPIFFE 工作负载证书,与 ADS 同 gRPC 端口(15010/15012 mTLS)(`pilot/pkg/bootstrap/istio_ca.go:L485-491`、`L156-192`)。
- **Galley**:配置校验 webhook,已折叠进 istiod。

数据面每 pod 两进程:**Envoy**(C++ 转发器,经 xDS 收配置)+ **istio-agent / pilot-agent**(Go sidecar:引导 Envoy、作 Envoy↔istiod 的 xDS 代理、跑本地 SDS server 把密钥送 Envoy 而不落盘)(`istio/istio:pkg/istio-agent/agent.go:L122-147`、`L244-247`,`pilot/cmd/pilot-agent/app/cmd.go:L46-52`)。数据流:**pod 流量 → iptables 重定向(15001/15006)→ Envoy 查本地 xDS 缓存转发**;istiod 只经持久 gRPC 流发**推送事件**,从不拦截活流量。

### 2.2 xDS 协议:typed 资源 + DiscoveryRequest/Response

v3 xDS 资源类型各有自己的 gRPC 服务(`envoyproxy/envoy:docs/root/api-docs/xds_protocol.rst:L24-34`):`Listener→LDS`、`RouteConfiguration→RDS`、`Cluster→CDS`、`ClusterLoadAssignment→EDS`、`Secret→SDS`、`TypedExtensionConfig→ECDS`。核心消息对(`envoyproxy/envoy:api/envoy/service/discovery/v3/discovery.proto:L62-165`):

**DiscoveryResponse**(server→client):`version_info`(该资源类型的当前版本,opaque)、`resources`(Any 编码 typed 资源)、`type_url`(ADS 上识别类型)、`nonce`(本次响应标识,client 在后续请求 echo 以 ACK/NACK)、`control_plane`(发送方标识)。

**DiscoveryRequest**(client→server):`version_info`(最近成功处理的版本,ACK echo server 版本 / NACK echo last-good 版本)、`node`、`resource_names`(订阅集,空=全部)、`type_url`、`response_nonce`(被 ACK/NACK 的响应的 nonce)、`error_detail`(NACK 时填 `google.rpc.Status`)。

### 2.3 ACK / NACK + version + nonce(健壮性的核心)

协议规范(`envoyproxy/envoy:docs/root/api-docs/xds_protocol.rst:L316-455`):

> *"ACK signifies that the individual resources were valid and that the client's intent is to apply them; it contains the version_info from the DiscoveryResponse. NACK signifies that at least one of the resources in the response were considered invalid. A NACK is indicated by the presence of the error_detail field. The version_info indicates the most recent version that the client is using."*
> — `xds_protocol.rst:L437-455`

**核心健壮性保证 —— NACK 时 client 保留 last-good config**,有两处证据:
1. NACK 的 `DiscoveryRequest.version_info` 填**上一个 good 版本**(非被拒版本),server 据此知道代理仍跑旧配置。
2. 文件订阅亦遵此:*"The last valid configuration for an xDS API will continue to apply if a configuration update rejection occurs."*(`xds_protocol.rst:L84-87`)

Istio 控制面侧 `WatchedResource` 按 type_url 跟踪 `NonceSent/NonceAcked/LastError`;`ShouldRespond` 实现完整 ACK/NACK 逻辑:`request.ErrorDetail != nil`(NACK)→ 记 `LastError`、`IncrementXDSRejects`、**不推新配置**;ACK → 清 `LastError`、记 `NonceAcked`(`istio/istio:pkg/xds/server.go:L62-95`、`L192-275`、`L330-355`)。

**ztunnel(Rust 数据面)的对应实现** —— 可直接移植的参照(`istio/ztunnel:src/xds/client.rs:L681-746`):
```rust
async fn handle_stream_event(&mut self, response: DeltaDiscoveryResponse,
    send: &mpsc::Sender<DeltaDiscoveryRequest>) -> Result<XdsSignal, Error> {
    let nonce = response.nonce.clone();
    let handler_response: Result<(), Vec<RejectedConfig>> =
        match self.config.handlers.get(&strng::new(&type_url)) {
            Some(h) => h.handle(&mut self.state, response),  // 失败不改 state
            None => Ok(()),
        };
    let (response_type, error) = match handler_response {
        Err(rejects) => (XdsSignal::Nack, Some(/* 聚合 rejects */)),
        _ => (XdsSignal::Ack, None),
    };
    send.send(DeltaDiscoveryRequest { type_url, response_nonce: nonce,
        error_detail: error.map(|msg| Status { message: msg, ..Default::default() }),
        ..Default::default() }).await?
}
```
> **健壮性分析**:NACK **不 apply 被拒配置**,代理继续跑 last-good;handler 返回 `Err(Vec<RejectedConfig>)` 时 state 未被新(坏)资源改动,只有后续成功 `handle`(修正后的推送)才更新 state。`RejectedConfig` 类型 + `handle_single_resource` 干净地把资源级错误与流级错误分离(`istio/ztunnel:src/xds.rs:L66-93`)。

### 2.4 ADS:单流有序避免配置竞态

> *"ADS allow a single management server, via a single gRPC stream, to deliver all API updates. This provides the ability to carefully sequence updates to avoid traffic drop... A single ADS stream is available per Envoy instance."*
> — `xds_protocol.rst:L818-832`;服务定义 `envoyproxy/envoy:api/envoy/service/discovery/v3/ads.proto`

非 ADS(分离流)下 CDS/LDS 在独立流到达、无顺序保证,Listener 可能引用还没到的 Cluster → 流量掉。ADS 让控制面在一条流上**排序**:Istio 显式定义 `PushOrder = [CDS, EDS, LDS, RDS, SDS, ...]`(`istio/istio:pilot/pkg/xds/ads.go:L504-515`)。nonce 按 type_url **分别跟踪**,CDS NACK 不影响 LDS(逻辑独立子流)。

### 2.5 SotW vs Delta/Incremental xDS

四个变体 = {SotW, Incremental} × {per-type 流, ADS}(`xds_protocol.rst:L120-155`)。Delta xDS 不发全量快照,只发 diff,有**逐资源版本**(`DeltaDiscoveryResponse{resources, removed_resources}`,`DeltaDiscoveryRequest{resource_names_subscribe, resource_names_unsubscribe, initial_resource_versions}`,`discovery.proto:L168-310`)。重连时 client 发 `initial_resource_versions`(资源名→已知版本)让 server 跳过未变资源。

| 维度 | SotW | Delta |
|---|---|---|
| server 变更时发 | 该类型全量资源集 | 仅 变更/新增/删除 名 |
| 大规模带宽(如 10 万 cluster) | 高(每次全量) | 低(仅 1 个变更) |
| 实现复杂度 | 低(无状态 server) | 高(server 须跟每 client 态) |
| nonce | SotW gRPC 可选 | **必需** |

**ztunnel 只用 Delta/Incremental ADS**(`client.delta_aggregated_resources(req)`,`istio/ztunnel:src/xds/client.rs:L645`)。

### 2.6 最终一致

> *"Since Envoy's xDS APIs are eventually consistent, traffic may drop briefly during updates... to avoid traffic drop, sequencing of updates should follow a **make before break** model: CDS updates must always be pushed first; EDS after CDS; LDS after CDS/EDS; RDS after LDS..."*
> — `xds_protocol.rst:L737-773`

无跨网格全局事务:istiod 异步推每个代理,各自独立 apply。单代理内 ADS+PushOrder 把不一致窗口压到近零;跨代理无顺序保证。资源 **TTL** 作安全阀:控制面死了可让资源过期,移除陈旧配置而非无限持有(`xds_protocol.rst:L780-808`)。

### 2.7 SDS:密钥经 xDS 下发不落盘

SDS 跑同一套 `DiscoveryRequest/Response`,但送 `Secret` 载荷,关键是**私钥经 gRPC 内存下发、从不落盘**。istio-agent 跑本地 Unix-socket SDS server,Envoy 向它(而非 istiod)取证;`generate()` 把 cert/key 以 `InlineBytes` 内联进 `DiscoveryResponse`(`istio/istio:security/pkg/nodeagent/sds/sdsservice.go:L128-155`、`L234-248`)。证书启动时**主动预热**(指数退避 `GenerateSecret`,`L95-115`)。→ 衔接 agi-stack 的 HITL `env_var` + `response_data_encrypted` 密封下发。

### 2.8 数据面拓扑:sidecar vs ambient(ztunnel/waypoint)

- **经典 sidecar**:每 pod 注入一个 Envoy,iptables 重定向 inbound(15006)/outbound(15001)全过 Envoy(mTLS、遥测、策略、重试、熔断)(`pilot/pkg/bootstrap/sidecarinjector.go`)。
- **Ambient mesh**:移除 per-pod sidecar。流量在**节点级**被 CNI 捕获,重定向到 per-node **ztunnel**(Rust,DaemonSet 每节点一个,处理 **L4 mTLS 隧道** HBONE/15008,从 istiod 收 Delta ADS workload/service 拓扑,轻量、无 per-HTTP 逻辑);**waypoint** 是按需的、namespace/SA 范围的 Envoy,处理 **L7**(HTTP 路由、AuthorizationPolicy、重试),仅需要时部署(`istio/ztunnel:ARCHITECTURE.md:L1-23`,端口表;`src/xds.rs:L31-36` Istio-custom xDS 资源类型)。

> **关键解耦**:L4(常开)ztunnel 极低开销为每 pod 建 mTLS;L7(按需)waypoint 只在需要复杂路由处处理。ztunnel 跑**双 Tokio runtime**:admin/xDS 单线程 runtime 与 worker 多线程 runtime 隔离,防 xDS 处理给数据面加延迟(`ARCHITECTURE.md:L1-8`)。→ 直接映射 agi-stack 端上"轻量常开 DP(ztunnel 式)+ 按需重型工具代理(waypoint 式)"。

### 2.9 ztunnel(Rust)可直接移植的模式(本次最大收获)

ztunnel 证明数据面可以是地道 Rust,以下模式可直接 fork(`istio/ztunnel`):
1. **Delta ADS client**(`src/xds/client.rs`):`handle_stream_event` → ACK/NACK 环,`tonic`(gRPC)+ `tokio` + `prost`,生产级。
2. **`RejectedConfig` + `handle_single_resource`**(`src/xds.rs:L66-93`):干净分离资源级 NACK 与流级错误,Rust 地道的逐资源错误聚合。
3. **`ProxyStateUpdateMutator` 写锁模式**(`src/xds.rs:L104-112`):全部状态变更包在 `Arc<RwLock<ProxyState>>`,保证配置更新相对数据面读路径的原子性 —— agi-stack 的 `ArcSwap<ToolRegistry>` 是其无锁等价。
4. **重连指数退避 + `initial_resource_versions`**(`src/xds/client.rs`):防不必要的重发。
5. **双 runtime 隔离**:admin/xDS 与 worker 分离,防配置处理影响 P99 —— 对任何处理活流量的 AI agent 平台至关重要。

### 2.10 机制 → agi-stack Rust 映射(Istio/xDS)

| Istio/xDS 机制 | 来源 · 引用 | agi-stack Rust 落地 |
|---|---|---|
| `DiscoveryResponse{version_info, nonce, type_url, resources}` | `envoyproxy/envoy:discovery.proto:L133-165` | `ConfigSnapshot{type_url, version, nonce, resources}` 从云 CP 推给端 DP(Spike 已落) |
| **ACK**:`{version=X, nonce=A, 无 error}` | `xds_protocol.rst:L384-397` | `ConfigAck::Ack{version, nonce}` —— DP 成功 apply,CP 记 applied=X |
| **NACK**:`{version=last_good, nonce=A, error_detail}` | `xds_protocol.rst:L399-416` | `ConfigAck::Nack{version, nonce, error}` —— DP 拒绝,留 last-good |
| **NACK 保留 last-good** | `xds_protocol.rst:L84-87`、ztunnel `src/xds.rs:L66` | `DataPlaneReconciler.last_good`,只在 ACK 替换;坏配置不 brick DP |
| `nonce` 每响应 | `discovery.proto` `nonce` 字段 | 每 push 一 nonce,关联 in-flight ACK |
| `type_url` 类型复用 | `discovery.proto` `type_url` 字段 | `TOOL_REGISTRY_TYPE_URL` 等;DP 拒绝错类型快照(type-check) |
| **ADS** 单流有序 | `ads.proto`、`xds_protocol.rst:L818-832` | 每 DP 单一有序配置流,避免类型间竞态 |
| **PushOrder**(CDS→EDS→LDS→RDS) | `istio/istio:pilot/pkg/xds/ads.go:L504-515` | 推序 `依赖→服务→策略→密钥`,避免悬挂引用 |
| **Delta/Incremental xDS** | `discovery.proto:L168-310`、ztunnel `client.rs:L645` | `DeltaConfigPush{added, removed}`(大规模);Spike 现用 SotW 全量,Delta 列为未来 |
| `initial_resource_versions` 重连 | `discovery.proto:L236-254` | 重连发 `{name→version}`,CP 跳过未变 |
| **最终一致** | `xds_protocol.rst:L737-773` | CP 推、DP 各自收敛;无跨 DP 事务;显式契约 |
| **SDS** 密钥不落盘 | `sdsservice.go:L128-248` | env_var/secret 经同流 `InlineBytes` 下发;衔接 HITL `response_data_encrypted` |
| Citadel/CA + SPIFFE | `pilot/pkg/bootstrap/istio_ca.go:L485-491` | 云 CP 签短期 agent 证书,主动轮换 |
| **sidecar**(每 workload 一代理) | `sidecarinjector.go` | DP 与 workload 同置;端上 embedded DP = "sidecar 被推配置后本地自治" |
| **ztunnel**(L4 常开,Rust) | `istio/ztunnel:ARCHITECTURE.md`、`src/xds.rs` | 端上轻量常开 DP:薄 Rust 执行器,收 Delta xDS 更新 |
| **waypoint**(L7 按需) | ambient 设计 | 按需重型工具代理:复杂工具编排时才实例化 |
| `Arc<RwLock<ProxyState>>` 原子更新 | ztunnel `src/xds.rs:L104-112` | `ArcSwap<ToolRegistry>` 无锁等价(读路径零锁) |
| 双 runtime 隔离 | ztunnel `ARCHITECTURE.md:L1-8` | xDS/admin 与 worker 分离,防配置处理影响数据面 P99 |

### 2.11 关键引用汇总(Istio/xDS)

1. **DiscoveryRequest/Response + Delta**:`envoyproxy/envoy:api/envoy/service/discovery/v3/discovery.proto:L62-310`
2. **ADS 服务定义**:`envoyproxy/envoy:api/envoy/service/discovery/v3/ads.proto`
3. **ACK/NACK + version/nonce 规范**:`envoyproxy/envoy:docs/root/api-docs/xds_protocol.rst:L316-455`(+ `L84-87` last-good)
4. **最终一致 + make-before-break 排序**:`envoyproxy/envoy:docs/root/api-docs/xds_protocol.rst:L737-773`
5. **SotW vs Delta 四变体**:`envoyproxy/envoy:docs/root/api-docs/xds_protocol.rst:L120-155`、`L845-855`
6. **SDS(密钥不落盘)**:`istio/istio:security/pkg/nodeagent/sds/sdsservice.go:L95-248`、`envoyproxy/envoy:api/envoy/service/secret/v3/sds.proto`
7. **istiod Server 结构(Pilot/CA/Galley 合一)**:`istio/istio:pilot/pkg/bootstrap/server.go:L104-160`、`L234-420`
8. **AdsPushAll / PushOrder**:`istio/istio:pilot/pkg/xds/ads.go:L183-185`、`L504-515`、`L565-578`
9. **istiod 侧 ACK/NACK 状态机**:`istio/istio:pkg/xds/server.go:L62-355`(`WatchedResource`、`ShouldRespond`、`Send`)
10. **ztunnel(Rust)ACK/NACK 数据面**:`istio/ztunnel:src/xds/client.rs:L645`、`L681-746`;`src/xds.rs:L66-115`;`ARCHITECTURE.md:L1-23`
11. **istio-agent(数据面引导 + 本地 SDS/xDS 代理)**:`istio/istio:pkg/istio-agent/agent.go:L122-247`、`pilot/cmd/pilot-agent/app/cmd.go:L46-52`

---

## 两系统对照:同一条轴的两半

| | Kubernetes | Istio/xDS |
|---|---|---|
| 控制面 | kube-apiserver(+ etcd) | istiod(Pilot/Citadel/Galley) |
| 数据面 | kubelet / kube-proxy(节点) | Envoy / ztunnel + istio-agent(pod/node) |
| 配置模型 | 声明式 spec/status,**DP 自算 diff** | typed 资源经 xDS push,**CP 算 diff(Delta)或发全量(SotW)** |
| 触发模型 | **level-triggered**(读当前态收敛) | push + ACK/NACK(版本化) |
| 一致性 | eventually consistent(informer 缓存) | eventually consistent(make-before-break) |
| 版本/并发 | `ResourceVersion` 乐观并发 | `version_info` + `nonce` |
| 坏配置 | reconcile 不前进,status 反映错误 | **NACK 保留 last-good** |
| 断连自治 | 节点用本地缓存继续跑 | Envoy 用 last-good config 继续跑 |
| 扩展控制面 | CRD + Operator | (Istio CRD,经 K8s) |

> **综合**:K8s 贡献"**声明式 + level-triggered + SSOT**"(DP 自算 diff、漏推自愈),Istio 贡献"**版本化 typed 分发 + ACK/NACK + last-good + 最终一致**"(坏配置不致瘫、断连容忍)。agi-stack 的 Spike(`crates/plugin-host/{control_plane,reconcile}.rs`)把两者合成一个**纯同步、运行时无关**的 CP→DP reconcile。综合设计与取舍见 [08-control-data-plane-separation](../architecture/08-control-data-plane-separation.md);决策见 [ADR-0009](../adr/0009-control-data-plane-separation.md)/[ADR-0010](../adr/0010-xds-style-config-distribution.md)。
