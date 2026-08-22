import { useEffect, useSyncExternalStore } from 'react';

import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';

import { ApiError } from '../services/client/ApiError';
import { httpClient } from '../services/client/httpClient';

const POLL_INTERVAL_MS = 30_000;
const webRendererRuntimeV2 = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
let pendingClose: ReturnType<typeof setTimeout> | null = null;

export type WebPluginDistributionSourceV2 = (signal: AbortSignal) => Promise<unknown | null>;

export function startWebPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  source: WebPluginDistributionSourceV2,
  pollIntervalMs = POLL_INTERVAL_MS
): () => void {
  const controller = new AbortController();
  let stopped = false;
  let inFlight: Promise<void> | null = null;

  const refresh = (): void => {
    if (stopped || inFlight !== null) return;
    const request = (async () => {
      const payload = await source(controller.signal);
      if (!stopped && payload !== null) await runtime.apply(payload);
    })().catch(() => undefined);
    inFlight = request;
    void request.finally(() => {
      if (inFlight === request) inFlight = null;
    });
  };

  refresh();
  const timer = setInterval(refresh, pollIntervalMs);
  return () => {
    stopped = true;
    controller.abort();
    clearInterval(timer);
  };
}

export function useWebPluginGenerationV2(enabled: boolean) {
  const generation = useSyncExternalStore(
    webRendererRuntimeV2.subscribe,
    webRendererRuntimeV2.getSnapshot,
    webRendererRuntimeV2.getSnapshot
  );

  useEffect(() => {
    if (pendingClose !== null) {
      clearTimeout(pendingClose);
      pendingClose = null;
    }
    if (!enabled) {
      return () => scheduleClose();
    }
    const stop = startWebPluginGenerationPollingV2(
      webRendererRuntimeV2,
      fetchWebPluginDistributionV2
    );
    return () => {
      stop();
      scheduleClose();
    };
  }, [enabled]);

  return generation;
}

async function fetchWebPluginDistributionV2(signal: AbortSignal): Promise<unknown | null> {
  try {
    return await httpClient.get<unknown>('/platform-plugins/v2/distribution', { signal });
  } catch (error) {
    if (error instanceof ApiError && error.statusCode === 404) return null;
    throw error;
  }
}

function scheduleClose(): void {
  pendingClose = setTimeout(() => {
    pendingClose = null;
    void webRendererRuntimeV2.close();
  }, 0);
}
