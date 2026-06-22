# Channels Module

> Last checked: 2026-06-22

多渠道通信模块，支持飞书、钉钉、企业微信等 IM 平台集成。

## 架构

遵循六边形架构 (Hexagonal Architecture):

```
src/
├── domain/model/channels/          # 领域层
│   └── message.py                  # 消息实体、适配器接口 (Port)
├── application/services/channels/  # 应用层
│   ├── channel_service.py          # 渠道服务编排
│   ├── channel_service_factory.py  # 渠道服务工厂
│   ├── channel_message_router.py   # 渠道消息路由
│   ├── event_bridge.py             # 事件桥接
│   ├── hitl_responder.py           # HITL 响应器
│   └── media_import_service.py     # 媒体导入服务
└── infrastructure/adapters/secondary/channels/  # 基础设施层
    └── channel_plugin_loader.py    # 通用渠道插件加载器

.memstack/plugins/feishu/           # 飞书插件 (实际实现)
    ├── memstack.plugin.json        # 插件清单
    ├── plugin.py                   # 插件入口
    ├── adapter.py                  # 主适配器
    ├── client.py                   # API 客户端
    ├── media.py                    # 媒体操作
    ├── cards.py                    # 卡片构建器
    ├── webhook.py                  # Webhook 处理器
    ├── docx.py                     # 文档操作
    ├── wiki.py                     # 知识库操作
    ├── drive.py                    # 云盘操作
    ├── bitable.py                  # 多维表格操作
    ├── cardkit_streaming.py        # CardKit 流式卡片
    ├── hitl_cards.py               # HITL 交互卡片
    ├── rich_cards.py               # 富文本卡片
    └── media_downloader.py         # 媒体下载器
```

> **注意**: 飞书实现已迁移至 `.memstack/plugins/feishu/` 作为本地插件。
> `channel_plugin_loader.py` 提供通用的渠道插件加载机制，支持任意渠道插件的动态加载。

## 快速开始

### 1. 安装依赖

```bash
pip install larksuiteoapi
```

### 2. 基础使用

```python
import asyncio
import os
from src.domain.model.channels import ChannelConfig
from src.application.services.channels import ChannelService
from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import load_channel_module

FeishuAdapter = load_channel_module("feishu", "adapter").FeishuAdapter

async def main():
    # 创建服务
    service = ChannelService()
    
    # 配置飞书
    config = ChannelConfig(
        app_id=os.getenv("FEISHU_APP_ID"),
        app_secret=os.getenv("FEISHU_APP_SECRET"),
        connection_mode="websocket",
    )
    
    # 注册适配器
    service.register_adapter(FeishuAdapter(config))
    
    # 监听消息
    service.on_message(lambda msg: print(f"[{msg.sender.name}] {msg.content.text}"))
    
    # 连接
    await service.connect_all()
    
    # 发送消息
    await service.send_text("feishu", "oc_xxx", "Hello!")
    
    # 保持运行
    await asyncio.sleep(60)
    
    # 断开
    await service.disconnect_all()

asyncio.run(main())
```

### 3. 增强版客户端使用

