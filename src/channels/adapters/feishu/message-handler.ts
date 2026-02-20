/**
 * 飞书适配器 - 消息处理
 * 参考 OpenClaw extensions/feishu/src/bot.ts
 */

import { UnifiedMessage, MessageContent, ChatType } from '../../core/types.js';

// 飞书消息事件
export interface FeishuMessageEvent {
  sender: {
    sender_id: {
      open_id?: string;
      user_id?: string;
      union_id?: string;
    };
    sender_type?: string;
    tenant_key?: string;
  };
  message: {
    message_id: string;
    root_id?: string;
    parent_id?: string;
    chat_id: string;
    chat_type: 'p2p' | 'group';
    message_type: string;
    content: string;
    mentions?: Array<{
      key: string;
      id: {
        open_id?: string;
        user_id?: string;
        union_id?: string;
      };
      name: string;
      tenant_key?: string;
    }>;
  };
}

/**
 * 解析消息内容
 */
export function parseMessageContent(content: string, messageType: string): string {
  try {
    const parsed = JSON.parse(content);
    if (messageType === 'text') {
      return parsed.text || '';
    }
    if (messageType === 'post') {
      return parsePostContent(content);
    }
    return content;
  } catch {
    return content;
  }
}

/**
 * 解析富文本内容
 */
function parsePostContent(content: string): string {
  try {
    const parsed = JSON.parse(content);
    const title = parsed.title || '';
    const contentBlocks = parsed.content || [];
    let textContent = title ? `${title}\n\n` : '';

    for (const paragraph of contentBlocks) {
      if (Array.isArray(paragraph)) {
        for (const element of paragraph) {
          if (element.tag === 'text') {
            textContent += element.text || '';
          } else if (element.tag === 'a') {
            textContent += element.text || element.href || '';
          } else if (element.tag === 'at') {
            textContent += `@${element.user_name || element.user_id || ''}`;
          } else if (element.tag === 'img') {
            textContent += '[图片]';
          }
        }
        textContent += '\n';
      }
    }

    return textContent.trim() || '[富文本消息]';
  } catch {
    return '[富文本消息]';
  }
}

/**
 * 检查是否 @ 了机器人
 */
export function checkBotMentioned(
  event: FeishuMessageEvent,
  botOpenId?: string
): boolean {
  if (!botOpenId) return false;
  const mentions = event.message.mentions ?? [];
  return mentions.some((m) => m.id.open_id === botOpenId);
}

/**
 * 提取媒体信息
 */
export function extractMediaInfo(
  content: string,
  messageType: string
): { imageKey?: string; fileKey?: string; fileName?: string } {
  try {
    const parsed = JSON.parse(content);
    switch (messageType) {
      case 'image':
        return { imageKey: parsed.image_key };
      case 'file':
        return { fileKey: parsed.file_key, fileName: parsed.file_name };
      case 'audio':
        return { fileKey: parsed.file_key };
      case 'video':
        return { fileKey: parsed.file_key, imageKey: parsed.image_key };
      default:
        return {};
    }
  } catch {
    return {};
  }
}

/**
 * 转换为统一消息格式
 */
export function normalizeFeishuMessage(
  event: FeishuMessageEvent,
  botOpenId?: string
): UnifiedMessage {
  const content = parseMessageContent(event.message.content, event.message.message_type);
  const mediaInfo = extractMediaInfo(event.message.content, event.message.message_type);

  return {
    id: event.message.message_id,
    channel: 'feishu',
    chatType: event.message.chat_type,
    chatId: event.message.chat_id,
    senderId: event.sender.sender_id.open_id || '',
    senderName: event.sender.sender_type,
    content: {
      type: event.message.message_type as any,
      text: content,
      imageKey: mediaInfo.imageKey,
      fileKey: mediaInfo.fileKey,
      fileName: mediaInfo.fileName,
    },
    timestamp: Date.now(),
    replyTo: event.message.parent_id,
    mentions: event.message.mentions?.map((m) => m.id.open_id || '').filter(Boolean),
    rawData: event,
  };
}
