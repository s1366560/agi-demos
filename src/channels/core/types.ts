/**
 * Channels 模块 - 核心类型定义
 * 参考 OpenClaw 飞书插件设计
 */

// 消息内容类型
export type MessageContentType = 'text' | 'image' | 'file' | 'audio' | 'video' | 'card' | 'post';

// 聊天类型
export type ChatType = 'p2p' | 'group';

// 消息内容
export interface MessageContent {
  type: MessageContentType;
  text?: string;
  imageKey?: string;
  fileKey?: string;
  fileName?: string;
  card?: Record<string, any>;
}

// 统一消息格式
export interface UnifiedMessage {
  id: string;
  channel: string;
  chatType: ChatType;
  chatId: string;
  senderId: string;
  senderName?: string;
  content: MessageContent;
  timestamp: number;
  replyTo?: string;
  mentions?: string[];
  rawData?: any;
}

// 发送消息选项
export interface SendMessageOptions {
  replyTo?: string;
  mentionUsers?: string[];
  silent?: boolean;
}

// 消息处理器
export type MessageHandler = (message: UnifiedMessage) => void | Promise<void>;

// 渠道配置
export interface ChannelConfig {
  enabled: boolean;
  appId?: string;
  appSecret?: string;
  encryptKey?: string;
  verificationToken?: string;
  connectionMode?: 'websocket' | 'webhook';
  webhookPort?: number;
  webhookPath?: string;
  [key: string]: any;
}

// 渠道适配器接口
export interface ChannelAdapter {
  readonly id: string;
  readonly name: string;
  readonly connected: boolean;
  
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  
  sendMessage(to: string, content: MessageContent, options?: SendMessageOptions): Promise<{ messageId: string }>;
  sendText(to: string, text: string, options?: SendMessageOptions): Promise<{ messageId: string }>;
  
  onMessage(handler: MessageHandler): void;
  onError(handler: (error: Error) => void): void;
  
  getChatMembers(chatId: string): Promise<Array<{ id: string; name?: string }>>;
  getUserInfo(userId: string): Promise<{ id: string; name?: string; avatar?: string }>;
}

// 事件类型
export enum ChannelEvent {
  MESSAGE_RECEIVED = 'message:received',
  MESSAGE_SENT = 'message:sent',
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  ERROR = 'error',
}

// 渠道事件
export interface ChannelEventPayload {
  type: ChannelEvent;
  channel: string;
  data?: any;
  error?: Error;
  timestamp: number;
}
