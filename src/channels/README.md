# AGI-Demos Channels 模块

多渠道通信统一接口，支持飞书、钉钉、企业微信等 IM 平台。

## 特性

- 🚀 **统一接口**: 所有渠道使用相同的 API
- 🔌 **可扩展**: 适配器模式，易于添加新渠道
- 💬 **实时通信**: WebSocket 长连接，消息实时推送
- 🛠 **工具函数**: 发送消息、查询成员、搜索历史等
- 📝 **TypeScript**: 完整的类型支持

## 安装

```bash
npm install @larksuiteoapi/node-sdk
```

## 快速开始

```typescript
import {
  createChannelsManager,
  createFeishuChannel,
} from './channels';

// 创建管理器
const manager = createChannelsManager();

// 创建飞书适配器
const feishu = createFeishuChannel({
  enabled: true,
  appId: 'cli_xxx',
  appSecret: 'xxx',
  connectionMode: 'websocket',
});

// 注册适配器
manager.register(feishu);

// 监听消息
feishu.onMessage((message) => {
  console.log(`[${message.senderName}] ${message.content.text}`);
});

// 连接
await manager.connectAll();

// 发送消息
await feishu.sendText('oc_xxx', 'Hello!');
```

## 配置

### 环境变量

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

### 配置文件

```typescript
// config/channels.ts
export const channelConfig = {
  feishu: {
    enabled: true,
    appId: process.env.FEISHU_APP_ID,
    appSecret: process.env.FEISHU_APP_SECRET,
    connectionMode: 'websocket', // 或 'webhook'
  },
};
```

## API 文档

### ChannelManager

```typescript
// 注册适配器
manager.register(adapter: ChannelAdapter): void

// 连接所有渠道
manager.connectAll(): Promise<void>

// 断开所有渠道
manager.disconnectAll(): Promise<void>

// 获取适配器
manager.getAdapter(id: string): ChannelAdapter | undefined

// 发送消息
manager.sendMessage(channelId: string, to: string, text: string): Promise<void>

// 广播消息
manager.broadcast(to: string, text: string): Promise<void>
```

### FeishuAdapter

```typescript
// 发送文本
adapter.sendText(to: string, text: string): Promise<{ messageId: string }>

// 发送消息（支持多种类型）
adapter.sendMessage(to: string, content: MessageContent): Promise<{ messageId: string }>

// 获取群成员
adapter.getChatMembers(chatId: string): Promise<Array<{ id: string; name?: string }>>

// 获取用户信息
adapter.getUserInfo(userId: string): Promise<{ id: string; name?: string; avatar?: string }>

// 监听消息
adapter.onMessage(handler: (message: UnifiedMessage) => void): () => void
```

### 工具函数

```typescript
import { sendTextMessage, sendCardMessage, getChatInfo } from './channels';

// 发送文本
await sendTextMessage(config, 'oc_xxx', 'Hello');

// 发送卡片
await sendCardMessage(config, 'oc_xxx', { /* 卡片配置 */ });

// 获取群信息
const info = await getChatInfo(config, 'oc_xxx');
```

## 消息格式

### UnifiedMessage

```typescript
interface UnifiedMessage {
  id: string;              // 消息ID
  channel: string;         // 渠道标识
  chatType: 'p2p' | 'group'; // 私聊/群聊
  chatId: string;          // 聊天ID
  senderId: string;        // 发送者ID
  senderName?: string;     // 发送者名称
  content: MessageContent; // 消息内容
  timestamp: number;       // 时间戳
  replyTo?: string;        // 回复的消息ID
  mentions?: string[];     // @的用户列表
}
```

### MessageContent

```typescript
type MessageContent =
  | { type: 'text'; text: string }
  | { type: 'image'; imageKey: string }
  | { type: 'file'; fileKey: string; fileName?: string }
  | { type: 'card'; card: Record<string, any> };
```

## 开发计划

- [x] 飞书适配器 (WebSocket)
- [ ] 钉钉适配器
- [ ] 企业微信适配器
- [ ] Slack 适配器
- [ ] Discord 适配器

## 参考

- [OpenClaw Feishu Plugin](https://github.com/openclaw/openclaw/tree/main/extensions/feishu)
- [飞书开放平台](https://open.feishu.cn/)

## License

MIT
