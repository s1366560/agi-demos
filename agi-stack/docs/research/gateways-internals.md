# 网关内部设计调研:ShenYu / Kong / Higress(proxy-wasm)→ 热插拔 · 可扩展

> 目标:学习三类开源 API 网关如何做到**插件链可扩展**与**配置/插件热插拔**,提炼可移植到 Rust AI Agent 核心的设计模式。综合落地见 [06-agent-core-design §2/§3](../architecture/06-agent-core-design.md)。

## 一、Apache ShenYu —— 责任链 + Copy-on-Write 热插拔

### 1.1 Plugin Chain = 迭代器,不是递归
`ShenyuPlugin` 接口是契约点:`execute(exchange, chain)` / `getOrder()` / `skip(exchange)` / `before` / `after`。执行器 `DefaultShenyuPluginChain`(`ShenyuWebHandler` 内部类)用 **`index` 推进**而非递归:插件持有 `chain` 引用,调用 `chain.execute()` 继续,**不调用则截断链**(短路,如鉴权失败直接返回)。链是 per-request 一次性对象,`index` 存实例内,无并发竞争。
> `apache/shenyu:shenyu-web/.../ShenyuWebHandler.java`(`DefaultShenyuPluginChain.execute`,~210-230)

### 1.2 Selector / Rule 两级匹配
`AbstractShenyuPlugin.execute()` 模板方法:① 读 `BaseDataCache` 判 enabled → ② Selector 匹配(L1 LRU → L2 Trie → 线性)→ ③ Rule 匹配(同两级缓存)→ ④ `doExecute()` 委托子类。**先粗(selector)后细(rule)**。
> `apache/shenyu:shenyu-plugin/shenyu-plugin-base/.../AbstractShenyuPlugin.java`(~75-130)

### 1.3 热插拔三路径
- **A · Enable/Disable(毫秒级)**:`ShenyuWebHandler` 监听 `PluginHandlerEvent`,`onPluginEnabled/Removed` 用 **Copy-on-Write**:`new ArrayList<>(this.plugins)` → 增删 → `this.plugins = newList`(volatile 原子换),**读路径零锁**。`SORTED` 事件触发 `sortPlugins()` 重排。
- **B · ext-lib JAR 轮询**:`ShenyuLoaderService` `scheduleAtFixedRate` 定时扫描目录加载。
- **C · 自定义 ClassLoader 上传**:`ShenyuPluginLoader.findClass()` + `defineClass()` + `getOrCreateSpringBean()`,Base64 JAR 即时加载。
- **排序运行时可改**:`sortPlugins()` 优先读管理面同步的 `getSort()`,fallback 编译期 `getOrder()` → 不重启调序。

## 二、Kong —— CP/DP 分离(Hybrid Mode)

### 2.1 两阶段 Phase 模型 + 组合 key
`plugins_iterator.lua` 两阶段:先**收集**适用插件,再按 Phase(`access`/`header_filter`/`body_filter`/...)执行。`lookup_cfg()` 用 **8 级 Route/Service/Consumer 组合 key 优先级**,最精确匹配 wins。`create_configure()` 提供批量配置刷新钩子(`configure` phase)。

### 2.2 控制面 / 数据面分离 + 配置 hash
- **CP** `control_plane.lua`:`push_config()` 经 WebSocket + semaphore 队列推送。
- **DP** `data_plane.lua`:**三线程模型**(recv 配置 / apply 配置 / heartbeat 报版本),`calculate_config_hash()` 比对后**幂等 apply**,跳过重复更新;断线重连全量重传。
> 这是"云端控制面 → 边缘/端上数据面"推送的最佳参考模板。

## 三、Higress / Envoy / proxy-wasm —— 跨宿主稳定 ABI

