import { useEffect, useLayoutEffect, useSyncExternalStore } from 'react';

import {
  createWebRendererDefinitionsV2,
  RendererGenerationLeaseStoreV2,
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  projectRendererPluginGenerationStateV2,
  startRendererGenerationPollingV2,
  type RendererPluginGenerationStateV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import { validateWebRendererContributionsV2 } from '../routes/v2/webRendererArtifactCatalogV2';
import { ApiError } from '../services/client/ApiError';
import { kernelHttpClient } from '../services/client/kernelHttpClient';
import { useAuthStore } from '../stores/auth';
import { useTenantStore } from '../stores/tenant';
import { useProjectStore } from '../stores/project';
import { WebOperationAdmissionV2, installWebOperationAdmissionV2 } from './webOperationAdmissionV2';
import { logger } from '../utils/logger';

const POLL_INTERVAL_MS = 30_000;
const webRendererRuntimeV2 = new RendererPluginRuntimeV2(
  'web',
  createWebRendererDefinitionsV2(validateWebRendererContributionsV2)
);
const webRendererLeaseStoreV2 = new RendererGenerationLeaseStoreV2(webRendererRuntimeV2);
const webRendererStatusStoreV2 = new RendererGenerationStatusStoreV2();
let pendingClose: ReturnType<typeof setTimeout> | null = null;
let operationAdmission: WebOperationAdmissionV2 | undefined;
let detachOperations: (() => void) | undefined;
let identitySubscriptions: Array<() => void> = [];

export type WebPluginDistributionSourceV2 = (signal: AbortSignal) => Promise<unknown | null>;

export function activateWebPluginGenerationRootV2(): void {
  if (pendingClose !== null) {
    clearTimeout(pendingClose);
    pendingClose = null;
  }
  webRendererLeaseStoreV2.activateRoot();
  operationAdmission = new WebOperationAdmissionV2(webRendererRuntimeV2);
  detachOperations = installWebOperationAdmissionV2(operationAdmission);
  const admission = operationAdmission;
  admission.setEnabled(useAuthStore.getState().isAuthenticated);
  identitySubscriptions = [
    useAuthStore.subscribe((state, previous) => {
      if (
        state.token !== previous.token ||
        state.user?.id !== previous.user?.id ||
        state.isAuthenticated !== previous.isAuthenticated
      )
        admission.invalidate();
      admission.setEnabled(state.isAuthenticated);
    }),
    useTenantStore.subscribe((state, previous) => {
      if (state.currentTenant?.id !== previous.currentTenant?.id) admission.invalidate();
    }),
    useProjectStore.subscribe((state, previous) => {
      if (state.currentProject?.id !== previous.currentProject?.id) admission.invalidate();
    }),
  ];
}

export async function deactivateWebPluginGenerationRootV2(): Promise<void> {
  const admission = operationAdmission;
  operationAdmission = undefined;
  detachOperations?.();
  detachOperations = undefined;
  for (const unsubscribe of identitySubscriptions) unsubscribe();
  identitySubscriptions = [];
  // Revoke the old root synchronously so a replacement root can mount while I/O drains.
  const rootClosing = webRendererLeaseStoreV2.deactivateRoot();
  const operationsClosing = admission?.close();
  const results = await Promise.allSettled([rootClosing, operationsClosing]);
  const failed = results.find((result) => result.status === 'rejected');
  if (failed?.status === 'rejected') throw failed.reason;
}

export function startWebPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  source: WebPluginDistributionSourceV2,
  pollIntervalMs = POLL_INTERVAL_MS,
  statusStore = new RendererGenerationStatusStoreV2()
): () => void {
  return startRendererGenerationPollingV2({ runtime, source, statusStore, pollIntervalMs });
}

export function useWebPluginGenerationV2(enabled: boolean): RendererPluginGenerationStateV2 {
  const state = useRendererPluginGenerationStateV2(
    enabled,
    webRendererLeaseStoreV2,
    webRendererStatusStoreV2
  );

  useLayoutEffect(() => {
    const admission = operationAdmission;
    admission?.setEnabled(enabled);
    return () => admission?.setEnabled(false);
  }, [enabled]);

  useEffect(() => {
    if (pendingClose !== null) {
      clearTimeout(pendingClose);
      pendingClose = null;
    }
    if (!enabled) {
      scheduleClose();
      return;
    }
    const stop = startWebPluginGenerationPollingV2(
      webRendererRuntimeV2,
      fetchWebPluginDistributionV2,
      POLL_INTERVAL_MS,
      webRendererStatusStoreV2
    );
    return () => {
      stop();
      scheduleClose();
    };
  }, [enabled]);

  return state;
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
  try {
    return await kernelHttpClient.get<unknown>('/platform-plugins/v2/distribution', { signal });
  } catch (error) {
    if (error instanceof ApiError && error.statusCode === 404) return null;
    throw error;
  }
}

function scheduleClose(): void {
  pendingClose = setTimeout(() => {
    pendingClose = null;
    void webRendererRuntimeV2.close().catch((error: unknown) => {
      logger.error('Failed to close plugin generation', error);
      webRendererStatusStoreV2.fail(error, webRendererRuntimeV2.getSnapshot() !== undefined);
    });
  }, 0);
}
