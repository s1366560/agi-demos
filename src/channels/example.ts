/**
 * AGI-Demos Channels 模块使用示例
 */

import {
  createChannelsManager,
  createFeishuChannel,
  ChannelManager,
  FeishuAdapter,
  UnifiedMessage,
} from './index.js';

// ========== 示例 1: 基础使用 ==========
async function basicExample() {
  // 创建渠道管理器
  const manager = createChannelsManager();

  // 创建飞书适配器
  const feishu = createFeishuChannel({
    enabled: true,
    appId: 'cli_xxx',
    appSecret: 'xxx',
    domain: 'feishu',
    connectionMode: 'websocket',
  });

  // 注册适配器
  manager.register(feishu);

  // 监听消息
  feishu.onMessage((message: UnifiedMessage) => {
    console.log(`[${message.channel}] ${message.senderName}: ${message.content.text}`);
    
    // 回复消息
    if (message.content.text?.includes('hello')) {
      feishu.sendText(message.chatId, 'Hello! 👋');
    }
  });

  // 连接所有渠道
  await manager.connectAll();

  // 发送消息
  await feishu.sendText('oc_xxx', '大家好！');

  // 获取群成员
  const members = await feishu.getChatMembers('oc_xxx');
  console.log('群成员:', members);
}

// ========== 示例 2: 多渠道 ==========
async function multiChannelExample() {
  const manager = createChannelsManager();

  // 飞书
  const feishu = createFeishuChannel({
    enabled: true,
    appId: process.env.FEISHU_APP_ID!,
    appSecret: process.env.FEISHU_APP_SECRET!,
  });

  // 钉钉（未来实现）
  // const dingtalk = createDingtalkAdapter({...});

  manager.register(feishu);
  // manager.register(dingtalk);

  // 统一消息处理
  manager.onMessage((message: UnifiedMessage) => {
    console.log(`[${message.channel}] ${message.senderName}: ${message.content.text}`);
  });

  await manager.connectAll();
}

// ========== 示例 3: 消息路由 ==========
async function routingExample() {
  const manager = createChannelsManager();

  // 设置消息路由规则
  manager.setMessageRouter((message: UnifiedMessage) => {
    // 根据消息内容路由到不同的处理函数
    if (message.content.text?.includes('紧急')) {
      return 'urgent-handler';
    }
    return 'default-handler';
  });

  // 广播消息到所有渠道
  await manager.broadcast('oc_xxx', '这是一条广播消息');
}

// ========== 示例 4: 工具函数 ==========
async function toolsExample() {
  import { sendTextMessage, sendCardMessage, getChatInfo } from './index.js';

  const config = {
    appId: 'cli_xxx',
    appSecret: 'xxx',
  };

  // 直接发送文本
  await sendTextMessage(config, 'oc_xxx', 'Hello');

  // 发送卡片消息
  await sendCardMessage(config, 'oc_xxx', {
    config: { wide_screen_mode: true },
    header: {
      title: { tag: 'plain_text', content: '通知' },
    },
    elements: [
      { tag: 'div', text: { tag: 'plain_text', content: '这是一条卡片消息' } },
    ],
  });

  // 获取群信息
  const info = await getChatInfo(config, 'oc_xxx');
  console.log(info);
}

// 运行示例
if (require.main === module) {
  basicExample().catch(console.error);
}
