/**
 * AGI-Demos Channels 模块
 * 多渠道通信统一接口
 */

// Core
export * from './core/index.js';

// Manager
export { ChannelManager, channelManager } from './manager/channel-manager.js';

// Adapters
export * from './adapters/feishu/index.js';

// 便捷函数
import { ChannelManager } from './manager/channel-manager.js';
import { createFeishuAdapter, FeishuConfig } from './adapters/feishu/index.js';

/**
 * 快速创建并配置 Channels
 */
export function createChannelsManager(): ChannelManager {
  return new ChannelManager();
}

/**
 * 创建预设的飞书渠道
 */
export function createFeishuChannel(config: FeishuConfig) {
  return createFeishuAdapter(config);
}
