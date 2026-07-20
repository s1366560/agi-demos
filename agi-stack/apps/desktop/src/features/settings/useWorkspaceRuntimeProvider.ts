import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { DesktopApiClient, DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  DesktopRuntimeConfig,
  LlmProviderRoutingPolicy,
  LlmRoutingRole,
  ManagedLlmProvider,
  WorkspaceRuntimeProvider,
} from '../../types';
import {
  workspaceRuntimeModelOptions,
  workspaceRuntimeProviderFromAuthority,
  workspaceRuntimeRoutingMutation,
} from './workspaceRuntimeProviderModel';
import type { WorkspaceRuntimeModelOption } from './workspaceRuntimeProviderModel';

type WorkspaceRuntimeProviderSnapshot = {
  scopeKey: string;
  policy: LlmProviderRoutingPolicy | null;
  providers: ManagedLlmProvider[];
  provider: WorkspaceRuntimeProvider | null;
};

export type WorkspaceRuntimeProviderSelection = {
  provider: WorkspaceRuntimeProvider | null;
  modelOptions: WorkspaceRuntimeModelOption[];
  selectedModelValue: string | null;
  switchingModel: boolean;
  modelError: string | null;
  selectModel: (value: string) => Promise<void>;
};

export function useWorkspaceRuntimeProvider(
  config: DesktopRuntimeConfig,
  enabled: boolean,
  refreshRevision: number,
  role: LlmRoutingRole = 'default',
): WorkspaceRuntimeProviderSelection {
  const { t } = useI18n();
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
  const [snapshot, setSnapshot] = useState<WorkspaceRuntimeProviderSnapshot>({
    scopeKey: '',
    policy: null,
    providers: [],
    provider: null,
  });
  const snapshotRef = useRef(snapshot);
  const scopeKeyRef = useRef(scopeKey);
  const selectionRequestRef = useRef(0);
  const [selectionState, setSelectionState] = useState({
    scopeKey: '',
    switching: false,
    error: null as string | null,
  });
  snapshotRef.current = snapshot;
  scopeKeyRef.current = scopeKey;

  const commitAuthority = useCallback(
    (policy: LlmProviderRoutingPolicy, providers: ManagedLlmProvider[]) => {
      const nextSnapshot = {
        scopeKey,
        policy,
        providers,
        provider: workspaceRuntimeProviderFromAuthority(config, policy, providers, role),
      };
      snapshotRef.current = nextSnapshot;
      setSnapshot(nextSnapshot);
    },
    [config, role, scopeKey],
  );

  useEffect(() => {
    const controller = new AbortController();
    if (
      !enabled ||
      config.mode !== 'local' ||
      !config.tenantId.trim() ||
      !config.projectId.trim() ||
      !config.workspaceId.trim()
    ) {
      const emptySnapshot = { scopeKey, policy: null, providers: [], provider: null };
      snapshotRef.current = emptySnapshot;
      setSnapshot(emptySnapshot);
      selectionRequestRef.current += 1;
      setSelectionState({ scopeKey, switching: false, error: null });
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
          commitAuthority(policy, providers);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          const emptySnapshot = { scopeKey, policy: null, providers: [], provider: null };
          snapshotRef.current = emptySnapshot;
          setSnapshot(emptySnapshot);
        }
      });

    return () => controller.abort();
  }, [client, commitAuthority, config, enabled, refreshRevision, scopeKey]);

  const activeSnapshot =
    enabled && config.mode === 'local' && snapshot.scopeKey === scopeKey ? snapshot : null;
  const modelOptions = useMemo(
    () =>
      activeSnapshot?.policy
        ? workspaceRuntimeModelOptions(activeSnapshot.policy, activeSnapshot.providers, role)
        : [],
    [activeSnapshot, role],
  );
  const selectedModelValue = modelOptions.find((option) => option.selected)?.value ?? null;

  const selectModel = useCallback(
    async (value: string): Promise<void> => {
      const requestId = selectionRequestRef.current + 1;
      selectionRequestRef.current = requestId;
      const current = snapshotRef.current;
      const currentPolicy = current.scopeKey === scopeKey ? current.policy : null;
      const currentOption = currentPolicy
        ? workspaceRuntimeModelOptions(currentPolicy, current.providers, role).find(
            (option) => option.value === value,
          )
        : null;
      if (!enabled || config.mode !== 'local' || !currentPolicy || !currentOption) {
        throw new Error(t('chat.selectedModelUnavailable'));
      }
      if (currentOption.selected) return;

      setSelectionState({ scopeKey, switching: true, error: null });
      try {
        let providers = current.providers;
        let mutation = workspaceRuntimeRoutingMutation(config, currentPolicy, currentOption, role);
        if (!mutation) throw new Error(t('chat.modelRoutingContextChanged'));

        let updated: LlmProviderRoutingPolicy;
        try {
          updated = await client.updateLlmProviderRoutingPolicy(mutation);
        } catch (caught) {
          if (!(caught instanceof DesktopApiError) || caught.status !== 409) throw caught;
          const [latestPolicy, latestProviders] = await Promise.all([
            client.getLlmProviderRoutingPolicy(config.projectId, config.workspaceId),
            client.listLlmProviders(),
          ]);
          const latestOption = workspaceRuntimeModelOptions(
            latestPolicy,
            latestProviders,
            role,
          ).find((option) => option.value === value);
          if (!latestOption) {
            throw new Error(t('chat.selectedModelUnavailable'));
          }
          mutation = workspaceRuntimeRoutingMutation(config, latestPolicy, latestOption, role);
          if (!mutation) throw new Error(t('chat.modelRoutingContextChanged'));
          providers = latestProviders;
          updated = await client.updateLlmProviderRoutingPolicy(mutation);
        }

        if (selectionRequestRef.current !== requestId || scopeKeyRef.current !== scopeKey) return;
        commitAuthority(updated, providers);
        setSelectionState({ scopeKey, switching: false, error: null });
      } catch (caught) {
        if (selectionRequestRef.current === requestId && scopeKeyRef.current === scopeKey) {
          setSelectionState({
            scopeKey,
            switching: false,
            error: caught instanceof Error ? caught.message : String(caught),
          });
        }
        throw caught;
      }
    },
    [client, commitAuthority, config, enabled, role, scopeKey, t],
  );

  return {
    provider: activeSnapshot?.provider ?? null,
    modelOptions,
    selectedModelValue,
    switchingModel: selectionState.scopeKey === scopeKey && selectionState.switching,
    modelError: selectionState.scopeKey === scopeKey ? selectionState.error : null,
    selectModel,
  };
}
