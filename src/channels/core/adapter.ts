/**
 * Channels 模块 - 适配器基类
 */

import {
  ChannelAdapter,
  ChannelConfig,
  MessageContent,
  SendMessageOptions,
  UnifiedMessage,
  MessageHandler,
} from './types.js';
import { EventEmitter } from './event.js';

export abstract class BaseAdapter extends EventEmitter implements ChannelAdapter {
  protected _connected = false;
  protected config: ChannelConfig;
  protected errorHandlers: Set<(error: Error) => void> = new Set();

  constructor(
    public readonly id: string,
    public readonly name: string,
    config: ChannelConfig
  ) {
    super();
    this.config = config;
  }

  get connected(): boolean {
    return this._connected;
  }

  // 检查配置是否有效
  protected validateConfig(): void {
    if (!this.config.appId) {
      throw new Error(`${this.name}: appId is required`);
    }
    if (!this.config.appSecret) {
      throw new Error(`${this.name}: appSecret is required`);
    }
  }

  // 抽象方法 - 子类必须实现
  abstract connect(): Promise<void>;
  abstract disconnect(): Promise<void>;
  abstract sendMessage(
    to: string,
    content: MessageContent,
    options?: SendMessageOptions
  ): Promise<{ messageId: string }>;

  // 发送文本消息的便捷方法
  async sendText(to: string, text: string, options?: SendMessageOptions): Promise<{ messageId: string }> {
    return this.sendMessage(to, { type: 'text', text }, options);
  }

  // 错误处理
  onError(handler: (error: Error) => void): void {
    this.errorHandlers.add(handler);
  }

  protected handleError(error: Error): void {
    console.error(`[${this.name}] Error:`, error.message);
    this.errorHandlers.forEach((handler) => {
      try {
        handler(error);
      } catch (err) {
        console.error('Error handler failed:', err);
      }
    });
    this.emit('error' as any, undefined, error);
  }

  // 统一消息格式转换（子类实现）
  protected abstract normalizeMessage(rawData: any): UnifiedMessage | null;

  // 发送消息前的内容转换（子类实现）
  protected abstract denormalizeContent(content: MessageContent): any;
}
