# WeCom Channel Plugin

企业微信 (WeCom) IM 平台集成插件，提供消息收发、媒体管理、用户管理等完整能力。支持 Webhook 回调模式接入。

## 功能特性

- **消息收发**: 支持文本、图片、文件、语音、视频、卡片消息
- **用户管理**: 获取用户信息、部门用户列表
- **部门管理**: 部门列表查询
- **媒体操作**: 文件上传下载
- **菜单管理**: 应用菜单创建/查询/删除
- **标签管理**: 标签创建、用户标签管理

## 目录结构

```
.memstack/plugins/wecom/
├── memstack.plugin.json    # 插件配置文件
├── plugin.py               # 插件入口
├── adapter.py              # Channel 适配器实现
├── client.py               # API 客户端
├── webhook.py              # Webhook 处理器
└── README.md               # 本文档
```

## 快速开始

### 1. 企业微信配置

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)
2. 创建自建应用：进入「应用管理」→「创建应用」
3. 获取应用凭证：
   - `AgentId` (应用 ID)
   - `Secret` (应用密钥)
4. 获取企业信息：
   - `CorpId` (企业 ID)：在「我的企业」→「企业信息」中获取
5. 配置接收消息：
   - 设置「API 接收消息」的回调 URL
   - 设置 `Token` 和 `EncodingAESKey`（可选，用于消息加密）

### 2. 插件启用

```bash
# 启用插件
plugin_manager(action="enable", plugin_name="wecom-channel-plugin")
```

### 3. 渠道配置

配置渠道时需要提供以下参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `corp_id` | 是 | 企业 ID (wwxxx) |
| `agent_id` | 是 | 应用 AgentId |
| `secret` | 是 | 应用 Secret |
| `token` | 否 | 回调 Token (用于验证) |
| `encoding_aes_key` | 否 | 回调 EncodingAESKey (用于消息加密) |
| `connection_mode` | 否 | 连接模式，默认 `webhook` |
| `webhook_port` | 否 | Webhook 服务端口，默认 8000 |
| `webhook_path` | 否 | Webhook 路径，默认 `/api/v1/channels/events/wecom` |

## 编程使用

### 基础使用

```python
from src.domain.model.channels.message import ChannelConfig
from memstack_plugins_wecom.adapter import WeComAdapter

# 创建适配器
config = ChannelConfig(
    corp_id="wwxxxxxxxxxxxx",
    agent_id="100000",
    secret="xxxxxxxxxxxxxxxxxxxx",
    connection_mode="webhook"
)
adapter = WeComAdapter(config)

# 连接
await adapter.connect()

# 发送消息
await adapter.send_text("user_id", "Hello!")

# 处理接收消息
adapter.on_message(lambda msg: print(f"Received: {msg.content.text}"))
```

### 使用客户端

```python
from memstack_plugins_wecom.client import WeComClient

client = WeComClient(
    corp_id="wwxxxxxxxxxxxx",
    agent_id="100000",
    secret="xxxxxxxxxxxxxxxxxxxx"
)

# 发送消息
await client.send_text("user_id", "Hello!")

# 发送卡片
await client.send_textcard(
    to="user_id",
    title="标题",
    description="描述内容",
    url="https://example.com"
)

# 上传图片
media_id = await client.upload_media("/path/to/image.jpg", "image")

# 获取用户信息
user_info = await client.get_user("user_id")
```

## Webhook 事件

支持的回调事件：

| 事件类型 | 说明 |
|---------|------|
| `text` | 文本消息 |
| `image` | 图片消息 |
| `voice` | 语音消息 |
| `video` | 视频消息 |
| `file` | 文件消息 |
| `event` | 事件消息（如关注/取消关注） |

## 消息类型支持

| 类型 | 发送 | 接收 |
|------|------|------|
| 文本 | ✅ | ✅ |
| 图片 | ✅ | ✅ |
| 文件 | ✅ | ✅ |
| 语音 | ✅ | ✅ |
| 视频 | ✅ | ✅ |
| 卡片 | ✅ | ❌ |
| Markdown | ✅ | ❌ |

## 依赖

- `aiohttp` - 异步 HTTP 客户端
- `pycryptodome` - AES 加解密（可选，用于消息加密）
- `uvicorn` - Webhook 服务器
- `fastapi` - Webhook 框架

安装依赖：

```bash
pip install aiohttp pycryptodome uvicorn fastapi
```

## 注意事项

1. **消息加密**: 生产环境建议启用消息加密 (EncodingAESKey)，以确保安全性
2. **Token 刷新**: SDK 自动管理 access_token，无需手动处理
3. **频率限制**: 企业微信 API 有调用频率限制，发送消息时注意控制频率
4. **网络访问**: 确保服务器能访问企业微信 API (`qyapi.weixin.qq.com`)

## 相关文档

- [企业微信开发文档](https://developer.work.weixin.qq.com/document/)
- [企业微信 API 接口](https://developer.work.weixin.qq.com/document/1649178f8f6d4d4b5210d6dcs4c0c7)
- [飞书插件参考](../feishu/)