```python
from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import load_channel_module

FeishuClient = load_channel_module("feishu", "client").FeishuClient
PostBuilder = load_channel_module("feishu", "cards").PostBuilder

client = FeishuClient(app_id, app_secret)

# ========== 消息操作 ==========
# 发送文本
await client.send_text_message("oc_xxx", "Hello!")

# 发送 Markdown 卡片
await client.send_markdown_card(
    to="oc_xxx",
    content="# 标题\n\n内容",
    title="卡片标题"
)

# 发送富文本
post = PostBuilder(title="公告")
post.add_text("大家好！").add_link("点击查看", "https://example.com")
await client.send_card_message("oc_xxx", post.build())

# 回复消息
await client.reply_message(message_id, "收到！")

# 编辑消息
await client.edit_message(message_id, "已修改的内容")

# 撤回消息
await client.recall_message(message_id)

# 添加表情回应
await client.add_reaction(message_id, "OK")

# ========== 媒体操作 ==========
# 上传图片
with open("image.png", "rb") as f:
    image_key = await client.media.upload_image(f.read())
await client.send_image_message("oc_xxx", image_key)

# 上传文件
file_key = await client.media.upload_file(
    file=b"file content",
    file_name="document.pdf"
)

# 下载图片
image_bytes = await client.media.download_image(image_key)

# ========== 文档操作 ==========
# 创建文档
doc = await client.docs.create_document("项目文档")
doc_token = doc["document_token"]

# 获取文档内容
content = await client.docs.get_document_content(doc_token)

# 创建文本块
await client.docs.create_block(
    doc_token,
    parent_block_id=doc_token,
    block_type=2,  # 文本块
    content={"text": {"content": "内容"}}
)

# ========== 知识库操作 ==========
# 列出空间
spaces = await client.wiki.list_spaces()

# 创建节点
node = await client.wiki.create_node(
    space_id="space_xxx",
    title="新页面",
    node_type="docx"
)

# 列出节点
nodes = await client.wiki.list_nodes("space_xxx")

# ========== 云盘操作 ==========
# 创建文件夹
folder_token = await client.drive.create_folder("项目资料")

# 上传文件
file_token = await client.drive.upload_file(
    file=b"content",
    file_name="report.pdf",
    parent_token=folder_token
)

# 下载文件
file_bytes = await client.drive.download_file(file_token)

# 搜索文件
files = await client.drive.search_files("合同")

# ========== 多维表格操作 ==========
# 创建 Bitable
app_token = await client.bitable.create_app("项目管理")

# 创建表格
table_id = await client.bitable.create_table(app_token, "任务")

# 创建字段
field_id = await client.bitable.create_field(
    app_token, table_id,
    field_name="状态",
    field_type=3,  # 单选
    property={"options": [{"name": "进行中"}, {"name": "已完成"}]}
)

# 创建记录
record_id = await client.bitable.create_record(
    app_token, table_id,
    fields={"任务名称": "完成文档", "状态": "进行中"}
)

# 查询记录
records = await client.bitable.list_records(app_token, table_id)
```

### 4. Webhook 模式

```python
from fastapi import FastAPI, Request
from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import load_channel_module

# Webhook 符号通过 adapter 模块访问
adapter_mod = load_channel_module("feishu", "adapter")

app = FastAPI()

# 详细的 webhook 使用方式请参考 .memstack/plugins/feishu/webhook.py
```

### 5. 卡片构建器

```python
from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import load_channel_module

CardBuilder = load_channel_module("feishu", "cards").CardBuilder

# 简单 Markdown 卡片
card = CardBuilder.create_markdown_card(
    content="# 通知\n\n项目已部署",
    title="部署通知"
)

# 信息卡片
card = CardBuilder.create_info_card(
    title="系统状态",
    content=[
        {"tag": "div", "text": {"tag": "lark_md", "content": "**状态**: 正常"}},
        CardBuilder.create_divider(),
        {"tag": "div", "text": {"tag": "lark_md", "content": "**时间**: 2024-01-01"}},
    ],
    actions=[
        CardBuilder.create_button("查看详情", url="https://example.com", button_type="primary")
    ]
)

# 表格卡片
card = CardBuilder.create_table_card(
    title="销售数据",
    headers=["产品", "销量", "金额"],
    rows=[
        ["产品A", "100", "¥10,000"],
        ["产品B", "200", "¥20,000"],
    ]
)

# 提示卡片
card = CardBuilder.create_note_card(
    title="注意",
    note_text="这是一条重要提示",
    note_type="warning"  # default, info, warning, danger
)
```

## 插件加载器接口

`channel_plugin_loader.py` 提供通用的渠道插件加载机制:

```python
from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import (
    load_channel_module,
    register_channel_plugin,
)

# 加载已注册渠道的子模块
module = load_channel_module("feishu", "client")

# 注册新的渠道插件目录
register_channel_plugin("dingtalk", Path("/path/to/dingtalk/plugin"))
```

### 飞书模块映射

| 调用方式 | 加载模块 | 主要导出 |
|---------|---------|---------|
| `load_channel_module("feishu", "client")` | `client.py` | `FeishuClient`, `send_feishu_card`, `send_feishu_text` |
| `load_channel_module("feishu", "adapter")` | `adapter.py` | `FeishuAdapter` |
| `load_channel_module("feishu", "cards")` | `cards.py` | `CardBuilder`, `PostBuilder` |
| `load_channel_module("feishu", "cardkit_streaming")` | `cardkit_streaming.py` | `CardKitStreamingManager`, `CardStreamState` |
| `load_channel_module("feishu", "hitl_cards")` | `hitl_cards.py` | `HITLCardBuilder` |
| `load_channel_module("feishu", "rich_cards")` | `rich_cards.py` | `RichCardBuilder` |
| `load_channel_module("feishu", "media_downloader")` | `media_downloader.py` | `FeishuMediaDownloader` |
| `load_channel_module("feishu", "bitable")` | `bitable.py` | `FIELD_TYPE_*` 常量 |

