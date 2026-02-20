/**
 * 飞书适配器 - 客户端封装
 * 参考 OpenClaw extensions/feishu/src/client.ts
 */

import * as Lark from '@larksuiteoapi/node-sdk';
import { ChannelConfig } from '../../core/types.js';

export type FeishuDomain = 'feishu' | 'lark' | string;

export interface FeishuCredentials {
  appId: string;
  appSecret: string;
  domain?: FeishuDomain;
}

// 客户端缓存
const clientCache = new Map<string, Lark.Client>();

function resolveDomain(domain: FeishuDomain | undefined): Lark.Domain | string {
  if (domain === 'lark') {
    return Lark.Domain.Lark;
  }
  if (domain === 'feishu' || !domain) {
    return Lark.Domain.Feishu;
  }
  return domain.replace(/\/+$/, '');
}

/**
 * 创建或获取缓存的飞书客户端
 */
export function createFeishuClient(creds: FeishuCredentials): Lark.Client {
  const cacheKey = `${creds.appId}:${creds.domain || 'feishu'}`;
  
  const cached = clientCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const client = new Lark.Client({
    appId: creds.appId,
    appSecret: creds.appSecret,
    appType: Lark.AppType.SelfBuild,
    domain: resolveDomain(creds.domain),
  });

  clientCache.set(cacheKey, client);
  return client;
}

/**
 * 创建 WebSocket 客户端
 */
export function createFeishuWSClient(creds: FeishuCredentials): Lark.WSClient {
  return new Lark.WSClient({
    appId: creds.appId,
    appSecret: creds.appSecret,
    domain: resolveDomain(creds.domain),
    loggerLevel: Lark.LoggerLevel.info,
  });
}

/**
 * 创建事件分发器
 */
export function createEventDispatcher(
  encryptKey?: string,
  verificationToken?: string
): Lark.EventDispatcher {
  return new Lark.EventDispatcher({
    encryptKey,
    verificationToken,
  });
}

/**
 * 从配置中提取凭证
 */
export function extractCredentials(config: ChannelConfig): FeishuCredentials {
  if (!config.appId || !config.appSecret) {
    throw new Error('Feishu: appId and appSecret are required');
  }
  return {
    appId: config.appId,
    appSecret: config.appSecret,
    domain: config.domain as FeishuDomain,
  };
}
