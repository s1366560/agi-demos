import { useCallback, useEffect, useState } from 'react';

import type { DesktopCapabilitySnapshot } from './capabilitySnapshot';
import type { DesktopWorkbenchCapabilityClient } from './workbenchCapabilityClient';

export type DesktopCapabilityLoadState = {
  loading: boolean;
  reload: () => void;
  snapshot: DesktopCapabilitySnapshot | null;
};

export type DesktopCapabilityGenerationStatus =
  | 'admitted'
  | 'degraded'
  | 'empty'
  | 'error'
  | 'loading'
  | 'ready';

export function useDesktopCapabilitySnapshot(
  client: DesktopWorkbenchCapabilityClient,
  enabled: boolean,
  generationStatus: DesktopCapabilityGenerationStatus = 'admitted',
  generationDigest = 'admitted',
  generationError?: unknown,
): DesktopCapabilityLoadState {
  const [snapshot, setSnapshot] = useState<DesktopCapabilitySnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((current) => current + 1), []);
  const waitingForGeneration =
    generationStatus === 'loading' ||
    ((generationStatus === 'ready' || generationStatus === 'degraded') &&
      generationDigest.trim() === '');
  const generationFailureCode =
    generationStatus === 'empty'
      ? 'desktop_renderer_generation_empty'
      : generationStatus === 'error'
        ? capabilitySnapshotFailureCode(generationError)
        : '';

  useEffect(() => {
    if (!enabled) {
      setSnapshot(null);
      setLoading(false);
      return undefined;
    }
    if (waitingForGeneration) {
      setLoading(true);
      return undefined;
    }
    if (generationFailureCode) {
      setSnapshot(null);
      setLoading(false);
      console.warn('[desktop-capability-snapshot]', generationFailureCode);
      return undefined;
    }

    const controller = new AbortController();
    const started = performance.now();
    traceCapabilitySnapshot(
      `[desktop-capability-snapshot] load digest=${generationDigest || 'none'}`,
    );
    setSnapshot(null);
    setLoading(true);
    let published = false;
    const publish = (nextSnapshot: DesktopCapabilitySnapshot) => {
      if (controller.signal.aborted) return;
      published = true;
      setSnapshot(nextSnapshot);
      setLoading(false);
    };
    void client
      .loadSnapshot(controller.signal, publish)
      .then((nextSnapshot) => {
        if (!controller.signal.aborted) {
          traceCapabilitySnapshot(
            `[desktop-capability-snapshot] loaded ${Math.round(performance.now() - started)}ms`,
          );
          publish(nextSnapshot);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.warn('[desktop-capability-snapshot]', capabilitySnapshotFailureCode(error));
          if (!published) setSnapshot(null);
          setLoading(false);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [
    attempt,
    client,
    enabled,
    generationDigest,
    generationFailureCode,
    waitingForGeneration,
  ]);

  return { loading, reload, snapshot };
}

function traceCapabilitySnapshot(message: string): void {
  const env = (globalThis as { process?: { env?: { NODE_ENV?: string } } }).process?.env
    ?.NODE_ENV;
  if (env === 'production') return;
  console.info(message);
}

function capabilitySnapshotFailureCode(error: unknown): string {
  if (typeof error !== 'object' || error === null) return 'snapshot_load_failed';
  for (const key of ['reasonCode', 'code']) {
    const value = Reflect.get(error, key);
    if (typeof value === 'string' && /^[a-z][a-z0-9_:-]{0,255}$/.test(value)) return value;
  }
  return 'snapshot_load_failed';
}
