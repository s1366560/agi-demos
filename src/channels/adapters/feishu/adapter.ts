/**
 * 飞书适配器 - 主类
 * 参考 OpenClaw extensions/feishu/src/channel.ts 和 bot.ts
 */

import * as Lark from '@larksuiteoapi/node-sdk';
import { BaseAdapter } from '../../core/adapter.js';
import {
  ChannelConfig,
  MessageContent,
  SendMessageOptions,
  UnifiedMessage,
} from '../../core/types.js';
import { ChannelEvent } from '../../core/event.js';
import {
  createFeishuClient,
  createFeishuWSClient,
  createEventDispatcher,
  extractCredentials,
} from './client.js';
import {
  FeishuMessageEvent,
  normalizeFeishuMessage,
  checkBotMentioned,
} from './message-handler.js';

export interface FeishuConfig extends ChannelConfig {
  domain?: 'feishu' | 'lark';
  connectionMode?: 'websocket' | 'webhook';
  webhookPort?: number;
  webhookPath?: string;
}

export class FeishuAdapter extends BaseAdapter {
  private wsClient?: Lark.WSClient;
  private eventDispatcher?: Lark.EventDispatcher;
  private botOpenId?: string;
  private messageHistory: Map<string, boolean> = new Map(); // 去重

  constructor(config: FeishuConfig) {
    super('feishu', 'Feishu', config);
    this.validateConfig();
  }

  /**
   * 连接到飞书
   */
  async connect(): Promise<void> {
    if (this._connected) {
      console.log('[Feishu] Already connected');
      return;
    }

    try {
      const creds = extractCredentials(this.config);
      const mode = this.config.connectionMode || 'websocket';

      if (mode === 'webhook') {
        await this.connectWebhook(creds);
      } else {
        await this.connectWebSocket(creds);
      }

      this._connected = true;
      this.emit(ChannelEvent.CONNECTED, { channel: this.id });
      console.log('[Feishu] Connected successfully');
    } catch (error) {
      this.handleError(error as Error);
      throw error;
    }
  }

  /**
   * WebSocket 连接
   */
  private async connectWebSocket(creds: any): Promise<void> {
    this.wsClient = createFeishuWSClient(creds);
    this.eventDispatcher = createEventDispatcher(
      this.config.encryptKey,
      this.config.verificationToken
    );

    // 注册事件处理器
    this.registerEventHandlers();

    // 启动 WebSocket
    this.wsClient.start({ eventDispatcher: this.eventDispatcher! });
  }

  /**
   * Webhook 连接（简化版，实际需 HTTP 服务器）
   */
  private async connectWebhook(creds: any): Promise<void> {
    console.log('[Feishu] Webhook mode - HTTP server not implemented');
    // TODO: 实现 HTTP 服务器接收飞书回调
  }

  /**
   * 注册事件处理器
   */
  private registerEventHandlers(): void {
    if (!this.eventDispatcher) return;

    // 消息接收事件
    this.eventDispatcher.register({
      'im.message.receive_v1': async (data: any) => {
        try {
          const event = data as FeishuMessageEvent;
          
          // 去重检查
          if (this.messageHistory.has(event.message.message_id)) {
            return;
          }
          this.messageHistory.set(event.message.message_id, true);
          
          // 限制历史记录大小
          if (this.messageHistory.size > 10000) {
            const firstKey = this.messageHistory.keys().next().value;
            this.messageHistory.delete(firstKey);
          }

          const message = normalizeFeishuMessage(event, this.botOpenId);
          this.dispatchMessage(message);
          this.emit(ChannelEvent.MESSAGE_RECEIVED, message);
        } catch (err) {
          this.handleError(err as Error);
        }
      },

      // 消息编辑事件
      'im.message.updated_v1': async (data: any) => {
        console.log('[Feishu] Message edited:', data?.message?.message_id);
      },

      // 消息删除事件
      'im.message.deleted_v1': async (data: any) => {
        console.log('[Feishu] Message deleted:', data?.message_id);
      },

      // 机器人被添加到群
      'im.chat.member.bot.added_v1': async (data: any) => {
        console.log('[Feishu] Bot added to chat:', data?.chat_id);
      },

      // 机器人被移除群
      'im.chat.member.bot.deleted_v1': async (data: any) => {
        console.log('[Feishu] Bot removed from chat:', data?.chat_id);
      },
    });
  }

