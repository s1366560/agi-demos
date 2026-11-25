import interaction from './desktopInteractionMessages.json';
import { createContext, useContext } from 'react';
import {
  runtimeClustersEnUS,
  runtimeClustersZhCN,
} from '../desktop/runtime-clusters/locales/runtimeClustersMessages';

export const DesktopLocale = createContext('en');
export function useI18n(en?: Record<string, string>, chinese?: Record<string, string>) {
  const zh = useContext(DesktopLocale).startsWith('zh');
  const table: Record<string, string> = zh
    ? { ...runtimeClustersZhCN, ...interaction.zh, ...chinese }
    : { ...runtimeClustersEnUS, ...interaction.en, ...en };
  const common: Record<string, string> = zh
    ? { 'common.close': '关闭', 'common.refresh': '刷新', 'common.retry': '重试' }
    : { 'common.close': 'Close', 'common.refresh': 'Refresh', 'common.retry': 'Retry' };
  return {
    t(key: string, params?: Record<string, string | number>) {
      return (table[key] ?? common[key] ?? key).replace(/\{(\w+)\}/g, (match, name: string) =>
        String(params?.[name] ?? match),
      );
    },
  };
}
