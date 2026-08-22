import { useEffect, useLayoutEffect, useSyncExternalStore } from 'react';

import {
  createDesktopRendererDefinitionsV2,
  RendererGenerationLeaseStoreV2,
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  projectRendererPluginGenerationStateV2,
  startRendererGenerationPollingV2,
  type RendererPluginGenerationStateV2,
} from '@agistack/plugin-runtime';

import { desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';

import { validateDesktopRendererContributionsV2 } from './desktopRendererArtifactCatalogV2';

import bootstrapProfileV2 from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';

const DISTRIBUTION_PATH_V2 = '/api/v1/platform-plugins/v2/distribution';
const MAX_DISTRIBUTION_BYTES_V2 = 4 * 1024 * 1024;
const POLL_INTERVAL_MS = 30_000;
const desktopRendererRuntimeV2 = new RendererPluginRuntimeV2(
  'desktop-renderer',
  createDesktopRendererDefinitionsV2(validateDesktopRendererContributionsV2)
);
const desktopRendererLeaseStoreV2 = new RendererGenerationLeaseStoreV2(
  desktopRendererRuntimeV2
);
const desktopRendererStatusStoreV2 = new RendererGenerationStatusStoreV2();
let pendingClose: ReturnType<typeof setTimeout> | null = null;

export function activateDesktopPluginGenerationRootV2(): void {
  desktopRendererLeaseStoreV2.activateRoot();
}

export async function deactivateDesktopPluginGenerationRootV2(): Promise<void> {
  await desktopRendererLeaseStoreV2.deactivateRoot();
}

export function useDesktopPluginGenerationV2(
  config: DesktopRuntimeConfig,
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
    void desktopRendererLeaseStoreV2.commit(snapshot);
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
      config,
      desktopRendererStatusStoreV2
    );
    return () => {
      stop();
      scheduleClose();
    };
  }, [config.apiBaseUrl, config.apiKey, config.localApiToken, config.mode, enabled]);

  const state = projectRendererPluginGenerationStateV2(enabled, snapshot.generation, status);
  return state;
}

function startDesktopPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  config: DesktopRuntimeConfig,
  statusStore: RendererGenerationStatusStoreV2
): () => void {
  return startRendererGenerationPollingV2({
    runtime,
    source: (signal) => fetchDesktopPluginDistributionV2(config, signal),
    statusStore,
    bootstrap:
      config.mode === 'local' ? () => runtime.bootstrap(bootstrapProfileV2) : undefined,
    pollIntervalMs: POLL_INTERVAL_MS,
  });
}

async function fetchDesktopPluginDistributionV2(
  config: DesktopRuntimeConfig,
  signal: AbortSignal
): Promise<unknown | null> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);

  const response = await desktopApiFetch(config, DISTRIBUTION_PATH_V2, {
    method: 'GET',
    headers,
    signal,
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`plugin_v2_distribution_http_${response.status}`);
  const raw = await response.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_DISTRIBUTION_BYTES_V2) {
    throw new Error('plugin_v2_distribution_too_large');
  }
  return JSON.parse(raw) as unknown;
}

function scheduleClose(): void {
  pendingClose = setTimeout(() => {
    pendingClose = null;
    void desktopRendererRuntimeV2.close();
  }, 0);
}