  /**
   * 断开连接
   */
  async disconnect(): Promise<void> {
    if (this.wsClient) {
      // WebSocket 客户端没有显式的 close 方法，依赖垃圾回收
      this.wsClient = undefined;
    }
    this._connected = false;
    this.emit(ChannelEvent.DISCONNECTED, { channel: this.id });
    console.log('[Feishu] Disconnected');
  }

  /**
   * 发送消息
   */
  async sendMessage(
    to: string,
    content: MessageContent,
    options?: SendMessageOptions
  ): Promise<{ messageId: string }> {
    if (!this._connected) {
      throw new Error('Feishu adapter not connected');
    }

    const creds = extractCredentials(this.config);
    const client = createFeishuClient(creds);

    // 构建接收者 ID
    const receiveId = to.startsWith('ou_') ? to : to.replace(/^chat:/, '');
    const receiveIdType = to.startsWith('ou_') ? 'open_id' : 'chat_id';

    let response: any;

    switch (content.type) {
      case 'text':
        response = await client.im.message.create({
          params: { receive_id_type: receiveIdType },
          data: {
            receive_id: receiveId,
            msg_type: 'text',
            content: JSON.stringify({ text: content.text }),
          },
        });
        break;

      case 'image':
        response = await client.im.message.create({
          params: { receive_id_type: receiveIdType },
          data: {
            receive_id: receiveId,
            msg_type: 'image',
            content: JSON.stringify({ image_key: content.imageKey }),
          },
        });
        break;

      case 'card':
        response = await client.im.message.create({
          params: { receive_id_type: receiveIdType },
          data: {
            receive_id: receiveId,
            msg_type: 'interactive',
            content: JSON.stringify(content.card),
          },
        });
        break;

      default:
        throw new Error(`Unsupported message type: ${content.type}`);
    }

    const messageId = response?.data?.message_id;
    if (!messageId) {
      throw new Error('Failed to send message: no message_id returned');
    }

    this.emit(ChannelEvent.MESSAGE_SENT, { messageId, to, content });
    return { messageId };
  }

  /**
   * 获取群成员列表
   */
  async getChatMembers(chatId: string): Promise<Array<{ id: string; name?: string }>> {
    const creds = extractCredentials(this.config);
    const client = createFeishuClient(creds);

    const response: any = await client.im.chatMembers.get({
      path: { chat_id: chatId },
      params: { member_id_type: 'open_id' },
    });

    const members = response?.data?.items || [];
    return members.map((m: any) => ({
      id: m.member_id,
      name: m.name,
    }));
  }

  /**
   * 获取用户信息
   */
  async getUserInfo(userId: string): Promise<{ id: string; name?: string; avatar?: string }> {
    const creds = extractCredentials(this.config);
    const client = createFeishuClient(creds);

    const response: any = await client.contact.user.get({
      path: { user_id: userId },
      params: { user_id_type: 'open_id' },
    });

    const user = response?.data?.user;
    return {
      id: user?.open_id || userId,
      name: user?.name,
      avatar: user?.avatar?.avatar_origin,
    };
  }

  /**
   * 转换为统一消息格式
   */
  protected normalizeMessage(rawData: any): UnifiedMessage | null {
    return normalizeFeishuMessage(rawData, this.botOpenId);
  }

  /**
   * 发送消息前的内容转换
   */
  protected denormalizeContent(content: MessageContent): any {
    return content;
  }
}
