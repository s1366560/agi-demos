import { useLayoutEffect, useSyncExternalStore } from 'react';

import {
  createWebRendererDefinitionsV2,
  RendererGenerationLeaseStoreV2,
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  projectRendererPluginGenerationStateV2,
  startRendererGenerationPollingV2,
  WebPublicViewReconcilerV2,
  type RendererPluginGenerationStateV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import { validateWebRendererContributionsV2 } from '../routes/v2/webRendererArtifactCatalogV2';
import { kernelHttpClient } from '../services/client/kernelHttpClient';
import { useAuthStore } from '../stores/auth';
import { useTenantStore } from '../stores/tenant';
import { useProjectStore } from '../stores/project';
import { WebOperationAdmissionV2, installWebOperationAdmissionV2 } from './webOperationAdmissionV2';
import { logger } from '../utils/logger';
import { WebPublicViewIdentityV2 } from './webPublicViewIdentityV2';

const POLL_INTERVAL_MS = 30_000;
const webRendererRuntimeV2 = new RendererPluginRuntimeV2(
  'web',
  createWebRendererDefinitionsV2(validateWebRendererContributionsV2),
  validateWebRendererContributionsV2
);
const webRendererLeaseStoreV2 = new RendererGenerationLeaseStoreV2(webRendererRuntimeV2);
const webRendererStatusStoreV2 = new RendererGenerationStatusStoreV2();
let hostEnabled = false;
let operationAdmission: WebOperationAdmissionV2 | undefined;
let detachOperations: (() => void) | undefined;
let identitySubscriptions: Array<() => void> = [];

const identityLifecycle = new WebPublicViewIdentityV2(
  webRendererRuntimeV2,
  webRendererStatusStoreV2,
  (ready) => operationAdmission?.setEnabled(ready),
  (error) => logger.error('Failed to close plugin generation', error)
);

function refreshIdentity(): void {
  void identityLifecycle.replace(
    hostEnabled && useAuthStore.getState().isAuthenticated
      ? fetchWebPluginDistributionV2
      : undefined
  );
}

export type WebPluginDistributionSourceV2 = (signal: AbortSignal) => Promise<unknown | null>;

export function activateWebPluginGenerationRootV2(): void {
  webRendererLeaseStoreV2.activateRoot();
  operationAdmission = new WebOperationAdmissionV2(webRendererRuntimeV2);
  detachOperations = installWebOperationAdmissionV2(operationAdmission);
  const admission = operationAdmission;
  admission.setEnabled(false);
  identitySubscriptions = [
    useAuthStore.subscribe((state, previous) => {
      if (
        state.token !== previous.token ||
        state.user?.id !== previous.user?.id ||
        state.isAuthenticated !== previous.isAuthenticated
      )
        refreshIdentity();
    }),
    useTenantStore.subscribe((state, previous) => {
      if (state.currentTenant?.id !== previous.currentTenant?.id) refreshIdentity();
    }),
    useProjectStore.subscribe((state, previous) => {
      if (state.currentProject?.id !== previous.currentProject?.id) refreshIdentity();
    }),
  ];
}

export async function deactivateWebPluginGenerationRootV2(): Promise<void> {
  hostEnabled = false;
  const viewClosing = identityLifecycle.replace();
  const admission = operationAdmission;
  operationAdmission = undefined;
  detachOperations?.();
  detachOperations = undefined;
  for (const unsubscribe of identitySubscriptions) unsubscribe();
  identitySubscriptions = [];
  // Revoke the old root synchronously so a replacement root can mount while I/O drains.
  const rootClosing = webRendererLeaseStoreV2.deactivateRoot();
  const operationsClosing = admission?.close();
  const results = await Promise.allSettled([rootClosing, operationsClosing, viewClosing]);
  const failed = results.find((result) => result.status === 'rejected');
  if (failed?.status === 'rejected') throw failed.reason;
}

export function startWebPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  source: WebPluginDistributionSourceV2,
  pollIntervalMs = POLL_INTERVAL_MS,
  statusStore = new RendererGenerationStatusStoreV2()
): () => void {
  const reconciler = new WebPublicViewReconcilerV2(runtime);
  return startRendererGenerationPollingV2({
    runtime,
    source,
    statusStore,
    pollIntervalMs,
    apply: async (payload) => {
      await reconciler.apply(payload);
      return undefined;
    },
  });
}

export function useWebPluginGenerationV2(enabled: boolean): RendererPluginGenerationStateV2 {
  const ready = useSyncExternalStore(
    identityLifecycle.subscribe,
    identityLifecycle.getSnapshot,
    identityLifecycle.getSnapshot
  );
  const generation = useRendererGenerationLeaseV2(webRendererLeaseStoreV2);
  const status = useSyncExternalStore(
    webRendererStatusStoreV2.subscribe,
    webRendererStatusStoreV2.getSnapshot,
    webRendererStatusStoreV2.getSnapshot
  );
  useLayoutEffect(() => {
    hostEnabled = enabled;
    refreshIdentity();
    return () => {
      hostEnabled = false;
      refreshIdentity();
    };
  }, [enabled]);
  return projectRendererPluginGenerationStateV2(enabled, ready ? generation : undefined, status);
}

export function useRendererPluginGenerationStateV2(
  enabled: boolean,
  leaseStore: RendererGenerationLeaseStoreV2,
  statusStore: RendererGenerationStatusStoreV2
): RendererPluginGenerationStateV2 {
  const generation = useRendererGenerationLeaseV2(leaseStore);
  const status = useSyncExternalStore(
    statusStore.subscribe,
    statusStore.getSnapshot,
    statusStore.getSnapshot
  );
  return projectRendererPluginGenerationStateV2(enabled, generation, status);
}

export function useRendererGenerationLeaseV2(
  store: RendererGenerationLeaseStoreV2
): RuntimeGenerationV2 | undefined {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  useLayoutEffect(() => {
    void store.commit(snapshot).catch((error: unknown) => {
      logger.error('Failed to commit plugin generation lease', error);
    });
  }, [snapshot, store]);
  return snapshot.generation;
}

async function fetchWebPluginDistributionV2(signal: AbortSignal): Promise<unknown | null> {
  return kernelHttpClient.get<unknown>('/platform-plugins/v2/web-view', { signal });
}
