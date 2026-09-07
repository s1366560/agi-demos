# Channels Module

> Last checked: 2026-08-25

渠道领域保留现有 FastAPI、应用服务和 Feishu 实现，但生产装配由 Protocol V2 generation
负责。`.memstack/plugins/*` 本地目录扫描、V1 manifest 和运行时 `setup(api)` 已退役。

## V2 组合边界

生产 Profile 显式启用两个模块：

- `builtin://memstack/channel/adapter-catalog`
- `builtin://memstack/channel/feishu-adapter`

它们公开：

- `service:channel-adapter-catalog`
- `service:channel-adapter-resolver`
- `channel.runtime.reload` 类型化事件

精确 contract、配置 Schema、依赖 alias 和 digest 位于：

- `config/plugin-manifests-v2/memstack-runtime-kernel.v2.json`
- `config/plugin-profiles/memstack-default.v2.yaml`
- `shared/catalogs/plugin-module-catalog.v2.json`
- `shared/graphs/plugin-service-dependencies.v2.json`
- `shared/graphs/plugin-events.v2.json`

## 代码结构

```text
src/domain/model/channels/                  # 消息与渠道领域模型
src/application/services/channels/          # 应用编排、HITL、媒体导入
src/infrastructure/adapters/secondary/channels/
  feishu/                                   # 内置 Feishu 实现
  channel_plugin_loader.py                  # 内置实现模块加载适配器
  connection_manager.py                     # 连接生命周期
src/infrastructure/plugins/v2/channel_adapters.py
                                             # V2 catalog/provider effects
```

`channel_plugin_loader.py` 只负责加载仓库内置实现，不能作为 V1 插件发现或 Profile
authority。生产调用方通过当前 generation 的 `ChannelAdapterResolverV2` 获取 metadata 和
adapter；不得从 `.memstack/plugins` 注册实现。

## 生命周期

1. Loader 在执行入口点前验证 manifest/catalog/runtime digest。
2. catalog effect 注册 resolver service。
3. Feishu contribution 通过 Profile alias 注入 catalog。
4. request/operation 从 pinned generation 解析 resolver。
5. generation 替换或 candidate 失败时 disposer 逆序释放贡献和连接资源。

缺少 catalog、未知 channel type、配置 Schema 错误或实现加载失败必须结构化失败；不得回退
V1 registry 或静态 builtin 选择。

## 凭据和安全

- `FEISHU_APP_SECRET`、verification token 等凭据只来自环境或授权 vault/grant。
- 日志、receipt、Profile、Bundle 和 generation descriptor 不得包含明文凭据。
- Webhook/HITL 响应仍执行 tenant/project、source component 和 action membership 校验。
- Feishu callback 必须 marshaling 到捕获的应用 event loop，不能直接复用 websocket callback
  loop。

## 修改与验证

修改 channel contract、effect 或 Profile 后运行：

```bash
uv run python scripts/generate_plugin_protocol_v2.py
uv run python scripts/generate_plugin_protocol_v2.py --check
make plugin-v2-contract-gate
uv run pytest src/tests/unit/infrastructure/plugins/v2/test_channel_adapters.py -q
uv run pytest src/tests/unit/infrastructure/channels -q
```

运行真实 Feishu 集成时使用环境或 vault 中已有配置；不要把 secret 写进测试、文档或命令
输出。
