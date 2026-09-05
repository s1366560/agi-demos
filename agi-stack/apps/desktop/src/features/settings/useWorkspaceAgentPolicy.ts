import { useCallback, useEffect, useState } from 'react';

import type { DesktopWorkspaceAgentPolicyClientV2 } from '../../plugins/desktopWorkspaceAgentPolicyAuthorityModuleV2';
import type { DesktopTenantProvidersClientV2 } from '../../plugins/desktopTenantProvidersAuthorityModuleV2';
import type { DesktopWorkspaceRosterOperationsV2 } from '../../plugins/desktopWorkspaceRosterAuthorityModuleV2';
import type {
  DesktopRuntimeConfig,
  ManagedLlmProvider,
  WorkspaceAgentPolicy,
  WorkspaceMemberSummary,
} from '../../types';
import { workspaceRuntimeModelOptions } from './workspaceRuntimeProviderModel';
import type { WorkspaceRuntimeModelOption } from './workspaceRuntimeProviderModel';

type WorkspaceAgentPolicyState = {
  scopeKey: string;
  policy: WorkspaceAgentPolicy | null;
  providers: ManagedLlmProvider[];
  members: WorkspaceMemberSummary[];
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
  workspaceRosterOperationsV2: DesktopWorkspaceRosterOperationsV2,
  policyClient: DesktopWorkspaceAgentPolicyClientV2,
  providerClient: Pick<DesktopTenantProvidersClientV2, 'listLlmProviders'>,
): WorkspaceAgentPolicyAuthority {
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
    members: [],
    loading: false,
    compatibilityMode: false,
    error: null,
  });

  useEffect(() => {
    const controller = new AbortController();
    if (!enabled || !config.tenantId || !config.projectId) {
      setState({
        scopeKey,
        policy: null,
        providers: [],
        members: [],
        loading: false,
        compatibilityMode: false,
        error: null,
      });
      return () => controller.abort();
    }
    setState({
      scopeKey,
      policy: null,
      providers: [],
      members: [],
      loading: true,
      compatibilityMode: false,
      error: null,
    });
    const policyPromise = config.workspaceId
      ? policyClient.getWorkspaceAgentPolicy(
          config.projectId,
          config.workspaceId,
          controller.signal,
        )
      : Promise.resolve<WorkspaceAgentPolicy | null>(null);
    const membersPromise = config.workspaceId
      ? workspaceRosterOperationsV2.listWorkspaceMembers({
          config,
          signal: controller.signal,
        })
      : Promise.resolve<WorkspaceMemberSummary[]>([]);
    void Promise.all([
      policyPromise,
      providerClient.listLlmProviders(controller.signal),
      membersPromise,
    ])
      .then(([policy, providers, members]) => {
        if (controller.signal.aborted) return;
        setState({
          scopeKey,
          policy,
          providers,
          members,
          loading: false,
          compatibilityMode: false,
          error: null,
        });
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setState({
          scopeKey,
          policy: null,
          providers: [],
          members: [],
          loading: false,
          compatibilityMode: false,
          error: caught instanceof Error ? caught.message : String(caught),
        });
      });
    return () => controller.abort();
  }, [
    policyClient,
    providerClient,
    config,
    enabled,
    refreshRevision,
    scopeKey,
    workspaceRosterOperationsV2,
  ]);

  const current =
    state.scopeKey === scopeKey ? state : { ...state, policy: null, providers: [], members: [] };
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
