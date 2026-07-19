import { useEffect, useMemo, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig, WorkspaceRuntimeProvider } from '../../types';
import { workspaceRuntimeProviderFromAuthority } from './workspaceRuntimeProviderModel';

export function useWorkspaceRuntimeProvider(
  config: DesktopRuntimeConfig,
  enabled: boolean,
  refreshRevision: number,
): WorkspaceRuntimeProvider | null {
  const client = useMemo(() => new DesktopApiClient(config), [config]);
  const scopeKey = [
    config.mode,
    config.apiBaseUrl,
    config.localApiToken,
    config.apiKey,
    config.tenantId,
    config.projectId,
    config.workspaceId,
  ].join('\u0000');
  const [snapshot, setSnapshot] = useState<{
    scopeKey: string;
    provider: WorkspaceRuntimeProvider | null;
  }>({ scopeKey: '', provider: null });

  useEffect(() => {
    const controller = new AbortController();
    if (
      !enabled ||
      config.mode !== 'local' ||
      !config.tenantId.trim() ||
      !config.projectId.trim() ||
      !config.workspaceId.trim()
    ) {
      setSnapshot({ scopeKey, provider: null });
      return () => controller.abort();
    }

    void Promise.all([
      client.getLlmProviderRoutingPolicy(
        config.projectId,
        config.workspaceId,
        controller.signal,
      ),
      client.listLlmProviders(controller.signal),
    ])
      .then(([policy, providers]) => {
        if (!controller.signal.aborted) {
          setSnapshot({
            scopeKey,
            provider: workspaceRuntimeProviderFromAuthority(config, policy, providers),
          });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setSnapshot({ scopeKey, provider: null });
      });

    return () => controller.abort();
  }, [client, config, enabled, refreshRevision, scopeKey]);

  return enabled && config.mode === 'local' && snapshot.scopeKey === scopeKey
    ? snapshot.provider
    : null;
}
