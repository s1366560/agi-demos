import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { DesktopApiClient } from '../api/client';

import {
  DesktopRendererDeliveryReconcilerV2,
  RendererGenerationLeaseStoreV2,
  RendererGenerationStatusStoreV2,
  projectRendererPluginGenerationStateV2,
  startRendererGenerationPollingV2,
  type GenerationLeaseV2,
  type RendererPluginGenerationStateV2,
  type RuntimeGenerationV2,
  type RendererPluginRuntimeV2,
} from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';

import { createDesktopProductionRendererRuntimeV2 } from './desktopProductionRendererRuntimeV2';
import { assertDesktopRendererDeliveryAvailableV2 } from './desktopRendererDeliveryStatusV2';

const RENDERER_DISTRIBUTION_COMMAND_V2 = 'platform_plugin_renderer_delivery_current_v2';
const POLL_INTERVAL_MS = 30_000;

const desktopRendererRuntimeV2 = createDesktopProductionRendererRuntimeV2();
const desktopRendererLeaseStoreV2 = new RendererGenerationLeaseStoreV2(desktopRendererRuntimeV2);
const desktopRendererStatusStoreV2 = new RendererGenerationStatusStoreV2();
const desktopRendererDistributionReconcilerV2 = new DesktopRendererDeliveryReconcilerV2(
  desktopRendererRuntimeV2,
  async (delivery_token, receipt) => {
    const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
    if (!invoke) throw new Error('desktop_renderer_receipt_ipc_unavailable');
    await invoke('platform_plugin_renderer_receipt_submit_v2', { delivery_token, receipt });
  },
  async () => {
    await window.__MEMSTACK_DESKTOP__?.core?.invoke?.('platform_plugin_renderer_owner_retire_v2');
  }
);
export const DESKTOP_PLUGIN_CONFIGURATION_CHANGED_V2 = 'memstack:plugin-configuration-changed-v2';
let pendingClose: ReturnType<typeof setTimeout> | null = null;

export function activateDesktopPluginGenerationRootV2(): void {
  desktopRendererLeaseStoreV2.activateRoot();
}
export async function deactivateDesktopPluginGenerationRootV2(): Promise<void> {
  await desktopRendererLeaseStoreV2.deactivateRoot();
}

export function acquireDesktopPluginGenerationLeaseV2(
  generation: RuntimeGenerationV2
): GenerationLeaseV2 {
  return desktopRendererLeaseStoreV2.acquireGeneration(generation);
}

export function useDesktopPluginGenerationV2(
  config: DesktopRuntimeConfig,
  enabled: boolean,
  accountId?: string
): RendererPluginGenerationStateV2 {
  const owner = useMemo(() => Object.freeze({ config: { ...config }, accountId }), [
    config.mode, config.apiBaseUrl, config.apiKey, config.localApiToken,
    config.tenantId, config.projectId, accountId,
  ]);
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const openedOwner = useRef<typeof owner | null>(null);
  const [readyOwner, setReadyOwner] = useState<typeof owner | null>(null);
  const snapshot = useSyncExternalStore(
    desktopRendererLeaseStoreV2.subscribe,
    desktopRendererLeaseStoreV2.getSnapshot,
    desktopRendererLeaseStoreV2.getSnapshot
  );
  const status = useSyncExternalStore(
    desktopRendererStatusStoreV2.subscribe,
    desktopRendererStatusStoreV2.getSnapshot,
    desktopRendererStatusStoreV2.getSnapshot
  );
  useLayoutEffect(() => {
    if (readyOwner !== owner) return;
    void desktopRendererLeaseStoreV2.commit(snapshot).catch((error: unknown) => {
      desktopRendererStatusStoreV2.fail(
        error,
        desktopRendererRuntimeV2.getSnapshot() !== undefined
      );
    });
  }, [snapshot, readyOwner, owner]);

  useEffect(() => {
    if (pendingClose !== null) {
      clearTimeout(pendingClose);
      pendingClose = null;
    }
    if (!enabled) {
      scheduleClose();
      return;
    }

    let stopped = false;
    let stopPolling: (() => void) | undefined;
    openedOwner.current = null;
    const start = () => {
      stopPolling?.();
      stopPolling = startDesktopPluginGenerationPollingV2(
        desktopRendererRuntimeV2, desktopRendererStatusStoreV2, owner.config,
        () => !stopped && currentOwner.current === owner,
        () => { if (!stopped && currentOwner.current === owner) setReadyOwner(owner); },
      );
    };
    // Retire the old owner before staging a new scope. Rendering is already blocked
    // synchronously by readyOwner, including while an old network request drains.
    void desktopRendererDistributionReconcilerV2.close().then(() => {
      if (!stopped && currentOwner.current === owner) {
        openedOwner.current = owner;
        start();
      }
    }).catch((error: unknown) => {
      if (!stopped) {
        console.warn('[desktop-plugin-generation]', generationFailureTextV2(error));
        desktopRendererStatusStoreV2.fail(error, false);
      }
    });
    const refresh = () => { if (!stopped && currentOwner.current === owner) start(); };
    window.addEventListener(DESKTOP_PLUGIN_CONFIGURATION_CHANGED_V2, refresh);
    return () => {
      stopped = true;
      openedOwner.current = null;
      stopPolling?.();
      window.removeEventListener(DESKTOP_PLUGIN_CONFIGURATION_CHANGED_V2, refresh);
      scheduleClose();
    };
  }, [enabled, owner]);

  useEffect(() => {
    // Cloud apply publishes the lease, then awaits the receipt IPC before onReady.
    // Show that published generation for the owner whose close already finished.
    if (!enabled || openedOwner.current !== owner || readyOwner === owner) return;
    if (snapshot.generation) setReadyOwner(owner);
  }, [enabled, owner, readyOwner, snapshot.generation]);

  const state = projectRendererPluginGenerationStateV2(enabled, readyOwner === owner ? snapshot.generation : undefined, status);
  const blocked = enabled && readyOwner !== owner && status.status !== 'error';
  const visibleStatus = blocked ? 'loading' : state.status;
  const visibleDigest = blocked ? '' : state.generation?.snapshot.digest ?? '';
  useEffect(() => {
    console.info(`[desktop-plugin-generation] ${visibleStatus} digest=${visibleDigest || 'none'}`);
  }, [visibleDigest, visibleStatus]);
  if (blocked) return Object.freeze({ status: 'loading', generation: undefined, error: undefined });
  return state;
}

function startDesktopPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  statusStore: RendererGenerationStatusStoreV2,
  config: DesktopRuntimeConfig,
  isCurrent: () => boolean,
  onReady: () => void,
): () => void {
  let sourceSignal: AbortSignal | undefined;
  return startRendererGenerationPollingV2({
    runtime,
    source: async (signal) => {
      sourceSignal = signal;
      try {
        const payload = await fetchDesktopPluginDistributionV2(signal, config);
        signal.throwIfAborted();
        if (!isCurrent()) throw new Error('desktop_renderer_owner_changed');
        return payload;
      } catch (error) {
        if (!signal.aborted) {
          console.warn('[desktop-plugin-generation]', generationFailureTextV2(error));
        }
        throw error;
      }
    },
    apply: async (payload) => {
      if (!isCurrent()) throw new Error('desktop_renderer_owner_changed');
      const localDigest = localSnapshotDigestV2(payload);
      let receipt;
      try {
        receipt = await desktopRendererDistributionReconcilerV2.apply(payload);
      } catch (error) {
        if (isCurrent() && !sourceSignal?.aborted && config.mode === 'local' && config.tenantId && localDigest) {
          const code = error && typeof error === 'object' && 'code' in error && typeof error.code === 'string' ? error.code : 'renderer_generation_apply_failed';
          await new DesktopApiClient(config).localRendererReceiptV2(localDigest, 'nack', code, sourceSignal).catch(() => undefined);
        }
        throw error;
      }
      if (!isCurrent() || sourceSignal?.aborted) return receipt;
      onReady();
      if (config.mode === 'local' && config.tenantId && localDigest) {
        await new DesktopApiClient(config).localRendererReceiptV2(localDigest, 'ack', undefined, sourceSignal);
      }
      return receipt;
    },
    statusStore,
    pollIntervalMs: POLL_INTERVAL_MS,
  });
}

function generationFailureTextV2(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return 'desktop_plugin_generation_failed';
}

function localSnapshotDigestV2(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object' || !('source' in payload) || payload.source !== 'local' || !('snapshot' in payload)) return null;
  const snapshot = payload.snapshot;
  return snapshot && typeof snapshot === 'object' && 'digest' in snapshot && typeof snapshot.digest === 'string' ? snapshot.digest : null;
}

export async function fetchDesktopPluginDistributionV2(signal: AbortSignal, config: DesktopRuntimeConfig): Promise<unknown | null> {
  signal.throwIfAborted();
  if (config.mode === 'local' && config.tenantId) {
    const view = await new DesktopApiClient(config).localRendererViewV2(signal);
    signal.throwIfAborted();
    return view;
  }
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (invoke === undefined) {
    throw new Error('desktop_renderer_distribution_ipc_unavailable');
  }
  const distribution = await invoke<unknown>(RENDERER_DISTRIBUTION_COMMAND_V2);
  signal.throwIfAborted();
  assertDesktopRendererDeliveryAvailableV2(distribution);
  return distribution ?? null;
}

function scheduleClose(): void {
  pendingClose = setTimeout(() => {
    pendingClose = null;
    void desktopRendererDistributionReconcilerV2.close().catch((error: unknown) => {
      desktopRendererStatusStoreV2.fail(
        error,
        desktopRendererRuntimeV2.getSnapshot() !== undefined
      );
    });
  }, 0);
}
