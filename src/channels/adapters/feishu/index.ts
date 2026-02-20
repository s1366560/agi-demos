// 飞书适配器导出
export { FeishuAdapter, FeishuConfig } from './adapter.js';
export { createFeishuClient, createFeishuWSClient, createEventDispatcher } from './client.js';
export {
  normalizeFeishuMessage,
  parseMessageContent,
  checkBotMentioned,
  extractMediaInfo,
  FeishuMessageEvent,
} from './message-handler.js';
export { sendTextMessage, sendCardMessage, getChatInfo, replyMessage } from './tools.js';

// 便捷创建函数
import { FeishuAdapter, FeishuConfig } from './adapter.js';

export function createFeishuAdapter(config: FeishuConfig): FeishuAdapter {
  return new FeishuAdapter(config);
}
