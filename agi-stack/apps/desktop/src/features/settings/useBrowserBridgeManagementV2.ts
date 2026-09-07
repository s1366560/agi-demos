import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { BrowserBridgeManagementRuntimeStatusV2 } from '../../plugins/desktopBrowserBridgeManagementOperationContractV2';
import type { DesktopBrowserBridgeManagementClientV2 } from '../../plugins/desktopBrowserBridgeManagementAuthorityModuleV2';
import type {
  BrowserBridgeInstallResult,
  BrowserBridgeStatus,
  BrowserBridgeUninstallResult,
  DesktopRuntimeConfig,
} from '../../types';
const POLL_MS = 5000;
const empty = () => ({
  runtimeStatus: null as BrowserBridgeManagementRuntimeStatusV2 | null,
  bridgeStatus: null as BrowserBridgeStatus | null,
  optimisticEnabled: null as boolean | null,
  optimisticFullCdpEnabled: null as boolean | null,
  toggleBusy: false,
  fullCdpToggleBusy: false,
  actionBusy: null as 'install' | 'uninstall' | null,
  toggleError: null as string | null,
  fullCdpToggleError: null as string | null,
  actionError: null as string | null,
  loadError: null as string | null,
  installResult: null as BrowserBridgeInstallResult | null,
  uninstallResult: null as BrowserBridgeUninstallResult | null,
});
type State = ReturnType<typeof empty>;
export function useBrowserBridgeManagementV2(
  client: DesktopBrowserBridgeManagementClientV2,
  config?: DesktopRuntimeConfig,
) {
  const lifetime = useMemo(
    () => ({
      controller: new AbortController(),
      tail: Promise.resolve(),
      pending: 0,
      mutating: null as object | null,
    }),
    [client, config],
  );
  const latest = useRef(lifetime);
  latest.current = lifetime;
  const [stored, setStored] = useState(() => ({ lifetime, value: empty() }));
  const value = stored.lifetime === lifetime ? stored.value : empty();
  const active = useCallback(
    (signal: AbortSignal) => latest.current === lifetime && !signal.aborted,
    [lifetime],
  );
  const patch = useCallback(
    (change: Partial<State>) => {
      setStored((previous) => ({
        lifetime,
        value: { ...(previous.lifetime === lifetime ? previous.value : empty()), ...change },
      }));
    },
    [lifetime],
  );
  const enqueue = useCallback(
    (operation: (signal: AbortSignal) => Promise<void>) => {
      const signal = lifetime.controller.signal;
      if (!active(signal)) return Promise.resolve();
      lifetime.pending++;
      const task = lifetime.tail.then(async () => {
        if (active(signal)) await operation(signal);
      });
      lifetime.tail = task.catch(() => undefined);
      return task.finally(() => {
        lifetime.pending--;
      });
    },
    [active, lifetime],
  );
  const refresh = useCallback(
    () =>
      enqueue(async (signal) => {
        try {
          const snapshot = await client.loadSnapshot(signal);
          if (active(signal)) patch({ ...snapshot, loadError: null });
        } catch (error) {
          if (active(signal)) patch({ loadError: formatError(error) });
        }
      }),
    [active, client, enqueue, patch],
  );
  useLayoutEffect(() => {
    if (lifetime.controller.signal.aborted) lifetime.controller = new AbortController();
    const signal = lifetime.controller.signal;
    setStored({ lifetime, value: empty() });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (!active(signal)) return;
      if (lifetime.pending === 0) await refresh();
      if (active(signal))
        timer = setTimeout(() => {
          void poll();
        }, POLL_MS);
    };
    void poll();
    return () => {
      lifetime.controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [active, lifetime, refresh]);
  const mutate = useCallback(
    (kind: 'enabled' | 'fullCdp' | 'install' | 'uninstall', next?: boolean) => {
      const signal = lifetime.controller.signal;
      if (!active(signal) || lifetime.mutating) return Promise.resolve();
      const mutation = {};
      lifetime.mutating = mutation;
      if (kind === 'enabled')
        patch({ optimisticEnabled: next ?? false, toggleBusy: true, toggleError: null });
      else if (kind === 'fullCdp')
        patch({
          optimisticFullCdpEnabled: next ?? false,
          fullCdpToggleBusy: true,
          fullCdpToggleError: null,
        });
      else patch({ actionBusy: kind, actionError: null });
      return enqueue(async (operationSignal) => {
        try {
          if (kind === 'enabled' || kind === 'fullCdp') {
            const runtimeStatus = await (kind === 'enabled'
              ? client.setEnabled(next ?? false, operationSignal)
              : client.setFullCdpEnabled(next ?? false, operationSignal));
            if (active(operationSignal)) patch({ runtimeStatus });
          } else if (kind === 'install') {
            const result = await client.install(operationSignal);
            if (active(operationSignal)) patch({ installResult: result, uninstallResult: null });
          } else {
            const result = await client.uninstall(operationSignal);
            if (active(operationSignal)) patch({ uninstallResult: result, installResult: null });
          }
          if (active(operationSignal)) {
            try {
              const snapshot = await client.loadSnapshot(operationSignal);
              if (active(operationSignal)) patch({ ...snapshot, loadError: null });
            } catch (error) {
              if (active(operationSignal)) patch({ loadError: formatError(error) });
            }
          }
        } catch (error) {
          if (active(operationSignal))
            patch(
              kind === 'enabled'
                ? { toggleError: formatError(error) }
                : kind === 'fullCdp'
                  ? { fullCdpToggleError: formatError(error) }
                  : { actionError: formatError(error) },
            );
        } finally {
          if (active(operationSignal))
            patch({
              optimisticEnabled: null,
              optimisticFullCdpEnabled: null,
              toggleBusy: false,
              fullCdpToggleBusy: false,
              actionBusy: null,
            });
        }
      }).finally(() => {
        if (lifetime.mutating === mutation) lifetime.mutating = null;
      });
    },
    [active, client, enqueue, lifetime, patch],
  );
  return {
    ...value,
    enabled:
      value.optimisticEnabled ??
      value.runtimeStatus?.config.browser_bridge?.enabled ??
      value.bridgeStatus?.enabled ??
      false,
    fullCdpEnabled:
      value.optimisticFullCdpEnabled ??
      value.runtimeStatus?.config.browser_bridge?.full_cdp_access_enabled ??
      false,
    toggleBridge: (next: boolean) => mutate('enabled', next),
    toggleFullCdp: (next: boolean) => mutate('fullCdp', next),
    runRegistration: (action: 'install' | 'uninstall') => mutate(action),
  };
}
function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
