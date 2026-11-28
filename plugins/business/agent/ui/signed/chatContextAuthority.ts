import { useSyncExternalStore } from 'react';
import { invoke } from './reviewAuthority';
import type { agentService as canonicalService } from '../../../../../web/src/services/agentService';
export const agentService = {
  getContextStatus: (conversation_id: string) =>
    invoke<Awaited<ReturnType<typeof canonicalService.getContextStatus>>>('chat-project-context', {
      view: 'context-window',
      conversation_id,
    }),
};

function subscribe(listener: () => void) {
  const observer = new MutationObserver(listener);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class', 'data-theme'],
  });
  return () => observer.disconnect();
}

export function usePageDarkMode() {
  return useSyncExternalStore(subscribe, () => document.documentElement.classList.contains('dark'));
}
export function resolveThemeColor(property: string, fallback = '') {
  return getComputedStyle(document.documentElement).getPropertyValue(property).trim() || fallback;
}
export function useThemeColors<K extends string>(tokens: Record<K, string>) {
  usePageDarkMode();
  return Object.fromEntries(
    Object.entries(tokens).map(([key, property]) => [key, resolveThemeColor(property as string)])
  ) as Record<K, string>;
}