## 配置

环境变量:

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_ENCRYPT_KEY=xxx       # Webhook 加密密钥 (可选)
FEISHU_VERIFICATION_TOKEN=xxx # Webhook 验证令牌 (可选)
```

## API 参考

### FeishuClient

完整功能列表:

| 类别 | 方法 | 说明 |
|------|------|------|
| **消息** | `send_text_message()` | 发送文本消息 |
| | `send_card_message()` | 发送卡片消息 |
| | `send_markdown_card()` | 发送 Markdown 卡片 |
| | `send_image_message()` | 发送图片 |
| | `send_file_message()` | 发送文件 |
| | `reply_message()` | 回复消息 |
| | `edit_message()` | 编辑消息 |
| | `recall_message()` | 撤回消息 |
| | `get_message()` | 获取消息 |
| **互动** | `add_reaction()` | 添加表情 |
| | `remove_reaction()` | 移除表情 |
| **聊天** | `get_chat_info()` | 获取群信息 |
| | `get_chat_members()` | 获取群成员 |
| **用户** | `get_user_info()` | 获取用户信息 |
| **媒体** | `media.upload_image()` | 上传图片 |
| | `media.upload_file()` | 上传文件 |
| | `media.download_image()` | 下载图片 |
| | `media.download_file()` | 下载文件 |
| **文档** | `docs.create_document()` | 创建文档 |
| | `docs.get_document()` | 获取文档 |
| | `docs.get_document_content()` | 获取文档内容 |
| | `docs.list_document_blocks()` | 列出文档块 |
| | `docs.create_block()` | 创建文档块 |
| | `docs.update_block()` | 更新文档块 |
| | `docs.delete_block()` | 删除文档块 |
| **知识库** | `wiki.list_spaces()` | 列出空间 |
| | `wiki.get_space()` | 获取空间 |
| | `wiki.list_nodes()` | 列出节点 |
| | `wiki.create_node()` | 创建节点 |
| | `wiki.move_node()` | 移动节点 |
| **云盘** | `drive.list_files()` | 列出文件 |
| | `drive.create_folder()` | 创建文件夹 |
| | `drive.upload_file()` | 上传文件 |
| | `drive.download_file()` | 下载文件 |
| | `drive.move_file()` | 移动文件 |
| | `drive.copy_file()` | 复制文件 |
| | `drive.delete_file()` | 删除文件 |
| | `drive.search_files()` | 搜索文件 |
| **多维表** | `bitable.create_app()` | 创建应用 |
| | `bitable.list_tables()` | 列出表格 |
| | `bitable.create_table()` | 创建表格 |
| | `bitable.list_fields()` | 列出字段 |
| | `bitable.create_field()` | 创建字段 |
| | `bitable.list_records()` | 列出记录 |
| | `bitable.create_record()` | 创建记录 |
| | `bitable.update_record()` | 更新记录 |
| | `bitable.delete_record()` | 删除记录 |
| | `bitable.search_records()` | 搜索记录 |

## 消息格式

统一消息结构:

```python
@dataclass
class Message:
    id: str
    channel: str           # "feishu", "dingtalk", etc.
    chat_type: ChatType    # "p2p" or "group"
    chat_id: str
    sender: SenderInfo     # id, name, avatar
    content: MessageContent
    reply_to: Optional[str]  # 回复的消息ID
    mentions: List[str]    # @的用户ID列表
    created_at: datetime
```

## 开发计划

- [x] 飞书适配器 (WebSocket)
- [x] 飞书增强客户端 (完整 API 支持)
- [x] 飞书文档操作 (docx)
- [x] 飞书知识库操作 (wiki)
- [x] 飞书云盘操作 (drive)
- [x] 飞书多维表格操作 (bitable)
- [x] 卡片构建器
- [x] Webhook 处理器
- [x] 飞书插件迁移至 `.memstack/plugins/feishu/`
- [x] 通用渠道插件加载器 (`channel_plugin_loader.py`)
- [ ] 钉钉适配器
- [ ] 企业微信适配器
- [ ] 消息持久化
- [ ] 多渠道消息同步

## 参考

- [OpenClaw Feishu Plugin](https://github.com/openclaw/openclaw/tree/main/extensions/feishu)
- [飞书开放平台](https://open.feishu.cn/)
