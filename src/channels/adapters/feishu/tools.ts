/**
 * 飞书适配器 - 工具函数
 */

import { createFeishuClient, extractCredentials } from './client.js';

/**
 * 发送文本消息
 */
export async function sendTextMessage(
  config: { appId: string; appSecret: string; domain?: string },
  to: string,
  text: string
): Promise<{ messageId: string }> {
  const client = createFeishuClient(config);
  const receiveIdType = to.startsWith('ou_') ? 'open_id' : 'chat_id';

  const response: any = await client.im.message.create({
    params: { receive_id_type: receiveIdType },
    data: {
      receive_id: to,
      msg_type: 'text',
      content: JSON.stringify({ text }),
    },
  });

  return { messageId: response?.data?.message_id };
}

/**
 * 发送卡片消息
 */
export async function sendCardMessage(
  config: { appId: string; appSecret: string; domain?: string },
  to: string,
  card: Record<string, any>
): Promise<{ messageId: string }> {
  const client = createFeishuClient(config);
  const receiveIdType = to.startsWith('ou_') ? 'open_id' : 'chat_id';

  const response: any = await client.im.message.create({
    params: { receive_id_type: receiveIdType },
    data: {
      receive_id: to,
      msg_type: 'interactive',
      content: JSON.stringify(card),
    },
  });

  return { messageId: response?.data?.message_id };
}

/**
 * 获取群信息
 */
export async function getChatInfo(
  config: { appId: string; appSecret: string; domain?: string },
  chatId: string
): Promise<{ name?: string; description?: string; memberCount?: number }> {
  const client = createFeishuClient(config);

  const response: any = await client.im.chat.get({
    path: { chat_id: chatId },
  });

  const chat = response?.data;
  return {
    name: chat?.name,
    description: chat?.description,
    memberCount: chat?.member_count,
  };
}

/**
 * 回复消息
 */
export async function replyMessage(
  config: { appId: string; appSecret: string; domain?: string },
  messageId: string,
  text: string
): Promise<{ messageId: string }> {
  const client = createFeishuClient(config);

  const response: any = await client.im.message.reply({
    path: { message_id: messageId },
    data: {
      content: JSON.stringify({ text }),
      msg_type: 'text',
    },
  });

  return { messageId: response?.data?.message_id };
}
