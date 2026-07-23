import { useCallback, useEffect, useMemo, useState } from 'react';

import { DesktopApiClient, DesktopApiError } from '../../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedLlmProvider,
  WorkspaceAgentPolicy,
} from '../../types';
import { workspaceRuntimeModelOptions } from './workspaceRuntimeProviderModel';
import type { WorkspaceRuntimeModelOption } from './workspaceRuntimeProviderModel';

type WorkspaceAgentPolicyState = {
  scopeKey: string;
  policy: WorkspaceAgentPolicy | null;
  providers: ManagedLlmProvider[];
  loading: boolean;
  compatibilityMode: boolean;
  error: string | null;
};

export type WorkspaceAgentPolicyAuthority = WorkspaceAgentPolicyState & {
  workModelOptions: WorkspaceRuntimeModelOption[];
  codeModelOptions: WorkspaceRuntimeModelOption[];
  refresh: () => void;
  acceptPolicy: (policy: WorkspaceAgentPolicy) => void;
};

export function useWorkspaceAgentPolicy(
  config: DesktopRuntimeConfig,
  enabled: boolean,
): WorkspaceAgentPolicyAuthority {
  const client = useMemo(() => new DesktopApiClient(config), [config]);
  const scopeKey = [
    config.mode,
    config.apiBaseUrl,
    config.tenantId,
    config.projectId,
    config.workspaceId,
  ].join('\u0000');
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [state, setState] = useState<WorkspaceAgentPolicyState>({
    scopeKey: '',
    policy: null,
    providers: [],
    loading: false,
    compatibilityMode: false,
    error: null,
  });

  useEffect(() => {
    const controller = new AbortController();
    if (!enabled || !config.tenantId || !config.projectId || !config.workspaceId) {
      setState({
        scopeKey,
        policy: null,
        providers: [],
        loading: false,
        compatibilityMode: false,
        error: null,
      });
      return () => controller.abort();
    }
    setState((current) => ({ ...current, scopeKey, loading: true, error: null }));
    void Promise.all([
      loadAgentPolicy(client, config.projectId, config.workspaceId, controller.signal),
      client.listLlmProviders(controller.signal),
    ])
      .then(([policyResult, providers]) => {
        if (controller.signal.aborted) return;
        setState({
          scopeKey,
          policy: policyResult.policy,
          providers,
          loading: false,
          compatibilityMode: policyResult.compatibilityMode,
          error: null,
        });
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setState({
          scopeKey,
          policy: null,
          providers: [],
          loading: false,
          compatibilityMode: false,
          error: caught instanceof Error ? caught.message : String(caught),
        });
      });
    return () => controller.abort();
  }, [client, config, enabled, refreshRevision, scopeKey]);

  const current = state.scopeKey === scopeKey ? state : { ...state, policy: null, providers: [] };
  const refresh = useCallback(() => setRefreshRevision((value) => value + 1), []);
  const acceptPolicy = useCallback(
    (policy: WorkspaceAgentPolicy) => {
      setState((currentState) =>
        currentState.scopeKey === scopeKey
          ? { ...currentState, policy, compatibilityMode: false, error: null }
          : currentState,
      );
    },
    [scopeKey],
  );
  return {
    ...current,
    workModelOptions: current.policy
      ? workspaceRuntimeModelOptions(current.policy, current.providers, 'default', config.mode)
      : [],
    codeModelOptions: current.policy
      ? workspaceRuntimeModelOptions(current.policy, current.providers, 'coding', config.mode)
      : [],
    refresh,
    acceptPolicy,
  };
}

async function loadAgentPolicy(
  client: DesktopApiClient,
  projectId: string,
  workspaceId: string,
  signal: AbortSignal,
): Promise<{ policy: WorkspaceAgentPolicy; compatibilityMode: boolean }> {
  try {
    return {
      policy: await client.getWorkspaceAgentPolicy(projectId, workspaceId, signal),
      compatibilityMode: false,
    };
  } catch (caught) {
    if (
      !(caught instanceof DesktopApiError) ||
      (caught.status !== 404 && caught.status !== 405 && caught.status !== 501)
    ) {
      throw caught;
    }
    const legacy = await client.getLlmProviderRoutingPolicy(projectId, workspaceId, signal);
    return {
      policy: {
        ...legacy,
        reasoning_effort: 'medium',
        permission_mode: 'ask',
        capability_version: 'legacy-routing-policy-v1',
      },
      compatibilityMode: true,
    };
  }
}
