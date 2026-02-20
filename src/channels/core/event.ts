/**
 * Channels 模块 - 事件系统
 */

import { ChannelEvent, ChannelEventPayload, MessageHandler, UnifiedMessage } from './types.js';

type EventHandler = (payload: ChannelEventPayload) => void | Promise<void>;

export class EventEmitter {
  private handlers: Map<ChannelEvent, Set<EventHandler>> = new Map();
  private messageHandlers: Set<MessageHandler> = new Set();

  // 注册事件监听器
  on(event: ChannelEvent, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);

    // 返回取消订阅函数
    return () => {
      this.handlers.get(event)?.delete(handler);
    };
  }

  // 注册消息监听器
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => {
      this.messageHandlers.delete(handler);
    };
  }

  // 触发事件
  emit(event: ChannelEvent, data?: any, error?: Error): void {
    const payload: ChannelEventPayload = {
      type: event,
      channel: '',
      data,
      error,
      timestamp: Date.now(),
    };

    const handlers = this.handlers.get(event);
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(payload);
        } catch (err) {
          console.error(`Event handler error for ${event}:`, err);
        }
      });
    }
  }

  // 分发消息
  dispatchMessage(message: UnifiedMessage): void {
    this.messageHandlers.forEach((handler) => {
      try {
        handler(message);
      } catch (err) {
        console.error('Message handler error:', err);
      }
    });
  }

  // 移除所有监听器
  removeAllListeners(): void {
    this.handlers.clear();
    this.messageHandlers.clear();
  }
}
