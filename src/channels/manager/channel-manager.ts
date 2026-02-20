/**
 * Channels 模块 - 渠道管理器
 */

import { ChannelAdapter, ChannelConfig, UnifiedMessage } from '../core/types.js';
import { EventEmitter, ChannelEvent } from '../core/event.js';

export class ChannelManager extends EventEmitter {
  private adapters: Map<string, ChannelAdapter> = new Map();
  private messageRouter?: (message: UnifiedMessage) => string | undefined;

  // 注册渠道适配器
  register(adapter: ChannelAdapter): void {
    if (this.adapters.has(adapter.id)) {
      throw new Error(`Adapter ${adapter.id} already registered`);
    }
    this.adapters.set(adapter.id, adapter);
    console.log(`[ChannelManager] Registered adapter: ${adapter.name} (${adapter.id})`);
  }

  // 获取适配器
  getAdapter(id: string): ChannelAdapter | undefined {
    return this.adapters.get(id);
  }

  // 获取所有适配器
  getAllAdapters(): ChannelAdapter[] {
    return Array.from(this.adapters.values());
  }

  // 启动所有渠道
  async connectAll(): Promise<void> {
    const promises = Array.from(this.adapters.values()).map(async (adapter) => {
      try {
        await adapter.connect();
        // 监听消息并路由
        adapter.onMessage((message) => {
          this.dispatchMessage(message);
          this.emit(ChannelEvent.MESSAGE_RECEIVED, message);
        });
        console.log(`[ChannelManager] Connected: ${adapter.name}`);
      } catch (error) {
        console.error(`[ChannelManager] Failed to connect ${adapter.name}:`, error);
      }
    });
    await Promise.all(promises);
  }

  // 断开所有渠道
  async disconnectAll(): Promise<void> {
    const promises = Array.from(this.adapters.values()).map(async (adapter) => {
      try {
        await adapter.disconnect();
        console.log(`[ChannelManager] Disconnected: ${adapter.name}`);
      } catch (error) {
        console.error(`[ChannelManager] Error disconnecting ${adapter.name}:`, error);
      }
    });
    await Promise.all(promises);
    this.removeAllListeners();
  }

  // 设置消息路由函数
  setMessageRouter(router: (message: UnifiedMessage) => string | undefined): void {
    this.messageRouter = router;
  }

  // 发送消息到指定渠道
  async sendMessage(
    channelId: string,
    to: string,
    text: string
  ): Promise<{ messageId: string } | undefined> {
    const adapter = this.adapters.get(channelId);
    if (!adapter) {
      console.error(`[ChannelManager] Adapter not found: ${channelId}`);
      return undefined;
    }
    if (!adapter.connected) {
      console.error(`[ChannelManager] Adapter not connected: ${channelId}`);
      return undefined;
    }
    return adapter.sendText(to, text);
  }

  // 广播消息到所有渠道
  async broadcast(to: string, text: string): Promise<void> {
    const promises = Array.from(this.adapters.values())
      .filter((adapter) => adapter.connected)
      .map((adapter) =>
        adapter.sendText(to, text).catch((err) => {
          console.error(`[ChannelManager] Broadcast error to ${adapter.name}:`, err);
        })
      );
    await Promise.all(promises);
  }
}

// 单例实例
export const channelManager = new ChannelManager();
