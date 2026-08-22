import { useEffect, useSyncExternalStore } from "react";

import {
  desktopRendererHostDefinitionV2,
  RendererPluginRuntimeV2,
} from "@agistack/plugin-runtime";

import { desktopApiCredential, desktopLaunchCapability } from "../api/client";
import { desktopApiFetch } from "../api/cloudRequestBroker";
import type { DesktopRuntimeConfig } from "../types";

import bootstrapProfileV2 from "../../../../../shared/profiles/memstack-default-bootstrap.v2.json";

const DISTRIBUTION_PATH_V2 = "/api/v1/platform-plugins/v2/distribution";
const MAX_DISTRIBUTION_BYTES_V2 = 4 * 1024 * 1024;
const POLL_INTERVAL_MS = 30_000;
const desktopRendererRuntimeV2 = new RendererPluginRuntimeV2(
  "desktop-renderer",
  [desktopRendererHostDefinitionV2],
);
let pendingClose: ReturnType<typeof setTimeout> | null = null;

export function useDesktopPluginGenerationV2(
  config: DesktopRuntimeConfig,
  enabled: boolean,
) {
  const generation = useSyncExternalStore(
    desktopRendererRuntimeV2.subscribe,
    desktopRendererRuntimeV2.getSnapshot,
    desktopRendererRuntimeV2.getSnapshot,
  );

  useEffect(() => {
    if (pendingClose !== null) {
      clearTimeout(pendingClose);
      pendingClose = null;
    }
    if (!enabled) return () => scheduleClose();

    const stop = startDesktopPluginGenerationPollingV2(
      desktopRendererRuntimeV2,
      config,
    );
    return () => {
      stop();
      scheduleClose();
    };
  }, [
    config.apiBaseUrl,
    config.apiKey,
    config.localApiToken,
    config.mode,
    enabled,
  ]);

  return generation;
}

function startDesktopPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  config: DesktopRuntimeConfig,
): () => void {
  const controller = new AbortController();
  let stopped = false;
  let inFlight: Promise<void> | null = null;

  const refresh = (): void => {
    if (stopped || inFlight !== null) return;
    const request = (async () => {
      if (config.mode === "local" && runtime.getSnapshot() === undefined) {
        await runtime.bootstrap(bootstrapProfileV2);
      }
      if (stopped) return;
      const remote = await fetchDesktopPluginDistributionV2(
        config,
        controller.signal,
      );
      if (!stopped && remote !== null) await runtime.apply(remote);
    })().catch(() => undefined);
    inFlight = request;
    void request.finally(() => {
      if (inFlight === request) inFlight = null;
    });
  };

  refresh();
  const timer = setInterval(refresh, POLL_INTERVAL_MS);
  return () => {
    stopped = true;
    controller.abort();
    clearInterval(timer);
  };
}

async function fetchDesktopPluginDistributionV2(
  config: DesktopRuntimeConfig,
  signal: AbortSignal,
): Promise<unknown | null> {
  const headers = new Headers({ Accept: "application/json" });
  const credential = desktopApiCredential(config);
  if (credential) headers.set("Authorization", `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set("X-Agistack-Launch", launchCapability);

  const response = await desktopApiFetch(config, DISTRIBUTION_PATH_V2, {
    method: "GET",
    headers,
    signal,
  });
  if (response.status === 404) return null;
  if (!response.ok)
    throw new Error(`plugin_v2_distribution_http_${response.status}`);
  const raw = await response.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_DISTRIBUTION_BYTES_V2) {
    throw new Error("plugin_v2_distribution_too_large");
  }
  return JSON.parse(raw) as unknown;
}

function scheduleClose(): void {
  pendingClose = setTimeout(() => {
    pendingClose = null;
    void desktopRendererRuntimeV2.close();
  }, 0);
}