### 3.1 proxy-wasm ABI(v0.2.1)+ 三级上下文
`VMContext → PluginContext → HttpContext` 三级:VM(运行时)→ Plugin(含配置,`proxy_on_configure`)→ Http(单次请求)。host↔guest 经版本化 ABI 约定,**不同 host 实现可互换**(Envoy/Kong/自研)。
> `tetratelabs/proxy-wasm-go-sdk:proxywasm/types/context.go`;`proxy-wasm/spec:abi-versions/v0.2.1/README.md`

### 3.2 Higress ai-agent:WASM 内的完整 ReAct
`ai-agent/main.go` 在 Envoy filter 内异步跑完整 ReAct:`onHttpRequestBody` 构 ReAct prompt 发 LLM;`onHttpResponseBody` 解析 —— `Final Answer` → `ActionContinue`;`Action: tool` → `wrapper.HttpClient.Call()` 异步调工具 + **返回 `ActionPause` 挂起响应流**,工具回调拼 `Observation` 再请求 LLM,递归到 Final Answer 或 `MaxIterations`(计数器存 per-request context)。**证明 ReAct 可在 WASM 内以 ActionPause/回调协程风格异步跑完,宿主不阻塞。**
> `higress-group/higress:plugins/wasm-go/extensions/ai-agent/main.go`

### 3.3 零重启热更新
管理员改 `WasmPlugin` CRD → Higress CP 生成 xDS → Envoy 收 **ECDS**(Extension Config Discovery Service)→ 启**新 Wasm VM** 加载新 `.wasm` → 新请求路由到新 VM → 旧 VM drain 后销毁。**隔离性(每插件独立线性内存)是零重启的根本保证**,新旧版本并存不互污。

## 四、JVM 动态加载 vs Wasm 热插拔(为何不可信代码只走 WASM)

| 维度 | ShenYu/JVM SPI(`cdylib` 类比) | proxy-wasm / Wasmtime |
|---|---|---|
| 隔离性 | ClassLoader 隔离,**共享 JVM 堆**,类污染风险 | 线性内存隔离,syscall 走 hostcall 白名单,**沙箱级** |
| 热更新代价 | 旧 ClassLoader 等 GC(被引用则无法回收) | 新 VM ~毫秒启动,旧 VM drain 后销毁,**干净生命周期** |
| 跨平台 | 仅 JVM;iOS/浏览器不可用 | wasm32 目标;Wasmtime(服务器)/ Wasmi(iOS/embedded)/ 浏览器原生 |
| iOS 无 JIT | 不适用 | **Wasmi 解释器无 JIT**,App Store 合规 |
| 第三方不可信代码 | **不安全**(同进程内存) | **安全**(沙箱 + hostcall 白名单) |

→ 印证 [ADR-0002](../adr/0002-untrusted-plugins-wasm-only.md):不可信工具**只走 WASM**。

## 五、机制 → AI Agent 核心映射(节选)

| 借鉴机制 | 来源 | MemStack 设计点 | 目标 |
|---|---|---|---|
| 责任链 + index 迭代器 | ShenYu `DefaultShenyuPluginChain` | `ToolChain`(Vec<Arc<dyn Tool>> + index,`Continue/Halt/Pause`) | 可扩展 |
| `skip()` 条件短路 | ShenYu `ShenyuPlugin.skip()` | `Tool::should_run(&ctx)` | 可扩展 |
| Selector/Rule 两级匹配 | ShenYu `AbstractShenyuPlugin` | Skill 触发:粗 selector + 细 rule | 可扩展 |
| Copy-on-Write 换表 | ShenYu `onPluginEnabled/Removed` | `Arc<ArcSwap<ToolRegistry>>` 原子换,读无锁 | 热插拔 |
| `PluginDataSubscriber` 观察者 | ShenYu | `trait ToolConfigSubscriber` | 热插拔 |
| 排序运行时可改 | ShenYu `sortPlugins()` | `tool_config.priority: u32` + 重排换表 | 可扩展 |
| 组合 key 最精确匹配 | Kong `lookup_cfg()` | `(agent_type, skill_id, user_group)` key | 可扩展 |
| CP/DP 分离 + hash 幂等 | Kong `control_plane`/`data_plane` | ToolConfig 控制面 → 端上 ToolHost 数据面,`version`/hash 幂等 apply | 热插拔 |
| 三级上下文 ABI | proxy-wasm context.go | `WasmRuntime→WasmToolModule→WasmToolInvocation` | 热插拔+可扩展 |
| `ActionPause` + 异步回调 | Higress ai-agent | WASM 工具 hostcall 异步 + host 持 `Waker` resume | 可扩展 |
| Wasm VM 隔离 | proxy-wasm spec | 不可信 MCP 工具走 `WasmSandboxAdapter` | 热插拔+可扩展 |

