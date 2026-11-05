import { useEffect } from 'react';
import type { DesktopRuntimeConfig } from '../../types';

/** UI selection gives new user tabs a conversation; it never claims agent tabs. */
export function useBrowserContext(
  config: DesktopRuntimeConfig,
  conversationId: string | null,
  authenticated: boolean,
): void {
  useEffect(() => {
    const desktop = window.__MEMSTACK_DESKTOP__;
    const bridge = desktop?.iab;
    if (!bridge) return;
    const context = {
      conversation_id: authenticated ? conversationId : null,
      mode: config.mode,
      tenant_id: config.tenantId,
      project_id: config.projectId,
      ...(config.mode === 'local' ? { credential: config.apiKey } : {}),
    };
    let disposed = false;
    let revision = 0;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const activate = async () => {
      clearTimeout(timer);
      const request = ++revision;
      try {
        await bridge.activateContext(context);
        if (!disposed && request === revision) failures = 0;
      } catch {
        // The main process clears the old destination before authentication.
        // Retry only this live selection; stale failures cannot restore it.
        if (!disposed && request === revision && context.conversation_id) {
          const delay = Math.min(1000 * 2 ** Math.min(failures++, 3), 5000);
          timer = setTimeout(() => void activate(), delay);
        }
      }
    };
    void activate();
    const unsubscribe = desktop.events?.onSidecarRecovered?.(() => void activate());
    return () => {
      disposed = true;
      revision += 1;
      clearTimeout(timer);
      unsubscribe?.();
      void bridge.activateContext({ ...context, conversation_id: null }).catch(() => {});
    };
  }, [config.mode, config.apiBaseUrl, config.apiKey, config.tenantId, config.projectId,
    conversationId, authenticated]);
}
