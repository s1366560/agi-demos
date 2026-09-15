import { useEffect, useLayoutEffect, useSyncExternalStore } from 'react';

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
  _config: DesktopRuntimeConfig,
  enabled: boolean
): RendererPluginGenerationStateV2 {
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
    void desktopRendererLeaseStoreV2.commit(snapshot).catch((error: unknown) => {
      desktopRendererStatusStoreV2.fail(
        error,
        desktopRendererRuntimeV2.getSnapshot() !== undefined
      );
    });
  }, [snapshot]);

  useEffect(() => {
    if (pendingClose !== null) {
      clearTimeout(pendingClose);
      pendingClose = null;
    }
    if (!enabled) {
      scheduleClose();
      return;
    }

    const stop = startDesktopPluginGenerationPollingV2(
      desktopRendererRuntimeV2,
      desktopRendererStatusStoreV2
    );
    return () => {
      stop();
      scheduleClose();
    };
  }, [enabled]);

  const state = projectRendererPluginGenerationStateV2(enabled, snapshot.generation, status);
  return state;
}

function startDesktopPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  statusStore: RendererGenerationStatusStoreV2
): () => void {
  return startRendererGenerationPollingV2({
    runtime,
    source: fetchDesktopPluginDistributionV2,
    apply: (payload) => desktopRendererDistributionReconcilerV2.apply(payload),
    statusStore,
    pollIntervalMs: POLL_INTERVAL_MS,
  });
}

async function fetchDesktopPluginDistributionV2(signal: AbortSignal): Promise<unknown | null> {
  signal.throwIfAborted();
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