## 六、关键引用汇总

| 引用 | 内容 |
|---|---|
| `apache/shenyu:shenyu-plugin/shenyu-plugin-api/.../ShenyuPlugin.java` | Plugin 接口(execute/getOrder/named/skip/before/after) |
| `apache/shenyu:shenyu-web/.../ShenyuWebHandler.java` | 责任链迭代器 + Copy-on-Write 热插拔 + `PluginHandlerEvent` |
| `apache/shenyu:shenyu-plugin/shenyu-plugin-base/.../AbstractShenyuPlugin.java` | Selector/Rule 两级匹配 + LRU/Trie 缓存 |
| `apache/shenyu:shenyu-web/.../ShenyuPluginLoader.java` | 自定义 ClassLoader + defineClass |
| `apache/shenyu:shenyu-web/.../ShenyuLoaderService.java` | 定时扫描 + Base64 JAR 即时加载 |
| `apache/shenyu:.../PluginDataSubscriber.java` | 控制面→数据面订阅接口 |
| `Kong/kong:kong/runloop/plugins_iterator.lua` | 两阶段收集-执行 + 8 级优先级组合 key |
| `Kong/kong:kong/clustering/control_plane.lua` | CP push_config + WebSocket + semaphore |
| `Kong/kong:kong/clustering/data_plane.lua` | DP 三线程 + config hash + 幂等 apply |
| `Kong/kong:kong/runloop/wasm.lua` | Kong Wasm filter 与 Lua plugin 分离点 |
| `tetratelabs/proxy-wasm-go-sdk:proxywasm/types/context.go` | VMContext/PluginContext/HttpContext 三级上下文 |
| `proxy-wasm/spec:abi-versions/v0.2.1/README.md` | proxy-wasm ABI 规范 |
| `higress-group/higress:plugins/wasm-go/extensions/ai-agent/main.go` | ReAct 在 proxy-wasm 中实现(ActionPause + 异步工具) |
| `higress-group/higress:.../ai-agent/config.go` | Wasm 插件配置解析 + LLM/Tool 配置结构 |

## 七、核心结论(5 条)

1. **责任链 = 迭代器,非递归**(`index` 推进),Rust 可用 `index: usize` 精确复刻,无栈深问题。
2. **热插拔本质 = ABI 边界 + 原子替换**:ShenYu = ClassLoader 边界 + volatile swap;proxy-wasm = WASM 线性内存边界 + xDS 触发 VM 重建;Rust = `dyn Tool`/WASM 边界 + `ArcSwap`。
3. **Kong CP/DP 分离是端侧配置推送最优参考**:push loop + hash 比对 + WebSocket 三线程 + 幂等。
4. **proxy-wasm ABI 是跨宿主稳定 ABI 的成熟方案**:三级上下文 + `ActionContinue/Pause` + 异步 hostcall,可直接翻成 Rust trait,宿主可换(Wasmtime/Wasmi)。
5. **端上核心**(iOS+浏览器)只能走 `dyn Trait` 内置 + Wasmi 解释 + HTTP/WS 配置同步;服务器追加 Wasmtime + cdylib + gRPC。
