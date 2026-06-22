# Feishu Channel Plugin

飞书 (Lark) IM 平台集成插件，提供消息收发、文档管理、知识库、云盘、多维表格、卡片构建等完整能力。

## 概览

本插件从 `src/infrastructure/adapters/secondary/channels/feishu/` 迁移而来，作为 MemStack 本地插件运行。支持 WebSocket 长连接和 Webhook 回调两种接入模式。

## 文件结构

```
.memstack/plugins/feishu/
├── memstack.plugin.json    # 插件清单 (id, kind, version 等元数据)
├── __init__.py             # 包标识 (空文件)
├── plugin.py               # 插件入口 (FeishuChannelPlugin + _load_sibling)
├── adapter.py              # 主适配器 (FeishuAdapter，实现 ChannelAdapter 接口)
├── client.py               # API 客户端 (FeishuClient，统一封装飞书 Open API)
├── media.py                # 媒体子客户端 (FeishuMediaManager，图片/文件上传下载)
├── docx.py                 # 文档子客户端 (FeishuDocxClient，文档 CRUD)
├── wiki.py                 # 知识库子客户端 (FeishuWikiClient，空间/节点管理)
├── drive.py                # 云盘子客户端 (FeishuDriveClient，文件/文件夹操作)
├── bitable.py              # 多维表格子客户端 (FeishuBitableClient + FIELD_TYPE_* 常量)
├── cards.py                # 卡片构建器 (CardBuilder, PostBuilder)
├── cardkit_streaming.py    # CardKit 流式卡片 (CardKitStreamingManager, CardStreamState)
├── hitl_cards.py           # HITL 交互卡片 (HITLCardBuilder)
├── rich_cards.py           # 富文本卡片 (RichCardBuilder)
├── media_downloader.py     # 媒体下载器 (FeishuMediaDownloader)
└── webhook.py              # Webhook 处理器 (FeishuWebhookHandler, FeishuEventDispatcher)
```

## 插件发现与加载

### 发现机制

MemStack 插件运行时 (`PluginRuntimeManager`) 扫描 `.memstack/plugins/` 目录，查找包含 `memstack.plugin.json` 清单的子目录。清单定义了插件 ID、类型和元数据:

```json
{
  "id": "feishu-channel-plugin",
  "kind": "channel",
  "name": "Feishu Channel Plugin",
  "version": "1.0.0",
  "channels": ["feishu"]
}
```

### 加载流程

1. 发现阶段: `discovery.py` 扫描目录，读取 `memstack.plugin.json`
2. 加载阶段: `loader.py` 导入 `plugin.py`，获取模块级 `plugin` 属性
3. 注册阶段: 调用 `plugin.setup(api: PluginRuntimeApi)`，注册渠道类型和配置

### `_load_sibling` 模式

由于本地插件通过 `importlib.util.spec_from_file_location` 加载，不具备 Python 包上下文，**相对导入不可用**。所有模块间引用使用 `_load_sibling()` 函数:

```python
_PLUGIN_DIR = Path(__file__).resolve().parent

def _load_sibling(module_file: str) -> ModuleType:
    file_path = _PLUGIN_DIR / module_file
    module_name = f"feishu_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

子客户端 (`media.py`, `docx.py`, `wiki.py`, `drive.py`, `bitable.py`, `cardkit_streaming.py`) 在 `client.py` 中通过懒加载 `@property` 引入，避免循环依赖。

## Facade 桥接

现有消费方 (应用层服务、API 路由、测试) 通过过渡门面访问插件模块:

```
src/infrastructure/adapters/secondary/channels/feishu_facade.py
```

门面使用 `importlib` 从本目录加载模块，并缓存到 `sys.modules` (命名空间: `memstack_plugins_feishu.*`)。

### 可用 getter 函数

| 函数 | 加载模块 | 主要导出 |
|------|---------|---------|
| `get_client_module()` | `client.py` | `FeishuClient`, `send_feishu_card`, `send_feishu_text` |
| `get_adapter_module()` | `adapter.py` | `FeishuAdapter` |
| `get_cards_module()` | `cards.py` | `CardBuilder`, `PostBuilder` |
| `get_cardkit_streaming_module()` | `cardkit_streaming.py` | `CardKitStreamingManager`, `CardStreamState` |
| `get_hitl_cards_module()` | `hitl_cards.py` | `HITLCardBuilder` |
| `get_rich_cards_module()` | `rich_cards.py` | `RichCardBuilder` |
| `get_media_downloader_module()` | `media_downloader.py` | `FeishuMediaDownloader` |
| `get_bitable_module()` | `bitable.py` | `FIELD_TYPE_*` 常量 |

### 使用示例

```python
from src.infrastructure.adapters.secondary.channels.feishu_facade import (
    get_client_module,
    get_cards_module,
)

FeishuClient = get_client_module().FeishuClient
CardBuilder = get_cards_module().CardBuilder

client = FeishuClient(app_id, app_secret)
card = CardBuilder.create_markdown_card(content="# Hello", title="Test")
await client.send_card_message("oc_xxx", card)
```

## 配置

### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `FEISHU_APP_ID` | 是 | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 是 | 飞书应用 App Secret |
| `FEISHU_ENCRYPT_KEY` | 否 | Webhook 加密密钥 |
| `FEISHU_VERIFICATION_TOKEN` | 否 | Webhook 验证令牌 |

### 连接模式

- **WebSocket** (默认): 长连接，适合实时消息场景
- **Webhook**: 回调模式，需配置公网可达的回调地址

### 通过 Agent 工具启用

```python
plugin_manager(action="enable", plugin_name="feishu-channel-plugin")
plugin_manager(action="reload")
```

## 参考

- [飞书开放平台](https://open.feishu.cn/)
- [Channels 模块文档](../../../../src/infrastructure/adapters/secondary/channels/README.md)
- [插件系统架构](../../../../docs/archive/architecture/PLUGIN_TOOL_SUBSYSTEM_REFACTORING_PROPOSAL.md)
- [迁移计划](../../../../docs/architecture/FEISHU_PLUGIN_MIGRATION_PLAN.md)
